"""Fills Course Companion with sample courses so you can see how it looks.

    python manage.py seed_courses            add the samples (safe to run again)
    python manage.py seed_courses --reset    remove the samples first, then add them

For every university with at least two students it adds 10 courses (COS 401
Data Structures, COS 403 Web Development, STA 422 Statistics, ...), puts
students in them, and adds sample notes and past questions (small PDFs),
questions with answers, and lecture times on a few classmates' timetables
(so Timetable can suggest them to you). Everyone at that university who has signed in at
least once (so: you) gets the first four in My Courses.

Samples are the courses with no "added by" person (created_by empty); courses
students add themselves always have one, so --reset never touches them.
Course codes match the sample study groups (seed_studygroups), so those groups
show under each course's Study Groups.
"""
import random

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from accounts.models import StudentProfile, University
from datetime import time

from courses.models import ClassSlot, Course, CourseAnswer, CourseEnrollment, CourseMaterial, CourseQuestion
from studygroups.management.commands.seed_studygroups import tiny_pdf

COURSES = [
	('COS 401', 'Data Structures', ['Week 1 — Arrays and linked lists', 'Week 4 — Trees and AVL rotations'],
	 [('Why is a hash table lookup O(1) on average but O(n) in the worst case?',
	   ['Because of collisions: if every key lands in the same bucket you end up walking a list. A good hash function and resizing keep buckets short, so on average it is constant time.', 'Check slide 14 of the Week 6 notes — the lecturer drew it out.'])]),
	('COS 403', 'Web Development', ['HTML, CSS and the box model', 'Django views and templates'],
	 [('What is the difference between GET and POST in a form?',
	   ['GET puts the data in the URL and should only read things; POST sends it in the request body and is for changing things (saving, deleting). Always use POST for forms that change data, with a CSRF token in Django.'])]),
	('STA 422', 'Statistics', ['Hypothesis testing summary', 'Regression worked examples'],
	 [('When do we use a t-test instead of a z-test?',
	   ['Use t when the population standard deviation is unknown and you estimate it from the sample — especially for small samples (n < 30). With a known σ or a large sample, z is fine.'])]),
	('MTH 401', 'Linear Algebra', ['Eigenvalues and eigenvectors', 'Diagonalisation — solved examples'], []),
	('CSC 411', 'Software Engineering', ['SDLC models compared', 'UML diagrams cheat sheet'],
	 [('Is the waterfall model still used anywhere?', ['Yes — in projects with fixed, well-understood requirements (e.g. some government and embedded systems). Most teams mix it with agile now.'])]),
	('MTH 201', 'Mathematical Methods', ['Differential equations — first order'], []),
	('ECO 202', 'Microeconomics', ['Elasticity of demand notes'], []),
	('CSC 405', 'Compiler Construction', ['Lexical analysis with regular expressions'], []),
	('GST 201', 'Nigerian Peoples and Culture', ['Summary of chapters 1–5'], []),
	('PHY 102', 'General Physics II', ['Electric fields and potential'], []),
]


class Command(BaseCommand):
	help = 'Adds sample courses for Course Companion (python manage.py seed_courses [--reset]).'

	def add_arguments(self, parser):
		parser.add_argument('--reset', action='store_true', help='Remove earlier samples first.')

	def handle(self, *args, **opts):
		if opts['reset']:
			samples = Course.objects.filter(created_by__isnull=True)
			for m in CourseMaterial.objects.filter(course__in=samples):
				m.file.delete(save=False)
			n = samples.count()
			samples.delete()
			self.stdout.write(f'Removed {n} sample courses.')
		rng = random.Random(401)
		added = 0
		for uni in University.objects.all():
			students = list(StudentProfile.objects.filter(university=uni, user__is_active=True).select_related('user', 'department', 'level'))
			if len(students) < 2:
				continue
			real = [s.user for s in students if s.user.last_login]
			others = [s.user for s in students if not s.user.last_login] or [s.user for s in students]
			dept = (real and real[0].student_profile.department) or students[0].department
			for i, (code, title, notes, questions) in enumerate(COURSES):
				course, created = Course.objects.get_or_create(university=uni, code=code,
					defaults={'title': title, 'department': dept})
				if not created:
					continue
				added += 1
				people = rng.sample(others, k=min(len(others), rng.randint(8, 40)))
				members = people + (real if i < 4 else [])
				CourseEnrollment.objects.bulk_create([CourseEnrollment(user=u, course=course) for u in members], ignore_conflicts=True)
				for j, note in enumerate(notes):
					self._file(course, CourseMaterial.NOTES, note, None, rng.choice(people), f'{code} {note}')
				for year in (2024, 2023)[:1 + (i < 5)]:
					self._file(course, CourseMaterial.PAST_QUESTION, f'First semester exam', year, rng.choice(people), f'{code} {title} — exam {year}')
				# A weekly lecture (and for some, a tutorial) on a few classmates'
				# timetables, so "From your classmates" has suggestions to offer.
				venues = ['LT 1', 'LT 2', 'Faculty of Science LT', 'Computer Lab 3', 'ETF 101']
				slots = [(ClassSlot.LECTURE, i % 5, 8 + 2 * (i % 4), venues[i % len(venues)])]
				if i % 3 == 0:
					slots.append((ClassSlot.TUTORIAL, (i + 2) % 5, 14, 'Tutorial room B'))
				for kind, day, hour, venue in slots:
					ClassSlot.objects.bulk_create([ClassSlot(user=u, course=course, kind=kind, day=day, start=time(hour, 0),
						end=time(hour + 2, 0), venue=venue) for u in people[:3]])
				for qtitle, answers in questions:
					q = CourseQuestion.objects.create(course=course, author=rng.choice(people), title=qtitle)
					for k, body in enumerate(answers):
						CourseAnswer.objects.create(question=q, author=rng.choice(people), body=body, is_accepted=(k == 0 and len(answers) > 1))
		self.stdout.write(self.style.SUCCESS(f'Added {added} sample courses. Open /courses/ to see them.'))

	def _file(self, course, kind, title, year, who, heading):
		lines = [f'{course.code} — {course.title}', 'Sample file added by seed_courses to show how files look.',
			'1. Read the summary.', '2. Try the exercises.', '3. Discuss in the course questions.']
		data = tiny_pdf(heading[:60], lines)
		name = f'{course.code.replace(" ", "")}-{"notes" if kind == CourseMaterial.NOTES else "pq"}-{rng_safe(title)}.pdf'
		m = CourseMaterial(course=course, uploaded_by=who, kind=kind, title=title, year=year, file_name=name, size=len(data),
			downloads=random.Random(title).randint(0, 60))
		m.file.save(name, ContentFile(data), save=True)


def rng_safe(text):
	return ''.join(c if c.isalnum() else '-' for c in text.lower()).strip('-')[:30]
