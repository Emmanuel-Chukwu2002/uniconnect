"""What actually happens on a given date, after one-off changes (ClassChange).

A ClassSlot repeats every week. A ClassChange can cancel one week's class or
move it (another time, another day, another venue). Everything that shows or
reminds about classes goes through occurrences_on(), so a cancelled class
disappears from Home, gets no reminder, and is left out of the calendar feed,
and a moved class shows up at its new time instead:

    timetable page (courses/timetable.py)     Home "Today's classes"
    reminders (courses/reminders.py)          calendar export (courses/calendar_feed.py)
"""
from dataclasses import dataclass
from datetime import date as Date, time

from .models import ClassChange, ClassSlot

NORMAL, CANCELLED, MOVED_AWAY, MOVED, MOVED_IN = 'normal', 'cancelled', 'moved_away', 'moved', 'moved_in'


@dataclass
class Occurrence:
	"""One class on one date.

	state:
	  normal      as on the weekly timetable
	  moved       same day, different time or venue
	  moved_in    moved here from another day (change.date is the original day)
	  cancelled   not happening (still listed, crossed out, so it can be undone)
	  moved_away  moved to another day (listed with where it went)
	"""
	slot: ClassSlot
	date: Date
	start: time
	end: time
	venue: str
	state: str = NORMAL
	change: ClassChange = None

	@property
	def active(self):
		"""Actually happening at this date and time."""
		return self.state in (NORMAL, MOVED, MOVED_IN)

	# The slot's own details, so templates can treat an occurrence like a class.
	def __getattr__(self, name):
		return getattr(self.slot, name)


def _apply(slot, day, change):
	if change is None:
		return Occurrence(slot, day, slot.start, slot.end, slot.venue)
	if change.status == ClassChange.CANCELLED:
		return Occurrence(slot, day, slot.start, slot.end, slot.venue, CANCELLED, change)
	new_day = change.new_date or day
	start, end = change.new_start or slot.start, change.new_end or slot.end
	venue = change.new_venue or slot.venue
	if new_day != day:
		return Occurrence(slot, day, slot.start, slot.end, slot.venue, MOVED_AWAY, change)
	return Occurrence(slot, day, start, end, venue, MOVED, change)


def occurrences_on(user, day, slots=None):
	"""Every class of `user` on date `day`, in time order, changes applied.
	`slots`: the user's ClassSlots if already loaded (saves a query)."""
	if slots is None:
		slots = list(ClassSlot.objects.filter(user=user, day=day.weekday()).select_related('course'))
	else:
		slots = [s for s in slots if s.day == day.weekday()]
	changes = {c.slot_id: c for c in ClassChange.objects.filter(slot__in=[s.pk for s in slots], date=day)}
	out = [_apply(s, day, changes.get(s.pk)) for s in slots]
	# Classes moved here from another day.
	for c in (ClassChange.objects.filter(slot__user=user, status=ClassChange.MOVED, new_date=day)
			.exclude(date=day).select_related('slot', 'slot__course')):
		s = c.slot
		out.append(Occurrence(s, day, c.new_start or s.start, c.new_end or s.end, c.new_venue or s.venue, MOVED_IN, c))
	out.sort(key=lambda o: (o.start, o.slot.pk))
	return out


def occurrence(slot, day):
	"""`slot` on date `day` (it may have been moved; None if it doesn't fall on that day)."""
	moved_in = ClassChange.objects.filter(slot=slot, status=ClassChange.MOVED, new_date=day).exclude(date=day).first()
	if moved_in:
		c = moved_in
		return Occurrence(slot, day, c.new_start or slot.start, c.new_end or slot.end, c.new_venue or slot.venue, MOVED_IN, c)
	if slot.day != day.weekday():
		return None
	return _apply(slot, day, ClassChange.objects.filter(slot=slot, date=day).first())
