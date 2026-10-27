"""The full-screen video feed on phones (Home > Media tab, _reel_item.html)
and its template helpers (run: python manage.py test feed.test_media_reels).
How it looks and scrolls is checked in the browser; this checks what the
server sends."""
from django.test import TestCase, override_settings

from . import test_videos   # module import, so its tests don't run twice
from .models import Follow, Post, PostMedia
from .templatetags.post_extras import compact_count, first_video, with_hashtags


class HelperTests(TestCase):
	def test_compact_count(self):
		for n, want in [(0, '0'), (999, '999'), (1000, '1K'), (1250, '1.2K'), (17_400, '17K'), (2_300_000, '2.3M'), (None, '0')]:
			self.assertEqual(compact_count(n), want)

	def test_hashtags_are_marked_and_text_is_escaped(self):
		html = with_hashtags('Great game #UCL\n<script>x</script> a#b')
		self.assertIn('<span class="reel-tag">#UCL</span>', html)
		self.assertIn('<br>', html)
		self.assertIn('&lt;script&gt;', html)
		self.assertNotIn('<script>', html)
		self.assertNotIn('reel-tag">#b', html)          # not a tag in the middle of a word


@override_settings(MEDIA_ROOT=test_videos.TMP_MEDIA)
class MediaFeedTests(TestCase):
	setUp = test_videos.VideoTests.setUp
	student = test_videos.VideoTests.student

	def video_post(self, author, text='A video #Campus'):
		post = Post.objects.create(author=author, content=text)
		PostMedia.objects.create(post=post, ik_file_id=f'v{Post.objects.count()}', ik_url='https://ik.imagekit.io/demo/v.mp4')
		return post

	def reel(self, html, post):
		return html.split(f'id="reel-{post.pk}"')[1].split('</section>')[0]

	def test_media_tab_has_the_phone_feed(self):
		mine, theirs = self.video_post(self.me), self.video_post(self.friend)
		r = self.client.get('/home/?tab=media')
		html = r.content.decode()
		self.assertIn('media-reels-page', html)          # page class that switches the phone layout on
		self.assertIn('id="reels"', html)
		self.assertIn('js-reels-menu', html)             # menu + search in the tab row
		self.assertIn(f'id="post-{theirs.pk}"', html)    # the cards are still there for larger screens
		reel = self.reel(html, theirs)
		for cls in ('js-like-btn', 'js-open-comments', 'js-repost-btn', 'js-bookmark-btn', 'js-share-post', 'js-reel-sound', 'js-video-views'):
			self.assertIn(cls, reel)
		self.assertIn('class="js-uc-video reel-video"', reel)
		self.assertIn('preload="none"', reel)
		self.assertIn('muted', reel)
		self.assertIn('<span class="reel-tag">#Campus</span>', reel)
		self.assertIn('Original sound', reel)
		self.assertIn('js-reel-follow', reel)            # someone else, not followed: "+"
		self.assertNotIn('js-reel-follow', self.reel(html, mine))   # never on your own video

	def test_follow_button_follows_state(self):
		post = self.video_post(self.friend)
		Follow.objects.create(follower=self.me, following=self.friend, status=Follow.STATUS_PENDING)
		reel = self.reel(self.client.get('/home/?tab=media').content.decode(), post)
		self.assertIn('data-status="pending"', reel)
		self.assertIn('bi-hourglass-split', reel)
		Follow.objects.filter(follower=self.me).update(status=Follow.STATUS_ACCEPTED)
		reel = self.reel(self.client.get('/home/?tab=media').content.decode(), post)
		self.assertNotIn('js-reel-follow', reel)         # already following: no "+"

	def test_other_tabs_and_empty_media_tab_unchanged(self):
		self.video_post(self.friend)
		html = self.client.get('/home/?tab=foryou').content.decode()
		self.assertNotIn('id="reels"', html)
		self.assertNotIn('media-reels-page', html)
		Post.objects.all().delete()
		html = self.client.get('/home/?tab=media').content.decode()
		self.assertNotIn('id="reels"', html)
		self.assertNotIn('media-reels-page', html)
		self.assertIn('No videos yet', html)

	def test_first_video(self):
		post = self.video_post(self.friend)
		self.assertEqual(first_video(post).ik_url, 'https://ik.imagekit.io/demo/v.mp4')
		self.assertIsNone(first_video(Post.objects.create(author=self.me, content='text only')))
