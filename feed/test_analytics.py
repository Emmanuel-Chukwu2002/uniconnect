"""Post analytics (feed/analytics.py)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.analytics import nice_max, rate
from feed.models import Bookmark, Comment, Follow, Like, Post, PostView, Repost

User = get_user_model()


class AnalyticsTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		cs = Department.objects.create(faculty=fac, name='Computer Science')
		eco = Department.objects.create(faculty=fac, name='Economics')
		lvl = Level.objects.create(department=cs, name='400 Level')
		self.ada = self.student('ada', uni, fac, cs, lvl)
		self.ben = self.student('ben', uni, fac, cs, lvl)
		self.cy = self.student('cy', uni, fac, eco, lvl)
		self.post = Post.objects.create(author=self.ada, content='Notes for STA 422 are up')
		Follow.objects.create(follower=self.ben, following=self.ada, status=Follow.STATUS_ACCEPTED)

	def student(self, name, uni, fac, dep, lvl):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	def seen(self, user, *posts):
		self.client.force_login(user)
		return self.client.post('/posts/seen/', {'ids': ','.join(str(p.pk) for p in posts)}).json()

	def test_views_counted_once_a_day_and_not_your_own(self):
		self.assertEqual(self.seen(self.ben, self.post), {'recorded': 1})
		self.seen(self.ben, self.post)                                   # again today: still one
		self.seen(self.ada, self.post)                                   # the author: never counts
		self.client.force_login(self.cy)
		self.client.get(f'/post/{self.post.pk}/')                         # opened it
		self.assertEqual(PostView.objects.filter(kind=PostView.FEED).count(), 1)
		self.assertEqual(PostView.objects.filter(kind=PostView.DETAIL).count(), 1)
		PostView.objects.create(post=self.post, user=self.ben, kind=PostView.FEED, day=timezone.localdate() - timedelta(days=1))
		self.assertEqual(PostView.objects.count(), 3)

	def test_post_page_numbers(self):
		self.seen(self.ben, self.post)
		self.seen(self.cy, self.post)
		Like.objects.create(user=self.ben, post=self.post)
		Comment.objects.create(post=self.post, author=self.cy, content='thanks')
		Repost.objects.create(user=self.cy, post=self.post)
		Bookmark.objects.create(user=self.ben, post=self.post)
		Post.objects.create(author=self.ben, content='read this', quote_of=self.post, is_quote=True)
		self.client.force_login(self.ada)
		r = self.client.get(f'/post/{self.post.pk}/analytics/')
		self.assertEqual(r.context['views'], {'impressions': 2, 'reach': 2, 'opens': 0})
		self.assertEqual(r.context['eng']['total'], 5)
		self.assertEqual(r.context['rate'], '–')          # more engagements than tracked views: no fake 250%
		self.assertEqual(dict(r.context['audience']), {'Follow you': 50, 'Don’t follow you yet': 50, 'In your department': 50})
		self.assertContains(r, 'Impressions per day')
		self.assertContains(r, 'Show as a table')

	def test_only_the_author(self):
		self.client.force_login(self.ben)
		self.assertEqual(self.client.get(f'/post/{self.post.pk}/analytics/').status_code, 403)
		self.assertNotIn(f'/post/{self.post.pk}/analytics/', self.client.get('/home/').content.decode())
		self.client.force_login(self.ada)
		self.assertIn(f'/post/{self.post.pk}/analytics/', self.client.get('/home/').content.decode())

	def test_overview(self):
		self.seen(self.ben, self.post)
		Like.objects.create(user=self.ben, post=self.post)
		self.client.force_login(self.ada)
		r = self.client.get('/analytics/')
		tiles = {label: value for label, value, _ in r.context['tiles']}
		self.assertEqual(tiles, {'Impressions': '1', 'People reached': '1', 'Engagements': '1', 'New followers': '1'})
		self.assertEqual(r.context['top'], self.post)
		self.assertEqual(len(r.context['bars']), 28)
		self.assertEqual(r.context['bars'][-1]['n'], 1)

	def test_helpers(self):
		self.assertEqual([nice_max(n) for n in (0, 1, 4, 13, 72, 340)], [0, 1, 4, 15, 80, 400])
		self.assertEqual(rate(3, 0), '–')
		self.assertEqual(rate(1, 40), '2.5%')
