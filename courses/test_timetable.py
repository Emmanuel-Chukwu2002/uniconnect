"""Timetable (courses/timetable.py)."""
from datetime import time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from .models import ClassSlot, Course, CourseEnrollment

User = get_user_model()


class TimetableTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.ada, self.ben = [self.student(n, uni, fac, dep, lvl) for n in ('ada', 'ben')]
		self.course = Course.objects.create(university=uni, code='COS 401', title='Data Structures')
		for u in (self.ada, self.ben):
			CourseEnrollment.objects.create(user=u, course=self.course)
		self.client.force_login(self.ada)

	def student(self, name, uni, fac, dep, lvl):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	def add(self, **extra):
		data = {'course': self.course.pk, 'kind': 'lecture', 'day': 1, 'start': '10:00', 'end': '12:00', 'venue': 'LT 2'}
		data.update(extra)
		return self.client.post('/courses/timetable/add/', data)

	def test_add_show_edit_delete(self):
		self.add()
		slot = ClassSlot.objects.get()
		self.assertEqual((slot.user, slot.day, slot.start, slot.venue), (self.ada, 1, time(10), 'LT 2'))
		r = self.client.get('/courses/timetable/?day=1')
		self.assertContains(r, 'COS 401 – Data Structures')
		self.assertContains(r, 'LT 2')
		self.client.post(f'/courses/timetable/{slot.pk}/edit/', {'course': self.course.pk, 'kind': 'tutorial', 'day': 3,
			'start': '14:00', 'end': '15:00', 'venue': 'Room B'})
		slot.refresh_from_db()
		self.assertEqual((slot.kind, slot.day, slot.start), ('tutorial', 3, time(14)))
		self.client.force_login(self.ben)
		self.client.post(f'/courses/timetable/{slot.pk}/delete/')       # not his
		self.assertTrue(ClassSlot.objects.exists())
		self.client.force_login(self.ada)
		self.client.post(f'/courses/timetable/{slot.pk}/delete/')
		self.assertFalse(ClassSlot.objects.exists())

	def test_validation_and_clash_warning(self):
		self.add(end='09:00')                                           # ends before it starts
		self.add(course='', title='')                                  # neither course nor title
		self.assertFalse(ClassSlot.objects.exists())
		self.add(course='', title='SIWES briefing')
		self.assertEqual(ClassSlot.objects.get().name, 'SIWES briefing')
		self.add(day=1, start='11:00', end='13:00', course='', title='Club meeting')
		self.add()
		self.assertContains(self.client.get('/courses/timetable/?day=1'), 'Overlaps another class')

	def test_suggestions_from_classmates_and_home_card(self):
		ClassSlot.objects.create(user=self.ben, course=self.course, day=timezone.localdate().weekday(),
			start=time(0, 0), end=time(23, 59), venue='LT 2')
		r = self.client.get('/courses/timetable/')
		self.assertContains(r, 'From your classmates')
		self.assertContains(r, '1 classmate')
		slot = ClassSlot.objects.get()
		self.add(day=slot.day, start='00:00', end='23:59')              # "Add" copies it
		self.assertNotContains(self.client.get('/courses/timetable/'), 'From your classmates')
		self.assertContains(self.client.get('/home/'), 'Campus Pulse')       # top of Home

	def test_seed_timetable(self):
		from io import StringIO
		from django.core.management import call_command
		self.ada.last_login = timezone.now()
		self.ada.save()
		call_command('seed_timetable', stdout=StringIO())
		self.assertGreaterEqual(ClassSlot.objects.filter(user=self.ada).count(), 11)
		self.assertFalse(ClassSlot.objects.filter(user=self.ben).exists())        # never signed in: left alone
		n = ClassSlot.objects.count()
		call_command('seed_timetable', stdout=StringIO())                        # already has classes: skipped
		self.assertEqual(ClassSlot.objects.count(), n)
		call_command('seed_timetable', '--reset', stdout=StringIO())
		self.assertEqual(ClassSlot.objects.count(), n)


class TimetableSessionTests(TestCase):
	"""Study sessions you're going to show on the Timetable and Home."""
	setUp = TimetableTests.setUp
	student = TimetableTests.student

	def make(self, when, place='Faculty library', status='going', who=None):
		from studygroups.models import GroupSession, GroupSessionRSVP as R, StudyGroup, StudyGroupMember as M
		who = who or self.ada
		g = StudyGroup.objects.filter(name='COS 401 crew').first()
		if g is None:
			g = StudyGroup.objects.create(name='COS 401 crew', university=self.ada.student_profile.university, created_by=self.ada)
			M.objects.create(group=g, user=self.ada, role=M.OWNER)
			M.objects.create(group=g, user=self.ben)
		s = GroupSession.objects.create(group=g, created_by=self.ada, title='Past questions', starts_at=when, duration=60, place=place)
		R.objects.create(session=s, user=who, status=status)
		return s

	def test_session_on_its_day_with_a_clash_warning(self):
		from datetime import datetime, timedelta
		day = timezone.localdate() + timedelta(days=2)
		ClassSlot.objects.create(user=self.ada, course=self.course, kind='lecture', day=day.weekday(), start=time(10), end=time(12))
		self.make(timezone.make_aware(datetime.combine(day, time(11, 0))))
		page = self.client.get(f'/courses/timetable/?day={day.weekday()}')
		html = page.content.decode()
		self.assertIn('Past questions', html)
		self.assertIn('Study session', html)
		self.assertIn('Overlaps your COS 401 lecture', html)
		self.assertEqual([('slot' in i, 'session' in i) for i in page.context['items']], [(True, False), (False, True)])
		self.assertEqual(page.context['week'][day.weekday()]['count'], 2)

	def test_only_going_or_maybe_and_not_cancelled(self):
		from datetime import datetime, timedelta
		day = timezone.localdate() + timedelta(days=1)
		at = timezone.make_aware(datetime.combine(day, time(15, 0)))
		self.make(at, status='no')
		gone = self.make(at, who=self.ben)                 # Ben's, not Ada's
		page = self.client.get(f'/courses/timetable/?day={day.weekday()}')
		self.assertEqual(page.context['day_sessions'], [])
		maybe = self.make(at, status='maybe')
		page = self.client.get(f'/courses/timetable/?day={day.weekday()}')
		self.assertContains(page, 'You said maybe')
		maybe.is_cancelled = True; maybe.save()
		self.assertEqual(self.client.get(f'/courses/timetable/?day={day.weekday()}').context['day_sessions'], [])

	def test_today_on_home(self):
		from datetime import timedelta
		later = timezone.now() + timedelta(hours=1)
		if timezone.localtime(later).date() != timezone.localdate():
			self.skipTest('too close to midnight')
		self.make(later, place='LT 3')
		home = self.client.get('/home/').content.decode()
		# Quick access (where sessions used to show as circles) is now Campus Pulse; still in the strip data.
		from courses.today import strip
		self.assertIn('Past questions', [it.get('title') for it in strip(self.ada)['items'] if it['kind'] == 'session'])
		self.assertTrue(any(it['label'].startswith('Study at') for it in strip(self.ada)['items'] if it['kind'] == 'session'))
