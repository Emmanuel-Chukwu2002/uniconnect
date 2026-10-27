import secrets

from django.conf import settings
from django.db import models


class University(models.Model):
	"""The top level of the hierarchy. Every faculty, department, level,
	and student belongs to exactly one university."""
	name = models.CharField(max_length=200, unique=True)
	short_name = models.CharField(max_length=20, help_text="e.g. UNN, UNIPORT")
	email_domain = models.CharField(
		max_length=100,
		help_text="Official student email domain, without the @ sign (e.g. unn.edu.ng)",
	)
	matric_format_hint = models.CharField(
		max_length=150, blank=True,
		help_text="Shown to students as an example, e.g. CSC/2021/045 — not enforced as a strict pattern.",
	)
	logo = models.ImageField(upload_to='university_logos', blank=True, null=True)
	is_active = models.BooleanField(default=True, help_text="Inactive universities are hidden from registration.")

	class Meta:
		ordering = ['name']
		verbose_name_plural = 'universities'

	def __str__(self):
		return self.name


class Faculty(models.Model):
	university = models.ForeignKey(University, on_delete=models.CASCADE, related_name='faculties')
	name = models.CharField(max_length=150)

	class Meta:
		unique_together = ('university', 'name')
		ordering = ['name']
		verbose_name_plural = 'faculties'

	def __str__(self):
		return f'{self.name} — {self.university.short_name}'


class Department(models.Model):
	faculty = models.ForeignKey(Faculty, on_delete=models.CASCADE, related_name='departments')
	name = models.CharField(max_length=150)

	class Meta:
		unique_together = ('faculty', 'name')
		ordering = ['name']

	def __str__(self):
		return f'{self.name} — {self.faculty.name}'


class Level(models.Model):
	department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='levels')
	name = models.CharField(max_length=20, help_text="e.g. 100 Level")
	order = models.PositiveIntegerField(default=0, help_text="Controls display order (100L=100, 200L=200, ...).")

	class Meta:
		unique_together = ('department', 'name')
		ordering = ['order', 'name']

	def __str__(self):
		return self.name


class StudentProfile(models.Model):
	"""Extends the built-in User with university identity. This is what
	the rest of the platform (communities, resources, events, marketplace)
	scopes content against."""
	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='student_profile')
	university = models.ForeignKey(University, on_delete=models.PROTECT, related_name='students')
	faculty = models.ForeignKey(Faculty, on_delete=models.PROTECT, related_name='students')
	department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name='students')
	level = models.ForeignKey(Level, on_delete=models.PROTECT, related_name='students')
	matric_number = models.CharField(max_length=50)
	university_email = models.EmailField()
	profile_photo = models.ImageField(upload_to='profile_photos', blank=True, null=True)
	is_verified = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		# Unique PER university, not globally — two different schools can
		# have overlapping matric-number formats.
		unique_together = ('university', 'matric_number')

	def __str__(self):
		return f'{self.user.get_full_name()} ({self.matric_number})'


class EmailVerificationToken(models.Model):
	student = models.OneToOneField(StudentProfile, on_delete=models.CASCADE, related_name='verification_token')
	token = models.CharField(max_length=64, unique=True, editable=False)
	created_at = models.DateTimeField(auto_now_add=True)

	def save(self, *args, **kwargs):
		if not self.token:
			self.token = secrets.token_urlsafe(32)
		super().save(*args, **kwargs)

	def __str__(self):
		return f'Verification token for {self.student}'
