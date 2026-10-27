"""Class reminders (courses/reminders.py)."""
import io
from datetime import datetime, time, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from courses.models import ClassSlot, Course
from courses.reminders import due_reminders
from feed.models import Notification

User = get_user_model()


class ReminderTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.me = User.objects.create_user('ada', password='x', first_name='Ada')
		StudentProfile.objects.create(user=self.me, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number='1', university_email='ada@unn.edu.ng')
		self.course = Course.objects.create(university=uni, code='COS 401', title='Data Structures')
		# A Monday, 9:50 local time.
		self.now = timezone.make_aware(datetime(2026, 10, 19, 9, 50))
		self.soon = ClassSlot.objects.create(user=self.me, course=self.course, kind='lecture', day=0, start=time(10, 0), end=time(12, 0), venue='LT 2')
		ClassSlot.objects.create(user=self.me, course=self.course, kind='tutorial', day=0, start=time(14, 0), end=time(15, 0))   # later
		ClassSlot.objects.create(user=self.me, course=self.course, kind='lecture', day=0, start=time(9, 0), end=time(11, 0))     # already on
		ClassSlot.objects.create(user=self.me, course=self.course, kind='lecture', day=1, start=time(10, 0), end=time(12, 0))    # tomorrow

	def fresh(self):
		return User.objects.get(pk=self.me.pk)   # the once-per-request guard lives on the user object

	def test_only_the_class_starting_soon_once(self):
		made = due_reminders(self.fresh(), self.now)
		self.assertEqual([n.class_slot for n in made], [self.soon])
		self.assertEqual(due_reminders(self.fresh(), self.now + timedelta(minutes=3)), [])     # not twice
		self.assertEqual(Notification.objects.filter(type=Notification.CLASS_REMINDER).count(), 1)

	def test_wording_link_and_poll(self):
		self.client.force_login(self.me)
		with mock.patch('django.utils.timezone.now', return_value=self.now):
			data = self.client.get('/notifications/count/', HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()
		self.assertEqual(data['unread'], 1)
		self.assertEqual(data['reminders'][0]['text'], 'COS 401 lecture starts at 10:00 AM · LT 2')
		self.assertEqual(data['reminders'][0]['title'], 'Class in 10 minutes')
		html = self.client.get('/notifications/').content.decode()
		self.assertIn('Your <strong>COS 401</strong> lecture starts at 10:00 AM in <strong>LT 2</strong>.', html)
		self.assertIn('bi-alarm', html)
		n = Notification.objects.get()
		self.assertRedirects(self.client.get(f'/notifications/{n.pk}/open/'), '/courses/timetable/?day=0', fetch_redirect_response=False)

	def test_can_switch_off(self):
		self.me.student_profile.muted_notifications = [Notification.CLASS_REMINDER]
		self.me.student_profile.save()
		self.assertEqual(due_reminders(self.fresh(), self.now), [])

	def test_command(self):
		with mock.patch('django.utils.timezone.now', return_value=self.now):
			call_command('send_class_reminders', stdout=io.StringIO())
		self.assertEqual(Notification.objects.filter(recipient=self.me, class_slot=self.soon).count(), 1)
