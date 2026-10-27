"""Notification tabs and "Mark all as read" (feed/views.py notifications_page)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import Notification as N, Post
from feed.notifications import notify, unread_by_tab, unread_count

User = get_user_model()


class NotificationTabTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.me, self.amaka, self.tunde = [self.student(n, uni, fac, dep, lvl) for n in ('me', 'amaka', 'tunde')]
		post = Post.objects.create(author=self.me, content='Hello @me')
		notify(self.me, self.amaka, N.LIKE_POST, post=post)
		notify(self.me, self.tunde, N.LIKE_POST, post=post)      # grouped with Amaka's like
		notify(self.me, self.amaka, N.MENTION, post=post)
		notify(self.me, self.tunde, N.FOLLOW)
		self.client.force_login(self.me)

	def student(self, name, uni, fac, dep, lvl):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	def test_counts_per_tab(self):
		self.assertEqual(unread_by_tab(self.me), {'all': 3, 'mentions': 1, 'activity': 2, 'groups': 0, 'market': 0})

	def test_tab_shows_only_its_kinds_and_marks_only_those_read(self):
		r = self.client.get('/notifications/?tab=mentions')
		self.assertContains(r, 'mentioned you')
		self.assertNotContains(r, 'liked your')
		self.assertNotContains(r, 'started following you')
		self.assertEqual(unread_by_tab(self.me)['mentions'], 0)
		self.assertEqual(unread_by_tab(self.me)['activity'], 2)       # other tabs stay unread
		tabs = {t['key']: t['unread'] for t in r.context['tabs']}
		self.assertEqual((tabs['all'], tabs['activity']), (2, 2))
		self.assertContains(r, 'Mark all as read')

	def test_mark_all_as_read(self):
		self.client.post('/notifications/mark-all/', {'tab': 'groups'})
		self.assertEqual(unread_count(self.me), 0)
		self.assertNotContains(self.client.get('/notifications/?tab=groups'), 'Mark all as read')
		self.assertContains(self.client.get('/notifications/?tab=groups'), 'Nothing from groups or courses yet')
