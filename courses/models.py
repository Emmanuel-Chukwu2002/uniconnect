"""Course Companion (/courses/): everything for the courses you're taking,
in one place.

    Course            one course at a university, by code: "COS 401 — Data Structures".
                      Any student can add a missing course; codes are unique per university.
    CourseEnrollment  "My Courses": the courses a student added to their list.
    CourseMaterial    a file for a course: lecture Notes or a Past Question paper.
    CourseQuestion    a question about the course, with CourseAnswers; the asker can
                      mark the answer that helped ("accepted").

Study groups for a course are the Academic groups (studygroups app) at the
same university with the same course code — nothing extra is stored here.
Everything is for students of the course's university only.
"""
import os
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import reverse


def normalise_code(code):
	"""'cos401', 'COS  401', 'cos-401' → 'COS 401'."""
	code = ' '.join((code or '').upper().replace('-', ' ').split())
	m = re.fullmatch(r'([A-Z]{2,5})\s*(\d{3,4}[A-Z]?)', code)
	return f'{m.group(1)} {m.group(2)}' if m else code


class Course(models.Model):
	# Tile colour and icon on "My Courses", picked from the code's letters.
	ICONS = {
		'CSC': 'bi-code-slash', 'COS': 'bi-code-slash', 'CIT': 'bi-pc-display', 'SEN': 'bi-braces',
		'MTH': 'bi-calculator', 'MAT': 'bi-calculator', 'STA': 'bi-bar-chart', 'PHY': 'bi-lightning-charge',
		'CHM': 'bi-droplet-half', 'BIO': 'bi-flower1', 'GST': 'bi-book', 'ENG': 'bi-gear', 'EEE': 'bi-cpu',
		'ECO': 'bi-graph-up-arrow', 'ACC': 'bi-cash-coin', 'LAW': 'bi-bank', 'MED': 'bi-heart-pulse',
	}
	COLOURS = ['blue', 'navy', 'teal', 'slate', 'violet', 'green', 'orange', 'pink']

	university = models.ForeignKey('accounts.University', on_delete=models.CASCADE, related_name='courses')
	code = models.CharField(max_length=20, help_text='e.g. COS 401')
	title = models.CharField(max_length=120, help_text='e.g. Data Structures')
	department = models.ForeignKey('accounts.Department', on_delete=models.SET_NULL, null=True, blank=True, related_name='courses')
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='courses_added')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['code']
		constraints = [models.UniqueConstraint(fields=['university', 'code'], name='one_course_code_per_university')]

	def __str__(self):
		return f'{self.code} — {self.title}'

	def get_absolute_url(self):
		return reverse('course_detail', args=[self.pk])

	@property
	def prefix(self):
		return self.code.split()[0] if self.code else ''

	@property
	def icon(self):
		return self.ICONS.get(self.prefix, 'bi-journal-text')

	@property
	def colour(self):
		return self.COLOURS[sum(map(ord, self.prefix)) % len(self.COLOURS)] if self.prefix else 'blue'

	def study_groups(self):
		from studygroups.models import StudyGroup
		return StudyGroup.objects.filter(university_id=self.university_id, course_code__iexact=self.code)


class CourseEnrollment(models.Model):
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='course_enrollments')
	course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrollments')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['course__code']
		constraints = [models.UniqueConstraint(fields=['user', 'course'], name='one_enrollment_per_course')]


def validate_material_size(value, limit_mb=25):
	if value.size > limit_mb * 1024 * 1024:
		raise ValidationError(f'Files must be smaller than {limit_mb}MB.')


MATERIAL_EXTENSIONS = ['pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'txt', 'md', 'rtf', 'odt', 'odp',
	'zip', 'rar', 'png', 'jpg', 'jpeg', 'webp']


class CourseMaterial(models.Model):
	NOTES, PAST_QUESTION = 'notes', 'past_question'
	KIND_CHOICES = [(NOTES, 'Notes'), (PAST_QUESTION, 'Past question')]

	course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='materials')
	uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='course_materials')
	kind = models.CharField(max_length=14, choices=KIND_CHOICES, default=NOTES)
	title = models.CharField(max_length=150, help_text='e.g. Week 3 — Linked lists')
	year = models.PositiveSmallIntegerField(null=True, blank=True, help_text='For past questions: the exam year.')
	file = models.FileField(upload_to='course_materials/%Y/%m/', validators=[FileExtensionValidator(MATERIAL_EXTENSIONS), validate_material_size])
	file_name = models.CharField(max_length=150, blank=True)
	size = models.PositiveIntegerField(default=0)
	downloads = models.PositiveIntegerField(default=0)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']

	def __str__(self):
		return self.title

	@property
	def extension(self):
		return os.path.splitext(self.file_name or self.file.name)[1].lstrip('.').lower()

	@property
	def icon(self):
		e = self.extension
		return {'pdf': 'bi-file-earmark-pdf', 'doc': 'bi-file-earmark-word', 'docx': 'bi-file-earmark-word',
			'ppt': 'bi-file-earmark-ppt', 'pptx': 'bi-file-earmark-ppt', 'xls': 'bi-file-earmark-excel',
			'xlsx': 'bi-file-earmark-excel', 'zip': 'bi-file-earmark-zip', 'rar': 'bi-file-earmark-zip',
			'png': 'bi-file-earmark-image', 'jpg': 'bi-file-earmark-image', 'jpeg': 'bi-file-earmark-image',
			'webp': 'bi-file-earmark-image'}.get(e, 'bi-file-earmark-text')

	@property
	def kind_class(self):
		e = self.extension
		return 'pdf' if e == 'pdf' else 'word' if e in ('doc', 'docx', 'odt', 'rtf') else 'ppt' if e in ('ppt', 'pptx', 'odp') \
			else 'excel' if e in ('xls', 'xlsx', 'csv', 'ods') else 'zip' if e in ('zip', 'rar', '7z') \
			else 'image' if e in ('png', 'jpg', 'jpeg', 'webp', 'gif') else 'other'

	@property
	def badge(self):
		"""Big letter and small label for the app-style file tile, e.g. ('W', 'DOC')."""
		k, e = self.kind_class, self.extension
		return {'pdf': ('', 'PDF'), 'word': ('W', 'DOC'), 'ppt': ('P', 'PPT'), 'excel': ('X', 'XLS'),
			'zip': ('', 'ZIP'), 'image': ('', 'IMG')}.get(k, ('', (e or 'file')[:4].upper()))


class CourseQuestion(models.Model):
	course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='questions')
	author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='course_questions')
	title = models.CharField(max_length=200)
	body = models.TextField(max_length=4000, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']

	def __str__(self):
		return self.title

	def get_absolute_url(self):
		return reverse('course_question', args=[self.course_id, self.pk])


class CourseAnswer(models.Model):
	question = models.ForeignKey(CourseQuestion, on_delete=models.CASCADE, related_name='answers')
	author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='course_answers')
	body = models.TextField(max_length=4000)
	is_accepted = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-is_accepted', 'created_at']


class ClassSlot(models.Model):
	"""One weekly class on a student's own timetable (/courses/timetable/):
	"COS 401 lecture, Tuesday 10:00–12:00, LT 2". Usually for one of their
	courses; `title` covers anything else (a tutorial club, a practical).
	Classmates' slots for the same course are offered as suggestions."""
	LECTURE, TUTORIAL, PRACTICAL, OTHER = 'lecture', 'tutorial', 'practical', 'other'
	KIND_CHOICES = [(LECTURE, 'Lecture'), (TUTORIAL, 'Tutorial'), (PRACTICAL, 'Practical / Lab'), (OTHER, 'Other')]
	DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
	DAY_CHOICES = list(enumerate(DAYS))

	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='class_slots')
	course = models.ForeignKey(Course, on_delete=models.CASCADE, null=True, blank=True, related_name='slots')
	title = models.CharField(max_length=80, blank=True, help_text='Only when it is not one of your courses.')
	kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=LECTURE)
	day = models.PositiveSmallIntegerField(choices=DAY_CHOICES)
	start = models.TimeField()
	end = models.TimeField()
	venue = models.CharField(max_length=80, blank=True)
	# Set when this is a student's copy of a class from the department's official
	# timetable (OfficialClass, uploaded in the admin dashboard). The copy follows
	# the official class: when the department changes or deletes it, the copy does too.
	official = models.ForeignKey('OfficialClass', on_delete=models.CASCADE, null=True, blank=True, related_name='copies')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['day', 'start']

	def __str__(self):
		return f'{self.name} {self.get_day_display()} {self.start:%H:%M}'

	@property
	def name(self):
		return f'{self.course.code} – {self.course.title}' if self.course_id else self.title

	@property
	def short(self):
		return self.course.code if self.course_id else self.title

	@property
	def colour(self):
		return self.course.colour if self.course_id else 'slate'

	@property
	def icon(self):
		return self.course.icon if self.course_id else 'bi-calendar-event'

	@property
	def minutes(self):
		return (self.end.hour * 60 + self.end.minute) - (self.start.hour * 60 + self.start.minute)


class OfficialClass(models.Model):
	"""One weekly class on a department's official timetable, uploaded by a
	University Admin in the dashboard (/staff/timetable/, courses/official.py).
	Every student taking the course gets a copy on their own timetable
	(ClassSlot.official) automatically, now and when they add the course later."""
	course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='official_classes')
	kind = models.CharField(max_length=10, choices=ClassSlot.KIND_CHOICES, default=ClassSlot.LECTURE)
	day = models.PositiveSmallIntegerField(choices=ClassSlot.DAY_CHOICES)
	start = models.TimeField()
	end = models.TimeField()
	venue = models.CharField(max_length=80, blank=True)
	uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['course__code', 'day', 'start']
		constraints = [models.UniqueConstraint(fields=['course', 'kind', 'day', 'start'], name='one_official_class_per_time')]

	def __str__(self):
		return f'{self.course.code} {self.get_kind_display()} {self.get_day_display()} {self.start:%H:%M}'


class OfficialClassSkip(models.Model):
	"""A student removed their copy of an official class (they don't attend it),
	so it isn't added back to their timetable."""
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
	official = models.ForeignKey(OfficialClass, on_delete=models.CASCADE, related_name='skips')

	class Meta:
		constraints = [models.UniqueConstraint(fields=['user', 'official'], name='one_skip_per_official_class')]


class ClassChange(models.Model):
	"""A one-off change to one week's class: "cancelled on Tue 3 Nov" or
	"moved to Thu 5 Nov, 2-4 PM, LT 3". The weekly class itself stays the same.
	Made by the student on their timetable, or by the department for an
	official class (set_by is then the admin, and every student's copy gets one)."""
	CANCELLED, MOVED = 'cancelled', 'moved'
	STATUS_CHOICES = [(CANCELLED, 'Cancelled'), (MOVED, 'Moved')]

	slot = models.ForeignKey(ClassSlot, on_delete=models.CASCADE, related_name='changes')
	date = models.DateField(help_text='The date the class would normally happen.')
	status = models.CharField(max_length=10, choices=STATUS_CHOICES)
	new_date = models.DateField(null=True, blank=True)
	new_start = models.TimeField(null=True, blank=True)
	new_end = models.TimeField(null=True, blank=True)
	new_venue = models.CharField(max_length=80, blank=True)
	note = models.CharField(max_length=140, blank=True)
	set_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['date']
		constraints = [models.UniqueConstraint(fields=['slot', 'date'], name='one_change_per_class_date')]

	@property
	def by_department(self):
		return self.slot.official_id is not None and self.set_by_id is not None and self.set_by_id != self.slot.user_id


class TimetableFeed(models.Model):
	"""The private link a student's calendar app (Google Calendar, iPhone,
	Outlook) subscribes to: /courses/timetable/calendar/<token>.ics. Anyone
	with the link can read the timetable, so it can be reset."""
	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='timetable_feed')
	token = models.CharField(max_length=40, unique=True)
	created_at = models.DateTimeField(auto_now_add=True)


class Deadline(models.Model):
	"""An exam, test or assignment date for a course, shared with everyone taking it
	(Home's Today strip counts down to it; Course Companion lists them)."""
	EXAM, TEST, ASSIGNMENT, OTHER = 'exam', 'test', 'assignment', 'other'
	KIND_CHOICES = [(EXAM, 'Exam'), (TEST, 'Test'), (ASSIGNMENT, 'Assignment'), (OTHER, 'Other')]
	KIND_ICONS = {EXAM: 'bi-journal-check', TEST: 'bi-pencil-square', ASSIGNMENT: 'bi-file-earmark-text', OTHER: 'bi-flag'}

	course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='deadlines')
	kind = models.CharField(max_length=12, choices=KIND_CHOICES, default=EXAM)
	title = models.CharField(max_length=100, blank=True, help_text='e.g. First semester exam, Assignment 2')
	due_at = models.DateTimeField(db_index=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='course_deadlines')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['due_at']

	def __str__(self):
		return f'{self.course.code} {self.label}'

	@property
	def label(self):
		return self.title or self.get_kind_display()

	@property
	def icon(self):
		return self.KIND_ICONS.get(self.kind, 'bi-flag')


class DailyQuestion(models.Model):
	"""A multiple-choice question for a course. Each day every course shows one
	"Question of the day": one set for that date, or else one picked from the
	course's bank (questions with no date) — the same one for everybody."""
	course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='daily_questions')
	text = models.CharField(max_length=300)
	option_a = models.CharField(max_length=150)
	option_b = models.CharField(max_length=150)
	option_c = models.CharField(max_length=150, blank=True)
	option_d = models.CharField(max_length=150, blank=True)
	correct = models.CharField(max_length=1, choices=[('a', 'A'), ('b', 'B'), ('c', 'C'), ('d', 'D')])
	explanation = models.CharField(max_length=400, blank=True)
	day = models.DateField(null=True, blank=True, help_text='Show on this date; empty = part of the course bank.')
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['pk']

	def __str__(self):
		return f'{self.course.code}: {self.text[:60]}'

	@property
	def options(self):
		return [(k, getattr(self, f'option_{k}')) for k in 'abcd' if getattr(self, f'option_{k}')]


class DailyAnswer(models.Model):
	question = models.ForeignKey(DailyQuestion, on_delete=models.CASCADE, related_name='answers')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='daily_answers')
	day = models.DateField()
	choice = models.CharField(max_length=1)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['question', 'user', 'day'], name='one_daily_answer')]

	@property
	def is_correct(self):
		return self.choice == self.question.correct
