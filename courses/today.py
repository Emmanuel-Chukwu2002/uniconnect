"""Home's "Today" cards (they replaced Stories). "Quick access", round items for the day, in order —

    Question of the day   one per course you take (courses.DailyQuestion)
    Classes               today's classes still to come (your timetable)
    Study sessions        today's sessions in groups you're in
    New files             notes / past questions added to your courses in the last 3 days

and "Upcoming deadlines": exams, tests and assignments less than 7 days away, each
with a countdown ring that fills as the day gets closer.

Rendered by templates/feed/_today_strip.html; styles in restyle.css ("Today strip").
"""
from datetime import timedelta

from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from .models import ClassSlot, Course, CourseEnrollment, CourseMaterial, DailyAnswer, DailyQuestion, Deadline

COUNTDOWN_DAYS = 7    # deadlines further away aren't shown (the ring starts filling from here)
NEW_FILES_DAYS = 3


def clock(t):
	"""10:00 -> '10am', 14:30 -> '2:30pm' (works on Windows too, unlike strftime's %-I)."""
	h = t.hour % 12 or 12
	return f'{h}{":%02d" % t.minute if t.minute else ""}{"am" if t.hour < 12 else "pm"}'


def nice_date(d):
	"""'Thu 23 Oct'."""
	return f'{d:%a} {d.day} {d:%b}'


def my_courses(user):
	return list(Course.objects.filter(enrollments__user=user).order_by('code'))


# ---------------------------------------------------------------------
# Question of the day
# ---------------------------------------------------------------------
def question_for(course, day):
	"""Today's question for a course: one set for this date, else one from the bank
	(picked by the date, so everyone gets the same one and it changes daily)."""
	q = DailyQuestion.objects.filter(course=course, day=day).first()
	if q:
		return q
	bank = list(DailyQuestion.objects.filter(course=course, day__isnull=True).values_list('pk', flat=True))
	if not bank:
		return None
	return DailyQuestion.objects.get(pk=bank[(day.toordinal() + course.pk) % len(bank)])


def results(question, day):
	"""How classmates answered today: {'total', 'correct_pct', 'by': {choice: pct}}."""
	rows = dict(DailyAnswer.objects.filter(question=question, day=day).values('choice').annotate(n=Count('id')).values_list('choice', 'n'))
	total = sum(rows.values())
	by = {k: round(100 * rows.get(k, 0) / total) if total else 0 for k, _ in question.options}
	return {'total': total, 'correct_pct': by.get(question.correct, 0), 'by': by,
		'rows': [(k, text, by[k]) for k, text in question.options]}


def daily_questions(user, courses, day):
	out = []
	mine = {a.question_id: a for a in DailyAnswer.objects.filter(user=user, day=day)}
	for c in courses:
		q = question_for(c, day)
		if not q:
			continue
		q.my_answer = mine.get(q.pk)
		q.stats = results(q, day) if q.my_answer else None
		out.append(q)
	return out


# ---------------------------------------------------------------------
# Deadlines
# ---------------------------------------------------------------------
def countdown(due, now):
	"""('3d', 'in 3 days', fill 0–100) — the short text in the circle, the long one, the ring."""
	left = due - now
	secs = left.total_seconds()
	fill = max(4, min(100, round(100 * (1 - secs / (COUNTDOWN_DAYS * 86400)))))
	local = timezone.localtime(due)
	if secs <= 0:
		return 'Now', 'happening now', 100
	if secs < 3600:
		m = max(1, int(secs // 60))
		return f'{m}m', f'in {m} min', fill
	if local.date() == timezone.localtime(now).date():
		h = int(secs // 3600)
		return f'{h}h', f'today at {clock(local)}', fill
	days = (local.date() - timezone.localtime(now).date()).days
	if days == 1:
		return '1d', f'tomorrow at {clock(local)}', fill
	return f'{days}d', f'in {days} days · {nice_date(local)}', fill


def upcoming_deadlines(courses, now, days=COUNTDOWN_DAYS):
	rows = list(Deadline.objects.filter(course__in=courses, due_at__gte=now - timedelta(hours=2), due_at__lte=now + timedelta(days=days))
		.select_related('course', 'created_by'))
	for d in rows:
		d.short_left, d.long_left, d.fill = countdown(d.due_at, now)
		d.urgent = (d.due_at - now) <= timedelta(days=2)
	return rows


# ---------------------------------------------------------------------
# The strip
# ---------------------------------------------------------------------
def strip(user):
	courses = my_courses(user)
	now = timezone.localtime()
	today = now.date()
	items = []

	for q in daily_questions(user, courses, today):
		done = bool(q.my_answer)
		items.append({'kind': 'question', 'q': q, 'course': q.course, 'label': f'{q.course.code} Quiz',
			'sub': 'Answered' if done else 'Question of the day',
			'done': done, 'right': bool(q.my_answer and q.my_answer.is_correct)})

	# Today's classes, cancelled ones left out and moved ones at their new time (courses/schedule.py).
	from .schedule import occurrences_on
	for s in [o for o in occurrences_on(user, today) if o.active and o.end > now.time()][:6]:
		on = s.start <= now.time()
		items.append({'kind': 'class', 'slot': s, 'label': f'{s.short} at {clock(s.start)}',
			'sub': 'On now' if on else 'Class reminder', 'now': on, 'url': reverse('timetable'), 'icon': s.icon, 'colour': s.colour})

	from studygroups.sessions import my_sessions
	from courses.timetable import _day_bounds
	start, end = _day_bounds(today)
	for s in my_sessions(user, start, end):
		if s.ends_at <= now:
			continue
		on = s.starts_at <= now
		items.append({'kind': 'session', 'session': s, 'label': f'Study at {clock(s.local_start)}', 'title': s.title,
			'sub': 'On now' if on else 'Study session', 'now': on, 'url': s.url, 'photo': s.group.icon_url})

	# Deadlines get their own row ("Upcoming deadlines"), soonest first.
	deadlines = sorted(upcoming_deadlines(courses, now), key=lambda d: d.due_at)
	for d in deadlines:
		d.name = f'{d.course.code} {d.get_kind_display()}'

	items += events_soon(user, now)
	items += group_updates(user, now)
	items += opportunities_closing(user, now)
	items += new_opportunities(user, now, skip={i['url'] for i in items if i['kind'] == 'opportunity'})

	since = now - timedelta(days=NEW_FILES_DAYS)
	new = (CourseMaterial.objects.filter(course__in=courses, created_at__gte=since).exclude(uploaded_by=user)
		.values('course_id', 'kind').annotate(n=Count('id')).order_by('-n'))
	course_map = {c.pk: c for c in courses}
	for r in new[:4]:
		c = course_map[r['course_id']]
		past = r['kind'] == CourseMaterial.PAST_QUESTION
		items.append({'kind': 'files', 'course': c, 'n': r['n'], 'label': f'{c.code} {"Past Qs" if past else "Notes"}',
			'sub': f'{r["n"]} new file{"" if r["n"] == 1 else "s"}',
			'url': reverse('course_detail', args=[c.pk]) + ('?tab=past' if past else '?tab=notes')})
	items += inbox(user)
	far = sorted(upcoming_deadlines(courses, now, days=UPCOMING_DAYS), key=lambda d: d.due_at)
	for d in far:
		d.name = f'{d.course.code} {d.get_kind_display()}'
	return {'items': items, 'deadlines': far, 'upcoming': upcoming(user, far, now),
		'courses': courses, 'kinds': Deadline.KIND_CHOICES}


# ---------------------------------------------------------------------
# The rest of UniConnect: events, study groups, opportunities, messages, notifications
# ---------------------------------------------------------------------
EVENT_DAYS = 7            # Quick access shows events in the next week
OPPORTUNITY_DAYS = 7      # ...and opportunities that close within a week
GROUP_POST_HOURS = 48     # ...and study groups with posts in the last two days
NEW_OPPORTUNITY_DAYS = 7  # ...and opportunities posted in the last week
UPCOMING_DAYS = 7         # the "Upcoming" row: only what's less than a week away


def _university(user):
	profile = getattr(user, 'student_profile', None)
	return getattr(profile, 'university', None)


def _event_due(e):
	from datetime import datetime, time
	return timezone.make_aware(datetime.combine(e.date, e.time or time(23, 59)))


def _day_word(due, now):
	local = timezone.localtime(due)
	days = (local.date() - now.date()).days
	if days == 0:
		return 'Today'
	if days == 1:
		return 'Tomorrow'
	return f'{local:%a} {local.day} {local:%b}'


def _upcoming_events(now, days):
	from feed.models import Event
	return list(Event.objects.filter(date__gte=now.date(), date__lte=now.date() + timedelta(days=days)).order_by('date', 'time'))


def events_soon(user, now):
	from feed.models import Attendee
	events = [e for e in _upcoming_events(now, EVENT_DAYS) if _event_due(e) >= now]
	going = set(Attendee.objects.filter(user=user, event__in=events).values_list('event_id', flat=True))
	events.sort(key=lambda e: (e.pk not in going, e.date))
	out = []
	for e in events[:4]:
		due = _event_due(e)
		when = _day_word(due, now) + (f' · {clock(timezone.localtime(due))}' if e.time else '')
		out.append({'kind': 'event', 'label': e.title, 'sub': f'{"Going · " if e.pk in going else ""}{when}',
			'icon': e.category_icon, 'going': e.pk in going, 'url': reverse('event_detail', args=[e.pk])})
	return out


def group_updates(user, now):
	from studygroups.models import GroupPost, StudyGroupMember as M
	since = now - timedelta(hours=GROUP_POST_HOURS)
	groups = M.objects.filter(user=user, status=M.ACTIVE).values('group_id')
	rows = (GroupPost.objects.filter(group_id__in=groups, created_at__gte=since).exclude(author=user)
		.values('group_id').annotate(n=Count('id')).order_by('-n')[:3])
	from studygroups.models import StudyGroup
	by_id = StudyGroup.objects.in_bulk([r['group_id'] for r in rows])
	out = []
	for r in rows:
		g = by_id.get(r['group_id'])
		if g:
			out.append({'kind': 'group', 'label': g.name, 'n': r['n'],
				'sub': f'{r["n"]} new post{"" if r["n"] == 1 else "s"}', 'photo': g.icon_url,
				'url': reverse('group_detail', args=[g.pk])})
	return out


def _open_opportunities(user, now, days):
	from opportunities.models import Opportunity
	uni = _university(user)
	if not uni:
		return []
	return list(Opportunity.objects.filter(university=uni, is_closed=False, deadline__gte=now.date(),
		deadline__lte=now.date() + timedelta(days=days)).order_by('deadline'))


def _opportunity_due(o):
	from datetime import datetime, time
	return timezone.make_aware(datetime.combine(o.deadline, time(23, 59)))


def opportunities_closing(user, now):
	out = []
	for o in _open_opportunities(user, now, OPPORTUNITY_DAYS)[:3]:
		days = (o.deadline - now.date()).days
		out.append({'kind': 'opportunity', 'label': o.title, 'icon': o.icon, 'url': o.get_absolute_url(),
			'sub': 'Closes today' if days == 0 else ('Closes tomorrow' if days == 1 else f'Closes in {days}d')})
	return out


def new_opportunities(user, now, skip=()):
	"""Opportunities posted at your university in the last week (not yours, still open)."""
	from django.db.models import Q
	from opportunities.models import Opportunity
	uni = _university(user)
	if not uni:
		return []
	rows = (Opportunity.objects.filter(university=uni, is_closed=False, created_at__gte=now - timedelta(days=NEW_OPPORTUNITY_DAYS))
		.filter(Q(deadline__isnull=True) | Q(deadline__gte=now.date())).exclude(posted_by=user).order_by('-created_at'))
	out = []
	for o in rows:
		if o.get_absolute_url() in skip:
			continue
		out.append({'kind': 'opportunity', 'label': o.title, 'icon': o.icon, 'url': o.get_absolute_url(), 'new': True,
			'sub': f'New · {o.get_kind_display()}'})
		if len(out) == 3:
			break
	return out


def inbox(user):
	"""Unread messages and notifications, when there are any."""
	from chat.services import unread_chats_count
	from feed.notifications import unread_count
	out = []
	m = unread_chats_count(user)
	if m:
		out.append({'kind': 'inbox', 'label': 'Messages', 'icon': 'bi-chat-dots', 'n': m,
			'sub': f'{m} unread chat{"" if m == 1 else "s"}', 'url': reverse('messages')})
	n = unread_count(user)
	if n:
		out.append({'kind': 'inbox', 'label': 'Notifications', 'icon': 'bi-bell', 'n': n,
			'sub': f'{n} new', 'url': reverse('notifications')})
	return out


def upcoming(user, deadlines, now, days=UPCOMING_DAYS):
	"""The "Upcoming" row — every deadline in UniConnect, soonest first, each with a
	countdown ring: course exams/tests/assignments, events, opportunities closing,
	study sessions you're going to, polls you haven't voted in yet, and your
	scheduled posts going out."""
	rows = [{'kind': 'deadline', 'due': d.due_at, 'name': d.name, 'sub': d.get_kind_display(), 'icon': 'bi-file-earmark-text',
		'sheet': f'tdD{d.pk}', 'short': d.short_left, 'fill': d.fill, 'urgent': d.urgent, 'd': d} for d in deadlines]
	for e in _upcoming_events(now, days):
		due = _event_due(e)
		if due >= now:
			rows.append({'kind': 'event', 'due': due, 'name': e.title, 'sub': 'Event', 'icon': e.category_icon,
				'url': reverse('event_detail', args=[e.pk])})
	for o in _open_opportunities(user, now, days):
		rows.append({'kind': 'opportunity', 'due': _opportunity_due(o), 'name': o.title, 'sub': f'{o.get_kind_display()} closes',
			'icon': o.icon, 'url': o.get_absolute_url()})
	from studygroups.sessions import my_sessions
	for s in my_sessions(user, now, now + timedelta(days=days)):
		rows.append({'kind': 'session', 'due': s.starts_at, 'name': s.title, 'sub': 'Study session', 'icon': 'bi-people',
			'url': s.url})
	from django.db.models import Q
	from feed.models import Post, PostPoll
	uni = _university(user)
	polls = (PostPoll.objects.filter(closes_at__gt=now, closes_at__lte=now + timedelta(days=days))
		.exclude(votes__user=user).select_related('post'))
	polls = polls.filter(Q(post__author=user) | Q(post__author__student_profile__university=uni)) if uni else polls.filter(post__author=user)
	for pl in polls.order_by('closes_at')[:5]:
		text = ' '.join((pl.post.content or 'Poll').split())
		rows.append({'kind': 'poll', 'due': pl.closes_at, 'name': text[:40] + ('…' if len(text) > 40 else ''),
			'sub': 'Your poll closes' if pl.post.author_id == user.pk else 'Poll closes', 'icon': 'bi-bar-chart',
			'url': reverse('post_detail', args=[pl.post_id])})
	for p in Post.all_objects.filter(author=user, is_scheduled=True, created_at__gt=now, created_at__lte=now + timedelta(days=days)).order_by('created_at')[:5]:
		# Its text stays out of Home until it goes out (only "Scheduled post" shows here).
		rows.append({'kind': 'scheduled', 'due': p.created_at, 'name': 'Your scheduled post',
			'sub': 'Goes out', 'icon': 'bi-send', 'url': reverse('scheduled_posts')})
	for r in rows:
		if r['kind'] != 'deadline':
			r['short'], r['long'], r['fill'] = countdown(r['due'], now)
			r['urgent'] = r['kind'] == 'opportunity' and (r['due'] - now) <= timedelta(days=2)
		r['when'] = timezone.localtime(r['due'])
	rows = [r for r in rows if r['due'] - now < timedelta(days=days)]     # less than a week away
	rows.sort(key=lambda r: r['due'])
	return rows
