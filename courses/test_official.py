"""Calendar export, one-off class changes and the department's official timetable
(courses/calendar_feed.py, courses/schedule.py, courses/official.py, adminpanel timetable)."""
import io
import zipfile
from datetime import datetime, time, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from adminpanel.models import AdminRole
from feed.models import Notification

from . import official
from .calendar_feed import build_ics
from .models import ClassChange, ClassSlot, Course, CourseEnrollment, OfficialClass, OfficialClassSkip, TimetableFeed
from .reminders import due_reminders
from .schedule import occurrences_on
from .timetable import today_classes

User = get_user_model()


def next_weekday(day, weeks=0):
	today = timezone.localdate()
	return today + timedelta(days=(day - today.weekday()) % 7 + 7 * weeks)


class Base(TestCase):
	def setUp(self):
		self.uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		self.other_uni = University.objects.create(name='University of Ibadan', short_name='UI', email_domain='ui.edu.ng')
		fac = Faculty.objects.create(university=self.uni, name='Sciences')
		self.dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=self.dep, name='400 Level')
		self.ada, self.ben = [self.student(n, fac, lvl) for n in ('ada', 'ben')]
		self.course = Course.objects.create(university=self.uni, code='COS 401', title='Data Structures')
		for u in (self.ada, self.ben):
			CourseEnrollment.objects.create(user=u, course=self.course)

	def student(self, name, fac, lvl):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=self.uni, faculty=fac, department=self.dep, level=lvl,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	def slot(self, user=None, day=None, start=time(10, 0), end=time(12, 0), **extra):
		day = timezone.localdate().weekday() if day is None else day
		return ClassSlot.objects.create(user=user or self.ada, course=self.course, kind='lecture', day=day,
			start=start, end=end, venue='LT 2', **extra)


class ClassChangeTests(Base):
	def test_cancel_this_week_only(self):
		s = self.slot(day=1)
		d = next_weekday(1)
		self.client.force_login(self.ada)
		self.client.post(f'/courses/timetable/{s.pk}/change/', {'date': d.isoformat(), 'action': 'cancel'})
		[o] = occurrences_on(self.ada, d)
		self.assertEqual(o.state, 'cancelled')
		self.assertFalse(o.active)
		self.assertTrue(occurrences_on(self.ada, d + timedelta(days=7))[0].active)     # next week as normal
		self.client.post(f'/courses/timetable/{s.pk}/change/', {'date': d.isoformat(), 'action': 'clear'})
		self.assertFalse(ClassChange.objects.exists())

	def test_move_to_another_day(self):
		s = self.slot(day=1)
		d = next_weekday(1)
		thu = d + timedelta(days=2)
		self.client.force_login(self.ada)
		self.client.post(f'/courses/timetable/{s.pk}/change/', {'date': d.isoformat(), 'action': 'move',
			'new_date': thu.isoformat(), 'new_start': '14:00', 'new_end': '16:00', 'new_venue': 'LT 3'})
		self.assertEqual(occurrences_on(self.ada, d)[0].state, 'moved_away')
		[o] = occurrences_on(self.ada, thu)
		self.assertEqual((o.state, o.start, o.venue), ('moved_in', time(14, 0), 'LT 3'))
		page = self.client.get(f'/courses/timetable/?day={thu.weekday()}')
		self.assertContains(page, 'Moved here from')

	def test_bad_change_refused(self):
		s = self.slot(day=1)
		self.client.force_login(self.ada)
		wrong_day = next_weekday(2).isoformat()
		self.client.post(f'/courses/timetable/{s.pk}/change/', {'date': wrong_day, 'action': 'cancel'})
		self.client.post(f'/courses/timetable/{s.pk}/change/', {'date': next_weekday(1).isoformat(), 'action': 'move',
			'new_start': '14:00', 'new_end': '13:00'})
		self.assertFalse(ClassChange.objects.exists())
		self.client.force_login(self.ben)             # not his class
		r = self.client.post(f'/courses/timetable/{s.pk}/change/', {'date': next_weekday(1).isoformat(), 'action': 'cancel'})
		self.assertEqual(r.status_code, 404)

	def test_home_and_reminders_follow_changes(self):
		now = timezone.localtime()
		start = (now + timedelta(minutes=10)).time().replace(second=0, microsecond=0)
		if start < now.time() or start.hour >= 23:      # too close to midnight to test today
			return
		s = self.slot(start=start, end=time(23, 59))
		ClassChange.objects.create(slot=s, date=now.date(), status=ClassChange.CANCELLED)
		self.assertEqual(today_classes(self.ada), [])
		self.assertEqual(due_reminders(self.ada), [])
		ClassChange.objects.all().delete()
		self.ada._reminders_checked = False
		self.assertEqual(len(due_reminders(self.ada)), 1)


class CalendarTests(Base):
	def test_feed_has_weekly_classes_changes_and_alarm(self):
		s = self.slot(day=1)
		d = next_weekday(1, weeks=1)
		ClassChange.objects.create(slot=s, date=d, status=ClassChange.CANCELLED)
		ClassChange.objects.create(slot=s, date=d + timedelta(days=7), status=ClassChange.MOVED,
			new_date=d + timedelta(days=9), new_start=time(14, 0), new_end=time(16, 0))
		ics = build_ics(self.ada, 'https://uniconnect.example/')
		self.assertIn('BEGIN:VCALENDAR', ics)
		self.assertIn('RRULE:FREQ=WEEKLY', ics)
		self.assertIn('SUMMARY:COS 401 Lecture', ics)
		self.assertIn('LOCATION:LT 2', ics)
		self.assertIn(f'EXDATE;TZID=', ics)
		self.assertIn(d.strftime('%Y%m%d') + 'T100000', ics)
		self.assertIn('RECURRENCE-ID;TZID=', ics)
		self.assertIn('TRIGGER:-PT15M', ics)
		self.assertTrue(all(len(line.encode()) <= 75 for line in ics.split('\r\n')))

	def test_private_link_and_reset(self):
		self.slot()
		self.client.force_login(self.ada)
		self.client.get('/courses/timetable/')
		token = TimetableFeed.objects.get(user=self.ada).token
		self.client.logout()
		r = self.client.get(f'/courses/timetable/calendar/{token}.ics')     # calendar apps don't sign in
		self.assertEqual(r.status_code, 200)
		self.assertEqual(r['Content-Type'], 'text/calendar; charset=utf-8')
		self.assertEqual(self.client.get('/courses/timetable/calendar/wrong.ics').status_code, 404)
		self.client.force_login(self.ada)
		self.client.post('/courses/timetable/calendar/reset/')
		self.client.logout()
		self.assertEqual(self.client.get(f'/courses/timetable/calendar/{token}.ics').status_code, 404)

	def test_download_needs_sign_in(self):
		self.assertEqual(self.client.get('/courses/timetable/calendar.ics').status_code, 302)
		self.client.force_login(self.ada)
		r = self.client.get('/courses/timetable/calendar.ics')
		self.assertIn('attachment', r['Content-Disposition'])


def csv_file(text, name='timetable.csv'):
	return SimpleUploadedFile(name, text.encode('utf-8'), content_type='text/csv')


def xlsx_file(rows):
	"""A minimal .xlsx with inline strings, and times as fractions of a day (as Excel stores them)."""
	def cell(ref, v):
		if isinstance(v, float):
			return f'<c r="{ref}"><v>{v}</v></c>'
		return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'
	body = ''.join('<row r="%d">%s</row>' % (i + 1, ''.join(cell(f'{chr(65 + j)}{i + 1}', v) for j, v in enumerate(r)))
		for i, r in enumerate(rows))
	sheet = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
		f'<sheetData>{body}</sheetData></worksheet>')
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, 'w') as z:
		z.writestr('xl/worksheets/sheet1.xml', sheet)
	return SimpleUploadedFile('timetable.xlsx', buf.getvalue())


class OfficialTimetableTests(Base):
	CSV = ('course_code,course_title,type,day,start,end,venue\n'
		'cos401,Data Structures,Lecture,Monday,08:00,10:00,LT 2\n'
		'COS 401,,Practical,Wed,2:00 PM,4:00 PM,Lab 1\n'
		'MTH 401,Numerical Analysis,Lecture,Tuesday,10:00,12:00,Hall\n'
		'BAD 1,,Lecture,Funday,10:00,9:00,\n')

	def setUp(self):
		super().setUp()
		self.uniadmin = User.objects.create_user('uniadmin', password='x')
		AdminRole.objects.create(user=self.uniadmin, role=AdminRole.UNIVERSITY_ADMIN, university=self.uni)

	def upload(self, f, user=None, **extra):
		self.client.force_login(user or self.uniadmin)
		return self.client.post('/staff/timetable/', {'file': f, 'replace': '1', **extra}, follow=True)

	def test_upload_gives_every_student_the_classes(self):
		r = self.upload(csv_file(self.CSV), department=self.dep.pk)
		self.assertContains(r, 'Timetable saved for 2 courses')
		self.assertContains(r, 'Row 5')                                     # the bad row is reported
		self.assertEqual(OfficialClass.objects.count(), 3)
		mth = Course.objects.get(code='MTH 401')                             # created from course_title
		self.assertEqual(mth.department, self.dep)
		for u in (self.ada, self.ben):
			self.assertEqual(ClassSlot.objects.filter(user=u, official__isnull=False).count(), 2)
		lab = ClassSlot.objects.get(user=self.ada, kind='practical')
		self.assertEqual((lab.day, lab.start, lab.venue), (2, time(14, 0), 'Lab 1'))

	def test_reupload_updates_and_removes(self):
		self.upload(csv_file(self.CSV))
		self.upload(csv_file('course_code,day,start,end,venue\nCOS 401,Monday,08:00,11:00,LT 5\n'))
		self.assertEqual(OfficialClass.objects.filter(course=self.course).count(), 1)          # the practical was removed
		s = ClassSlot.objects.get(user=self.ada, official__isnull=False)
		self.assertEqual((s.end, s.venue), (time(11, 0), 'LT 5'))

	def test_excel_file(self):
		rows = [['Course Code', 'Day', 'Start', 'End', 'Venue'], ['COS 401', 'Friday', 8 / 24, 10.5 / 24, 'LT 1']]
		self.upload(xlsx_file(rows))
		o = OfficialClass.objects.get()
		self.assertEqual((o.day, o.start, o.end), (4, time(8, 0), time(10, 30)))

	def test_later_students_get_it_and_removed_copy_stays_removed(self):
		self.upload(csv_file(self.CSV))
		copy = ClassSlot.objects.filter(user=self.ada, official__isnull=False).first()
		self.client.force_login(self.ada)
		self.client.post(f'/courses/timetable/{copy.pk}/delete/')
		self.assertTrue(OfficialClassSkip.objects.filter(user=self.ada).exists())
		self.upload(csv_file(self.CSV))
		self.assertEqual(ClassSlot.objects.filter(user=self.ada, official__isnull=False).count(), 1)
		# A student who adds the course later gets its classes; dropping it removes them.
		CourseEnrollment.objects.filter(user=self.ben).delete()
		self.assertFalse(ClassSlot.objects.filter(user=self.ben, official__isnull=False).exists())
		CourseEnrollment.objects.create(user=self.ben, course=self.course)
		self.assertEqual(ClassSlot.objects.filter(user=self.ben, official__isnull=False).count(), 2)

	def test_students_cannot_edit_official_time(self):
		self.upload(csv_file(self.CSV))
		copy = ClassSlot.objects.filter(user=self.ada, official__isnull=False).first()
		self.client.force_login(self.ada)
		self.client.post(f'/courses/timetable/{copy.pk}/edit/', {'course': self.course.pk, 'kind': 'lecture', 'day': 6,
			'start': '07:00', 'end': '08:00'})
		copy.refresh_from_db()
		self.assertNotEqual(copy.day, 6)

	def test_department_cancels_a_week_and_students_are_told(self):
		self.upload(csv_file(self.CSV))
		o = OfficialClass.objects.get(course=self.course, kind='lecture')
		d = next_weekday(o.day)
		self.client.post(f'/staff/timetable/{o.pk}/action/', {'action': 'cancel', 'date': d.isoformat(), 'note': 'Lecturer away'})
		for u in (self.ada, self.ben):
			[occ] = [x for x in occurrences_on(u, d) if x.official_id == o.pk]
			self.assertEqual(occ.state, 'cancelled')
		n = Notification.objects.get(recipient=self.ada, type=Notification.CLASS_CHANGED)
		from feed.notifications import build_entries
		[entry] = build_entries([n])
		self.assertIn('Your department cancelled <strong>COS 401</strong> lecture', str(entry))
		self.assertIn('Lecturer away', self.client.get(f'/courses/timetable/?day={o.day}').content.decode() if
			self.client.force_login(self.ada) is None else '')
		self.client.force_login(self.uniadmin)
		# A student can't undo the department's change.
		self.client.force_login(self.ada)
		slot = ClassSlot.objects.get(user=self.ada, official=o)
		self.client.post(f'/courses/timetable/{slot.pk}/change/', {'date': d.isoformat(), 'action': 'clear'})
		self.assertTrue(ClassChange.objects.filter(slot=slot).exists())
		# The department can.
		self.client.force_login(self.uniadmin)
		self.client.post(f'/staff/timetable/{o.pk}/action/', {'action': 'undo', 'date': d.isoformat()})
		self.assertFalse(ClassChange.objects.exists())
		self.assertFalse(Notification.objects.filter(type=Notification.CLASS_CHANGED).exists())

	def test_department_moves_a_week(self):
		self.upload(csv_file(self.CSV))
		o = OfficialClass.objects.get(course=self.course, kind='lecture')
		d = next_weekday(o.day)
		self.client.post(f'/staff/timetable/{o.pk}/action/', {'action': 'move', 'date': d.isoformat(),
			'new_date': (d + timedelta(days=3)).isoformat(), 'new_start': '15:00', 'new_end': '17:00', 'new_venue': 'LT 9'})
		[occ] = [x for x in occurrences_on(self.ben, d + timedelta(days=3)) if x.official_id == o.pk]
		self.assertEqual((occ.state, occ.start, occ.venue), ('moved_in', time(15, 0), 'LT 9'))

	def test_permissions_and_scope(self):
		mod = User.objects.create_user('mod', password='x')
		AdminRole.objects.create(user=mod, role=AdminRole.MODERATOR)
		self.client.force_login(mod)
		self.assertEqual(self.client.get('/staff/timetable/').status_code, 403)
		other = User.objects.create_user('uiadmin', password='x')
		AdminRole.objects.create(user=other, role=AdminRole.UNIVERSITY_ADMIN, university=self.other_uni)
		self.upload(csv_file(self.CSV))
		o = OfficialClass.objects.first()
		self.client.force_login(other)
		r = self.client.post(f'/staff/timetable/{o.pk}/action/', {'action': 'delete'})
		self.assertEqual(r.status_code, 404)
		self.client.force_login(self.ada)                                    # students: no dashboard
		self.assertEqual(self.client.get('/staff/timetable/').status_code, 403)

	def test_page_and_template(self):
		self.upload(csv_file(self.CSV))
		r = self.client.get('/staff/timetable/')
		self.assertContains(r, 'COS 401')
		self.assertContains(r, 'Change a week')
		t = self.client.get('/staff/timetable/template.csv')
		self.assertIn('course_code,course_title,type,day,start,end,venue', t.content.decode())
		self.client.force_login(self.ada)
		self.assertContains(self.client.get(f'/courses/timetable/?day=0'), 'Official')
