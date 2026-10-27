"""Bookmark folders (feed/bookmark_folders.py)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import Bookmark, BookmarkFolder, Post

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class BookmarkFolderTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.ada, self.ben = [self.student(n, uni, fac, dep, lvl) for n in ('ada', 'ben')]
		self.p1 = Post.objects.create(author=self.ben, content='Past questions for STA 341')
		self.p2 = Post.objects.create(author=self.ben, content='Cultural day is Friday')
		self.client.force_login(self.ada)

	def student(self, name, uni, fac, dep, lvl):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	def test_new_folder_with_a_post_then_move_it(self):
		r = self.client.post('/bookmarks/folders/new/', {'name': '  Exam   prep ', 'post': self.p1.pk}, **AJAX).json()
		exam = BookmarkFolder.objects.get(user=self.ada)
		self.assertEqual((exam.name, r['message']), ('Exam prep', 'Saved to Exam prep.'))
		self.assertEqual(Bookmark.objects.get(user=self.ada, post=self.p1).folder, exam)   # bookmarked and filed
		d = self.client.get(f'/bookmarks/folders/?post={self.p1.pk}').json()
		self.assertEqual((d['current'], d['folders'][0]['n']), (exam.pk, 1))
		# Same name again (any case) isn't allowed.
		self.assertEqual(self.client.post('/bookmarks/folders/new/', {'name': 'exam PREP'}, **AJAX).status_code, 400)
		# Back to no folder: still bookmarked.
		self.client.post('/bookmarks/folders/put/', {'post': self.p1.pk, 'folder': ''}, **AJAX)
		self.assertIsNone(Bookmark.objects.get(user=self.ada, post=self.p1).folder)

	def test_page_shows_folders_and_filters(self):
		exam = BookmarkFolder.objects.create(user=self.ada, name='Exam prep')
		Bookmark.objects.create(user=self.ada, post=self.p1, folder=exam)
		Bookmark.objects.create(user=self.ada, post=self.p2)
		html = self.client.get('/bookmarks/').content.decode()
		self.assertIn('Exam prep', html)
		self.assertIn('Cultural day', html)
		html = self.client.get(f'/bookmarks/?folder={exam.pk}').content.decode()
		self.assertIn('Past questions', html)
		self.assertNotIn('Cultural day', html)
		self.assertIn('Move to a bookmark folder', html)                          # the ... menu of a saved post

	def test_rename_delete_and_privacy(self):
		exam = BookmarkFolder.objects.create(user=self.ada, name='Exam prep')
		Bookmark.objects.create(user=self.ada, post=self.p1, folder=exam)
		self.client.post(f'/bookmarks/folders/{exam.pk}/rename/', {'name': 'Exams'})
		exam.refresh_from_db()
		self.assertEqual(exam.name, 'Exams')
		bens = BookmarkFolder.objects.create(user=self.ben, name='Ben stuff')
		self.assertEqual(self.client.get(f'/bookmarks/?folder={bens.pk}').status_code, 302)          # not yours
		self.assertEqual(self.client.post(f'/bookmarks/folders/{bens.pk}/delete/').status_code, 404)
		self.assertEqual(self.client.post('/bookmarks/folders/put/', {'post': self.p2.pk, 'folder': bens.pk}, **AJAX).status_code, 404)
		self.assertNotIn('Ben stuff', str(self.client.get('/bookmarks/folders/').json()))
		self.client.post(f'/bookmarks/folders/{exam.pk}/delete/')
		self.assertFalse(BookmarkFolder.objects.filter(pk=exam.pk).exists())
		self.assertIsNone(Bookmark.objects.get(user=self.ada, post=self.p1).folder)                 # kept, back in All
