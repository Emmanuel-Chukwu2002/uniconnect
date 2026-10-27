"""Polls in feed posts (feed/polls.py)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import Post, PostPoll, PostPollVote

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class PollTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.ada, self.ben, self.cy = [self.student(n, uni, fac, dep, lvl) for n in ('ada', 'ben', 'cy')]
		self.client.force_login(self.ada)

	def student(self, name, uni, fac, dep, lvl):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	def make(self, **extra):
		data = {'content': 'Best study spot?', 'poll': '1', 'poll_option_1': 'Library', 'poll_option_2': 'Hostel', 'poll_days': '3'}
		data.update(extra)
		return self.client.post('/post/new/', data)

	def test_create_poll(self):
		self.make(poll_option_3='library')                  # duplicate choice is dropped
		poll = PostPoll.objects.get()
		self.assertEqual([o.text for o in poll.options.all()], ['Library', 'Hostel'])
		self.assertAlmostEqual((poll.closes_at - timezone.now()).total_seconds(), 3 * 86400, delta=60)

	def test_poll_needs_two_choices_question_and_no_media(self):
		self.make(poll_option_2='')
		self.make(content='')
		self.make(media=SimpleUploadedFile('a.png', b'\x89PNG\r\n\x1a\n' + b'0' * 50, 'image/png'))
		self.assertFalse(PostPoll.objects.exists())
		self.client.post('/post/new/', {'content': 'Just text', 'poll_option_1': 'ignored'})   # poll switched off
		self.assertFalse(PostPoll.objects.exists())
		self.assertTrue(Post.objects.filter(content='Just text').exists())

	def test_voting(self):
		self.make()
		post = Post.objects.get()
		poll = post.poll
		library, hostel = poll.options.all()
		r = self.client.get('/home/')
		self.assertContains(r, 'Your poll')                      # the author sees results straight away (like X)
		self.assertNotContains(r, 'js-pp-vote')
		self.assertIn("own poll", self.client.post(f'/post/{post.pk}/poll/vote/', {'option': library.pk}, **AJAX).json()['error'])
		self.client.force_login(self.ben)
		self.assertContains(self.client.get('/home/'), 'js-pp-vote')   # others vote first
		r = self.client.post(f'/post/{post.pk}/poll/vote/', {'option': library.pk}, **AJAX)
		self.assertIn('100%', r.json()['html'])
		r = self.client.post(f'/post/{post.pk}/poll/vote/', {'option': hostel.pk}, **AJAX)  # votes are final
		self.assertIn('already voted', r.json()['error'])
		self.client.force_login(self.cy)
		self.client.post(f'/post/{post.pk}/poll/vote/', {'option': hostel.pk}, **AJAX)
		self.assertEqual(PostPollVote.objects.count(), 2)
		self.assertContains(self.client.get(f'/post/{post.pk}/'), '50%')
		poll.closes_at = timezone.now() - timedelta(minutes=1)
		poll.save()
		self.client.force_login(User.objects.create_user('dee', password='x'))
		self.assertIn('closed', self.client.post(f'/post/{post.pk}/poll/vote/', {'option': hostel.pk}, **AJAX).json()['error'])
