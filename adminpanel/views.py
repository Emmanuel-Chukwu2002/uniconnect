"""The UniConnect admin dashboard (/staff/). Each view checks the admin's
permission and university scope on the server (permissions.py) before showing
or changing anything, and every change is written to the audit log (audit.py).
"""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.models import Department, Faculty, StudentProfile, University
from feed.models import Report

from . import audit, charts, services, stats
from . import permissions as P
from .content import KINDS, open_report_counts
from .models import AccountAction, AdminLog, AdminRole, Announcement

User = get_user_model()
PAGE = 25


def _page(request, qs):
	return Paginator(qs, PAGE).get_page(request.GET.get('page'))


def _days(request):
	d = request.GET.get('days', '7')
	return (d, stats.PERIODS[d]) if d in stats.PERIODS else ('7', 7)


def _safe_back(request, fallback):
	nxt = request.POST.get('next')
	if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
		return redirect(nxt)
	return redirect(fallback)


def _reason(request):
	return ' '.join((request.POST.get('reason') or '').split())[:1000]


def ctx(request, section, **extra):
	"""What every dashboard page needs: the admin, the sidebar, the bell."""
	admin = request.admin
	pending = Report.objects.filter(status__in=[Report.OPEN, Report.REVIEWING])
	if admin.university:
		pending = pending.filter(university=admin.university)
	nav = [
		('overview', 'Overview', 'bi-house-door-fill', 'staff_overview', P.VIEW),
		('users', 'User Management', 'bi-person-fill', 'staff_users', P.VIEW_USERS),
		('moderation', 'Content Moderation', 'bi-shield-fill', 'staff_moderation', P.REMOVE),
		('reports', 'Reports & Complaints', 'bi-flag-fill', 'staff_reports', P.REVIEW),
		('universities', 'Universities', 'bi-bank2', 'staff_universities', P.VIEW),
		('marketplace', 'Marketplace', 'bi-shop', 'staff_marketplace', P.REMOVE),
		('bookshop', 'Bookshop', 'bi-book-fill', 'staff_bookshop', P.REMOVE),
		('events', 'Events', 'bi-calendar-event', 'staff_events', P.REMOVE),
		('groups', 'Groups & Communities', 'bi-people-fill', 'staff_groups', P.REMOVE),
		('timetable', 'Official Timetable', 'bi-calendar-week', 'staff_timetable', P.TIMETABLE),
		('analytics', 'Analytics', 'bi-graph-up-arrow', 'staff_analytics', P.ANALYTICS),
		('announcements', 'Announcements', 'bi-megaphone-fill', 'staff_announcements', P.ANNOUNCE),
		('logs', 'Admin Logs', 'bi-clipboard-data', 'staff_logs', P.LOGS),
		('settings', 'Settings', 'bi-gear-fill', 'staff_settings', P.VIEW),
	]
	return {'admin': admin, 'section': section, 'pending_count': pending.count(),
		'nav': [(k, label, icon, reverse(url)) for k, label, icon, url, perm in nav if admin.can(perm)], **extra}


# ---------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------

@P.admin_required()
def overview(request):
	admin = request.admin
	services.lift_expired()
	key, days = _days(request)
	reg_labels, reg_values = stats.registration_series(admin, days)
	act_labels, act_groups = stats.activity_series(admin, days)
	issues = stats.system_status()
	quick = [(label, icon, url) for label, icon, url, perm in [
		('Review Reports', 'bi-flag-fill', reverse('staff_reports'), P.REVIEW),
		('Manage Users', 'bi-person-fill', reverse('staff_users'), P.VIEW_USERS),
		('Moderate Content', 'bi-shield-fill', reverse('staff_moderation'), P.REMOVE),
		('Add University', 'bi-bank2', reverse('staff_universities') + '#add', P.UNIVERSITIES),
		('Create Announcement', 'bi-megaphone-fill', reverse('staff_announcements') + '#new', P.ANNOUNCE),
	] if admin.can(perm)]
	return render(request, 'adminpanel/overview.html', ctx(request, 'overview',
		days_key=key, days=days, periods=[('7', 'Last 7 days'), ('30', 'Last 30 days'), ('90', 'Last 90 days')],
		cards=stats.overview_cards(admin, days),
		reg_chart=charts.line_chart(reg_labels, reg_values, 'New registrations'),
		act_chart=charts.bar_chart(act_labels, act_groups, 'Posts, comments and likes'),
		act_names=list(act_groups),
		universities=stats.most_active_universities(admin),
		reports=stats.recent_reports(admin),
		activity=stats.recent_activity(admin),
		quick=quick, issues=issues))


@P.admin_required()
def search(request):
	admin = request.admin
	q = ' '.join(request.GET.get('q', '').split())[:60]
	users = posts = reports = []
	if q:
		if admin.can(P.VIEW_USERS):
			users = list(_users_qs(admin, q)[:10])
		if admin.can(P.REMOVE):
			posts = list(KINDS['posts'].for_admin(admin, q)[:10])
		if admin.can(P.REVIEW):
			rq = _reports_qs(admin)
			rid = q.lstrip('#')
			reports = list(rq.filter(pk=int(rid))[:1] if rid.isdigit() else
				rq.filter(Q(target_label__icontains=q) | Q(reported_user__username__icontains=q) | Q(details__icontains=q))[:10])
	return render(request, 'adminpanel/search.html', ctx(request, '', q=q, users=users, posts=posts, reports=reports))


# ---------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------

def _users_qs(admin, q='', status='', university=''):
	qs = (StudentProfile.objects.select_related('user', 'university', 'faculty', 'department', 'level')
		.filter(admin.scope_q('university')))
	for word in q.split()[:6]:
		cond = (Q(user__username__icontains=word) | Q(user__first_name__icontains=word) | Q(user__last_name__icontains=word)
			| Q(university__name__icontains=word) | Q(university__short_name__icontains=word)
			| Q(faculty__name__icontains=word) | Q(department__name__icontains=word))
		if admin.can(P.PRIVATE):
			cond |= Q(user__email__icontains=word) | Q(university_email__icontains=word) | Q(matric_number__icontains=word)
		qs = qs.filter(cond)
	suspended = AccountAction.objects.filter(kind=AccountAction.SUSPENSION, lifted_at__isnull=True).values('user_id')
	if status == 'active':
		qs = qs.filter(user__is_active=True)
	elif status == 'suspended':
		qs = qs.filter(user_id__in=suspended)
	elif status == 'unverified':
		qs = qs.filter(is_verified=False)
	elif status == 'warned':
		qs = qs.filter(user__account_actions__kind=AccountAction.WARNING)
	elif status == 'flagged':
		qs = qs.filter(user_id__in=flagged_user_ids(admin))
	if university and admin.university is None:
		qs = qs.filter(university_id=university)
	return qs.annotate(n_reports=Count('user__reports_received', filter=Q(user__reports_received__status__in=[Report.OPEN, Report.REVIEWING]),
		distinct=True)).order_by('-created_at').distinct()


def flagged_user_ids(admin):
	"""Accounts worth a look: 3+ open reports, or a matric number used by more than
	one account at the same university (a possible duplicate)."""
	reported = set(Report.objects.filter(status__in=[Report.OPEN, Report.REVIEWING]).values('reported_user_id')
		.annotate(n=Count('id')).filter(n__gte=3).values_list('reported_user_id', flat=True))
	dupes = set()
	pairs = (StudentProfile.objects.filter(admin.scope_q('university')).values('university_id', 'matric_number')
		.annotate(n=Count('id')).filter(n__gt=1))
	for p in pairs:
		dupes |= set(StudentProfile.objects.filter(university_id=p['university_id'], matric_number__iexact=p['matric_number'])
			.values_list('user_id', flat=True))
	return reported | dupes


@P.admin_required(P.VIEW_USERS)
def users(request):
	admin = request.admin
	q = ' '.join(request.GET.get('q', '').split())[:60]
	status = request.GET.get('status', '')
	uni = request.GET.get('university', '')
	page = _page(request, _users_qs(admin, q, status, uni))
	suspended = set(AccountAction.objects.filter(kind=AccountAction.SUSPENSION, lifted_at__isnull=True,
		user_id__in=[p.user_id for p in page]).values_list('user_id', flat=True))
	flagged = flagged_user_ids(admin)
	for p in page:
		p.is_suspended = p.user_id in suspended
		p.is_flagged = p.user_id in flagged
	return render(request, 'adminpanel/users.html', ctx(request, 'users', page=page, q=q, status=status, uni=uni,
		statuses=[('', 'All'), ('active', 'Active'), ('suspended', 'Suspended'), ('warned', 'Warned'),
			('unverified', 'Unverified'), ('flagged', 'Flagged')],
		universities=University.objects.order_by('name') if admin.university is None else []))


def _student_or_404(admin, user_id):
	user = get_object_or_404(User.objects.select_related('student_profile'), pk=user_id)
	prof = getattr(user, 'student_profile', None)
	if prof is None:
		if not admin.is_super:
			raise Http404
	elif not admin.in_scope(prof.university_id):
		raise Http404
	return user, prof


@P.admin_required(P.VIEW_USERS)
def user_detail(request, user_id):
	admin = request.admin
	user, prof = _student_or_404(admin, user_id)
	from feed.models import Comment, Listing, Post
	from bookshop.models import Book
	summary = [
		('Posts', Post.objects.filter(author=user).count()),
		('Comments', Comment.objects.filter(author=user).count()),
		('Listings', Listing.objects.filter(seller=user).count()),
		('Books', Book.objects.filter(seller=user).count()),
		('Reports made', Report.objects.filter(reporter=user).count()),
		('Reports received', Report.objects.filter(reported_user=user).count()),
	]
	reports = list(Report.objects.filter(reported_user=user).select_related('reviewed_by')[:20])
	actions = list(AccountAction.objects.filter(user=user).select_related('actor')[:20])
	same_matric = []
	if prof and admin.can(P.PRIVATE):
		same_matric = list(StudentProfile.objects.filter(university_id=prof.university_id, matric_number__iexact=prof.matric_number)
			.exclude(user=user).select_related('user'))
	role = AdminRole.objects.filter(user=user).first()
	return render(request, 'adminpanel/user_detail.html', ctx(request, 'users', u=user, prof=prof, summary=summary,
		reports=reports, actions=actions, suspension=services.active_suspension(user), same_matric=same_matric,
		target_role=role, is_protected=user.is_superuser or role is not None or user.pk == request.user.pk))


@P.admin_required(P.VIEW_USERS)
@require_POST
def user_action(request, user_id):
	admin = request.admin
	user, prof = _student_or_404(admin, user_id)
	action = request.POST.get('action')
	reason = _reason(request)
	protected = user.is_superuser or user.pk == request.user.pk or (AdminRole.objects.filter(user=user).exists() and not admin.is_super)
	need = {'warn': P.WARN, 'suspend': P.SUSPEND, 'reactivate': P.SUSPEND, 'verify': P.VERIFY, 'unverify': P.VERIFY,
		'clear_photo': P.REMOVE, 'clear_cover': P.REMOVE, 'clear_bio': P.REMOVE}.get(action)
	if need is None:
		raise Http404
	admin.require(need)
	back = redirect('staff_user', user_id=user.pk)
	if action in ('warn', 'suspend', 'reactivate', 'clear_photo', 'clear_cover', 'clear_bio') and not reason:
		messages.error(request, 'Give a reason — it is kept in the audit log.')
		return back
	if action in ('suspend', 'warn') and protected:
		messages.error(request, "You can't do that to this account.")
		return back
	if action == 'warn':
		services.warn(request.user, user, reason)
		messages.success(request, 'Warning sent. The student will see it next time they open UniConnect.')
	elif action == 'suspend':
		days = request.POST.get('days')
		services.suspend(request.user, user, reason, int(days) if days and days.isdigit() and int(days) > 0 else None)
		messages.success(request, 'Account suspended.')
	elif action == 'reactivate':
		services.reactivate(request.user, user, reason)
		messages.success(request, 'Account reactivated.')
	elif action in ('verify', 'unverify') and prof:
		services.set_verified(request.user, user, action == 'verify')
		messages.success(request, 'Verification updated.')
	elif action.startswith('clear_') and prof:
		services.clear_profile(request.user, user, action[6:], reason)
		messages.success(request, 'Profile updated.')
	return back


# ---------------------------------------------------------------------
# Reports & complaints
# ---------------------------------------------------------------------

STATUS_TABS = [('pending', 'Pending', [Report.OPEN]), ('review', 'Under review', [Report.REVIEWING]),
	('resolved', 'Resolved', list(Report.CLOSED)), ('all', 'All', None)]
PILL = {Report.OPEN: ('Pending', 'amber'), Report.REVIEWING: ('Under Review', 'blue'), Report.REMOVED: ('Resolved', 'green'),
	Report.ACTIONED: ('Resolved', 'green'), Report.DISMISSED: ('Dismissed', 'grey')}


def _reports_qs(admin):
	qs = Report.objects.select_related('reporter', 'reported_user', 'reviewed_by', 'assigned_to', 'university')
	if admin.university:
		qs = qs.filter(university=admin.university)
	return qs


@P.admin_required(P.REVIEW)
def reports(request):
	admin = request.admin
	tab = request.GET.get('status', 'pending')
	statuses = dict((k, v) for k, _, v in STATUS_TABS)
	if tab not in statuses:
		tab = 'pending'
	qs = _reports_qs(admin)
	counts = {k: (qs.filter(status__in=v).count() if v else qs.count()) for k, _, v in STATUS_TABS}
	if statuses[tab]:
		qs = qs.filter(status__in=statuses[tab])
	kind = request.GET.get('type', '')
	if kind in dict(Report.TARGET_CHOICES):
		qs = qs.filter(target_type=kind)
	reason = request.GET.get('reason', '')
	if reason in dict(Report.REASON_CHOICES):
		qs = qs.filter(reason=reason)
	return render(request, 'adminpanel/reports.html', ctx(request, 'reports', page=_page(request, qs), tab=tab,
		tabs=[(k, label, counts[k]) for k, label, _ in STATUS_TABS], kind=kind, reason=reason,
		types=Report.TARGET_CHOICES, reasons=Report.REASON_CHOICES, pill=PILL))


def _report_or_404(admin, pk):
	report = get_object_or_404(_reports_qs(admin), pk=pk)
	return report


@P.admin_required(P.REVIEW)
def report_detail(request, pk):
	admin = request.admin
	report = _report_or_404(admin, pk)
	kind, obj = services.target_of(report)
	others = list(Report.objects.filter(target_type=report.target_type, target_id=report.target_id).exclude(pk=report.pk)
		.select_related('reporter')[:20]) if report.target_id else []
	history = list(Report.objects.filter(reported_user=report.reported_user).exclude(pk=report.pk)
		.exclude(target_type=report.target_type, target_id=report.target_id)[:10])
	return render(request, 'adminpanel/report_detail.html', ctx(request, 'reports', r=report, kind=kind, obj=obj,
		obj_url=kind.url(obj) if kind and obj is not None else '', others=others, history=history, pill=PILL,
		actions=AccountAction.objects.filter(report=report).select_related('actor'),
		is_open=report.status in (Report.OPEN, Report.REVIEWING)))


@P.admin_required(P.REVIEW)
@require_POST
def report_action(request, pk):
	admin = request.admin
	report = _report_or_404(admin, pk)
	action = request.POST.get('action')
	reason = _reason(request)
	back = redirect('staff_report', pk=report.pk)
	if report.status not in (Report.OPEN, Report.REVIEWING):
		messages.info(request, 'This report has already been decided.')
		return back
	if action == 'review':
		services.start_review(request.user, report)
		messages.success(request, 'You are reviewing this report.')
		return back
	if not reason:
		messages.error(request, 'Give a reason for the decision — it is kept with the report and in the audit log.')
		return back
	if action == 'dismiss':
		services.dismiss(request.user, report, reason)
		messages.success(request, 'Report dismissed.')
	elif action == 'remove':
		admin.require(P.REMOVE)
		services.remove_reported(request.user, report, reason)
		messages.success(request, 'Content removed. Every open report about it is resolved.')
	elif action in ('warn', 'suspend'):
		admin.require(P.WARN if action == 'warn' else P.SUSPEND)
		owner = report.reported_user
		if owner.is_superuser or owner.pk == request.user.pk or (AdminRole.objects.filter(user=owner).exists() and not admin.is_super):
			messages.error(request, "You can't do that to this account.")
			return back
		days = request.POST.get('days')
		services.action_on_owner(request.user, report, action, reason,
			int(days) if days and days.isdigit() and int(days) > 0 else None)
		messages.success(request, 'Warning sent.' if action == 'warn' else 'Account suspended.')
	else:
		raise Http404
	return redirect('staff_reports')


# ---------------------------------------------------------------------
# Content tables: Content Moderation, Marketplace, Bookshop, Events, Groups & Communities
# ---------------------------------------------------------------------

SECTIONS = {
	'moderation': ('Content Moderation', 'Posts, comments, images and videos', ['posts', 'comments', 'media']),
	'marketplace': ('Marketplace', 'Listings students are selling', ['listings']),
	'bookshop': ('Bookshop', 'Books listed in the Bookshop', ['books']),
	'events': ('Events', 'Events on UniConnect', ['events']),
	'groups': ('Groups & Communities', 'Study groups and communities', ['groups', 'communities']),
}


def content_page(section):
	@P.admin_required(P.REMOVE)
	def view(request):
		admin = request.admin
		title, sub, kinds = SECTIONS[section]
		key = request.GET.get('tab', kinds[0])
		if key not in kinds:
			key = kinds[0]
		kind = KINDS[key]
		q = ' '.join(request.GET.get('q', '').split())[:60]
		only_reported = request.GET.get('reported') == '1'
		qs = kind.for_admin(admin, q)
		if only_reported:
			from feed.models import Report as Rep
			ids = Rep.objects.filter(target_type=kind.report_type, status__in=[Rep.OPEN, Rep.REVIEWING]).values('target_id')
			qs = qs.filter(pk__in=ids)
		page = _page(request, qs)
		counts = open_report_counts(kind.report_type, [o.pk for o in page])
		rows = [{'obj': o, 'title': kind.title(o), 'url': kind.url(o), 'owner': kind.owner(o), 'details': kind.details(o),
			'reports': counts.get(o.pk, 0), 'created': getattr(o, 'created_at', None)} for o in page]
		return render(request, 'adminpanel/content.html', ctx(request, section, title=title, sub=sub, kind=kind, page=page,
			rows=rows, q=q, only_reported=only_reported, tabs=[(k, KINDS[k].label) for k in kinds], tab=key,
			columns=[c for c, _ in kind.details(page[0])] if rows else []))
	view.__name__ = f'{section}_page'
	return view


@P.admin_required(P.REMOVE)
@require_POST
def content_remove(request, key, pk):
	admin = request.admin
	kind = KINDS.get(key)
	if kind is None or not kind.removable:
		raise Http404
	obj = kind.get(pk)
	if obj is None or not admin.in_scope(kind.university_id(obj)):
		raise Http404
	reason = _reason(request)
	if not reason:
		messages.error(request, 'Give a reason — it is kept in the audit log.')
	else:
		services.remove_content(request.user, kind, obj, reason)
		messages.success(request, f'{kind.noun.capitalize()} removed.')
	return _safe_back(request, 'staff_overview')


# ---------------------------------------------------------------------
# Universities
# ---------------------------------------------------------------------

@P.admin_required()
def universities(request):
	admin = request.admin
	if request.method == 'POST':
		admin.require(P.UNIVERSITIES)
		name = ' '.join((request.POST.get('name') or '').split())[:200]
		short = ' '.join((request.POST.get('short_name') or '').split())[:20]
		domain = (request.POST.get('email_domain') or '').strip().lower().lstrip('@')[:100]
		if not (name and short and domain) or '.' not in domain:
			messages.error(request, 'Give the full name, a short name and the student email domain (e.g. unn.edu.ng).')
		elif University.objects.filter(name__iexact=name).exists():
			messages.error(request, 'A university with that name already exists.')
		else:
			uni = University.objects.create(name=name, short_name=short, email_domain=domain,
				is_active=request.POST.get('is_active') == '1')
			audit.log(request.user, 'university.create', 'university', uni.pk, uni.name, '', uni)
			messages.success(request, f'{uni.name} added.')
			return redirect('staff_university', pk=uni.pk)
	qs = University.objects.annotate(n_students=Count('students', distinct=True), n_faculties=Count('faculties', distinct=True))
	if admin.university:
		qs = qs.filter(pk=admin.university.pk)
	return render(request, 'adminpanel/universities.html', ctx(request, 'universities', unis=qs.order_by('name')))


@P.admin_required()
def university_detail(request, pk):
	admin = request.admin
	uni = get_object_or_404(University, pk=pk)
	if not admin.in_scope(uni.pk):
		raise Http404
	if request.method == 'POST':
		what = request.POST.get('what')
		if what == 'update':
			admin.require(P.UNIVERSITIES)
			uni.name = ' '.join((request.POST.get('name') or uni.name).split())[:200]
			uni.short_name = ' '.join((request.POST.get('short_name') or uni.short_name).split())[:20]
			uni.email_domain = (request.POST.get('email_domain') or uni.email_domain).strip().lower().lstrip('@')[:100]
			uni.matric_format_hint = (request.POST.get('matric_format_hint') or '').strip()[:100]
			uni.is_active = request.POST.get('is_active') == '1'
			uni.save()
			audit.log(request.user, 'university.update', 'university', uni.pk, uni.name,
				'Active' if uni.is_active else 'Inactive (hidden from registration)', uni)
			messages.success(request, 'University updated.')
		elif what == 'faculty':
			admin.require(P.STRUCTURE)
			name = ' '.join((request.POST.get('name') or '').split())[:150]
			if name and not uni.faculties.filter(name__iexact=name).exists():
				f = Faculty.objects.create(university=uni, name=name)
				audit.log(request.user, 'faculty.create', 'faculty', f.pk, f'{name} ({uni.short_name})', '', uni)
				messages.success(request, 'Faculty added.')
		elif what == 'department':
			admin.require(P.STRUCTURE)
			fac = get_object_or_404(Faculty, pk=request.POST.get('faculty'), university=uni)
			name = ' '.join((request.POST.get('name') or '').split())[:150]
			if name and not fac.departments.filter(name__iexact=name).exists():
				d = Department.objects.create(faculty=fac, name=name)
				audit.log(request.user, 'department.create', 'department', d.pk, f'{name} ({uni.short_name})', '', uni)
				messages.success(request, 'Department added.')
		return redirect('staff_university', pk=uni.pk)
	faculties = list(uni.faculties.prefetch_related('departments').annotate(n_students=Count('students', distinct=True)).order_by('name'))
	dept_counts = dict(StudentProfile.objects.filter(university=uni).values('department_id').annotate(n=Count('id'))
		.values_list('department_id', 'n'))
	for f in faculties:
		f.depts = [(d, dept_counts.get(d.pk, 0)) for d in f.departments.all()]
	return render(request, 'adminpanel/university_detail.html', ctx(request, 'universities', uni=uni, faculties=faculties,
		n_students=StudentProfile.objects.filter(university=uni).count(),
		n_verified=StudentProfile.objects.filter(university=uni, is_verified=True).count(),
		admins=AdminRole.objects.filter(university=uni).select_related('user')))


# ---------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------

@P.admin_required(P.ANALYTICS)
def analytics(request):
	admin = request.admin
	key, days = _days(request)
	reg_labels, reg_values = stats.registration_series(admin, days)
	act_labels, act_groups = stats.activity_series(admin, days)
	eng_labels, eng_groups = stats.engagement(admin, days)
	rep_labels, rep_groups = stats.reports_series(admin, days)
	return render(request, 'adminpanel/analytics.html', ctx(request, 'analytics', days_key=key, days=days,
		periods=[('7', 'Last 7 days'), ('30', 'Last 30 days'), ('90', 'Last 90 days')],
		active=stats.active_users_summary(admin),
		reg_chart=charts.line_chart(reg_labels, reg_values, 'New registrations'),
		act_chart=charts.bar_chart(act_labels, act_groups, 'Posts and comments'), act_names=list(act_groups),
		eng_chart=charts.bar_chart(eng_labels, eng_groups, 'Engagement'), eng_names=list(eng_groups),
		rep_chart=charts.bar_chart(rep_labels, rep_groups, 'Reports'), rep_names=list(rep_groups),
		unis=stats.university_activity(admin, days), top_groups=stats.active_groups_and_communities(admin, days),
		moderation=stats.moderation_summary(admin, days), reason_labels=dict(Report.REASON_CHOICES)))


# ---------------------------------------------------------------------
# Official timetable (courses/official.py)
# ---------------------------------------------------------------------

def _timetable_uni(request, admin):
	"""The university whose timetable is shown: a University Admin's own; a Super Admin picks one."""
	if admin.university:
		return admin.university
	pk = request.POST.get('university') or request.GET.get('university')
	return University.objects.filter(pk=pk).first() if pk and str(pk).isdigit() else None


@P.admin_required(P.TIMETABLE)
def timetable(request):
	from courses import official
	from courses.models import ClassChange, ClassSlot, OfficialClass
	admin = request.admin
	uni = _timetable_uni(request, admin)
	back = reverse('staff_timetable') + (f'?university={uni.pk}' if uni and admin.university is None else '')
	if request.method == 'POST':
		if uni is None:
			messages.error(request, 'Choose the university this timetable is for.')
			return redirect('staff_timetable')
		upload = request.FILES.get('file')
		if not upload:
			messages.error(request, 'Choose the timetable file to upload.')
			return redirect(back)
		if upload.size > 2 * 1024 * 1024:
			messages.error(request, 'The file is too big (2 MB at most).')
			return redirect(back)
		dept = Department.objects.filter(pk=request.POST.get('department') or 0, faculty__university=uni).first()
		try:
			rows, errors = official.check_rows(official.read_rows(upload))
		except official.UploadError as e:
			messages.error(request, str(e))
			return redirect(back)
		if not rows:
			messages.error(request, 'No classes could be read from the file. ' + ' '.join(errors[:5]))
			return redirect(back)
		result = official.import_rows(uni, rows, request.user, department=dept, replace=bool(request.POST.get('replace')))
		errors += result['errors']
		audit.log(request.user, 'timetable.upload', 'university', uni.pk, uni.name,
			f'{result["added"]} added, {result["updated"]} updated, {result["removed"]} removed in {result["courses"]} courses '
			f'from {upload.name}', uni)
		text = (f'Timetable saved for {result["courses"]} course{"" if result["courses"] == 1 else "s"}: '
			f'{result["added"]} class{"" if result["added"] == 1 else "es"} added, {result["updated"]} updated, '
			f'{result["removed"]} removed. {result["students"]} student{"" if result["students"] == 1 else "s"} taking '
			f'these courses now have them on their timetable.')
		if result['new_courses']:
			text += ' New courses created: ' + ', '.join(result['new_courses']) + '.'
		messages.success(request, text)
		if errors:
			more = f' (and {len(errors) - 6} more)' if len(errors) > 6 else ''
			messages.warning(request, f'{len(errors)} row{"" if len(errors) == 1 else "s"} skipped: ' + ' '.join(errors[:6]) + more)
		return redirect(back)
	classes, courses = [], []
	if uni:
		qs = (OfficialClass.objects.filter(course__university=uni).select_related('course')
			.annotate(students=Count('copies', distinct=True)))
		q = ' '.join(request.GET.get('q', '').split())[:40]
		if q:
			qs = qs.filter(Q(course__code__icontains=q) | Q(course__title__icontains=q) | Q(venue__icontains=q))
		classes = list(qs)
		today = timezone.localdate()
		# Coming changes the department made, per official class.
		upcoming = {}
		for c in (ClassChange.objects.filter(slot__official__in=classes, date__gte=today, set_by__isnull=False)
				.exclude(set_by=F('slot__user')).values('slot__official_id', 'date', 'status', 'new_date', 'new_start')
				.distinct().order_by('date')):
			upcoming.setdefault(c['slot__official_id'], []).append(c)
		for o in classes:
			o.coming_changes = upcoming.get(o.pk, [])
			o.next_dates = [today + timedelta(days=(o.day - today.weekday()) % 7 + 7 * w) for w in range(6)]
		courses = sorted({o.course for o in classes}, key=lambda c: c.code)
	return render(request, 'adminpanel/timetable.html', ctx(request, 'timetable', uni=uni, classes=classes,
		course_count=len(courses), q=request.GET.get('q', ''), columns=official.COLUMNS,
		template_rows=official.TEMPLATE_ROWS, kinds=ClassSlot.KIND_CHOICES,
		departments=Department.objects.filter(faculty__university=uni).select_related('faculty') if uni else [],
		universities=University.objects.order_by('name') if admin.university is None else []))


@P.admin_required(P.TIMETABLE)
def timetable_template(request):
	from django.http import HttpResponse
	from courses import official
	resp = HttpResponse(official.template_csv(), content_type='text/csv; charset=utf-8')
	resp['Content-Disposition'] = 'attachment; filename="official-timetable-template.csv"'
	return resp


@P.admin_required(P.TIMETABLE)
@require_POST
def timetable_action(request, pk):
	"""One official class: cancel or move one week (for every student taking it), undo that, or delete the class."""
	from datetime import date, time
	from courses import official
	from courses.models import OfficialClass
	admin = request.admin
	o = get_object_or_404(OfficialClass.objects.select_related('course', 'course__university'), pk=pk)
	if not admin.in_scope(o.course.university_id):
		raise Http404
	uni = o.course.university
	back = reverse('staff_timetable') + (f'?university={uni.pk}' if admin.university is None else '')
	action = request.POST.get('action')

	def _d(v):
		try:
			return date.fromisoformat(v or '')
		except ValueError:
			return None

	def _t(v):
		try:
			return time.fromisoformat(v or '')
		except ValueError:
			return None
	label = f'{o.course.code} {o.get_kind_display().lower()}'
	if action == 'delete':
		n = o.copies.count()
		o.delete()
		audit.log(request.user, 'timetable.delete', 'course', o.course_id, label, f'{o.get_day_display()} {o.start:%H:%M}', uni)
		messages.success(request, f'{label} on {o.get_day_display()} removed from the official timetable and from {n} student timetable{"" if n == 1 else "s"}.')
		return redirect(back)
	day = _d(request.POST.get('date'))
	today = timezone.localdate()
	if day is None or day.weekday() != o.day or day < today:
		messages.error(request, f'Pick one of the coming {o.get_day_display()}s.')
		return redirect(back)
	when = f'{day:%a} {day.day} {day:%b}'
	note = ' '.join((request.POST.get('note') or '').split())[:140]
	if action == 'undo':
		official.undo_official_change(o, day)
		audit.log(request.user, 'timetable.restore', 'course', o.course_id, label, when, uni)
		messages.success(request, f'{label} on {when} is back to normal for every student.')
		return redirect(back)
	if action == 'cancel':
		n = official.change_official(o, day, request.user, cancel=True, note=note)
		audit.log(request.user, 'timetable.cancel', 'course', o.course_id, label, f'{when}. {note}'.strip(), uni)
		messages.success(request, f'{label} on {when} cancelled. {n} student{"" if n == 1 else "s"} told.')
		return redirect(back)
	if action == 'move':
		new_day = _d(request.POST.get('new_date')) or day
		start, end = _t(request.POST.get('new_start')), _t(request.POST.get('new_end'))
		venue = ' '.join((request.POST.get('new_venue') or '').split())[:80]
		if not (start and end) or end <= start or new_day < today:
			messages.error(request, 'Give a date from today on and a start time before the end time.')
			return redirect(back)
		n = official.change_official(o, day, request.user, cancel=False, new_date=new_day, new_start=start, new_end=end,
			new_venue=venue if venue != o.venue else '', note=note)
		audit.log(request.user, 'timetable.move', 'course', o.course_id, label,
			f'{when} moved to {new_day:%a %d %b} {start:%H:%M}-{end:%H:%M} {venue}'.strip(), uni)
		messages.success(request, f'{label} on {when} moved to {new_day:%a} {new_day.day} {new_day:%b}, {start:%H:%M}. {n} student{"" if n == 1 else "s"} told.')
		return redirect(back)
	return redirect(back)


# ---------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------

@P.admin_required(P.ANNOUNCE)
def announcements(request):
	admin = request.admin
	if request.method == 'POST':
		title = ' '.join((request.POST.get('title') or '').split())[:120]
		body = (request.POST.get('body') or '').strip()[:1000]
		kind = request.POST.get('kind') if request.POST.get('kind') in dict(Announcement.KIND_CHOICES) else Announcement.INFO
		audience = request.POST.get('audience')
		uni = None
		if audience == Announcement.UNIVERSITY or not admin.can(P.ANNOUNCE_ALL):
			audience = Announcement.UNIVERSITY
			uni = admin.university or University.objects.filter(pk=request.POST.get('university') or 0).first()
			if uni is None or not admin.in_scope(uni.pk):
				messages.error(request, 'Choose the university this announcement is for.')
				return redirect('staff_announcements')
		days = request.POST.get('days')
		ends = timezone.now() + timedelta(days=int(days)) if days and days.isdigit() and int(days) > 0 else None
		if not (title and body):
			messages.error(request, 'Give the announcement a title and a message.')
		else:
			a = Announcement.objects.create(title=title, body=body, kind=kind, audience=audience, university=uni,
				author=request.user, ends_at=ends)
			audit.log(request.user, 'announcement.create', 'announcement', a.pk, title,
				f'To {uni.short_name if uni else "all universities"}', uni)
			messages.success(request, 'Announcement published. Students see it at the top of UniConnect.')
		return redirect('staff_announcements')
	qs = Announcement.objects.select_related('author', 'university')
	if admin.university:
		qs = qs.filter(university=admin.university)
	return render(request, 'adminpanel/announcements.html', ctx(request, 'announcements', page=_page(request, qs),
		kinds=Announcement.KIND_CHOICES, universities=University.objects.filter(is_active=True).order_by('name') if admin.university is None else []))


@P.admin_required(P.ANNOUNCE)
@require_POST
def announcement_action(request, pk):
	admin = request.admin
	a = get_object_or_404(Announcement, pk=pk)
	if (a.university_id is None and not admin.can(P.ANNOUNCE_ALL)) or (a.university_id and not admin.in_scope(a.university_id)):
		raise Http404
	action = request.POST.get('action')
	if action == 'unpublish':
		a.is_published = False
		a.save(update_fields=['is_published'])
		audit.log(request.user, 'announcement.unpublish', 'announcement', a.pk, a.title, '', a.university)
	elif action == 'publish':
		a.is_published = True
		a.save(update_fields=['is_published'])
		audit.log(request.user, 'announcement.create', 'announcement', a.pk, a.title, 'Published again', a.university)
	elif action == 'delete':
		audit.log(request.user, 'announcement.delete', 'announcement', a.pk, a.title, '', a.university)
		a.delete()
	return redirect('staff_announcements')


# ---------------------------------------------------------------------
# Admin logs, settings (roles), help
# ---------------------------------------------------------------------

@P.admin_required(P.LOGS)
def logs(request):
	admin = request.admin
	qs = AdminLog.objects.select_related('actor', 'university')
	if admin.university:
		qs = qs.filter(university=admin.university)
	action = request.GET.get('action', '')
	if action:
		qs = qs.filter(action=action)
	who = request.GET.get('who', '')
	if who:
		qs = qs.filter(actor__username__icontains=who)
	page = _page(request, qs)
	for l in page:
		l.label = audit.describe(l.action)
	return render(request, 'adminpanel/logs.html', ctx(request, 'logs', page=page, action=action, who=who,
		actions=sorted(audit.LABELS.items(), key=lambda x: x[1])))



def _invite(request, user):
	try:
		services.send_staff_invite(request, user)
	except Exception as e:  # no email set up yet, wrong password, mail server down...
		messages.warning(request, f"The invitation email to {user.email} couldn't be sent ({e.__class__.__name__}). "
			"Check the email settings, then use Resend invite.")
		return False
	audit.log(request.user, 'staff.invite', 'user', user.pk, user.username, user.email)
	messages.success(request, f'Invitation sent to {user.email}. They choose their own password from the link.')
	return True


def _create_staff(request, admin):
	"""Settings > Add a staff member: an admin account that isn't a student."""
	from django.core.validators import validate_email
	from django.core.exceptions import ValidationError
	first = ' '.join((request.POST.get('first_name') or '').split())[:150]
	last = ' '.join((request.POST.get('last_name') or '').split())[:150]
	email = (request.POST.get('email') or '').strip().lower()
	role = request.POST.get('role')
	uni = University.objects.filter(pk=request.POST.get('university') or 0).first() if admin.is_super else admin.university
	try:
		validate_email(email)
		error = None
	except ValidationError:
		error = 'Enter a valid email address.'
	if error:
		pass
	elif not first:
		error = 'Enter their name.'
	elif User.objects.filter(email__iexact=email).exists() or StudentProfile.objects.filter(university_email__iexact=email).exists():
		error = 'An account with that email already exists. Use "Give an existing account a role" instead.'
	elif role not in dict(AdminRole.ROLE_CHOICES):
		error = 'Choose a role.'
	elif not admin.is_super and role not in P.UNI_ADMIN_CAN_ASSIGN:
		error = 'University Admins can add Moderators and Support Staff only.'
	elif role == AdminRole.UNIVERSITY_ADMIN and uni is None:
		error = 'A University Admin needs a university.'
	if error:
		messages.error(request, error)
		return
	user = services.create_staff_account(request.user, first, last, email, role, uni)
	_invite(request, user)


@P.admin_required()
def settings_page(request):
	admin = request.admin
	if request.method == 'POST':
		admin.require(P.ROLES)
		what = request.POST.get('what')
		if what == 'assign':
			ident = (request.POST.get('user') or '').strip().lstrip('@')
			target = User.objects.filter(Q(username__iexact=ident) | Q(email__iexact=ident)).first()
			role = request.POST.get('role')
			uni = University.objects.filter(pk=request.POST.get('university') or 0).first()
			if not admin.is_super:
				uni = admin.university
			error = None
			if target is None:
				error = 'No account with that username or email.'
			elif target.pk == request.user.pk or target.is_superuser:
				error = "That account's role can't be changed here."
			elif role not in dict(AdminRole.ROLE_CHOICES):
				error = 'Choose a role.'
			elif not admin.is_super and role not in P.UNI_ADMIN_CAN_ASSIGN:
				error = 'University Admins can add Moderators and Support Staff only.'
			elif role == AdminRole.UNIVERSITY_ADMIN and uni is None:
				error = 'A University Admin needs a university.'
			elif not admin.is_super and getattr(getattr(target, 'student_profile', None), 'university_id', None) not in (None, admin.university_id):
				error = 'That account belongs to another university.'
			existing = AdminRole.objects.filter(user=target).first() if target else None
			if not error and existing and not admin.is_super and existing.role not in P.UNI_ADMIN_CAN_ASSIGN:
				error = 'Only a Super Admin can change that role.'
			if error:
				messages.error(request, error)
			else:
				AdminRole.objects.update_or_create(user=target, defaults={'role': role,
					'university': None if role == AdminRole.SUPER_ADMIN else uni, 'assigned_by': request.user})
				audit.log(request.user, 'role.assign', 'user', target.pk, target.username,
					f'{dict(AdminRole.ROLE_CHOICES)[role]}{" — " + uni.short_name if uni and role != AdminRole.SUPER_ADMIN else ""}', uni)
				messages.success(request, f'@{target.username} is now {dict(AdminRole.ROLE_CHOICES)[role]}.')
		elif what == 'create':
			_create_staff(request, admin)
		elif what == 'resend':
			r = get_object_or_404(AdminRole.objects.select_related('user'), pk=request.POST.get('role_id'), user__last_login__isnull=True)
			if not admin.is_super and r.university_id != admin.university_id:
				raise Http404
			_invite(request, r.user)
		elif what == 'remove':
			r = get_object_or_404(AdminRole, pk=request.POST.get('role_id'))
			if r.user_id == request.user.pk or (not admin.is_super and (r.role not in P.UNI_ADMIN_CAN_ASSIGN or r.university_id != admin.university_id)):
				raise Http404
			audit.log(request.user, 'role.remove', 'user', r.user_id, r.user.username, r.get_role_display(), r.university)
			r.delete()
			messages.success(request, 'Role removed.')
		return redirect('staff_settings')
	team = AdminRole.objects.select_related('user', 'university', 'assigned_by').order_by('role', 'user__username')
	if admin.university:
		team = team.filter(university=admin.university)
	perm_rows = [
		('View dashboard and users', P.VIEW_USERS), ('See private details (email, matric number)', P.PRIVATE),
		('Verify students', P.VERIFY), ('Warn accounts', P.WARN), ('Suspend / reactivate accounts', P.SUSPEND),
		('Review reports', P.REVIEW), ('Remove content', P.REMOVE), ('Add and edit universities', P.UNIVERSITIES),
		('Faculties and departments', P.STRUCTURE), ('Announcements', P.ANNOUNCE), ('Analytics', P.ANALYTICS),
		('Admin logs', P.LOGS), ('Assign roles', P.ROLES)]
	matrix = [(label, [perm in P.PERMS[r] for r, _ in AdminRole.ROLE_CHOICES]) for label, perm in perm_rows]
	assignable = AdminRole.ROLE_CHOICES if admin.is_super else [(r, l) for r, l in AdminRole.ROLE_CHOICES if r in P.UNI_ADMIN_CAN_ASSIGN]
	return render(request, 'adminpanel/settings.html', ctx(request, 'settings', team=team, matrix=matrix,
		roles=AdminRole.ROLE_CHOICES, assignable=assignable,
		superusers=User.objects.filter(is_superuser=True, is_active=True) if admin.is_super else [],
		universities=University.objects.order_by('name') if admin.is_super else []))


@P.admin_required()
def view_platform(request):
	"""Quick Access > View Platform. Students who are admins just go to their own feed;
	admins who aren't students pick a university to look at, read-only (viewing.py)."""
	from .viewing import SESSION_KEY, allowed_university
	admin = request.admin
	if hasattr(request.user, 'student_profile'):
		return redirect('home')
	if admin.university_id:
		request.session[SESSION_KEY] = admin.university_id
		return redirect('home')
	if request.method == 'POST':
		uni = allowed_university(admin, request.POST.get('university'))
		if uni:
			request.session[SESSION_KEY] = uni.pk
			return redirect('home')
		messages.error(request, 'Choose a university.')
	unis = University.objects.annotate(n=Count('students', distinct=True),
		levels=Count('faculties__departments__levels', distinct=True)).order_by('-n', 'name')
	return render(request, 'adminpanel/view_platform.html', ctx(request, '', unis=unis,
		current=request.session.get(SESSION_KEY)))


@P.admin_required()
def view_platform_stop(request):
	from .viewing import SESSION_KEY
	request.session.pop(SESSION_KEY, None)
	return redirect('staff_overview')


@P.admin_required()
def help_page(request):
	return render(request, 'adminpanel/help.html', ctx(request, ''))


# ---------------------------------------------------------------------
# Student side: acknowledging a warning
# ---------------------------------------------------------------------

@login_required
@require_POST
def acknowledge_warning(request, pk):
	AccountAction.objects.filter(pk=pk, user=request.user, kind=AccountAction.WARNING, acknowledged_at__isnull=True).update(
		acknowledged_at=timezone.now())
	return _safe_back(request, 'home')
