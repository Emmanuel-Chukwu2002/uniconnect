"""Threads (feed/threads.py)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import Notification, Post, PostDraft

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class ThreadTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.ada, self.ben = [self.student(n, uni, fac, dep, lvl) for n in ('ada', 'ben')]
		self.client.force_login(self.ada)

	def student(self, name, uni, fac, dep, lvl):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	def post_thread(self, *texts, **extra):
		return self.client.post('/post/new/', {'content': texts[0], 'thread_part': list(texts[1:]), **extra})

	def test_write_and_read_a_thread(self):
		r = self.post_thread('Exam tips 🧵', 'Do past questions #STA341', '', 'Sleep, @ben')
		root = Post.objects.get(content='Exam tips 🧵')
		self.assertRedirects(r, f'/post/{root.pk}/')
		parts = list(Post.objects.filter(thread_root=root).order_by('thread_index'))
		self.assertEqual([(p.content, p.thread_index) for p in parts], [('Do past questions #STA341', 1), ('Sleep, @ben', 2)])
		self.assertTrue(Notification.objects.filter(recipient=self.ben, post=parts[1]).exists())   # mention in a part

		home = self.client.get('/home/').content.decode()
		self.assertIn('Exam tips', home)
		self.assertIn('Show this thread', home)
		self.assertNotIn('Do past questions', home)                       # parts only on the post page
		page = self.client.get(f'/post/{parts[0].pk}/').content.decode()
		for text in ('Exam tips', 'Do past questions', 'Sleep,', 'Add another post'):
			self.assertIn(text, page)
		self.assertIn('Part of a thread', self.client.get('/hashtag/STA341/', follow=True).content.decode())
		self.client.force_login(self.ben)
		self.assertNotIn('Add another post', self.client.get(f'/post/{root.pk}/').content.decode())

	def test_add_to_thread_later_and_only_your_own(self):
		root = Post.objects.create(author=self.ada, content='First')
		self.assertContains(self.client.get(f'/post/new/?thread={root.pk}'), 'Adding to your thread')
		r = self.client.post('/post/new/', {'content': 'Second', 'thread': root.pk, 'thread_part': ['Third']})
		self.assertRedirects(r, f'/post/{root.pk}/')
		self.assertEqual(list(Post.objects.filter(thread_root=root).order_by('thread_index').values_list('content', flat=True)),
			['Second', 'Third'])
		bens = Post.objects.create(author=self.ben, content='Not yours')
		self.client.post('/post/new/', {'content': 'Sneaky', 'thread': bens.pk})
		self.assertIsNone(Post.objects.get(content='Sneaky').thread_root)   # a plain post instead

	def test_limits_and_delete(self):
		r = self.post_thread('Too long', 'x' * 501)
		self.assertEqual(r.status_code, 200)
		self.assertFalse(Post.objects.filter(content='Too long').exists())
		self.assertContains(r, 'up to 500 characters')
		self.post_thread('Big', *[f'part {i}' for i in range(25)])
		self.assertFalse(Post.objects.filter(content='Big').exists())
		self.post_thread('Short', 'two', 'three')
		root = Post.objects.get(content='Short')
		self.assertContains(self.client.get('/home/'), 'Delete the whole thread (3 posts)')
		self.client.post(f'/post/{root.pk}/delete/')
		self.assertFalse(Post.all_objects.filter(content__in=['two', 'three']).exists())

	def test_scheduled_thread_goes_out_together(self):
		when = timezone.localtime(timezone.now() + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M')
		self.post_thread('Later', 'later two', schedule_at=when)
		root = Post.all_objects.get(content='Later')
		part = Post.all_objects.get(content='later two')
		self.assertTrue(root.is_scheduled and part.is_scheduled and part.created_at > root.created_at)
		listing = self.client.get('/post/scheduled/').content.decode()
		self.assertIn('Thread · 2 posts go out together', listing)
		self.assertNotIn('later two', listing)
		self.client.post(f'/post/scheduled/{root.pk}/now/')
		part.refresh_from_db()
		self.assertFalse(part.is_scheduled)
		self.assertTrue(Post.objects.filter(content='later two').exists())

	def test_drafts_keep_the_thread(self):
		root = Post.objects.create(author=self.ada, content='Mine')
		self.client.post('/post/drafts/save/', {'content': 'Start', 'thread_part': ['Next', ' ']}, **AJAX)
		self.client.post('/post/drafts/save/', {'content': 'More', 'thread': root.pk}, **AJAX)
		a, b = PostDraft.objects.order_by('pk')
		self.assertEqual((a.thread_parts, b.thread_root_id), (['Next'], root.pk))
		page = self.client.get('/post/drafts/').content.decode()
		self.assertIn('Thread · 2 posts', page)
		self.assertIn('Adding to your thread', page)
		self.assertContains(self.client.get(f'/post/new/?draft={b.pk}'), 'Adding to your thread')


class ThreadMediaTests(TestCase):
	"""Every post in a thread can have its own photos (up to 4) or video."""
	setUp = ThreadTests.setUp
	student = ThreadTests.student

	def png(self, name):
		import io
		from django.core.files.uploadedfile import SimpleUploadedFile
		from PIL import Image
		buf = io.BytesIO(); Image.new('RGB', (8, 8), 'red').save(buf, 'PNG')
		return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')

	def test_parts_have_their_own_media(self):
		import shutil, tempfile
		from django.core.files.uploadedfile import SimpleUploadedFile
		from django.test import override_settings
		tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp, True)
		with override_settings(MEDIA_ROOT=tmp):
			self.client.post('/post/new/', {'content': 'Faculty week 🧵', 'thread_part': ['Day 1', '', 'Day 3'],
				'thread_media_0': [self.png('a.png'), self.png('b.png')],
				'thread_media_1': [SimpleUploadedFile('demo.mp4', b'\x00\x00\x00\x18ftypmp42', content_type='video/mp4')]})
			root = Post.objects.get(content='Faculty week 🧵')
			parts = list(Post.objects.filter(thread_root=root).order_by('thread_index'))
			self.assertEqual([p.content for p in parts], ['Day 1', '', 'Day 3'])       # a photo-only box counts
			self.assertEqual([p.media_items.count() for p in parts], [2, 1, 0])
			self.assertTrue(parts[1].media_items.get().is_video)
			# Photos and a video in one box: refused, nothing posted.
			r = self.client.post('/post/new/', {'content': 'Mixed', 'thread_part': ['x'],
				'thread_media_0': [self.png('c.png'), SimpleUploadedFile('v.mp4', b'\x00\x00\x00\x18ftypmp42', content_type='video/mp4')]})
			self.assertEqual(r.status_code, 200)
			self.assertFalse(Post.objects.filter(content='Mixed').exists())

	def test_drafts_keep_part_media(self):
		import shutil, tempfile
		from django.test import override_settings
		tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp, True)
		with override_settings(MEDIA_ROOT=tmp):
			self.client.post('/post/drafts/save/', {'content': 'Start', 'thread_part': ['Two', 'Three'],
				'thread_media_1': [self.png('three.png')]}, **AJAX)
			d = PostDraft.objects.get()
			from feed.drafts import draft_payload
			data = draft_payload(d)
			self.assertEqual((data['thread'], list(data['thread_media'].keys()), data['media']), (['Two', 'Three'], ['2'], []))


class ThreadEditDeleteTests(TestCase):
	"""Editing or deleting one post of a thread leaves the rest alone."""
	setUp = ThreadTests.setUp
	student = ThreadTests.student

	def make(self):
		root = Post.objects.create(author=self.ada, content='Exam tips 🧵')
		parts = [Post.objects.create(author=self.ada, content=t, thread_root=root, thread_index=i + 1)
			for i, t in enumerate(['Two', 'Three', 'Four'])]
		return root, parts

	def contents(self, root):
		return [root.content] + list(Post.objects.filter(thread_root=root).order_by('thread_index').values_list('content', flat=True))

	def test_delete_a_later_post(self):
		root, parts = self.make()
		r = self.client.post(f'/post/{parts[1].pk}/delete/', {'on_detail': '1', 'next': '/home/'})
		self.assertRedirects(r, f'/post/{root.pk}/', fetch_redirect_response=False)
		self.assertEqual(self.contents(root), ['Exam tips 🧵', 'Two', 'Four'])

	def test_delete_just_the_first_post(self):
		root, parts = self.make()
		r = self.client.post(f'/post/{root.pk}/delete/', {'scope': 'one', 'on_detail': '1'})
		new_root = Post.objects.get(pk=parts[0].pk)
		self.assertRedirects(r, f'/post/{new_root.pk}/', fetch_redirect_response=False)
		self.assertIsNone(new_root.thread_root_id)
		self.assertEqual(self.contents(new_root), ['Two', 'Three', 'Four'])
		self.assertFalse(Post.all_objects.filter(pk=root.pk).exists())
		self.assertContains(self.client.get('/home/'), 'Show this thread')

	def test_delete_the_whole_thread(self):
		root, parts = self.make()
		self.client.post(f'/post/{root.pk}/delete/', {'scope': 'thread', 'next': '/home/'})
		self.assertFalse(Post.all_objects.filter(pk__in=[root.pk] + [p.pk for p in parts]).exists())

	def test_old_delete_form_still_deletes_the_thread(self):
		root, parts = self.make()
		self.client.post(f'/post/{root.pk}/delete/', {'next': '/home/'})
		self.assertFalse(Post.all_objects.filter(pk__in=[p.pk for p in parts]).exists())

	def test_only_the_author(self):
		root, parts = self.make()
		self.client.force_login(self.ben)
		self.assertEqual(self.client.post(f'/post/{parts[0].pk}/delete/').status_code, 403)
		self.assertEqual(len(self.contents(root)), 4)

	def test_menu_offers_both_choices_on_the_first_post(self):
		root, parts = self.make()
		page = self.client.get(f'/post/{root.pk}/').content.decode()
		self.assertIn('Delete just this post', page)
		self.assertIn('Delete the whole thread (4 posts)', page)
		self.assertIn('Delete this post from your thread?', page)          # a later post's own delete

	def test_edit_one_post(self):
		root, parts = self.make()
		page = self.client.get(f'/post/{parts[1].pk}/edit/').content.decode()
		self.assertIn('Post 3 of 4 in your thread', page)
		self.client.post(f'/post/{parts[1].pk}/edit/', {'content': 'Three (fixed)', 'next': f'/post/{root.pk}/'})
		self.assertEqual(self.contents(root), ['Exam tips 🧵', 'Two', 'Three (fixed)', 'Four'])
		self.assertTrue(Post.objects.get(pk=parts[1].pk).is_edited)
