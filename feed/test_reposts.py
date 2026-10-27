"""Reposts and quote posts (run: python manage.py test feed.test_reposts)."""
import re

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from .models import Comment, Like, Notification, Post, Repost

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


def cards(html):
	"""The post cards on a page, in order: (post id, repost label text or '')."""
	out = []
	for m in re.finditer(r'<div class="post-card" id="post-(\d+)"(.*?)<div class="post-card-head">', html, re.S):
		label = re.search(r'js-repost-label[^>]*>(.*?)</div>', m.group(2), re.S)
		text = ' '.join(re.sub(r'<[^>]+>', ' ', label.group(1)).split()) if label else ''
		out.append((int(m.group(1)), text))
	return out


class RepostTests(TestCase):
	def setUp(self):
		unn = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		other = University.objects.create(name='Other University', short_name='OU', email_domain='ou.edu.ng')
		self.john = self.student('john', unn)          # User A
		self.david = self.student('david', unn)        # User B
		self.cara = self.student('cara', unn)          # someone else in the feed
		self.outsider = self.student('out', other)
		self.post = Post.objects.create(author=self.john, content='Today was a great day at university!')
		self.client.force_login(self.david)

	def student(self, username, uni):
		user = User.objects.create_user(username, password='x', first_name=username.title())
		fac = Faculty.objects.get_or_create(university=uni, name='Sciences')[0]
		dep = Department.objects.get_or_create(faculty=fac, name='Computer Science')[0]
		lvl = Level.objects.get_or_create(department=dep, name='400 Level')[0]
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=username, university_email=f'{username}@{uni.email_domain}')
		return user

	def repost(self, post=None, action='repost'):
		return self.client.post(f'/post/{(post or self.post).pk}/repost/', {'action': action}, **AJAX)

	def quote(self, text, post=None):
		return self.client.post(f'/post/{(post or self.post).pk}/quote/', {'content': text}, **AJAX)

	# ---------------- simple reposts ----------------
	def test_repost_records_who_and_what_without_copying(self):
		res = self.repost().json()
		self.assertEqual((res['ok'], res['reposted'], res['reposts_count']), (True, True, 1))
		self.assertTrue(Repost.objects.filter(user=self.david, post=self.post).exists())
		self.assertEqual(Post.objects.count(), 1)                  # no copy of the post
		self.post.refresh_from_db()
		self.assertEqual(self.post.content, 'Today was a great day at university!')
		self.assertEqual(self.post.author, self.john)

	def test_reposting_twice_never_makes_two(self):
		self.repost(); res = self.repost().json()
		self.assertEqual((res['reposted'], res['reposts_count']), (True, 1))
		self.assertEqual(Repost.objects.count(), 1)
		with self.assertRaises(IntegrityError), transaction.atomic():
			Repost.objects.create(user=self.david, post=self.post)

	def test_undo_repost(self):
		self.repost()
		res = self.repost(action='undo').json()
		self.assertEqual((res['reposted'], res['reposts_count']), (False, 0))
		self.assertFalse(Repost.objects.exists())

	def test_no_action_toggles(self):
		self.assertTrue(self.client.post(f'/post/{self.post.pk}/repost/', **AJAX).json()['reposted'])
		self.assertFalse(self.client.post(f'/post/{self.post.pk}/repost/', **AJAX).json()['reposted'])

	def test_cannot_undo_someone_elses_repost(self):
		Repost.objects.create(user=self.cara, post=self.post)
		res = self.repost(action='undo').json()                    # David "undoes" — only his own row could go
		self.assertTrue(Repost.objects.filter(user=self.cara, post=self.post).exists())
		self.assertEqual(res['reposts_count'], 1)

	def test_repost_appears_in_home_feed_once_with_attribution(self):
		self.repost()
		self.client.force_login(self.cara)
		html = self.client.get('/home/').content.decode()
		self.assertEqual(cards(html), [(self.post.pk, 'David reposted')])
		self.assertIn('Today was a great day at university!', html)

	def test_feed_shows_you_reposted_and_counts_others_without_duplicates(self):
		Repost.objects.create(user=self.cara, post=self.post)
		self.repost()
		html = self.client.get('/home/').content.decode()
		self.assertEqual(cards(html), [(self.post.pk, 'You and 1 other reposted')])

	def test_reposted_post_moves_to_the_top_of_the_feed(self):
		newer = Post.objects.create(author=self.cara, content='A newer post')
		self.repost()                                              # repost the older one now
		ids = [c[0] for c in cards(self.client.get('/home/').content.decode())]
		self.assertEqual(ids, [self.post.pk, newer.pk])

	def test_following_tab_shows_reposts_by_people_you_follow(self):
		from .models import Follow
		Follow.objects.create(follower=self.cara, following=self.david, status=Follow.STATUS_ACCEPTED)
		self.repost()
		self.client.force_login(self.cara)
		self.assertEqual(cards(self.client.get('/home/?tab=following').content.decode()), [(self.post.pk, 'David reposted')])

	def test_repost_tab_on_profile(self):
		mine = Post.objects.create(author=self.david, content='David wrote this himself')
		self.repost()
		html = self.client.get('/u/david/?tab=repost').content.decode()
		listed = cards(html)
		self.assertIn((self.post.pk, 'You reposted'), listed)
		self.assertNotIn(mine.pk, [c[0] for c in listed])         # not just his own posts
		self.client.force_login(self.cara)
		self.assertIn((self.post.pk, 'David reposted'), cards(self.client.get('/u/david/?tab=repost').content.decode()))

	def test_posts_tab_shows_posts_quotes_and_reposts_in_time_order(self):
		mine = Post.objects.create(author=self.david, content='David wrote this himself')
		q = self.quote('Worth discussing').json()['post_id']
		self.repost()                                              # newest: repost of John's post
		expected = [(self.post.pk, 'David reposted'), (q, ''), (mine.pk, '')]
		self.client.force_login(self.cara)                         # what a follower sees
		self.assertEqual(cards(self.client.get('/u/david/').content.decode())[:3], expected)
		self.client.force_login(self.david)                        # and David on his own profile
		self.assertEqual(cards(self.client.get('/profile/').content.decode())[:3],
			[(self.post.pk, 'You reposted'), (q, ''), (mine.pk, '')])
		self.repost(action='undo')
		self.assertNotIn(self.post.pk, [c[0] for c in cards(self.client.get('/profile/').content.decode())])

	def test_reposting_your_own_post_moves_it_up_your_posts_tab(self):
		old = Post.objects.create(author=self.david, content='An older post of mine')
		newer = Post.objects.create(author=self.david, content='A newer post of mine')
		self.repost(old)
		ids = cards(self.client.get('/profile/').content.decode())
		self.assertEqual(ids[:2], [(old.pk, 'You reposted'), (newer.pk, '')])
		self.assertEqual([i for i, _ in ids].count(old.pk), 2)    # desktop + phone layout, once each

	def test_undo_removes_it_from_feed_and_profile(self):
		self.repost(); self.repost(action='undo')
		self.assertEqual(cards(self.client.get('/u/david/?tab=repost').content.decode()), [])
		self.assertContains(self.client.get('/u/david/?tab=repost'), 'No reposts yet')
		self.assertEqual(cards(self.client.get('/home/').content.decode()), [(self.post.pk, '')])

	def test_icon_shows_count_and_my_state(self):
		Repost.objects.create(user=self.cara, post=self.post)
		html = self.client.get('/home/').content.decode()
		self.assertRegex(html, r'js-repost-btn " data-post-id="%d" data-reposted="0"' % self.post.pk)
		self.assertRegex(html, r'js-repost-count">1</span>')
		self.repost()
		html = self.client.get('/home/').content.decode()
		self.assertRegex(html, r'js-repost-btn reposted" data-post-id="%d" data-reposted="1"' % self.post.pk)
		self.assertRegex(html, r'js-repost-count">2</span>')

	def test_repost_notifies_the_author_and_undo_takes_it_back(self):
		self.repost()
		n = Notification.objects.get(recipient=self.john, type=Notification.REPOST)
		self.assertEqual(n.actor, self.david)
		self.repost(action='undo')
		self.assertFalse(Notification.objects.filter(type=Notification.REPOST).exists())

	# ---------------- quotes ----------------
	def test_quote_creates_a_new_post_pointing_at_the_original(self):
		res = self.quote('This is an important discussion for university students.').json()
		q = Post.objects.get(pk=res['post_id'])
		self.assertEqual((q.author, q.quote_of, q.is_quote), (self.david, self.post, True))
		self.assertEqual(q.content, 'This is an important discussion for university students.')
		self.assertEqual(res['reposts_count'], 1)                  # quotes count on the icon, like X
		self.assertFalse(Repost.objects.exists())                  # a quote is not a repost
		self.post.refresh_from_db()
		self.assertEqual(self.post.content, 'Today was a great day at university!')
		self.assertIn('quote-embed', res['html'])
		self.assertIn('Today was a great day at university!', res['html'])

	def test_quote_in_feed_shows_comment_then_embedded_original(self):
		q = Post.objects.get(pk=self.quote('Worth discussing').json()['post_id'])
		self.client.force_login(self.cara)
		html = self.client.get('/home/').content.decode()
		card = html[html.index(f'id="post-{q.pk}"'):]
		card = card[:card.index('post-card-actions')]
		self.assertLess(card.index('Worth discussing'), card.index('class="quote-embed"'))
		self.assertIn(f'href="/post/{self.post.pk}/"', card)
		self.assertIn('@john', card)

	def test_quote_shows_on_profile_repost_and_posts_tabs(self):
		q = self.quote('Worth discussing').json()['post_id']
		self.assertIn(q, [c[0] for c in cards(self.client.get('/u/david/?tab=repost').content.decode())])
		self.assertIn(q, [c[0] for c in cards(self.client.get('/u/david/').content.decode())])

	def test_quote_needs_text_and_a_sane_length(self):
		self.assertEqual(self.quote('   ').status_code, 400)
		self.assertEqual(self.quote('x' * 501).status_code, 400)
		self.assertEqual(self.quote('   ').json()['error'], 'Add a comment, a photo or a video to quote this post.')
		self.assertEqual(Post.objects.count(), 1)

	# ---------------- quotes with your own photos / video ----------------
	def image(self, name='photo.png', colour=(30, 60, 200)):
		import io
		from PIL import Image
		from django.core.files.uploadedfile import SimpleUploadedFile
		buf = io.BytesIO()
		Image.new('RGB', (80, 60), colour).save(buf, 'PNG')
		return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')

	def quote_with(self, text, files):
		return self.client.post(f'/post/{self.post.pk}/quote/', {'content': text, 'media': files}, **AJAX)

	def test_quote_with_words_and_photos(self):
		import shutil, tempfile
		from django.test import override_settings
		tmp = tempfile.mkdtemp()
		try:
			with override_settings(MEDIA_ROOT=tmp):
				res = self.quote_with('Look at these', [self.image('a.png'), self.image('b.png', (200, 30, 30))]).json()
				q = Post.objects.get(pk=res['post_id'])
				self.assertEqual((q.is_quote, q.quote_of, q.media_items.count()), (True, self.post, 2))
				html = res['html']
				# your photos first, then the post you quoted
				self.assertLess(html.index('post-card-media-grid'), html.index('class="quote-embed"'))
				self.assertEqual(self.post.media_items.count(), 0)   # the original is untouched
		finally:
			shutil.rmtree(tmp, ignore_errors=True)

	def test_quote_with_only_a_photo(self):
		import shutil, tempfile
		from django.test import override_settings
		tmp = tempfile.mkdtemp()
		try:
			with override_settings(MEDIA_ROOT=tmp):
				res = self.quote_with('', [self.image()]).json()
				self.assertTrue(res['ok'])
				q = Post.objects.get(pk=res['post_id'])
				self.assertEqual((q.content, q.media_items.count()), ('', 1))
				self.client.force_login(self.john)
				self.assertContains(self.client.get('/notifications/'), 'quoted your post.')
		finally:
			shutil.rmtree(tmp, ignore_errors=True)

	def test_quote_media_follows_the_post_rules(self):
		res = self.quote_with('Too many', [self.image(f'{i}.png') for i in range(5)])
		self.assertEqual(res.status_code, 400)
		self.assertIn('up to 4 photos', res.json()['error'])
		self.assertEqual(Post.objects.count(), 1)

	def test_quote_notifies_the_author(self):
		q = self.quote('Worth discussing').json()['post_id']
		n = Notification.objects.get(recipient=self.john, type=Notification.QUOTE)
		self.assertEqual(n.post_id, q)
		self.client.force_login(self.john)
		self.assertContains(self.client.get('/notifications/'), 'quoted your post')

	def test_quote_of_a_quote_does_not_nest_forever(self):
		q1 = Post.objects.get(pk=self.quote('First quote').json()['post_id'])
		self.client.force_login(self.cara)
		q2 = Post.objects.get(pk=self.quote('Quoting the quote', post=q1).json()['post_id'])
		html = self.client.get(f'/post/{q2.pk}/').content.decode()
		self.assertEqual(html.count('class="quote-embed"'), 1)
		self.assertIn('Quoting @john', html)

	def test_deleted_original(self):
		q = Post.objects.get(pk=self.quote('Worth discussing').json()['post_id'])
		Repost.objects.create(user=self.cara, post=self.post)
		self.post.delete()
		q.refresh_from_db()
		self.assertIsNone(q.quote_of)
		self.assertTrue(q.is_quote)
		self.assertFalse(Repost.objects.exists())                  # reposts go with the post
		self.assertContains(self.client.get('/home/'), 'This post is unavailable.')
		self.assertEqual(self.client.get('/u/cara/?tab=repost').status_code, 200)

	def test_a_post_cannot_quote_itself(self):
		self.post.quote_of = self.post
		with self.assertRaises(IntegrityError), transaction.atomic():
			self.post.save()

	def test_quote_preview_for_the_composer(self):
		page = self.client.get(f'/post/{self.post.pk}/quote/preview/')
		self.assertContains(page, 'Today was a great day at university!')
		self.assertContains(page, 'quote-embed-static')

	# ---------------- permissions and validation ----------------
	def test_logged_out_users_cannot_repost_or_quote(self):
		self.client.logout()
		self.assertEqual(self.client.post(f'/post/{self.post.pk}/repost/').status_code, 302)
		self.assertEqual(self.client.post(f'/post/{self.post.pk}/quote/', {'content': 'hi'}).status_code, 302)
		self.assertFalse(Repost.objects.exists())
		self.assertEqual(Post.objects.count(), 1)

	def test_must_post(self):
		self.assertEqual(self.client.get(f'/post/{self.post.pk}/repost/', **AJAX).status_code, 405)
		self.assertEqual(self.client.get(f'/post/{self.post.pk}/quote/', **AJAX).status_code, 405)

	def test_csrf_is_enforced(self):
		from django.test import Client
		strict = Client(enforce_csrf_checks=True)
		strict.force_login(self.david)
		self.assertEqual(strict.post(f'/post/{self.post.pk}/repost/', **AJAX).status_code, 403)
		self.assertEqual(strict.post(f'/post/{self.post.pk}/quote/', {'content': 'x'}, **AJAX).status_code, 403)

	def test_missing_or_other_university_posts(self):
		self.assertEqual(self.client.post('/post/99999/repost/', **AJAX).status_code, 404)
		elsewhere = Post.objects.create(author=self.outsider, content='Elsewhere')
		self.assertEqual(self.repost(elsewhere).status_code, 404)
		self.assertEqual(self.quote('hi', elsewhere).status_code, 404)
		self.assertEqual(self.repost(elsewhere).json()['error'], "That post isn't available any more.")
		self.assertFalse(Repost.objects.exists())

	# ---------------- everything else keeps working ----------------
	def test_likes_and_comments_on_reposted_and_quoted_posts(self):
		self.repost()
		q = self.quote('Worth discussing').json()['post_id']
		for pid in (self.post.pk, q):
			self.assertTrue(self.client.post(f'/like/{pid}/toggle/', **AJAX).json()['liked'])
		self.assertEqual(Like.objects.count(), 2)
		self.client.post(f'/post/{self.post.pk}/comments/add/', {'content': 'Nice'}, **AJAX)
		self.assertEqual(Comment.objects.filter(post=self.post).count(), 1)
		self.assertEqual(self.client.get('/home/').status_code, 200)
