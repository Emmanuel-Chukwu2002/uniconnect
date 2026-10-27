"""Class reminders: a notification 15 minutes before each class on your
timetable (ClassSlot).

There's no background job in UniConnect, so reminders are made when you're
using it: every page load (feed/context_processors.py) and the bell's
30-second check (feed/views.py notifications_count) call due_reminders(),
which adds a "Class starting soon" notification for any of today's classes
that start in the next 15 minutes and haven't been reminded about yet.
The 30-second check also shows a pop-up for a new reminder (static/js/app.js).
So with UniConnect open in a tab you're reminded on time; open it 5 minutes
before a class and you're reminded straight away; a class that has already
started is never reminded about. A class cancelled for today gets no
reminder; one moved to another time is reminded about at its new time
(courses/schedule.py).

    python manage.py send_class_reminders     does the same for everyone,
                                              e.g. every 5 minutes from a scheduler

Switch them off in Settings > Notifications > Class reminders.
"""
from datetime import datetime, timedelta

from django.utils import timezone

from .models import ClassSlot

LEAD_MINUTES = 15


def _key(slot, day):
	return f'class:{slot.pk}:{day.isoformat()}'


def due_reminders(user, now=None):
	"""Create reminders for `user`'s classes starting within LEAD_MINUTES.
	Returns the new Notification rows (usually none)."""
	from feed.models import Notification as N
	from feed.notifications import is_muted
	if not getattr(user, 'is_authenticated', False):
		return []
	if getattr(user, '_reminders_checked', False):     # once per request
		return []
	user._reminders_checked = True
	now = timezone.localtime(now or timezone.now())
	soon = (now + timedelta(minutes=LEAD_MINUTES)).time()
	if soon < now.time():                               # the window crosses midnight: nothing today
		soon = datetime.max.time()
	from .schedule import occurrences_on
	slots = [o.slot for o in occurrences_on(user, now.date()) if o.active and now.time() < o.start <= soon]
	if not slots or is_muted(user, N.CLASS_REMINDER):
		return []
	today = now.date()
	done = set(N.objects.filter(recipient=user, type=N.CLASS_REMINDER, group_key__in=[_key(s, today) for s in slots])
		.values_list('group_key', flat=True))
	made = []
	for s in slots:
		if _key(s, today) in done:
			continue
		made.append(N.objects.create(recipient=user, actor=user, type=N.CLASS_REMINDER, class_slot=s, group_key=_key(s, today)))
	return made


def kind_word(slot):
	"""'lecture', 'tutorial', 'practical' — or '' for Other."""
	return {ClassSlot.LECTURE: 'lecture', ClassSlot.TUTORIAL: 'tutorial', ClassSlot.PRACTICAL: 'practical'}.get(slot.kind, '')


def pop_up(n, now=None):
	"""What the page's pop-up needs for a new reminder notification `n`."""
	from django.urls import reverse
	now = timezone.localtime(now or timezone.now())
	o = todays(n.class_slot, now.date())
	start = datetime.combine(now.date(), o.start)
	mins = max(1, round((start - now.replace(tzinfo=None)).total_seconds() / 60))
	return {'title': f'Class in {mins} minute{"" if mins == 1 else "s"}', 'text': reminder_text(o),
		'url': reverse('notification_open', args=[n.pk])}


def todays(slot, day):
	"""The class as it happens on `day` (moved time and venue if it was moved)."""
	from .schedule import occurrence
	return occurrence(slot, day) or slot


def clock(t):
	return t.strftime('%I:%M %p').lstrip('0')


def reminder_text(slot):
	"""'COS 401 lecture starts at 10:00 AM · LT 2' — for the pop-up."""
	what = f'{slot.short} {kind_word(slot)}'.strip()
	return f'{what} starts at {clock(slot.start)}' + (f' · {slot.venue}' if slot.venue else '')
