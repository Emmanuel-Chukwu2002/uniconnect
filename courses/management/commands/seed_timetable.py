"""Fills a sample weekly timetable so you can see how Timetable looks.

    python manage.py seed_timetable            fill the timetable of everyone who has signed in
                                               and has no classes yet
    python manage.py seed_timetable --reset    clear those people's timetables first, then fill them
    python manage.py seed_timetable --user UNN-2022249381    just that account

It uses each person's My Courses (adding the first four sample courses from
seed_courses if they have none), and spreads lectures, tutorials and a lab
over Monday to Saturday, with a class later today so "Today's classes"
shows on Home. Only accounts that have signed in are touched (sample
accounts are left alone); --reset only clears the accounts it fills.
"""
from datetime import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from courses.models import ClassSlot, Course, CourseEnrollment

# (course number in My Courses, kind, day 0=Mon..5=Sat, start hour, minutes long, venue)
WEEK = [
	(0, ClassSlot.LECTURE, 0, 8, 120, 'LT 1'),
	(1, ClassSlot.LECTURE, 0, 12, 120, 'Faculty of Science LT'),
	(2, ClassSlot.LECTURE, 1, 10, 120, 'LT 2'),
	(0, ClassSlot.TUTORIAL, 1, 14, 60, 'Tutorial room B'),
	(3, ClassSlot.LECTURE, 2, 9, 120, 'ETF 101'),
	(1, ClassSlot.PRACTICAL, 2, 14, 180, 'Computer Lab 3'),
	(2, ClassSlot.TUTORIAL, 3, 11, 60, 'Tutorial room A'),
	(0, ClassSlot.LECTURE, 3, 14, 60, 'LT 1'),
	(3, ClassSlot.TUTORIAL, 4, 10, 60, 'Tutorial room B'),
	(1, ClassSlot.LECTURE, 4, 12, 60, 'Faculty of Science LT'),
	(None, ClassSlot.OTHER, 5, 10, 120, 'Main library, 2nd floor'),
]


class Command(BaseCommand):
	help = 'Adds a sample weekly timetable (python manage.py seed_timetable [--reset] [--user USERNAME]).'

	def add_arguments(self, parser):
		parser.add_argument('--reset', action='store_true', help='Clear their timetables first.')
		parser.add_argument('--user', help='Only this username.')

	def handle(self, *args, **opts):
		User = get_user_model()
		users = User.objects.filter(is_active=True, student_profile__isnull=False).select_related('student_profile')
		if opts['user']:
			users = users.filter(username=opts['user'])
			if not users.exists():
				raise CommandError(f'No student with the username {opts["user"]}.')
		else:
			users = users.filter(last_login__isnull=False)
		filled = 0
		for user in users:
			if opts['reset']:
				ClassSlot.objects.filter(user=user).delete()
			elif ClassSlot.objects.filter(user=user).exists():
				continue
			courses = list(Course.objects.filter(enrollments__user=user).order_by('code')[:4])
			if not courses:
				courses = list(Course.objects.filter(university=user.student_profile.university).order_by('code')[:4])
				for c in courses:
					CourseEnrollment.objects.get_or_create(user=user, course=c)
			slots = []
			for idx, kind, day, hour, mins, venue in WEEK:
				end = hour * 60 + mins
				course = courses[idx % len(courses)] if (idx is not None and courses) else None
				slots.append(ClassSlot(user=user, course=course, title='' if course else 'Group study session',
					kind=kind, day=day, start=time(hour, 0), end=time(end // 60, end % 60), venue=venue))
			# One more class later today (if there's still time), so Home shows "Today's classes".
			now = timezone.localtime()
			if now.hour < 21:
				start = min(now.hour + 1, 21)
				course = courses[0] if courses else None
				slots.append(ClassSlot(user=user, course=course, title='' if course else 'Revision class',
					kind=ClassSlot.TUTORIAL, day=now.weekday(), start=time(start, 0), end=time(start + 1, 30),
					venue='Faculty reading room'))
			ClassSlot.objects.bulk_create(slots)
			filled += 1
			self.stdout.write(f'  {user.username}: {len(slots)} classes')
		if not filled:
			self.stdout.write('Nobody to fill (everyone who has signed in already has classes — use --reset to refill).')
		else:
			self.stdout.write(self.style.SUCCESS(f'Filled {filled} timetable{"" if filled == 1 else "s"}. Open /courses/timetable/ to see it.'))
