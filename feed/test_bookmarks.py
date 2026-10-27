"""Tests for bookmarks (run: python manage.py test feed.test_bookmarks)."""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Bookmark, Post

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class BookmarkTests(TestCase):
	def setUp(self):
		self.ada = User.objects.create_user('ada', password='x', first_name='Ada')
		self.ben = User.objects.create_user('ben', password='x', first_name='Ben')
		self.post = Post.objects.create(author=self.ben, content='Exam timetable is out')
		self.client.force_login(self.ada)

	def toggle(self):
		return self.client.post(f'/bookmark/{self.post.pk}/toggle/', **AJAX).json()['bookmarked']

	def test_toggle_saves_then_removes(self):
		self.assertTrue(self.toggle())
		self.assertTrue(Bookmark.objects.filter(user=self.ada, post=self.post).exists())
		self.assertFalse(self.toggle())
		self.assertFalse(Bookmark.objects.filter(user=self.ada, post=self.post).exists())

	def test_database_refuses_duplicates(self):
		Bookmark.objects.create(user=self.ada, post=self.post)
		with self.assertRaises(IntegrityError), transaction.atomic():
			Bookmark.objects.create(user=self.ada, post=self.post)

	def test_page_lists_only_my_bookmarks(self):
		other = Post.objects.create(author=self.ada, content='Only Ben saved this')
		Bookmark.objects.create(user=self.ada, post=self.post)
		Bookmark.objects.create(user=self.ben, post=other)
		page = self.client.get('/bookmarks/')
		self.assertContains(page, 'Exam timetable is out')
		self.assertNotContains(page, 'Only Ben saved this')
		self.assertContains(page, '<div class="profile-topbar-name">Bookmarks</div>', html=True)

	def test_empty_state(self):
		self.assertContains(self.client.get('/bookmarks/'), 'No bookmarks yet.')

	def test_deleted_post_leaves_no_broken_bookmark(self):
		Bookmark.objects.create(user=self.ada, post=self.post)
		self.post.delete()
		self.assertFalse(Bookmark.objects.exists())
		self.assertEqual(self.client.get('/bookmarks/').status_code, 200)

	def test_login_required(self):
		self.client.logout()
		self.assertEqual(self.client.get('/bookmarks/').status_code, 302)
		self.assertEqual(self.client.post(f'/bookmark/{self.post.pk}/toggle/').status_code, 302)
		self.assertFalse(Bookmark.objects.exists())

