"""Composer tools: scheduled posts and locations (feed/scheduling.py)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import Notification, Post, PostPoll, Venue

User = get_user_model()
FMT = '%Y-%m-%dT%H:%M'


class ComposeToolsTests(TestCase):
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

	def later(self, **kw):
		return timezone.localtime(timezone.now() + timedelta(**kw)).strftime(FMT)

	def test_scheduled_post_hidden_until_due(self):
		r = self.client.post('/post/new/', {'content': 'Exam tips thread @ben', 'schedule_at': self.later(hours=2)})
		self.assertRedirects(r, '/post/scheduled/', fetch_redirect_response=False)
		post = Post.all_objects.get()
		self.assertTrue(post.is_scheduled)
		self.assertGreater(post.created_at, timezone.now() + timedelta(minutes=110))
		self.assertFalse(Post.objects.exists())                                   # hidden everywhere
		self.assertNotIn('Exam tips thread', self.client.get('/home/').content.decode())
		self.assertNotIn('Exam tips thread', self.client.get('/u/ada/').content.decode())
		self.assertEqual(self.client.get(f'/post/{post.pk}/').status_code, 404)
		self.assertFalse(Notification.objects.filter(recipient=self.ben).exists())  # mention waits
		self.assertContains(self.client.get('/post/scheduled/'), 'Exam tips thread')
		# Its time comes:
		Post.all_objects.filter(pk=post.pk).update(created_at=timezone.now() - timedelta(seconds=5))
		self.client.force_login(self.ben)
		self.assertIn('Exam tips thread', self.client.get('/home/').content.decode())
		self.assertTrue(Notification.objects.filter(recipient=self.ben, type=Notification.MENTION).exists())
		self.assertFalse(Post.all_objects.get().is_scheduled)

	def test_time_rules(self):
		html = self.client.post('/post/new/', {'content': 'too soon', 'schedule_at': self.later(minutes=1)}).content.decode()
		self.assertIn('at least 5 minutes', html)
		html = self.client.post('/post/new/', {'content': 'too far', 'schedule_at': self.later(days=40)}).content.decode()
		self.assertIn('30 days', html)
		self.assertFalse(Post.all_objects.exists())

	def test_change_time_post_now_delete(self):
		self.client.post('/post/new/', {'content': 'one', 'schedule_at': self.later(hours=2)})
		self.client.post('/post/new/', {'content': 'two', 'schedule_at': self.later(hours=3)})
		one, two = Post.all_objects.order_by('created_at')
		self.client.post(f'/post/scheduled/{one.pk}/time/', {'when': self.later(days=2)})
		one.refresh_from_db()
		self.assertGreater(one.created_at, timezone.now() + timedelta(days=1))
		self.client.post(f'/post/scheduled/{two.pk}/now/')
		self.assertTrue(Post.objects.filter(pk=two.pk).exists())
		self.client.post(f'/post/scheduled/{one.pk}/delete/')
		self.assertFalse(Post.all_objects.filter(pk=one.pk).exists())
		self.client.force_login(self.ben)                                      # not yours: 404
		self.client.post('/post/new/', {'content': 'bens', 'schedule_at': self.later(hours=2)})
		self.client.force_login(self.ada)
		self.assertEqual(self.client.post(f'/post/scheduled/{Post.all_objects.get(content="bens").pk}/delete/').status_code, 404)

	def test_scheduled_poll_opens_when_posted(self):
		self.client.post('/post/new/', {'content': 'Best study spot?', 'poll': '1', 'poll_option_1': 'Library',
			'poll_option_2': 'Hostel', 'poll_days': '1', 'schedule_at': self.later(days=2)})
		poll = PostPoll.objects.get()
		self.assertGreater(poll.closes_at, timezone.now() + timedelta(days=2, hours=23))

	def test_location(self):
		self.client.post('/post/new/', {'content': 'Reading here', 'location': '  Main   Library '})
		post = Post.objects.get()
		self.assertEqual(post.location, 'Main Library')
		html = self.client.get('/home/').content.decode()
		self.assertIn('bi-geo-alt-fill"></i> Main Library', html)
		Venue.objects.create(name='Main Auditorium', address='UNN')
		places = self.client.get('/places/', {'q': 'main'}).json()['places']
		self.assertEqual(places[0], 'Main Library')                          # tagged before: first
		self.assertIn('Main Auditorium', places)
		self.assertIn('Reading here', self.client.get('/search/?q=library&type=posts').content.decode())
