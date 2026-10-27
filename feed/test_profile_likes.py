"""The profile's Likes tab is private to its owner
(run: python manage.py test feed.test_profile_likes)."""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from .models import Like, Post

User = get_user_model()


class ProfileLikesPrivacyTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.ada = self.student('ada', uni, fac, dep, lvl)
		self.ben = self.student('ben', uni, fac, dep, lvl)
		self.ada_post = Post.objects.create(author=self.ada, content='Ada wrote this')
		self.liked = Post.objects.create(author=self.ben, content='A post Ada liked quietly')
		Like.objects.create(user=self.ada, post=self.liked)

	def student(self, username, uni, fac, dep, lvl):
		user = User.objects.create_user(username, password='x', first_name=username.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=username, university_email=f'{username}@unn.edu.ng')
		return user

	def lists(self, page):
		"""Just the profile's tab lists (not the sidebars, where popular posts appear)."""
		html = page.content.decode()
		return ' '.join(re.findall(r'<div class="profile-empty-state">(.*?)<div class="profile-(?:mobile|tabs)|<div class="profile-empty-state">(.*)', html, re.S)[0])

	def test_owner_sees_their_likes_tab_marked_private(self):
		self.client.force_login(self.ada)
		page = self.client.get('/profile/?tab=likes')
		self.assertContains(page, 'href="?tab=likes"', count=2)        # desktop + phone tab bars
		self.assertContains(page, 'A post Ada liked quietly')
		self.assertContains(page, 'Only you can see your likes.', count=2)

	def test_visitors_get_no_likes_tab(self):
		self.client.force_login(self.ben)
		page = self.client.get('/u/ada/')
		self.assertNotContains(page, 'href="?tab=likes"')
		self.assertContains(page, 'href="?tab=posts"')

	def test_visitors_cannot_open_likes_by_address(self):
		self.client.force_login(self.ben)
		page = self.client.get('/u/ada/?tab=likes')
		self.assertEqual(page.status_code, 200)
		self.assertNotIn('A post Ada liked quietly', self.lists(page))   # likes stay hidden…
		self.assertIn('Ada wrote this', self.lists(page))                # …they get Ada's posts instead
		self.assertNotContains(page, 'Only you can see your likes')

	def test_own_profile_by_username_is_still_the_owner(self):
		self.client.force_login(self.ada)
		self.assertContains(self.client.get('/u/ada/?tab=likes'), 'A post Ada liked quietly')
