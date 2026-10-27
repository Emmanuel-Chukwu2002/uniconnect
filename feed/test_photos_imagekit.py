"""Photos (posts and stories) on ImageKit: uploaded there, served at the
right size for each screen, and deleted with their post or story
(run: python manage.py test feed.test_photos_imagekit). ImageKit itself is
never contacted: its API calls are replaced with fakes."""
import itertools
import shutil
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from . import imagekit
from .models import Post, PostMedia, Story
from .test_videos import KEYS, NO_KEYS, VideoTests, png_bytes

TMP_MEDIA = tempfile.mkdtemp()
_ids = itertools.count(1)


def fake_upload(f, folder=imagekit.PHOTO_FOLDER):
	n = next(_ids)
	return {'fileId': f'img{n}', 'url': f'https://ik.imagekit.io/demo{folder}/p{n}.png', 'width': 4000, 'height': 3000}


def photo(name='p.png'):
	return SimpleUploadedFile(name, png_bytes(), content_type='image/png')


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class PhotoTests(TestCase):
	# Same two students as the video tests.
	setUp = VideoTests.setUp
	student = VideoTests.student

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(TMP_MEDIA, ignore_errors=True)

	# ---------- URLs ----------
	def test_sized_urls_are_sharp_and_never_upscaled(self):
		url = 'https://ik.imagekit.io/demo/a.jpg'
		self.assertEqual(imagekit.sized_image_url(url, 1080), url + '?tr=w-1080,c-at_max,q-90')
		srcset = imagekit.srcset(url)
		for w in imagekit.PHOTO_WIDTHS:
			self.assertIn(f'?tr=w-{w},c-at_max,q-90 {w}w', srcset)

	# ---------- posts ----------
	@override_settings(**KEYS)
	def test_post_photos_go_to_imagekit(self):
		with mock.patch.object(imagekit, 'upload_image', side_effect=fake_upload) as up:
			r = self.client.post('/post/new/', {'content': 'Two photos', 'media': [photo('a.png'), photo('b.png')]})
		self.assertEqual(r.status_code, 302)
		self.assertEqual(up.call_count, 2)
		items = list(Post.objects.get(content='Two photos').media_items.all())
		self.assertEqual(len(items), 2)
		for m in items:
			self.assertTrue(m.ik_image_url.startswith('https://ik.imagekit.io/demo/uniconnect/photos/'))
			self.assertFalse(m.image)                      # nothing stored on this server
			self.assertTrue(m.is_photo and not m.is_video)
		html = self.client.get('/home/').content.decode()
		self.assertIn('srcset="' + items[0].photo_srcset, html)
		self.assertIn(f'data-full="{items[0].ik_image_url}?tr=w-2560,c-at_max,q-90"', html)
		self.assertIn('sizes="(max-width: 640px) 50vw, 310px"', html)   # two photos side by side

	@override_settings(**KEYS)
	def test_imagekit_down_keeps_photo_here(self):
		with mock.patch.object(imagekit, 'upload_image', side_effect=imagekit.ImageKitError("Couldn't reach ImageKit.")):
			r = self.client.post('/post/new/', {'content': 'Offline photo', 'media': [photo()]})
		self.assertEqual(r.status_code, 302)
		m = Post.objects.get(content='Offline photo').media_items.get()
		self.assertTrue(m.image)
		self.assertEqual(m.ik_image_url, '')
		self.assertEqual(m.photo_url, m.image.url)
		self.assertEqual(m.photo_srcset, '')

	@override_settings(**NO_KEYS)
	def test_without_imagekit_photos_stay_here(self):
		with mock.patch.object(imagekit, 'upload_image') as up:
			self.client.post('/post/new/', {'content': 'Local photo', 'media': [photo()]})
		up.assert_not_called()
		m = Post.objects.get(content='Local photo').media_items.get()
		self.assertTrue(m.image)
		html = self.client.get('/home/').content.decode()
		self.assertIn(f'src="{m.image.url}"', html)
		self.assertNotIn('srcset=', html.split('Local photo')[1].split('post-card-actions')[0])

	@override_settings(**KEYS)
	def test_deleting_post_deletes_photo_from_imagekit(self):
		with mock.patch.object(imagekit, 'upload_image', side_effect=fake_upload):
			self.client.post('/post/new/', {'content': 'Delete me', 'media': [photo()]})
		post = Post.objects.get(content='Delete me')
		file_id = post.media_items.get().ik_image_file_id
		with mock.patch.object(imagekit, 'delete_file') as delete:
			self.client.post(f'/post/{post.pk}/delete/')
		delete.assert_called_once_with(file_id)

	# ---------- stories ----------
	@override_settings(**KEYS)
	def test_story_photo_goes_to_imagekit(self):
		with mock.patch.object(imagekit, 'upload_image', side_effect=fake_upload):
			self.client.post('/stories/new/', {'image': photo(), 'caption': 'Sunset'})
		story = Story.objects.get(caption='Sunset')
		self.assertTrue(story.ik_image_url.startswith('https://ik.imagekit.io/demo/uniconnect/stories/'))
		self.assertFalse(story.image)
		self.assertEqual(story.image_url, story.ik_image_url + '?tr=w-1440,c-at_max,q-90')
		with mock.patch.object(imagekit, 'delete_file') as delete:
			story.delete()
		delete.assert_called_once_with(story.ik_image_file_id)

	@override_settings(**KEYS)
	def test_story_kept_here_if_imagekit_down(self):
		with mock.patch.object(imagekit, 'upload_image', side_effect=imagekit.ImageKitError('down')):
			self.client.post('/stories/new/', {'image': photo(), 'caption': 'Fallback'})
		story = Story.objects.get(caption='Fallback')
		self.assertTrue(story.image)
		self.assertEqual(story.image_url, story.image.url)

	def test_story_still_needs_a_photo(self):
		self.client.post('/stories/new/', {'caption': 'No photo'})
		self.assertFalse(Story.objects.filter(caption='No photo').exists())

	# ---------- the real upload request ----------
	@override_settings(**KEYS)
	def test_upload_image_sends_private_key_and_folder(self):
		sent = {}

		class Resp:
			def __enter__(self): return self
			def __exit__(self, *a): return False
			def read(self): return b'{"fileId": "abc123", "url": "https://ik.imagekit.io/demo/uniconnect/photos/p.png", "width": 64}'

		def fake_urlopen(req, timeout=0):
			sent['auth'] = req.headers['Authorization']
			sent['body'] = req.data
			return Resp()
		with mock.patch('urllib.request.urlopen', fake_urlopen):
			details = imagekit.upload_image(photo('my photo!.png'))
		self.assertEqual(details['fileId'], 'abc123')
		self.assertTrue(sent['auth'].startswith('Basic '))
		self.assertIn(b'name="folder"\r\n\r\n/uniconnect/photos', sent['body'])
		self.assertIn(b'filename="my_photo_.png"', sent['body'])
		self.assertIn(png_bytes()[:8], sent['body'])

	@override_settings(**KEYS)
	def test_upload_image_rejects_odd_answers(self):
		class Resp:
			def __enter__(self): return self
			def __exit__(self, *a): return False
			def read(self): return b'{"fileId": "../../etc", "url": "javascript:alert(1)"}'
		with mock.patch('urllib.request.urlopen', lambda req, timeout=0: Resp()):
			with self.assertRaises(imagekit.ImageKitError):
				imagekit.upload_image(photo())


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class SmallPhotoTests(TestCase):
	"""Small photos are shown at their true size, never stretched."""
	setUp = VideoTests.setUp
	student = VideoTests.student

	def post_with(self, w, h, n=1):
		up = lambda f, folder=imagekit.PHOTO_FOLDER: dict(fake_upload(f, folder), width=w, height=h)
		with override_settings(**KEYS), mock.patch.object(imagekit, 'upload_image', side_effect=up):
			self.client.post('/post/new/', {'content': f'{w}x{h} x{n}', 'media': [photo() for _ in range(n)]})
		return Post.objects.get(content=f'{w}x{h} x{n}')

	def card(self, post):
		html = self.client.get('/home/').content.decode()
		return html.split(f'id="post-{post.pk}"')[1].split('post-card-actions')[0]

	def test_sizes_are_saved(self):
		m = self.post_with(300, 168).media_items.get()
		self.assertEqual((m.width, m.height), (300, 168))
		self.assertTrue(m.is_small and m.is_small_tile)

	def test_small_single_photo_not_stretched(self):
		post = self.post_with(300, 168)
		card = self.card(post)
		self.assertIn('post-card-media-item is-small', card)
		self.assertIn('width="300" height="168"', card)
		self.assertNotIn('srcset=', card)

	def test_big_photo_fills_frame(self):
		card = self.card(self.post_with(4000, 3000))
		self.assertNotIn('is-small', card)
		self.assertEqual(card.count(' 2048w'), 1)          # each size once

	def test_srcset_never_bigger_than_the_photo(self):
		m = self.post_with(900, 600).media_items.get()
		self.assertFalse(m.is_small)
		self.assertTrue(m.photo_srcset.endswith('?tr=w-900,c-at_max,q-90 900w'))
		self.assertNotIn('1080w', m.photo_srcset)

	def test_grid_tiles_use_the_tile_limit(self):
		card = self.card(self.post_with(400, 300, n=2))   # small for a single photo, fine as a tile
		self.assertNotIn('is-small', card)

	def test_local_photo_size_read_from_file(self):
		with override_settings(**NO_KEYS):
			self.client.post('/post/new/', {'content': 'local size', 'media': [photo()]})
		m = Post.objects.get(content='local size').media_items.get()
		self.assertEqual((m.width, m.height), (64, 36))
		self.assertTrue(m.is_small)
