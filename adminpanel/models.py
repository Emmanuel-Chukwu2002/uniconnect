"""The UniConnect admin dashboard's own records (adminpanel/, /staff/).

AdminRole       who may use the dashboard, and how far their powers reach
AdminLog        an audit trail of every administrative action
AccountAction   warnings, suspensions and reactivations of student accounts
Announcement    platform-wide or university-wide notices shown to students

Reports themselves stay in feed.Report (students already file them there);
the dashboard adds a review workflow on top of that model.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class AdminRole(models.Model):
	"""One dashboard role per account. Django superusers are always Super Admins,
	even without a row; a plain is_staff account without a row is a platform-wide
	Moderator (what /moderation/ already allowed). Everyone else is a student."""
	SUPER_ADMIN = 'super_admin'
	UNIVERSITY_ADMIN = 'university_admin'
	MODERATOR = 'moderator'
	SUPPORT = 'support'
	ROLE_CHOICES = [
		(SUPER_ADMIN, 'Super Admin'),
		(UNIVERSITY_ADMIN, 'University Admin'),
		(MODERATOR, 'Moderator'),
		(SUPPORT, 'Support Staff'),
	]

	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='admin_role')
	role = models.CharField(max_length=20, choices=ROLE_CHOICES)
	# Required for University Admins; for Moderators and Support Staff it limits them
	# to one university (empty = every university). Super Admins are never limited.
	university = models.ForeignKey('accounts.University', on_delete=models.CASCADE, null=True, blank=True, related_name='admin_roles')
	assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
	created_at = models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return f'{self.user} — {self.get_role_display()}'


class AdminLog(models.Model):
	"""Who did what to which record, when and why. Written by adminpanel/audit.py
	for every dashboard action; never edited or deleted from the dashboard."""
	actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='admin_actions')
	action = models.CharField(max_length=40)
	target_type = models.CharField(max_length=20, blank=True)
	target_id = models.PositiveIntegerField(null=True, blank=True)
	target_label = models.CharField(max_length=200, blank=True)
	reason = models.TextField(blank=True)
	university = models.ForeignKey('accounts.University', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
	created_at = models.DateTimeField(default=timezone.now)

	class Meta:
		ordering = ['-created_at']
		indexes = [models.Index(fields=['created_at']), models.Index(fields=['action'])]

	def __str__(self):
		return f'{self.actor} {self.action} {self.target_type} #{self.target_id}'


class AccountAction(models.Model):
	"""A warning, suspension or reactivation of one student's account.

	A suspension also sets user.is_active = False, which is what actually stops
	the student signing in (Django refuses inactive accounts, and signs them out
	on their next request). A suspension with an end date is lifted by
	adminpanel/accounts.lift_expired(). A warning shows the student a notice
	in the app until they acknowledge it."""
	WARNING = 'warning'
	SUSPENSION = 'suspension'
	REACTIVATION = 'reactivation'
	KIND_CHOICES = [(WARNING, 'Warning'), (SUSPENSION, 'Suspension'), (REACTIVATION, 'Reactivation')]

	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='account_actions')
	kind = models.CharField(max_length=14, choices=KIND_CHOICES)
	reason = models.TextField()
	actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
	report = models.ForeignKey('feed.Report', on_delete=models.SET_NULL, null=True, blank=True, related_name='account_actions')
	ends_at = models.DateTimeField(null=True, blank=True, help_text='Suspensions only; empty = until reactivated.')
	lifted_at = models.DateTimeField(null=True, blank=True)
	acknowledged_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(default=timezone.now)

	class Meta:
		ordering = ['-created_at']
		indexes = [models.Index(fields=['kind', 'lifted_at'])]

	def __str__(self):
		return f'{self.get_kind_display()} for {self.user}'

	@property
	def is_active_suspension(self):
		return self.kind == self.SUSPENSION and self.lifted_at is None


class Announcement(models.Model):
	"""A notice from UniConnect staff, shown as a banner at the top of the app to
	every student (or to one university's students) while it is live."""
	EVERYONE = 'everyone'
	UNIVERSITY = 'university'
	AUDIENCE_CHOICES = [(EVERYONE, 'All universities'), (UNIVERSITY, 'One university')]
	INFO, MAINTENANCE, FEATURE, POLICY, OUTAGE = 'info', 'maintenance', 'feature', 'policy', 'outage'
	KIND_CHOICES = [(INFO, 'General'), (MAINTENANCE, 'Scheduled maintenance'), (FEATURE, 'New feature'),
		(POLICY, 'Policy change'), (OUTAGE, 'Service interruption')]

	title = models.CharField(max_length=120)
	body = models.TextField(max_length=1000)
	kind = models.CharField(max_length=12, choices=KIND_CHOICES, default=INFO)
	audience = models.CharField(max_length=12, choices=AUDIENCE_CHOICES, default=EVERYONE)
	university = models.ForeignKey('accounts.University', on_delete=models.CASCADE, null=True, blank=True, related_name='announcements')
	author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
	is_published = models.BooleanField(default=True)
	starts_at = models.DateTimeField(default=timezone.now)
	ends_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-starts_at']

	def __str__(self):
		return self.title

	@property
	def is_live(self):
		now = timezone.now()
		return self.is_published and self.starts_at <= now and (self.ends_at is None or self.ends_at > now)
