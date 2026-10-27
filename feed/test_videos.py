"""Tests for videos on ImageKit, thumbnails and view counts
(run: python manage.py test feed.test_videos). ImageKit itself is never
contacted: its API calls are replaced with fakes."""
import hashlib
import hmac
import io
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from accounts.models import Department, Faculty, Level, StudentProfile, University
from . import imagekit
from .models import Post, PostMedia, VideoView

User = get_user_model()
KEYS = dict(IMAGEKIT_PUBLIC_KEY='public_test', IMAGEKIT_PRIVATE_KEY='private_test', IMAGEKIT_UPLOAD_URL='', IMAGEKIT_API_URL='',
	IMAGEKIT_ADAPTIVE_STREAMING=False)
STREAMING = dict(KEYS, IMAGEKIT_ADAPTIVE_STREAMING=True)
NO_KEYS = dict(IMAGEKIT_PUBLIC_KEY='', IMAGEKIT_PRIVATE_KEY='')
TMP_MEDIA = tempfile.mkdtemp()


def ik_file(file_id, kind='video', **extra):
	rec = {
		'fileId': file_id, 'url': f'https://ik.imagekit.io/demo/uniconnect/{file_id}.mp4',
		'filePath': f'/uniconnect/videos/{file_id}.mp4', 'fileType': 'non-image', 'mime': 'video/mp4', 'size': 5_000_000,
	}
	if kind == 'thumbnail':
		rec.update(url=f'https://ik.imagekit.io/demo/uniconnect/{file_id}.jpg', filePath=f'/uniconnect/thumbnails/{file_id}.jpg',
			fileType='image', mime='image/jpeg', size=80_000)
	rec.update(extra)
	return rec


def png_bytes():
	buf = io.BytesIO()
	Image.new('RGB', (64, 36), (33, 121, 255)).save(buf, 'PNG')
	return buf.getvalue()


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class VideoTests(TestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(TMP_MEDIA, ignore_errors=True)

	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		self.me = self.student('ada', uni)
		self.friend = self.student('ben', uni)
		self.client.force_login(self.me)

	def student(self, username, uni):
		user = User.objects.create_user(username, password='x', first_name=username.title())
		fac = Faculty.objects.get_or_create(university=uni, name='Sciences')[0]
		dep = Department.objects.get_or_create(faculty=fac, name='Computer Science')[0]
		lvl = Level.objects.get_or_create(department=dep, name='400 Level')[0]
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=username, university_email=f'{username}@unn.edu.ng')
		return user

	def ik_post(self, **kwargs):
		post = Post.objects.create(author=self.me, content='A video')
		PostMedia.objects.create(post=post, ik_file_id='vid1', ik_url='https://ik.imagekit.io/demo/v.mp4', **kwargs)
		return post

	# ---------- signing ----------
	@override_settings(**KEYS)
	def test_auth_signature_is_hmac_sha1_of_token_and_expire(self):
		data = self.client.get('/imagekit/auth/').json()
		expected = hmac.new(b'private_test', f"{data['token']}{data['expire']}".encode(), hashlib.sha1).hexdigest()
		self.assertEqual(data['signature'], expected)
		self.assertEqual(data['publicKey'], 'public_test')
		self.assertNotIn('private_test', str(data))

	@override_settings(**NO_KEYS)
	def test_auth_is_off_without_keys(self):
		self.assertEqual(self.client.get('/imagekit/auth/').status_code, 404)

	def test_auth_needs_login(self):
		self.client.logout()
		self.assertEqual(self.client.get('/imagekit/auth/').status_code, 302)

	# ---------- checking uploads ----------
	@override_settings(**KEYS)
	def test_check_upload_rules(self):
		cases = [
			(ik_file('a'), 'video', None),
			(ik_file('a', filePath='/elsewhere/a.mp4'), 'video', 'not made from UniConnect'),
			(ik_file('a', mime='image/png'), 'video', 'not a video'),
			(ik_file('a', size=51 * 1024 * 1024), 'video', 'smaller than 50MB'),
			(ik_file('a', size=50 * 1024 * 1024), 'video', None),
			(ik_file('t', 'thumbnail'), 'thumbnail', None),
			(ik_file('t', 'thumbnail', fileType='non-image'), 'thumbnail', 'must be an image'),
		]
		for details, kind, error in cases:
			with mock.patch.object(imagekit, 'file_details', return_value=details):
				if error:
					with self.assertRaisesMessage(imagekit.ImageKitError, error):
						imagekit.check_upload('a', kind)
				else:
					self.assertEqual(imagekit.check_upload('a', kind), details)

	def test_file_id_is_validated_before_any_request(self):
		with override_settings(**KEYS), self.assertRaises(imagekit.ImageKitError):
			imagekit.file_details('../../files')

	# ---------- posting ----------
	@override_settings(**KEYS)
	def test_post_with_imagekit_video_and_thumbnail(self):
		files = {'v1': ik_file('v1'), 't1': ik_file('t1', 'thumbnail')}
		with mock.patch.object(imagekit, 'file_details', side_effect=lambda fid: files[fid]):
			r = self.client.post('/post/new/', {'content': 'Campus tour', 'ik_video_file_id': 'v1', 'ik_thumbnail_file_id': 't1'})
		self.assertEqual(r.status_code, 302)
		m = PostMedia.objects.get(post__content='Campus tour')
		self.assertEqual((m.ik_file_id, m.ik_url, m.ik_thumbnail_file_id), ('v1', files['v1']['url'], 't1'))
		self.assertTrue(m.is_video)
		# Default: the original file, untouched (no processing units), and no stream.
		self.assertEqual(m.video_url, files['v1']['url'] + '?tr=orig-true')
		self.assertEqual(m.stream_url, '')
		self.assertEqual(m.poster_url, files['t1']['url'] + '?tr=w-1920,c-at_max,q-90')
		with override_settings(IMAGEKIT_ADAPTIVE_STREAMING=True):
			self.assertEqual(m.stream_url, files['v1']['url'] + '/ik-master.m3u8?tr=sr-240_360_480_720_1080')

	@override_settings(**KEYS)
	def test_without_thumbnail_no_imagekit_processing_by_default(self):
		# (The composer normally makes a thumbnail in the browser; if it
		# couldn't, the post shows the video's first frame — ImageKit is
		# not asked to make one, as that would use processing units.)
		with mock.patch.object(imagekit, 'file_details', return_value=ik_file('v2')):
			self.client.post('/post/new/', {'content': 'Auto thumb', 'ik_video_file_id': 'v2'})
		m = PostMedia.objects.get(post__content='Auto thumb')
		self.assertEqual(m.poster_url, '')
		with override_settings(IMAGEKIT_ADAPTIVE_STREAMING=True):
			self.assertEqual(m.poster_url, m.ik_url + '/ik-thumbnail.jpg?tr=w-1920,c-at_max,q-90')

	@override_settings(**KEYS)
	def test_unknown_or_reused_upload_is_refused(self):
		with mock.patch.object(imagekit, '_request', side_effect=imagekit.ImageKitError('ImageKit answered 404.')):
			r = self.client.post('/post/new/', {'content': 'x', 'ik_video_file_id': 'nope'})
		self.assertContains(r, 'ImageKit has no file with that ID')
		self.ik_post()
		with mock.patch.object(imagekit, 'file_details', return_value=ik_file('vid1')):
			r = self.client.post('/post/new/', {'content': 'x', 'ik_video_file_id': 'vid1'})
		self.assertContains(r, 'already attached to a post')
		self.assertEqual(Post.objects.filter(content='x').count(), 0)

	@override_settings(**KEYS)
	def test_thumbnail_needs_a_video_and_photos_cant_mix(self):
		with mock.patch.object(imagekit, 'file_details', return_value=ik_file('t9', 'thumbnail')):
			r = self.client.post('/post/new/', {'content': 'x', 'ik_thumbnail_file_id': 't9'})
		self.assertContains(r, 'only be added together with a new video')
		photo = SimpleUploadedFile('p.png', png_bytes(), content_type='image/png')
		with mock.patch.object(imagekit, 'file_details', return_value=ik_file('v9')):
			r = self.client.post('/post/new/', {'content': 'x', 'ik_video_file_id': 'v9', 'media': [photo]})
		self.assertContains(r, 'photos or a video, not both')

	@override_settings(**NO_KEYS)
	def test_imagekit_ids_refused_when_not_configured(self):
		r = self.client.post('/post/new/', {'content': 'x', 'ik_video_file_id': 'v1'})
		self.assertContains(r, "aren&#x27;t set up on this server")

	@override_settings(**NO_KEYS)
	def test_local_video_with_local_thumbnail_still_works(self):
		video = SimpleUploadedFile('clip.mp4', b'\x00\x00\x00\x18ftypmp42', content_type='video/mp4')
		thumb = SimpleUploadedFile('t.png', png_bytes(), content_type='image/png')
		r = self.client.post('/post/new/', {'content': 'Local video test', 'media': [video], 'video_thumbnail': thumb})
		self.assertEqual(r.status_code, 302)
		m = PostMedia.objects.get(post__content='Local video test')
		self.assertTrue(m.video and m.thumbnail)
		self.assertEqual(m.poster_url, m.thumbnail.url)
		self.assertEqual(m.stream_url, '')

	# ---------- feed ----------
	@override_settings(**KEYS)
	def test_media_tab_default_plays_original_with_views(self):
		post = self.ik_post()
		VideoView.objects.create(post=post, user=self.friend)
		html = self.client.get('/home/?tab=media').content.decode()
		self.assertIn('src="https://ik.imagekit.io/demo/v.mp4?tr=orig-true"', html)
		self.assertNotIn('data-stream=', html)
		self.assertNotIn('ik-thumbnail.jpg', html)
		self.assertIn('preload="metadata"', html)
		self.assertIn('>1 view<', html)

	@override_settings(**STREAMING)
	def test_media_tab_with_streaming_switched_on(self):
		self.ik_post()
		html = self.client.get('/home/?tab=media').content.decode()
		self.assertIn('data-stream="https://ik.imagekit.io/demo/v.mp4/ik-master.m3u8?tr=sr-240_360_480_720_1080"', html)
		self.assertIn('poster="https://ik.imagekit.io/demo/v.mp4/ik-thumbnail.jpg?tr=w-1920,c-at_max,q-90"', html)

	# ---------- views ----------
	def test_views_count_once_per_person(self):
		post = self.ik_post()
		url = f'/video/{post.pk}/view/'
		self.assertEqual(self.client.post(url).json(), {'views': 1, 'label': '1 view'})
		self.assertEqual(self.client.post(url).json()['views'], 1)
		self.client.force_login(self.friend)
		self.assertEqual(self.client.post(url).json()['label'], '2 views')
		self.assertEqual(self.client.get(url).status_code, 405)

	def test_no_views_on_posts_without_video(self):
		post = Post.objects.create(author=self.me, content='Just text')
		self.assertEqual(self.client.post(f'/video/{post.pk}/view/').status_code, 400)

	# ---------- deleting ----------
	@override_settings(**KEYS)
	def test_deleting_the_post_deletes_its_files_on_imagekit(self):
		post = self.ik_post(ik_thumbnail_file_id='th1', ik_thumbnail_url='https://ik.imagekit.io/demo/t.jpg')
		with mock.patch.object(imagekit, 'delete_file') as deleted:
			self.client.post(f'/post/{post.pk}/delete/')
		self.assertFalse(Post.objects.filter(pk=post.pk).exists())
		self.assertEqual(sorted(c.args[0] for c in deleted.call_args_list), ['th1', 'vid1'])

	@override_settings(**KEYS)
	def test_imagekit_being_down_never_blocks_a_delete(self):
		post = self.ik_post()
		with mock.patch.object(imagekit, '_request', side_effect=imagekit.ImageKitError("Couldn't reach ImageKit.")):
			self.client.post(f'/post/{post.pk}/delete/')
		self.assertFalse(Post.objects.filter(pk=post.pk).exists())

	# ---------- python manage.py imagekit_status ----------
	@override_settings(**KEYS)
	def test_status_command_reports_usage_and_cleans_leftovers(self):
		from django.core.management import call_command
		post = self.ik_post(ik_thumbnail_file_id='th1', ik_thumbnail_url='https://ik.imagekit.io/demo/t.jpg')
		old, recent = '2026-01-01T00:00:00.000Z', '2999-01-01T00:00:00.000Z'
		listing = {
			imagekit.VIDEO_FOLDER: [
				{'fileId': 'vid1', 'filePath': '/uniconnect/videos/v.mp4', 'size': 9_000_000, 'createdAt': old},
				{'fileId': 'gone1', 'filePath': '/uniconnect/videos/abandoned.mp4', 'size': 7_000_000, 'createdAt': old},
				{'fileId': 'busy1', 'filePath': '/uniconnect/videos/uploading.mp4', 'size': 5_000_000, 'createdAt': recent},
			],
			imagekit.THUMBNAIL_FOLDER: [
				{'fileId': 'th1', 'filePath': '/uniconnect/thumbnails/t.jpg', 'size': 80_000, 'createdAt': old},
				{'fileId': 'gone2', 'filePath': '/uniconnect/thumbnails/abandoned.jpg', 'size': 60_000, 'createdAt': old},
			],
		}
		usage = {'bandwidthBytes': 18 * 1024 ** 3, 'mediaLibraryStorageBytes': 200 * 1024 ** 2, 'videoProcessingUnitsCount': 120}
		out = io.StringIO()
		with mock.patch.object(imagekit, 'usage', return_value=usage), \
				mock.patch.object(imagekit, 'list_files', side_effect=lambda path: listing.get(path, [])), \
				mock.patch.object(imagekit, 'delete_file') as deleted:
			call_command('imagekit_status', stdout=out)
			self.assertFalse(deleted.called)                      # only reports without the flag
			text = out.getvalue()
			self.assertIn('18.00 GB of 20 GB', text)
			self.assertIn('Bandwidth is at 90% of the free plan', text)
			self.assertIn(f'post {post.pk}', text)
			self.assertIn('Leftover uploads (on ImageKit, not on any post): 2', text)
			self.assertNotIn('uploading.mp4', text)              # uploaded just now: left alone
			call_command('imagekit_status', '--delete-leftovers', stdout=io.StringIO())
		self.assertEqual(sorted(c.args[0] for c in deleted.call_args_list), ['gone1', 'gone2'])
