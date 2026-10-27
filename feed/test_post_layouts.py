"""The two X-style post layouts (run: python manage.py test feed.test_post_layouts):
the compact Home feed card (_post_card.html) and the Post Details page
(post_detail.html + _post_detail_main.html)."""
from datetime import datetime, timedelta, timezone as dt_tz
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from .models import Comment, CommentLike, Post
from .templatetags.post_extras import short_ago
from . import test_videos   # module import, so its tests don't run twice


class ShortAgoTests(TestCase):
	def test_compact_ages(self):
		now = datetime(2026, 10, 14, 12, 0, tzinfo=dt_tz.utc)
		with mock.patch('django.utils.timezone.now', return_value=now):
			for delta, want in [(timedelta(seconds=20), 'now'), (timedelta(minutes=5), '5m'), (timedelta(hours=7), '7h'), (timedelta(days=3), '3d')]:
				self.assertEqual(short_ago(now - delta), want)
			self.assertEqual(short_ago(datetime(2026, 9, 1, 12, tzinfo=dt_tz.utc)), '1 Sep')
			self.assertEqual(short_ago(datetime(2025, 10, 13, 12, tzinfo=dt_tz.utc)), '13 Oct 25')
		self.assertEqual(short_ago(None), '')


class PostLayoutTests(TestCase):
	setUp = test_videos.VideoTests.setUp
	student = test_videos.VideoTests.student

	def make_post(self, text='Hello', author=None):
		return Post.objects.create(author=author or self.friend, content=text)

	def feed_card(self, post):
		html = self.client.get('/home/').content.decode()
		return html.split(f'id="post-{post.pk}"')[1].split('</article>')[0]

	def test_feed_card_is_compact(self):
		post = self.make_post()
		card = self.feed_card(post)
		self.assertIn('class="post-card-byline"', card)
		self.assertIn('post-card-handle">@ben<', card)                # short handle: not marked long
		self.assertIn('<time datetime=', card)
		self.assertNotIn('pd-meta', card)                             # no detail meta line in the feed

	def test_long_handle_marked(self):
		u = self.student('verylongusername', self.me.student_profile.university)
		card = self.feed_card(self.make_post(author=u))
		self.assertIn('post-card-handle is-long', card)

	def test_detail_layout(self):
		post = self.make_post()
		html = self.client.get(f'/post/{post.pk}/').content.decode()
		main = html.split('class="post-card post-detail"')[1]
		self.assertNotIn('post-card-byline', main)                    # not the feed's one-line header
		self.assertIn('class="pd-name-row"', main)                    # name on its own line…
		self.assertLess(main.index('pd-name-row'), main.index('post-card-handle'))   # …@handle under it
		# The time comes after the text, in its own line, before the usual action row.
		self.assertLess(main.index('post-card-text'), main.index('pd-meta'))
		self.assertLess(main.index('pd-meta'), main.index('post-card-actions'))
		self.assertIn('js-open-comments', main)                       # comments still open the comments sheet
		self.assertNotIn('pd-follow-btn', main)
	def test_delete_from_details_goes_home(self):
		post = self.make_post(author=self.me)
		html = self.client.get(f'/post/{post.pk}/').content.decode()
		self.assertIn('name="next" value="/home/"', html)
