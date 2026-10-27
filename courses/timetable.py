"""Timetable (/courses/timetable/, templates/courses/timetable.html): each
student's own weekly classes (ClassSlot), built from My Courses.

    /courses/timetable/?day=0-6             the week strip and that day's classes (today by default)
    /courses/timetable/?day=1&edit=<id>      the same, with that class open for editing
    /courses/timetable/add/                  POST: add a class (also used by "Add" on a suggestion)
    /courses/timetable/<id>/edit/            POST
    /courses/timetable/<id>/delete/          POST
    /courses/timetable/<id>/change/          POST: cancel or move one week's class, or undo that
    /courses/timetable/calendar.ics          download the timetable for a calendar app
    /courses/timetable/calendar/<token>.ics  the private link a calendar app subscribes to

One-off changes (ClassChange, courses/schedule.py): "no class this Tuesday" or
"moved to Thursday 2 PM". Home, reminders and the calendar export all follow them.
Classes from the department's official timetable (OfficialClass, uploaded in the
admin dashboard, courses/official.py) arrive on their own, marked "Official".

Suggestions: classes that classmates added for the courses you take, and
you haven't — one tap copies them. Home shows "Today's classes"
(today_agenda() below, used by feed/views.py home).

Study sessions (studygroups/sessions.py) you said Going or Maybe to show
here too, beside your classes: the week strip is the coming 7 days, so a
session appears on its day if it's within the next week; one that
overlaps a class says so.
"""
from datetime import time

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from feed.notifications import is_muted

from .models import ClassChange, ClassSlot, Course, CourseEnrollment, OfficialClassSkip
from .schedule import occurrences_on


class SlotForm(forms.ModelForm):
	class Meta:
		model = ClassSlot
		fields = ['course', 'title', 'kind', 'day', 'start', 'end', 'venue']
		widgets = {
			'start': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
			'end': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
			'title': forms.TextInput(attrs={'placeholder': 'e.g. SIWES briefing'}),
			'venue': forms.TextInput(attrs={'placeholder': 'e.g. LT 2, Faculty of Science'}),
		}

	def __init__(self, *args, user=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.user = user
		self.fields['course'].queryset = Course.objects.filter(enrollments__user=user).order_by('code') if user else Course.objects.none()
		self.fields['course'].required = False
		self.fields['course'].empty_label = 'Something else (type a title)'

	def clean(self):
		data = super().clean()
		if not data.get('course') and not (data.get('title') or '').strip():
			raise forms.ValidationError('Pick one of your courses, or type what the class is.')
		if data.get('course'):
			data['title'] = ''
		start, end = data.get('start'), data.get('end')
		if start and end and end <= start:
			self.add_error('end', 'The class must end after it starts.')
		return data


def _clashes(user, slot):
	return ClassSlot.objects.filter(user=user, day=slot.day, start__lt=slot.end, end__gt=slot.start).exclude(pk=slot.pk)


def today_classes(user):
	"""Today's classes still to come or happening now (for Home), one-off
	changes applied: cancelled ones left out, moved ones at their new time."""
	now = timezone.localtime()
	return [o for o in occurrences_on(user, now.date()) if o.active and o.end > now.time()][:4]


def _day_bounds(day):
	"""Start and end (aware) of a local date."""
	from datetime import datetime, timedelta
	start = timezone.make_aware(datetime.combine(day, time(0, 0)))
	return start, start + timedelta(days=1)


CLASS_STEPS = ('Today', '1 hour to go', 'Reminder', 'Started', 'Halfway')


def class_progress(start, end, now):
	"""How far along a class (or study session) is, for Home's class cards:
	five steps — it's today, an hour to go, the 15-minute reminder, started, halfway —
	and a status: Upcoming, Starting soon or In progress."""
	from datetime import timedelta
	marks = [None, start - timedelta(hours=1), start - timedelta(minutes=15), start, start + (end - start) / 2]
	steps = [True] + [now >= m for m in marks[1:]]
	if now >= start:
		status, key = 'In Progress', 'live'
		left = end - now
	elif now >= marks[2]:
		status, key = 'Starting soon', 'soon'
		left = start - now
	else:
		status, key = 'Upcoming', 'next'
		left = start - now
	mins = max(1, int(left.total_seconds() // 60))
	span = f'{mins // 60}h {mins % 60}m' if mins >= 60 else f'{mins} min'
	when = f'Ends in {span}' if key == 'live' else f'In {span}'
	return {'steps': list(zip(CLASS_STEPS, steps)), 'done': sum(steps), 'status': status, 'status_key': key, 'when': when}


def today_agenda(user):
	"""Home's "Today's classes" card: today's classes and study sessions still to come
	or happening now, in time order (at most 5), each with its progress (class_progress)."""
	from datetime import datetime
	from studygroups.sessions import my_sessions
	now = timezone.localtime()
	rows = []
	for s in today_classes(user):
		start = timezone.make_aware(datetime.combine(now.date(), s.start))
		end = timezone.make_aware(datetime.combine(now.date(), s.end))
		rows.append({'start': s.start, 'label': s.short + ('' if s.kind == ClassSlot.OTHER else f' {s.get_kind_display()}'),
			'where': ('Moved · ' if s.state != 'normal' else '') + s.venue, 'url': reverse('timetable'), 'now': s.start <= now.time(), 'session': False,
			'icon': 'bi-journal-text', **class_progress(start, end, now)})
	start, end = _day_bounds(now.date())
	for s in my_sessions(user, start, end):
		if s.ends_at <= now:
			continue
		rows.append({'start': s.local_start.time(), 'label': s.title, 'where': s.place or ('Online' if s.link else s.group.title),
			'url': s.url, 'now': s.starts_at <= now, 'session': True, 'icon': 'bi-people',
			**class_progress(s.starts_at, s.ends_at, now)})
	rows.sort(key=lambda r: r['start'])
	return rows[:5]


def suggestions_for(user):
	"""Classes classmates added for your courses that you don't have yet."""
	mine = set(ClassSlot.objects.filter(user=user, course__isnull=False).values_list('course_id', 'day', 'start'))
	courses = CourseEnrollment.objects.filter(user=user).values('course_id')
	rows = (ClassSlot.objects.filter(course_id__in=courses).exclude(user=user)
		.values('course_id', 'kind', 'day', 'start', 'end', 'venue').annotate(n=Count('id')).order_by('-n', 'day', 'start'))
	out, seen = [], set()
	course_map = {c.pk: c for c in Course.objects.filter(pk__in=courses)}
	for r in rows:
		key = (r['course_id'], r['day'], r['start'])
		if key in mine or key in seen:
			continue
		seen.add(key)
		r['course'] = course_map.get(r['course_id'])
		r['day_name'] = ClassSlot.DAYS[r['day']]
		r['kind_label'] = dict(ClassSlot.KIND_CHOICES).get(r['kind'], '')
		out.append(r)
		if len(out) >= 6:
			break
	return out


@login_required
def timetable(request):
	if getattr(request.user, 'student_profile', None) is None:
		raise Http404
	today = timezone.localdate().weekday()
	try:
		day = int(request.GET.get('day', today))
	except ValueError:
		day = today
	day = day if 0 <= day <= 6 else today
	slots = list(ClassSlot.objects.filter(user=request.user).select_related('course', 'official'))
	# Study sessions in the coming 7 days (studygroups/sessions.py), on their weekday.
	from datetime import timedelta
	from studygroups.sessions import my_sessions
	today_date = timezone.localdate()
	date_of = {d: today_date + timedelta(days=(d - today) % 7) for d in range(7)}
	week_start, _ = _day_bounds(today_date)
	sessions = my_sessions(request.user, week_start, week_start + timedelta(days=7))
	session_counts = {d: 0 for d in range(7)}
	for s in sessions:
		session_counts[s.local_start.weekday()] += 1
	# This week's real classes, date by date: one-off changes (cancelled, moved) applied.
	occ = {d: occurrences_on(request.user, date_of[d], slots) for d in range(7)}
	week = [{'n': d, 'short': ClassSlot.DAYS[d][:3], 'count': sum(o.active for o in occ[d]) + session_counts[d],
		'is_today': d == today, 'date': date_of[d]} for d in range(7)]
	day_slots = occ[day]
	live = [o for o in day_slots if o.active]
	for s in day_slots:
		s.clash = s.active and any(o is not s and o.start < s.end and o.end > s.start for o in live)
	now_dt = timezone.now()
	day_sessions = [s for s in sessions if s.local_start.date() == date_of[day]]
	for s in day_sessions:
		st, en = s.local_start.time(), s.local_end.time() if s.local_end.date() == s.local_start.date() else time(23, 59)
		s.clash_with = next((c for c in live if c.start < en and c.end > st), None)
		s.is_now = s.starts_at <= now_dt < s.ends_at
		s.is_past = s.ends_at <= now_dt
	# One list in time order: classes and sessions.
	items = [{'slot': s, 'at': s.start} for s in day_slots] + [{'session': s, 'at': s.local_start.time()} for s in day_sessions]
	items.sort(key=lambda i: i['at'])
	editing = None
	if request.GET.get('edit'):
		editing = next((s for s in slots if str(s.pk) == request.GET['edit'] and not s.official_id), None)
	# "Move this week's class": ?move=<slot id> opens the move form for this day's date.
	moving = None
	if request.GET.get('move'):
		moving = next((o for o in day_slots if str(o.pk) == request.GET['move'] and o.state != 'moved_in'), None)
	form = SlotForm(instance=editing, user=request.user, initial=None if editing else {'day': day, 'start': time(8, 0), 'end': time(10, 0)})
	now = timezone.localtime()
	return render(request, 'courses/timetable.html', {
		'week': week, 'day': day, 'day_name': ClassSlot.DAYS[day], 'today': today, 'slots': day_slots,
		'items': items, 'day_sessions': day_sessions, 'day_date': date_of[day], 'moving': moving,
		'class_count': sum(o.active for o in day_slots), 'feed_url': feed_url(request),
		'day_is_past': date_of[day] < today_date, 'today_date': today_date,
		'total': len(slots), 'form': form, 'editing': editing, 'tt_suggestions': suggestions_for(request.user),
		'now_time': now.time() if day == today else None,
		'has_courses': CourseEnrollment.objects.filter(user=request.user).exists(),
		'reminders_on': not is_muted(request.user, 'class_reminder'),
	})


def _back(day, extra=''):
	return redirect(f"{reverse('timetable')}?day={day}{extra}")


@login_required
@require_POST
def add_slot(request):
	form = SlotForm(request.POST, user=request.user)
	if not form.is_valid():
		errors = form.non_field_errors() or [e for errs in form.errors.values() for e in errs]
		messages.error(request, errors[0] if errors else 'Check the class details.')
		return _back(request.POST.get('day', ''))
	slot = form.save(commit=False)
	slot.user = request.user
	slot.save()
	clash = _clashes(request.user, slot).first()
	if clash:
		messages.warning(request, f'Added — note it overlaps {clash.short} ({clash.start:%H:%M}–{clash.end:%H:%M}).')
	else:
		messages.success(request, f'{slot.short} added to {slot.get_day_display()}.')
	return _back(slot.day)


@login_required
@require_POST
def edit_slot(request, slot_id):
	slot = get_object_or_404(ClassSlot, pk=slot_id, user=request.user)
	if slot.official_id:
		messages.error(request, 'This class is on your department\'s official timetable, so its time is set by the department. '
			'To change one week, use "Move this week" instead.')
		return _back(slot.day)
	form = SlotForm(request.POST, instance=slot, user=request.user)
	if not form.is_valid():
		errors = form.non_field_errors() or [e for errs in form.errors.values() for e in errs]
		messages.error(request, errors[0] if errors else 'Check the class details.')
		return _back(slot.day, f'&edit={slot.pk}')
	slot = form.save()
	messages.success(request, 'Class updated.')
	return _back(slot.day)


@login_required
@require_POST
def delete_slot(request, slot_id):
	slot = get_object_or_404(ClassSlot, pk=slot_id, user=request.user)
	day = slot.day
	if slot.official_id:            # don't add it back next time the department updates the timetable
		OfficialClassSkip.objects.get_or_create(user=request.user, official_id=slot.official_id)
	slot.delete()
	messages.success(request, 'Class removed from your timetable.')
	return _back(day)


def _date(value):
	from datetime import date
	try:
		return date.fromisoformat(value or '')
	except ValueError:
		return None


def _time(value):
	try:
		return time.fromisoformat(value or '')
	except ValueError:
		return None


@login_required
@require_POST
def change_slot(request, slot_id):
	"""Cancel or move one week's class (action=cancel / move), or undo that (action=clear).
	The weekly class stays as it is; only that date changes (courses/schedule.py)."""
	from datetime import timedelta
	slot = get_object_or_404(ClassSlot.objects.select_related('course'), pk=slot_id, user=request.user)
	day = _date(request.POST.get('date'))
	today = timezone.localdate()
	if day is None or day.weekday() != slot.day or day < today or day > today + timedelta(days=180):
		messages.error(request, 'Pick one of the coming dates this class is on.')
		return _back(slot.day)
	existing = ClassChange.objects.filter(slot=slot, date=day).first()
	if existing and existing.by_department:
		messages.error(request, 'Your department changed this class for that date, so it can only be changed back by them.')
		return _back(slot.day)
	action = request.POST.get('action')
	when = f'{day:%a} {day.day} {day:%b}'
	if action == 'clear':
		if existing:
			existing.delete()
		messages.success(request, f'{slot.short} is back to normal on {when}.')
		return _back(slot.day)
	note = ' '.join((request.POST.get('note') or '').split())[:140]
	if action == 'cancel':
		ClassChange.objects.update_or_create(slot=slot, date=day, defaults={'status': ClassChange.CANCELLED,
			'new_date': None, 'new_start': None, 'new_end': None, 'new_venue': '', 'note': note, 'set_by': request.user})
		messages.success(request, f'{slot.short} on {when} is marked cancelled. No reminder will be sent for it.')
		return _back(slot.day)
	if action == 'move':
		new_day = _date(request.POST.get('new_date')) or day
		start, end = _time(request.POST.get('new_start')), _time(request.POST.get('new_end'))
		venue = ' '.join((request.POST.get('new_venue') or '').split())[:80]
		error = None
		if not (start and end):
			error = 'Give the new start and end time.'
		elif end <= start:
			error = 'The class must end after it starts.'
		elif new_day < today or new_day > today + timedelta(days=180):
			error = 'Pick a date from today on.'
		elif new_day == day and start == slot.start and end == slot.end and venue in ('', slot.venue):
			error = 'That is the usual time and place. Change the date, time or venue.'
		if error:
			messages.error(request, error)
			return redirect(f"{reverse('timetable')}?day={slot.day}&move={slot.pk}#tt-form")
		ClassChange.objects.update_or_create(slot=slot, date=day, defaults={'status': ClassChange.MOVED,
			'new_date': new_day, 'new_start': start, 'new_end': end, 'new_venue': venue if venue != slot.venue else '',
			'note': note, 'set_by': request.user})
		messages.success(request, f'{slot.short} moved to {new_day:%a} {new_day.day} {new_day:%b}, {start:%H:%M}–{end:%H:%M}.')
		return _back(new_day.weekday())
	return _back(slot.day)


def feed_url(request):
	"""The private calendar link for this student (made the first time it's needed)."""
	from .calendar_feed import feed_for
	return request.build_absolute_uri(reverse('timetable_calendar_feed', args=[feed_for(request.user).token]))
