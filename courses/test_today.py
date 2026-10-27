"""Home's Today strip: deadlines, question of the day (run: python manage.py test courses)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from .models import ClassSlot, Course, CourseEnrollment, DailyAnswer, DailyQuestion, Deadline
from . import today as T

User = get_user_model()


class TodayStripTests(TestCase):
	def setUp(self):
		self.uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		self.ada, self.ben = (self.student(n) for n in ('ada', 'ben'))
		self.cos = Course.objects.create(university=self.uni, code='COS 401', title='Data Structures')
		for u in (self.ada, self.ben):
			CourseEnrollment.objects.create(user=u, course=self.cos)
		self.client.force_login(self.ada)

	def student(self, name):
		fac = Faculty.objects.get_or_create(university=self.uni, name='Sciences')[0]
		dep = Department.objects.get_or_create(faculty=fac, name='Computer Science')[0]
		lvl = Level.objects.get_or_create(department=dep, name='400 Level')[0]
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=self.uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	def test_home_shows_today_not_stories(self):
		html = self.client.get('/home/').content.decode()
		self.assertIn('Campus Pulse', html)                 # Campus Pulse replaced Quick access
		self.assertNotIn('aria-label="Quick access"', html)
		self.assertIn('data-sheet="tdAll"', html)           # Upcoming: View All
		self.assertNotIn('stories-row', html)
		self.assertRedirects(self.client.get('/messages/updates/'), '/messages/', fetch_redirect_response=False)

	def test_deadline_countdown_shared_with_coursemates(self):
		day = (timezone.localdate() + timedelta(days=3)).isoformat()
		self.client.post('/courses/deadlines/new/', {'course': self.cos.pk, 'kind': 'exam', 'title': 'First semester exam', 'date': day, 'time': '09:00'})
		d = Deadline.objects.get()
		self.assertEqual((d.created_by, d.kind), (self.ada, 'exam'))
		self.client.force_login(self.ben)                                  # a coursemate sees it
		html = self.client.get('/home/').content.decode()
		self.assertIn('COS 401 Exam', html)
		self.assertIn('>3d</b>', html)
		self.assertEqual(self.client.post(f'/courses/deadlines/{d.pk}/delete/').status_code, 404)   # only the one who added it
		self.client.force_login(self.ada)
		self.client.post(f'/courses/deadlines/{d.pk}/delete/')
		self.assertFalse(Deadline.objects.exists())
		r = self.client.post('/courses/deadlines/new/', {'course': self.cos.pk, 'kind': 'exam', 'date': '2020-01-01'})
		self.assertFalse(Deadline.objects.exists())                          # past dates are refused

	def test_countdown_text(self):
		now = timezone.now()
		self.assertEqual(T.countdown(now + timedelta(days=5, hours=1), now)[0], '5d')
		self.assertEqual(T.countdown(now + timedelta(minutes=30), now)[0], '30m')
		self.assertEqual(T.clock(timezone.datetime(2026, 1, 1, 14, 30).time()), '2:30pm')

	def test_question_of_the_day(self):
		q1 = DailyQuestion.objects.create(course=self.cos, text='FIFO?', option_a='Stack', option_b='Queue', correct='b')
		DailyQuestion.objects.create(course=self.cos, text='LIFO?', option_a='Stack', option_b='Queue', correct='a')
		today = timezone.localdate()
		q = T.question_for(self.cos, today)
		self.assertEqual(q, T.question_for(self.cos, today))                # same for everybody all day
		# Home's Quick access (where it used to show) was replaced by Campus Pulse; it's still in the strip data.
		self.assertIn('COS 401 Quiz', [it['label'] for it in T.strip(self.ada)['items']])
		r = self.client.post(f'/courses/daily/{q.pk}/answer/', {'choice': q.correct}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		self.assertTrue(r.json()['right'])
		self.assertIn('You got it right', r.json()['html'])
		self.client.post(f'/courses/daily/{q.pk}/answer/', {'choice': 'a' if q.correct == 'b' else 'b'})   # one try
		self.assertEqual(DailyAnswer.objects.get(user=self.ada).choice, q.correct)
		self.client.force_login(self.ben)
		r = self.client.post(f'/courses/daily/{q.pk}/answer/', {'choice': 'a' if q.correct == 'b' else 'b'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		self.assertFalse(r.json()['right'])
		self.assertIn('50% got it right', r.json()['html'])
		other = q1 if q != q1 else DailyQuestion.objects.exclude(pk=q1.pk).get()
		self.assertEqual(self.client.post(f'/courses/daily/{other.pk}/answer/', {'choice': 'a'}).status_code, 404)  # not today's

	def test_classes_today_in_strip(self):
		now = timezone.localtime()
		if now.hour >= 23:
			return
		ClassSlot.objects.create(user=self.ada, course=self.cos, day=now.weekday(), start=now.replace(hour=23, minute=0).time(), end=now.replace(hour=23, minute=59).time())
		self.assertIn('COS 401 at 11pm', [it['label'] for it in T.strip(self.ada)['items']])   # Quick access is now Campus Pulse

	def test_seed(self):
		from io import StringIO
		from django.core.management import call_command
		call_command('seed_today', stdout=StringIO())
		self.assertTrue(DailyQuestion.objects.filter(course=self.cos).count() >= 4)
		self.assertEqual(Deadline.objects.filter(course=self.cos).count(), 2)
		call_command('seed_today', '--reset', stdout=StringIO())
		self.assertEqual(Deadline.objects.filter(course=self.cos).count(), 2)

	def test_upcoming_has_every_kind_of_deadline(self):
		from datetime import time
		from feed.models import Event, Post, PostPoll
		from opportunities.models import Opportunity
		now = timezone.now()
		Deadline.objects.create(course=self.cos, kind='assignment', due_at=now + timedelta(days=5), created_by=self.ben)
		Event.objects.create(title='Hack Night', location='Lab 2', date=(now + timedelta(days=3)).date(), time=time(18, 0))
		Opportunity.objects.create(university=self.uni, posted_by=self.ben, title='Data Intern', organization='Acme',
			description='x', apply_email='a@b.co', deadline=(now + timedelta(days=4)).date())
		Opportunity.objects.create(university=self.uni, posted_by=self.ben, title='Far Away', organization='Acme',
			description='x', apply_email='a@b.co', deadline=(now + timedelta(days=12)).date())
		Opportunity.objects.create(university=self.uni, posted_by=self.ben, title='Open Role', organization='Acme',
			description='x', apply_email='a@b.co')
		poll_post = Post.objects.create(author=self.ben, content='Best day for revision?')
		PostPoll.objects.create(post=poll_post, closes_at=now + timedelta(days=1))
		from feed.scheduling import schedule
		schedule(Post.objects.create(author=self.ada, content='Exam tips thread'), now + timedelta(hours=5))
		got = {u['kind']: u['name'] for u in T.strip(self.ada)['upcoming']}
		self.assertEqual(set(got), {'deadline', 'event', 'opportunity', 'poll', 'scheduled'})
		self.assertEqual(got['opportunity'], 'Data Intern')
		self.assertNotIn('Far Away', [u['name'] for u in T.strip(self.ada)['upcoming']])   # a week or more away: not shown
		quick = [i['label'] for i in T.strip(self.ada)['items'] if i['kind'] == 'opportunity']
		self.assertIn('Open Role', quick)                         # new opportunities in Quick access
		html = self.client.get('/home/').content.decode()
		self.assertIn('Best day for revision?', html)
		self.assertIn('Your scheduled post', html)
		self.assertNotIn('Exam tips thread', html)          # its text stays hidden until it goes out
