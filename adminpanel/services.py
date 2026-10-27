"""What dashboard actions actually do. Views check permission and scope first;
everything here assumes that has been done, and every action is audited.

Reports never delete anything by themselves: a moderator reviews the evidence
and chooses dismiss, remove the content, warn, or suspend.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from feed.models import Report

from . import audit
from .content import BY_REPORT_TYPE
from .models import AccountAction as A


# ---------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------

def _uni(user):
	prof = getattr(user, 'student_profile', None)
	return prof.university if prof else None


def active_suspension(user):
	return A.objects.filter(user=user, kind=A.SUSPENSION, lifted_at__isnull=True).first()


def warn(actor, user, reason, report=None):
	act = A.objects.create(user=user, kind=A.WARNING, reason=reason, actor=actor, report=report)
	audit.log(actor, 'user.warn', 'user', user.pk, user.username, reason, _uni(user))
	return act


@transaction.atomic
def suspend(actor, user, reason, days=None, report=None):
	if user.is_superuser or user.pk == actor.pk:
		raise ValueError("That account can't be suspended from the dashboard.")
	A.objects.filter(user=user, kind=A.SUSPENSION, lifted_at__isnull=True).update(lifted_at=timezone.now())
	ends = timezone.now() + timedelta(days=days) if days else None
	act = A.objects.create(user=user, kind=A.SUSPENSION, reason=reason, actor=actor, report=report, ends_at=ends)
	type(user).objects.filter(pk=user.pk).update(is_active=False)      # signs them out and blocks sign-in
	audit.log(actor, 'user.suspend', 'user', user.pk, user.username,
		reason + (f' (for {days} day{"s" if days != 1 else ""})' if days else ''), _uni(user))
	return act


@transaction.atomic
def reactivate(actor, user, reason):
	A.objects.filter(user=user, kind=A.SUSPENSION, lifted_at__isnull=True).update(lifted_at=timezone.now())
	type(user).objects.filter(pk=user.pk).update(is_active=True)
	act = A.objects.create(user=user, kind=A.REACTIVATION, reason=reason, actor=actor)
	audit.log(actor, 'user.reactivate', 'user', user.pk, user.username, reason, _uni(user))
	return act


def lift_expired(user=None):
	"""Suspensions whose end date has passed: reactivate the account."""
	from django.contrib.auth import get_user_model
	now = timezone.now()
	due = A.objects.filter(kind=A.SUSPENSION, lifted_at__isnull=True, ends_at__isnull=False, ends_at__lte=now)
	if user is not None:
		due = due.filter(user=user)
	ids = list(due.values_list('user_id', flat=True))
	if ids:
		due.update(lifted_at=now)
		get_user_model().objects.filter(pk__in=ids).update(is_active=True)
	return len(ids)


def set_verified(actor, user, verified):
	prof = user.student_profile
	prof.is_verified = verified
	prof.save(update_fields=['is_verified'])
	audit.log(actor, 'user.verify' if verified else 'user.unverify', 'user', user.pk, user.username, '', prof.university)


def clear_profile(actor, user, what, reason):
	prof = user.student_profile
	if what == 'photo' and prof.profile_photo:
		prof.profile_photo.delete(save=False)
		prof.profile_photo = None
	elif what == 'cover' and prof.cover_photo:
		prof.cover_photo.delete(save=False)
		prof.cover_photo = None
	elif what == 'bio':
		prof.bio = ''
	prof.save()
	audit.log(actor, 'user.clear_profile', 'user', user.pk, user.username, f'{what}: {reason}', prof.university)


def unacknowledged_warnings(user):
	return A.objects.filter(user=user, kind=A.WARNING, acknowledged_at__isnull=True)


# ---------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------

def target_of(report):
	"""(Kind, object or None) for what a report is about."""
	kind = BY_REPORT_TYPE.get(report.target_type)
	if kind is None:
		return None, None
	obj = kind.get(report.target_id) if report.target_id else None
	if obj is None and report.target_type == 'post' and report.post_id:
		obj = report.post
	return kind, obj


def same_target(report):
	"""Every still-open report about the same thing (closed together)."""
	return Report.objects.filter(target_type=report.target_type, target_id=report.target_id,
		status__in=[Report.OPEN, Report.REVIEWING])


def start_review(actor, report):
	if report.status == Report.OPEN:
		report.status, report.assigned_to = Report.REVIEWING, actor
		report.save(update_fields=['status', 'assigned_to'])
		audit.log(actor, 'report.review', 'report', report.pk, f'Report #{report.pk}', '', report.university)


def _close(actor, report, status, reason):
	now = timezone.now()
	same_target(report).update(status=status, reviewed_by=actor, reviewed_at=now, decision_reason=reason,
		assigned_to=report.assigned_to or actor)


@transaction.atomic
def dismiss(actor, report, reason):
	_close(actor, report, Report.DISMISSED, reason)
	audit.log(actor, 'report.dismiss', report.target_type, report.target_id, report.target_label or f'Report #{report.pk}',
		reason, report.university)


@transaction.atomic
def remove_reported(actor, report, reason):
	kind, obj = target_of(report)
	if obj is not None and kind.removable:
		snapshot = kind.snapshot(obj)
		same_target(report).filter(post_snapshot='').update(post_snapshot=snapshot)
		_close(actor, report, Report.REMOVED, reason)
		obj.delete()
	else:
		_close(actor, report, Report.REMOVED, reason)
	audit.log(actor, 'report.remove', report.target_type, report.target_id, report.target_label, reason, report.university)


@transaction.atomic
def action_on_owner(actor, report, action, reason, days=None):
	"""Warn or suspend the account behind the report, and close the report as Action taken."""
	user = report.reported_user
	if action == 'warn':
		warn(actor, user, reason, report)
	else:
		suspend(actor, user, reason, days, report)
	_close(actor, report, Report.ACTIONED, f'{action}: {reason}')


@transaction.atomic
def remove_content(actor, kind, obj, reason):
	"""Direct moderation from a content table (no report needed)."""
	label, owner = kind.title(obj), kind.owner(obj)
	uid = kind.university_id(obj)
	snapshot = kind.snapshot(obj)
	open_reports = Report.objects.filter(target_type=kind.report_type, target_id=obj.pk, status__in=[Report.OPEN, Report.REVIEWING])
	open_reports.filter(post_snapshot='').update(post_snapshot=snapshot)
	open_reports.update(status=Report.REMOVED, reviewed_by=actor, reviewed_at=timezone.now(), decision_reason=reason)
	pk = obj.pk
	obj.delete()
	from accounts.models import University
	audit.log(actor, 'content.remove', kind.report_type, pk, label,
		f'{reason}\n\nRemoved: {snapshot}'[:4000], University.objects.filter(pk=uid).first() if uid else None)
	return owner


# ---------------------------------------------------------------------
# Student side: filing a report about anything
# ---------------------------------------------------------------------

def file_report(reporter, kind, obj, reason, details=''):
	"""Create (or update the reporter's open) report about obj. Returns the report."""
	owner = kind.owner(obj)
	if owner is None:
		raise ValueError('nothing to report against')
	from accounts.models import University
	uid = kind.university_id(obj)
	post = obj if kind.report_type == 'post' else None
	report = Report.objects.filter(reporter=reporter, target_type=kind.report_type, target_id=obj.pk,
		status__in=[Report.OPEN, Report.REVIEWING]).first()
	if report is None:
		report = Report(reporter=reporter, target_type=kind.report_type, target_id=obj.pk, post=post,
			reported_user=owner, post_snapshot=kind.snapshot(obj) if kind.removable else '',
			university=University.objects.filter(pk=uid).first() if uid else None)
	report.reason = reason
	report.target_label = kind.title(obj)[:200]
	if details:
		report.details = details[:1000]
	report.save()
	return report


# ---------------------------------------------------------------------
# Staff accounts for admins who aren't students
# ---------------------------------------------------------------------

def create_staff_account(actor, first_name, last_name, email, role, university):
	"""A sign-in for an admin who isn't a student. No password is set: they choose
	their own from the invitation link (send_staff_invite), so nobody else knows it."""
	import re
	from django.contrib.auth import get_user_model
	from .models import AdminRole
	User = get_user_model()
	base = re.sub(r'[^a-z0-9_]', '', email.split('@')[0].lower())[:20] or 'staff'
	username, n = base, 1
	while User.objects.filter(username__iexact=username).exists():
		n += 1
		username = f'{base}{n}'
	user = User(username=username, email=email, first_name=first_name, last_name=last_name, is_staff=True)
	user.set_unusable_password()
	user.save()
	AdminRole.objects.create(user=user, role=role, assigned_by=actor,
		university=None if role == AdminRole.SUPER_ADMIN else university)
	audit.log(actor, 'staff.create', 'user', user.pk, username,
		f'{dict(AdminRole.ROLE_CHOICES)[role]}{" — " + university.short_name if university and role != AdminRole.SUPER_ADMIN else ""}', university)
	return user


def send_staff_invite(request, user):
	"""Email a link to choose a password (Django's password-reset page, valid for
	PASSWORD_RESET_TIMEOUT, 3 days by default). Raises if the email can't be sent."""
	from django.contrib.auth.tokens import default_token_generator
	from django.core.mail import send_mail
	from django.urls import reverse
	from django.utils.encoding import force_bytes
	from django.utils.http import urlsafe_base64_encode
	link = request.build_absolute_uri(reverse('password_reset_confirm', args=[
		urlsafe_base64_encode(force_bytes(user.pk)), default_token_generator.make_token(user)]))
	role = getattr(getattr(user, 'admin_role', None), 'get_role_display', lambda: 'an admin')()
	send_mail(
		'Your UniConnect admin account',
		f'Hello {user.first_name or user.username},\n\n'
		f'{request.user.get_full_name() or request.user.username} has added you to the UniConnect admin team as {role}.\n\n'
		f'Choose your password here (the link works once and expires in a few days):\n{link}\n\n'
		f'Then sign in with this email address ({user.email}). You will go straight to the admin dashboard.\n',
		None, [user.email], fail_silently=False)
