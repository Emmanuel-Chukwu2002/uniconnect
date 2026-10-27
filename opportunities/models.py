"""Opportunities: internships, jobs, scholarships, fellowships, competitions
and volunteering posted by students for students at the same university
(/opportunities/). Anyone can post one; it closes on its deadline, or when
the person who posted it marks it closed."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Opportunity(models.Model):
	INTERNSHIP, JOB, SCHOLARSHIP, FELLOWSHIP, COMPETITION, VOLUNTEER = (
		'internship', 'job', 'scholarship', 'fellowship', 'competition', 'volunteer')
	KIND_CHOICES = [
		(INTERNSHIP, 'Internship'), (JOB, 'Job'), (SCHOLARSHIP, 'Scholarship'),
		(FELLOWSHIP, 'Fellowship'), (COMPETITION, 'Competition'), (VOLUNTEER, 'Volunteering'),
	]
	KIND_ICONS = {
		INTERNSHIP: 'bi-briefcase', JOB: 'bi-person-workspace', SCHOLARSHIP: 'bi-mortarboard',
		FELLOWSHIP: 'bi-award', COMPETITION: 'bi-trophy', VOLUNTEER: 'bi-heart',
	}

	university = models.ForeignKey('accounts.University', on_delete=models.CASCADE, related_name='opportunities')
	posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='opportunities_posted')
	title = models.CharField(max_length=120)
	organization = models.CharField(max_length=120, help_text='Company, school or group offering it.')
	kind = models.CharField(max_length=12, choices=KIND_CHOICES, default=INTERNSHIP)
	location = models.CharField(max_length=120, blank=True, help_text='City or campus, e.g. Lagos or Faculty of Engineering.')
	is_remote = models.BooleanField(default=False, help_text='Can be done online / from anywhere.')
	description = models.TextField(max_length=4000, help_text='What it is, what you will do, and how to apply.')
	eligibility = models.CharField(max_length=300, blank=True, help_text='Who can apply, e.g. 300–400 level Computer Science students.')
	reward = models.CharField(max_length=120, blank=True, help_text='Pay, stipend or award, e.g. ₦80,000 a month.')
	apply_url = models.URLField(blank=True, help_text='Link to the application page.')
	apply_email = models.EmailField(blank=True, help_text='Or an email address to send applications to.')
	deadline = models.DateField(null=True, blank=True, help_text='Last day to apply. Leave empty if there is none.')
	is_closed = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']
		verbose_name_plural = 'opportunities'
		indexes = [models.Index(fields=['university', 'is_closed', 'deadline'])]

	def __str__(self):
		return f'{self.title} — {self.organization}'

	def clean(self):
		if not self.apply_url and not self.apply_email:
			raise ValidationError('Add a link or an email address so people know how to apply.')

	def get_absolute_url(self):
		return reverse('opportunity_detail', args=[self.pk])

	@property
	def icon(self):
		return self.KIND_ICONS.get(self.kind, 'bi-briefcase')

	# Banner on the detail page: a free Pexels photo for each kind (loaded
	# from Pexels' servers; nothing is stored here).
	PHOTOS = {'internship': 574077, 'job': 30688592, 'scholarship': 5940711, 'fellowship': 6147001,
		'competition': 5965612, 'volunteer': 6147001}

	@property
	def banner_url(self):
		pid = self.PHOTOS.get(self.kind, 2305098)
		return f'https://images.pexels.com/photos/{pid}/pexels-photo-{pid}.jpeg?auto=compress&cs=tinysrgb&w=1260&h=520&fit=crop'

	@property
	def initials(self):
		words = [w for w in self.organization.replace('&', ' ').split() if w[:1].isalnum()]
		return (''.join(w[0] for w in words[:2]) or '?').upper()

	@property
	def requirements(self):
		"""Who can apply, as a list for the "Requirements" bullets: one item per
		line or ";" (or per sentence when it's written as sentences)."""
		import re
		text = (self.eligibility or '').strip()
		if not text:
			return []
		parts = re.split(r'\s*(?:\n|;|•)\s*', text)
		if len(parts) == 1:
			parts = re.split(r'(?<=\.)\s+(?=[A-Z])', text)
		return [p.strip(' .-') for p in parts if p.strip(' .-')]

	@property
	def days_left(self):
		if not self.deadline:
			return None
		return (self.deadline - timezone.localdate()).days

	@property
	def is_open(self):
		return not self.is_closed and (self.deadline is None or self.deadline >= timezone.localdate())


class OpportunitySave(models.Model):
	"""A student's saved opportunity (the bookmark on each card)."""
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_opportunities')
	opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name='saves')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		unique_together = ('user', 'opportunity')
