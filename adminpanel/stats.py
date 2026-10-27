"""Numbers for the Overview and Analytics pages — all counted from the database,
scoped to the admin's university when they have one.

Definitions (so the numbers can be explained):
  Total users        student accounts (accounts.StudentProfile)
  Active users       DISTINCT students who did something in the period: posted,
                     commented, liked, reposted, saved a post, opened or saw a post
                     (feed.PostView, demo rows excluded) or sent a chat message.
                     Monthly active = distinct over 30 days, never a sum of days.
  Pending reports    reports Pending or Under review
  Suspended          accounts with a suspension not yet lifted
  Events             upcoming and today's events
  Change (↑ 12%)     this period's new items compared with the period before it
"""
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import StudentProfile, University
from feed.models import Bookmark, Comment, Event, Like, Post, PostView, Report, Repost

from .models import AccountAction

User = get_user_model()
PERIODS = {'7': 7, '30': 30, '90': 90}


def _scoped(qs, admin, field):
	return qs.filter(admin.scope_q(field)) if admin.university else qs


def change(cur, prev):
	"""(text, direction) for a change badge: ('12%', 'up'), ('New', 'up'), ('0%', 'flat')."""
	if prev == 0:
		return ('New', 'up') if cur else ('0%', 'flat')
	pct = round((cur - prev) * 100 / prev)
	return (f'{abs(pct)}%', 'up' if pct > 0 else 'down' if pct < 0 else 'flat')


def active_user_ids(admin, start, end):
	"""Distinct students with a qualifying action between start and end."""
	ids = set()
	sources = [
		(Post.objects, 'author_id', 'author__student_profile__university'),
		(Comment.objects, 'author_id', 'author__student_profile__university'),
		(Like.objects, 'user_id', 'user__student_profile__university'),
		(Repost.objects, 'user_id', 'user__student_profile__university'),
		(Bookmark.objects, 'user_id', 'user__student_profile__university'),
		(PostView.objects.filter(is_simulated=False), 'user_id', 'user__student_profile__university'),
	]
	try:
		from chat.models import Message
		sources.append((Message.objects.filter(sender__isnull=False), 'sender_id', 'sender__student_profile__university'))
	except Exception:
		pass
	for qs, field, uni in sources:
		qs = _scoped(qs.filter(created_at__gte=start, created_at__lt=end), admin, uni)
		ids |= set(qs.values_list(field, flat=True).distinct())
	ids.discard(None)
	students = _scoped(StudentProfile.objects.filter(user_id__in=ids), admin, 'university')
	return set(students.values_list('user_id', flat=True))


def overview_cards(admin, days):
	now = timezone.now()
	start, prev = now - timedelta(days=days), now - timedelta(days=2 * days)
	period = 'this week' if days == 7 else f'in {days} days'

	students = _scoped(StudentProfile.objects.all(), admin, 'university')
	new_now = students.filter(created_at__gte=start).count()
	new_prev = students.filter(created_at__gte=prev, created_at__lt=start).count()

	active_now = len(active_user_ids(admin, start, now))
	active_prev = len(active_user_ids(admin, prev, start))

	posts = _scoped(Post.objects.all(), admin, 'author__student_profile__university')
	posts_now = posts.filter(created_at__gte=start).count()
	posts_prev = posts.filter(created_at__gte=prev, created_at__lt=start).count()

	reports = _scoped(Report.objects.all(), admin, 'university')
	pending = reports.filter(status__in=[Report.OPEN, Report.REVIEWING]).count()
	rep_now = reports.filter(created_at__gte=start).count()
	rep_prev = reports.filter(created_at__gte=prev, created_at__lt=start).count()

	susp = _scoped(AccountAction.objects.filter(kind=AccountAction.SUSPENSION), admin, 'user__student_profile__university')
	suspended = susp.filter(lifted_at__isnull=True).values('user_id').distinct().count()
	susp_now = susp.filter(created_at__gte=start).count()
	susp_prev = susp.filter(created_at__gte=prev, created_at__lt=start).count()

	unis = University.objects.filter(is_active=True)
	if admin.university:
		unis = unis.filter(pk=admin.university.pk)

	events = Event.objects.all()
	if admin.university:
		events = events.filter(Q(organizer__student_profile__university=admin.university) | Q(community__university=admin.university))
	upcoming = events.filter(date__gte=timezone.localdate()).count()
	ev_now = events.filter(created_at__gte=start).count()
	ev_prev = events.filter(created_at__gte=prev, created_at__lt=start).count()

	from studygroups.models import StudyGroup
	from communities.models import Community
	groups = _scoped(StudyGroup.objects.all(), admin, 'university')
	comms = _scoped(Community.objects.all(), admin, 'university')
	gc = groups.count() + comms.count()
	gc_now = groups.filter(created_at__gte=start).count() + comms.filter(created_at__gte=start).count()
	gc_prev = (groups.filter(created_at__gte=prev, created_at__lt=start).count()
		+ comms.filter(created_at__gte=prev, created_at__lt=start).count())

	def card(key, label, value, sub, icon, tone, delta=None, bad_when_up=False):
		text, direction = delta if delta else ('', 'flat')
		good = (direction == 'down') if bad_when_up else (direction == 'up')
		return {'key': key, 'label': label, 'value': value, 'sub': sub, 'icon': icon, 'tone': tone,
			'delta': text, 'dir': direction, 'good': good if direction != 'flat' else None}

	return [
		card('users', 'Total Users', students.count(), f'+{new_now:,} new {period}', 'bi-people-fill', 'blue', change(new_now, new_prev)),
		card('active', 'Active Users', active_now, f'Active in the last {days} days', 'bi-activity', 'green', change(active_now, active_prev)),
		card('posts', 'Total Posts', posts.count(), f'+{posts_now:,} {period}', 'bi-file-earmark-text-fill', 'purple', change(posts_now, posts_prev)),
		card('reports', 'Pending Reports', pending, 'Need review', 'bi-flag-fill', 'red', change(rep_now, rep_prev), bad_when_up=True),
		card('suspended', 'Suspended Accounts', suspended, 'Currently suspended', 'bi-slash-circle', 'red', change(susp_now, susp_prev), bad_when_up=True),
		card('universities', 'Total Universities', unis.count(), 'Active universities', 'bi-bank2', 'blue', None),
		card('events', 'Events', upcoming, 'Upcoming & ongoing', 'bi-calendar-event-fill', 'amber', change(ev_now, ev_prev)),
		card('groups', 'Groups & Communities', gc, 'Total groups and communities', 'bi-people-fill', 'teal', change(gc_now, gc_prev)),
	]


# ---------------------------------------------------------------------
# Time series
# ---------------------------------------------------------------------

def buckets(days):
	"""[(start_date, end_date_exclusive, label)] covering the last `days` days:
	daily for 7, 5-day steps for 30, weekly for 90."""
	step = 1 if days <= 7 else 5 if days <= 30 else 7
	today = timezone.localdate()
	first = today - timedelta(days=days - 1)
	out, d = [], first
	while d <= today:
		end = min(d + timedelta(days=step), today + timedelta(days=1))
		out.append((d, end, f'{d:%b} {d.day}'))
		d = end
	return out


def series(qs, field, bks):
	"""Counts of qs rows whose `field` falls in each bucket (one query)."""
	tz = timezone.get_current_timezone()
	start = timezone.make_aware(datetime.combine(bks[0][0], time.min), tz)
	dates = [timezone.localtime(v).date() for v in qs.filter(**{f'{field}__gte': start}).values_list(field, flat=True)]
	return [sum(1 for x in dates if a <= x < b) for a, b, _ in bks]


def registration_series(admin, days):
	bks = buckets(days)
	return [b[2] for b in bks], series(_scoped(StudentProfile.objects.all(), admin, 'university'), 'created_at', bks)


def activity_series(admin, days):
	bks = buckets(days)
	posts = series(_scoped(Post.objects.all(), admin, 'author__student_profile__university'), 'created_at', bks)
	comments = series(_scoped(Comment.objects.all(), admin, 'author__student_profile__university'), 'created_at', bks)
	likes = series(_scoped(Like.objects.all(), admin, 'user__student_profile__university'), 'created_at', bks)
	return [b[2] for b in bks], {'Posts': posts, 'Comments': comments, 'Likes': likes}


def most_active_universities(admin, limit=5):
	qs = University.objects.annotate(n_students=Count('students', distinct=True))
	if admin.university:
		qs = qs.filter(pk=admin.university.pk)
	return list(qs.order_by('-n_students', 'name')[:limit])


def recent_reports(admin, limit=5):
	return list(_scoped(Report.objects.all(), admin, 'university').select_related('reported_user')[:limit])


def recent_activity(admin, limit=6):
	"""A merged feed of recent events on the platform (newest first)."""
	items = []
	show_email = admin.can('private_details')
	for p in _scoped(StudentProfile.objects.select_related('user'), admin, 'university').order_by('-created_at')[:limit]:
		items.append({'when': p.created_at, 'icon': 'bi-person-plus-fill', 'tone': 'blue', 'title': 'New user registered',
			'sub': p.university_email if show_email else f'@{p.user.username}'})
	for r in _scoped(Report.objects.all(), admin, 'university').order_by('-created_at')[:limit]:
		what = f'{r.get_target_type_display()} #{r.target_id}' if r.target_id else r.get_target_type_display()
		items.append({'when': r.created_at, 'icon': 'bi-flag-fill' if r.target_type == 'post' else 'bi-shield-fill-exclamation',
			'tone': 'red', 'title': 'Post reported' if r.target_type == 'post' else 'Report submitted',
			'sub': f'{r.get_reason_display()} ({what})'})
	for a in (_scoped(AccountAction.objects.filter(kind=AccountAction.SUSPENSION), admin, 'user__student_profile__university')
			.select_related('user').order_by('-created_at')[:limit]):
		items.append({'when': a.created_at, 'icon': 'bi-slash-circle', 'tone': 'red', 'title': 'User suspended',
			'sub': f'@{a.user.username}'})
	events = Event.objects.all()
	if admin.university:
		events = events.filter(Q(organizer__student_profile__university=admin.university) | Q(community__university=admin.university))
	for e in events.order_by('-created_at')[:limit]:
		items.append({'when': e.created_at, 'icon': 'bi-calendar-check', 'tone': 'green', 'title': 'New event created', 'sub': e.title})
	from .models import AdminLog
	for l in AdminLog.objects.filter(action='university.create').order_by('-created_at')[:limit]:
		if admin.university is None:
			items.append({'when': l.created_at, 'icon': 'bi-bank2', 'tone': 'blue', 'title': 'New university added', 'sub': l.target_label})
	items.sort(key=lambda i: i['when'], reverse=True)
	for i in items:
		i['ago'] = short_ago(i['when'])
	return items[:limit]


def short_ago(dt):
	secs = max(0, int((timezone.now() - dt).total_seconds()))
	for unit, n in (('d', 86400), ('h', 3600), ('m', 60)):
		if secs >= n:
			return f'{secs // n}{unit} ago'
	return 'just now'


def system_status():
	"""Real checks: the database answers, no migrations are waiting, uploads can be written."""
	issues = []
	try:
		User.objects.exists()
	except Exception:
		issues.append('The database is not answering.')
	try:
		from django.db import connection
		from django.db.migrations.executor import MigrationExecutor
		plan = MigrationExecutor(connection).migration_plan(MigrationExecutor(connection).loader.graph.leaf_nodes())
		if plan:
			issues.append(f'{len(plan)} database migration(s) not applied — run python manage.py migrate.')
	except Exception:
		pass
	try:
		import os
		from django.conf import settings
		if not os.access(settings.MEDIA_ROOT, os.W_OK) and os.path.exists(settings.MEDIA_ROOT):
			issues.append('Uploads folder (media/) is not writable.')
	except Exception:
		pass
	return issues


# ---------------------------------------------------------------------
# Analytics page
# ---------------------------------------------------------------------

def engagement(admin, days):
	bks = buckets(days)
	labels = [b[2] for b in bks]
	reposts = series(_scoped(Repost.objects.all(), admin, 'user__student_profile__university'), 'created_at', bks)
	views = series(_scoped(PostView.objects.filter(is_simulated=False), admin, 'user__student_profile__university'), 'created_at', bks)
	likes = series(_scoped(Like.objects.all(), admin, 'user__student_profile__university'), 'created_at', bks)
	return labels, {'Likes': likes, 'Reposts': reposts, 'Views': views}


def reports_series(admin, days):
	bks = buckets(days)
	qs = _scoped(Report.objects.all(), admin, 'university')
	received = series(qs, 'created_at', bks)
	resolved = series(qs.filter(status__in=Report.CLOSED, reviewed_at__isnull=False), 'reviewed_at', bks)
	return [b[2] for b in bks], {'Received': received, 'Resolved': resolved}


def active_users_summary(admin):
	now = timezone.now()
	return {
		'daily': len(active_user_ids(admin, now - timedelta(days=1), now)),
		'weekly': len(active_user_ids(admin, now - timedelta(days=7), now)),
		'monthly': len(active_user_ids(admin, now - timedelta(days=30), now)),
	}


def active_groups_and_communities(admin, days, limit=5):
	from communities.models import Community
	from studygroups.models import GroupPost, StudyGroup
	start = timezone.now() - timedelta(days=days)
	comms = list(_scoped(Community.objects.all(), admin, 'university')
		.annotate(n=Count('posts', filter=Q(posts__created_at__gte=start), distinct=True))
		.filter(n__gt=0).order_by('-n')[:limit])
	groups = list(_scoped(StudyGroup.objects.all(), admin, 'university')
		.annotate(n=Count('posts', filter=Q(posts__created_at__gte=start), distinct=True))
		.filter(n__gt=0).order_by('-n')[:limit])
	rows = [{'name': c.name, 'kind': 'Community', 'n': c.n} for c in comms] + [{'name': g.title, 'kind': 'Group', 'n': g.n} for g in groups]
	return sorted(rows, key=lambda r: -r['n'])[:limit]


def university_activity(admin, days, limit=8):
	"""Per university: students, new this period, posts this period."""
	start = timezone.now() - timedelta(days=days)
	qs = University.objects.annotate(
		n_students=Count('students', distinct=True),
		n_new=Count('students', filter=Q(students__created_at__gte=start), distinct=True))
	if admin.university:
		qs = qs.filter(pk=admin.university.pk)
	rows = list(qs.order_by('-n_students')[:limit])
	posts = dict(Post.objects.filter(created_at__gte=start).values('author__student_profile__university')
		.annotate(n=Count('id')).values_list('author__student_profile__university', 'n'))
	for u in rows:
		u.n_posts = posts.get(u.pk, 0)
	return rows


def moderation_summary(admin, days):
	start = timezone.now() - timedelta(days=days)
	reps = _scoped(Report.objects.filter(created_at__gte=start), admin, 'university')
	acts = _scoped(AccountAction.objects.filter(created_at__gte=start), admin, 'user__student_profile__university')
	return {
		'reports': reps.count(),
		'removed': reps.filter(status=Report.REMOVED).count(),
		'dismissed': reps.filter(status=Report.DISMISSED).count(),
		'actioned': reps.filter(status=Report.ACTIONED).count(),
		'warnings': acts.filter(kind=AccountAction.WARNING).count(),
		'suspensions': acts.filter(kind=AccountAction.SUSPENSION).count(),
		'by_reason': list(reps.values('reason').annotate(n=Count('id')).order_by('-n')),
	}
