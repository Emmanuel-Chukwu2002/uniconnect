"""Pinning a post to your profile (feed/views.py toggle_pin)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import PinnedPost, Post

User = get_user_model()


class PinnedPostTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.ada, self.ben = [self.student(n, uni, fac, dep, lvl) for n in ('ada', 'ben')]
		self.old = Post.objects.create(author=self.ada, content='My old intro post')
		self.new = Post.objects.create(author=self.ada, content='Something newer')
		self.client.force_login(self.ada)

	def student(self, name, uni, fac, dep, lvl):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	def test_pin_shows_first_once_and_unpin(self):
		self.client.post(f'/post/{self.old.pk}/pin/', {'next': '/profile/'})
		html = self.client.get('/u/ada/').content.decode()
		self.assertIn('Pinned', html)
		self.assertLess(html.index('My old intro post'), html.index('Something newer'))
		self.assertEqual(html.count('My old intro post'), html.count('Something newer'))   # not repeated lower down (the page has a phone and a desktop layout)
		self.assertIn('Unpin from profile', self.client.get('/home/').content.decode())
		self.client.post(f'/post/{self.new.pk}/pin/')                    # pinning another replaces it
		self.assertEqual(PinnedPost.objects.get().post, self.new)
		self.client.post(f'/post/{self.new.pk}/pin/')                    # again: unpin
		self.assertFalse(PinnedPost.objects.exists())

	def test_only_your_own_posts(self):
		self.client.force_login(self.ben)
		self.assertEqual(self.client.post(f'/post/{self.old.pk}/pin/').status_code, 403)
		self.assertFalse(PinnedPost.objects.exists())

	def test_deleting_the_post_unpins_it(self):
		PinnedPost.objects.create(user=self.ada, post=self.old)
		self.old.delete()
		self.assertFalse(PinnedPost.objects.exists())
		self.assertEqual(self.client.get('/u/ada/').status_code, 200)
