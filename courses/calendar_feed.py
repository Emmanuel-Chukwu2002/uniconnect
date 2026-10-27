"""Calendar export: a student's timetable as an iCalendar (.ics) file, so Google
Calendar, the iPhone Calendar or Outlook show the classes and remind about them,
even when UniConnect isn't open.

    /courses/timetable/calendar.ics           download once (signed in)
    /courses/timetable/calendar/<token>.ics   subscribe: the calendar app checks it
                                              again every few hours, so new classes
                                              and changes show up on their own
    /courses/timetable/calendar/reset/        POST: a new private link (the old one stops working)

Each weekly class is one repeating event (RRULE:FREQ=WEEKLY). A cancelled week
is left out (EXDATE); a moved week replaces that one date (RECURRENCE-ID).
Each event carries a 15-minute alarm unless class reminders are switched off.
The format is RFC 5545.
"""
import secrets
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from feed.notifications import is_muted

from .models import ClassChange, ClassSlot, TimetableFeed
from .reminders import LEAD_MINUTES

KIND = dict(ClassSlot.KIND_CHOICES)


def feed_for(user):
	feed = TimetableFeed.objects.filter(user=user).first()
	if feed is None:
		feed = TimetableFeed.objects.create(user=user, token=secrets.token_urlsafe(24))
	return feed


def _esc(text):
	return (text or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def _fold(line):
	"""Lines longer than 75 bytes are continued on the next line after a space (RFC 5545 3.1)."""
	raw = line.encode('utf-8')
	if len(raw) <= 75:
		return line
	parts, chunk = [], b''
	for ch in line:
		b = ch.encode('utf-8')
		if len(chunk) + len(b) > (75 if not parts else 74):
			parts.append(chunk.decode('utf-8'))
			chunk = b''
		chunk += b
	parts.append(chunk.decode('utf-8'))
	return '\r\n '.join(parts)


def _local(day, t):
	return datetime.combine(day, t).strftime('%Y%m%dT%H%M%S')


def _first_date(slot):
	"""The first date the weekly class happens: its weekday, on or after the day it was added."""
	start = timezone.localtime(slot.created_at).date() if slot.created_at else timezone.localdate()
	return start + timedelta(days=(slot.day - start.weekday()) % 7)


def _vtimezone(tz):
	"""A VTIMEZONE for the site's time zone at its current offset (UniConnect's
	universities are in Nigeria, which has no daylight saving)."""
	off = timezone.localtime().utcoffset() or timedelta(0)
	mins = int(off.total_seconds() // 60)
	sign = '+' if mins >= 0 else '-'
	text = f'{sign}{abs(mins) // 60:02d}{abs(mins) % 60:02d}'
	return ['BEGIN:VTIMEZONE', f'TZID:{tz}', 'BEGIN:STANDARD', 'DTSTART:19700101T000000',
		f'TZOFFSETFROM:{text}', f'TZOFFSETTO:{text}', f'TZNAME:{timezone.localtime().tzname() or tz}',
		'END:STANDARD', 'END:VTIMEZONE']


def _event(uid, stamp, tz, day, start, end, summary, venue, description, url, alarm, extra=()):
	lines = ['BEGIN:VEVENT', f'UID:{uid}', f'DTSTAMP:{stamp}', *extra,
		f'DTSTART;TZID={tz}:{_local(day, start)}', f'DTEND;TZID={tz}:{_local(day, end)}',
		f'SUMMARY:{_esc(summary)}']
	if venue:
		lines.append(f'LOCATION:{_esc(venue)}')
	if description:
		lines.append(f'DESCRIPTION:{_esc(description)}')
	if url:
		lines.append(f'URL:{url}')
	if alarm:
		lines += ['BEGIN:VALARM', 'ACTION:DISPLAY', f'DESCRIPTION:{_esc(summary)}',
			f'TRIGGER:-PT{LEAD_MINUTES}M', 'END:VALARM']
	return lines + ['END:VEVENT']


def build_ics(user, base_url=''):
	"""The whole calendar for `user` as text."""
	tz = settings.TIME_ZONE
	stamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
	host = (base_url.split('://')[-1].split('/')[0] or 'uniconnect').split(':')[0]
	alarm = not is_muted(user, 'class_reminder')
	page = base_url.rstrip('/') + reverse('timetable') if base_url else ''
	slots = list(ClassSlot.objects.filter(user=user).select_related('course'))
	changes = {}
	for c in ClassChange.objects.filter(slot__in=slots).order_by('date'):
		changes.setdefault(c.slot_id, []).append(c)
	lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//UniConnect//Timetable//EN', 'CALSCALE:GREGORIAN',
		'METHOD:PUBLISH', 'X-WR-CALNAME:UniConnect timetable', f'X-WR-TIMEZONE:{tz}',
		'REFRESH-INTERVAL;VALUE=DURATION:PT6H', 'X-PUBLISHED-TTL:PT6H', *_vtimezone(tz)]
	for s in slots:
		kind = '' if s.kind == ClassSlot.OTHER else f' {KIND[s.kind]}'
		summary = f'{s.short}{kind}'
		desc = s.name + (' (official timetable)' if s.official_id else '')
		uid = f'class-{s.pk}@{host}'
		first = _first_date(s)
		mine = changes.get(s.pk, [])
		# Weeks that don't happen at the usual time: cancelled ones and moved ones.
		exdates = [c for c in mine if c.status == ClassChange.CANCELLED and c.date >= first]
		extra = ['RRULE:FREQ=WEEKLY']
		if exdates:
			extra.append(f'EXDATE;TZID={tz}:' + ','.join(_local(c.date, s.start) for c in exdates))
		lines += _event(uid, stamp, tz, first, s.start, s.end, summary, s.venue, desc, page, alarm, extra)
		for c in mine:
			if c.status != ClassChange.MOVED or c.date < first:
				continue
			note = f'Moved from {c.date:%a %d %b} {s.start:%H:%M}' + (f'. {c.note}' if c.note else '')
			lines += _event(uid, stamp, tz, c.new_date or c.date, c.new_start or s.start, c.new_end or s.end,
				f'{summary} (moved)', c.new_venue or s.venue, note, page, alarm,
				[f'RECURRENCE-ID;TZID={tz}:{_local(c.date, s.start)}'])
	lines.append('END:VCALENDAR')
	return '\r\n'.join(_fold(l) for l in lines) + '\r\n'


def _response(user, request, download):
	resp = HttpResponse(build_ics(user, request.build_absolute_uri('/')), content_type='text/calendar; charset=utf-8')
	if download:
		resp['Content-Disposition'] = 'attachment; filename="uniconnect-timetable.ics"'
	resp['Cache-Control'] = 'private, max-age=0'
	return resp


@login_required
def download(request):
	return _response(request.user, request, download=True)


def subscribed(request, token):
	"""No sign-in: calendar apps can't sign in, the long random token is the key."""
	feed = TimetableFeed.objects.select_related('user').filter(token=token).first()
	if feed is None or not feed.user.is_active:
		raise Http404
	return _response(feed.user, request, download=False)


@login_required
@require_POST
def reset(request):
	TimetableFeed.objects.filter(user=request.user).delete()
	feed_for(request.user)
	messages.success(request, 'New calendar link made. The old link has stopped working, so subscribe again with the new one.')
	return redirect(reverse('timetable') + '#tt-calendar')
