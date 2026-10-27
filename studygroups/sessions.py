"""Study sessions / meetups in a group.

Any member can schedule one from the group's Sessions tab: a title, a date
and time, how long, and where — a place, an online link, or both. Then:
  * everyone in the group gets a notification, and the group chat says so;
  * members answer Going / Maybe / Can't go (the one who made it is Going);
  * 30 minutes before it starts, people who said Going or Maybe get a
    "Study session starting soon" reminder — made while UniConnect is
    open, the same way as class reminders (courses/reminders.py), so no
    background job is needed;
  * "Add to calendar" downloads it as an .ics file for a phone's calendar.
Once it has started: who came is recorded — people tick "I was there"
themselves, and the organiser or an admin can mark the whole list — and
anyone can share notes from it (words, photos of the board, slides). Those
files also appear in the group's Files tab. (attendance / notes below)

The person who made it, or a group admin, can change it (update below) or
cancel it. When the time, length or place changes, the people who said
Going or Maybe get a notification saying what changed, the chat says so,
and the reminder is reset to the new time.
"""
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from .models import (GroupSession as S, GroupSessionRSVP as R, SessionAttendance as A, SessionNote, StudyGroupMember as M)

LEAD_MINUTES = 30


def when_text(session):
	"""'Thu 23 Oct, 4:00 PM' in Lagos time."""
	t = timezone.localtime(session.starts_at)
	return t.strftime('%a %d %b, %I:%M %p').replace(' 0', ' ')


def clean(data, keep=None):
	"""The form's fields tidied, or ValidationError. `keep`: a session's
	current start, which may stay as it is even once it has passed."""
	title = ' '.join((data.get('title') or '').split())
	if not title:
		raise ValidationError('Give the session a title — e.g. "STA 341 past questions".')
	if len(title) > 100:
		raise ValidationError('The title can be up to 100 characters.')
	try:
		day = datetime.strptime(data.get('date') or '', '%Y-%m-%d').date()
		clock = datetime.strptime(data.get('time') or '', '%H:%M').time()
	except ValueError:
		raise ValidationError('Choose the date and time.')
	starts = timezone.make_aware(datetime.combine(day, clock))
	now = timezone.now()
	if starts <= now and starts != keep:
		raise ValidationError('Choose a time in the future.')
	if starts > now + timedelta(days=365):
		raise ValidationError('Sessions can be scheduled up to a year ahead.')
	try:
		duration = int(data.get('duration') or 60)
	except ValueError:
		duration = 60
	if duration not in dict(S.DURATIONS):
		duration = 60
	place = ' '.join((data.get('place') or '').split())[:120]
	link = (data.get('link') or '').strip()
	if link and not link.lower().startswith(('http://', 'https://')):
		link = 'https://' + link
	if link:
		from django.core.validators import URLValidator
		try:
			URLValidator()(link)
		except ValidationError:
			raise ValidationError("That meeting link doesn't look right.")
	notes = (data.get('notes') or '').strip()[:1000]
	return {'title': title, 'starts_at': starts, 'duration': duration, 'place': place, 'link': link[:200], 'notes': notes}


def _chat_note(group, text):
	if group.conversation_id:
		from . import chat
		try:
			chat._say(group.conversation, text)
		except Exception:
			pass


def create(group, user, data):
	fields = clean(data)
	session = S.objects.create(group=group, created_by=user, **fields)
	R.objects.create(session=session, user=user, status=R.GOING)
	from feed.models import Notification as N
	from feed.notifications import notify
	for m in group.members.filter(status=M.ACTIVE).exclude(user=user).select_related('user'):
		notify(m.user, user, N.GROUP_SESSION, study_group=group, group_session=session)
	where = f' · {session.place}' if session.place else (' · online' if session.link else '')
	_chat_note(group, f'📅 New study session: {session.title} — {when_text(session)}{where}. Answer in the Sessions tab.')
	return session


def update(session, user, data):
	"""Change a session. Returns the list of what changed (words), e.g.
	['time: Wed 4:00 PM → Thu 5:00 PM', 'place: Library → LT 2']."""
	if session.is_cancelled:
		raise ValidationError('This session was cancelled.')
	if session.ends_at <= timezone.now():
		raise ValidationError('This session is over.')
	fields = clean(data, keep=timezone.localtime(session.starts_at).replace(second=0, microsecond=0))
	changes = []
	if fields['starts_at'] != session.starts_at:
		changes.append(f'time: {when_text(session)} → {when_text(S(starts_at=fields["starts_at"]))}')
	if fields['duration'] != session.duration:
		changes.append(f'length: {session.get_duration_display()} → {dict(S.DURATIONS)[fields["duration"]]}')
	if fields['place'] != session.place:
		changes.append(f'place: {session.place or "none"} → {fields["place"] or "none"}')
	if fields['link'] != session.link:
		changes.append('online link changed' if fields['link'] else 'online link removed')
	quiet = fields['title'] != session.title or fields['notes'] != session.notes
	if not changes and not quiet:
		return []
	time_moved = fields['starts_at'] != session.starts_at
	for k, v in fields.items():
		setattr(session, k, v)
	session.save()
	from feed.models import Notification as N
	if time_moved:
		# Remind again at the new time.
		N.objects.filter(group_session=session, type=N.SESSION_REMINDER).delete()
	if changes:
		from feed.notifications import notify
		coming = session.rsvps.filter(status__in=[R.GOING, R.MAYBE]).exclude(user=user).select_related('user')
		for a in coming:
			notify(a.user, user, N.SESSION_CHANGED, study_group=session.group, group_session=session, replace=True)
		_chat_note(session.group, f'✏️ Study session changed: {session.title} — ' + '; '.join(changes))
	return changes or ['details']


def rsvp(session, user, status):
	if session.is_cancelled:
		raise ValidationError('This session was cancelled.')
	if session.ends_at <= timezone.now():
		raise ValidationError('This session is over.')
	if status not in dict(R.CHOICES):
		raise ValidationError('Choose Going, Maybe or Can’t go.')
	R.objects.update_or_create(session=session, user=user, defaults={'status': status})


def can_cancel(session, me):
	return bool(me) and (session.created_by_id == me.user_id or me.is_admin)


def cancel(session, user):
	if session.is_cancelled:
		return
	session.is_cancelled = True
	session.save(update_fields=['is_cancelled'])
	from feed.models import Notification as N
	# Nobody should be reminded about it any more.
	N.objects.filter(group_session=session, type=N.SESSION_REMINDER, is_read=False).delete()
	_chat_note(session.group, f'❌ Study session cancelled: {session.title} ({when_text(session)})')


def for_group(group, user):
	"""(upcoming, past) sessions with counts and your answer on each."""
	now = timezone.now()
	sessions = list(group.sessions.select_related('created_by', 'created_by__student_profile').prefetch_related('rsvps__user__student_profile'))
	for s in sessions:
		answers = list(s.rsvps.all())
		s.going = [a.user for a in answers if a.status == R.GOING]
		s.maybe_count = sum(1 for a in answers if a.status == R.MAYBE)
		s.mine = next((a.status for a in answers if a.user_id == user.pk), '')
		s.is_now = s.starts_at <= now < s.ends_at
	upcoming = [s for s in sessions if s.ends_at > now]
	past = [s for s in sessions if s.ends_at <= now][::-1][:10]
	return upcoming, past


def prepare(sessions, user, me):
	for s in sessions:
		s.can_cancel = can_cancel(s, me)
		if has_started(s) and not s.is_cancelled:
			follow_up(s, user, me)


def my_sessions(user, start, end):
	"""Sessions starting between `start` and `end` that `user` said Going or
	Maybe to, in groups they're still in (for the Timetable and Home)."""
	qs = (S.objects.filter(is_cancelled=False, starts_at__gte=start, starts_at__lt=end,
		rsvps__user=user, rsvps__status__in=[R.GOING, R.MAYBE],
		group__members__user=user, group__members__status=M.ACTIVE)
		.select_related('group').distinct().order_by('starts_at'))
	answers = dict(R.objects.filter(user=user, session__in=qs).values_list('session_id', 'status'))
	out = []
	for s in qs:
		s.mine = answers.get(s.pk, '')
		s.local_start = timezone.localtime(s.starts_at)
		s.local_end = timezone.localtime(s.ends_at)
		s.url = reverse('group_detail', args=[s.group_id]) + f'?tab=sessions#s{s.pk}'
		out.append(s)
	return out


def next_session(group):
	return group.sessions.filter(is_cancelled=False, starts_at__gt=timezone.now()).order_by('starts_at').first()


# ---------------------------------------------------------------------
# Reminders, made while the app is open (like courses/reminders.py)
# ---------------------------------------------------------------------

def due_reminders(user, now=None):
	from feed.models import Notification as N
	from feed.notifications import is_muted
	if not getattr(user, 'is_authenticated', False) or getattr(user, '_session_reminders_checked', False):
		return []
	user._session_reminders_checked = True
	now = now or timezone.now()
	soon = list(S.objects.filter(is_cancelled=False, starts_at__gt=now, starts_at__lte=now + timedelta(minutes=LEAD_MINUTES),
		rsvps__user=user, rsvps__status__in=[R.GOING, R.MAYBE], group__members__user=user,
		group__members__status=M.ACTIVE).select_related('group').distinct())
	if not soon or is_muted(user, N.SESSION_REMINDER):
		return []
	done = set(N.objects.filter(recipient=user, type=N.SESSION_REMINDER, group_session__in=soon).values_list('group_session_id', flat=True))
	return [N.objects.create(recipient=user, actor=user, type=N.SESSION_REMINDER, group_session=s, study_group=s.group,
		group_key=f'session:{s.pk}') for s in soon if s.pk not in done]


def pop_up(n, now=None):
	s = n.group_session
	now = now or timezone.now()
	mins = max(1, round((s.starts_at - now).total_seconds() / 60))
	where = s.place or ('Online' if s.link else s.group.title)
	return {'title': f'Study session in {mins} minute{"" if mins == 1 else "s"}',
		'text': f'{s.title} · {timezone.localtime(s.starts_at).strftime("%I:%M %p").lstrip("0")} · {where}',
		'url': reverse('notification_open', args=[n.pk])}


# ---------------------------------------------------------------------
# "Add to calendar" (.ics)
# ---------------------------------------------------------------------

def _ics_text(text):
	return (text or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def ics(session, request):
	fmt = '%Y%m%dT%H%M%SZ'
	import datetime as _dt
	start = session.starts_at.astimezone(_dt.timezone.utc)
	end = session.ends_at.astimezone(_dt.timezone.utc)
	url = request.build_absolute_uri(reverse('group_detail', args=[session.group_id]) + '?tab=sessions')
	desc = '\n'.join(x for x in [session.notes, session.link, url] if x)
	lines = [
		'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//UniConnect//Study sessions//EN', 'BEGIN:VEVENT',
		f'UID:session-{session.pk}@uniconnect', f'DTSTAMP:{timezone.now().astimezone(_dt.timezone.utc).strftime(fmt)}',
		f'DTSTART:{start.strftime(fmt)}', f'DTEND:{end.strftime(fmt)}',
		f'SUMMARY:{_ics_text(session.title)} ({_ics_text(session.group.title)})',
		f'LOCATION:{_ics_text(session.place or session.link)}', f'DESCRIPTION:{_ics_text(desc)}',
		'BEGIN:VALARM', 'TRIGGER:-PT30M', 'ACTION:DISPLAY', f'DESCRIPTION:{_ics_text(session.title)}', 'END:VALARM',
		'END:VEVENT', 'END:VCALENDAR',
	]
	return '\r\n'.join(lines) + '\r\n'


# ---------------------------------------------------------------------
# After it starts: who came, and notes
# ---------------------------------------------------------------------

FOLLOW_UP_DAYS = 30          # attendance and notes can be added up to a month later
MAX_NOTE_FILES = 6


def has_started(session):
	return session.starts_at <= timezone.now()


def can_follow_up(session):
	return (not session.is_cancelled and has_started(session)
		and timezone.now() <= session.ends_at + timedelta(days=FOLLOW_UP_DAYS))


def set_attended(session, user, came, by=None):
	"""Tick or untick one person."""
	if not can_follow_up(session):
		raise ValidationError('Attendance can be marked once the session has started (and up to a month after).')
	if came:
		A.objects.get_or_create(session=session, user=user, defaults={'marked_by': by or user})
	else:
		A.objects.filter(session=session, user=user).delete()


def mark_list(session, by, user_ids):
	"""The organiser's checklist: exactly these members came."""
	if not can_follow_up(session):
		raise ValidationError('Attendance can be marked once the session has started (and up to a month after).')
	members = set(session.group.members.filter(status=M.ACTIVE).values_list('user_id', flat=True))
	wanted = {int(u) for u in user_ids if str(u).isdigit()} & members
	A.objects.filter(session=session).exclude(user_id__in=wanted).delete()
	have = set(A.objects.filter(session=session).values_list('user_id', flat=True))
	A.objects.bulk_create([A(session=session, user_id=u, marked_by=by) for u in wanted - have])
	return len(wanted)


def add_note(session, user, body, files):
	"""Share notes: some words and/or files. Returns (note, file errors)."""
	if not can_follow_up(session):
		raise ValidationError('Notes can be shared once the session has started.')
	body = (body or '').strip()[:3000]
	files = [f for f in files if f][:MAX_NOTE_FILES]
	if not body and not files:
		raise ValidationError('Write something or add a file.')
	from .forms import GroupFileForm
	note = SessionNote.objects.create(session=session, author=user, body=body)
	saved, errors = 0, []
	for f in files:
		form = GroupFileForm(files={'file': f})
		if form.is_valid():
			obj = form.save(commit=False)
			obj.group, obj.uploaded_by, obj.session_note = session.group, user, note
			obj.save()
			saved += 1
		else:
			errors.append(f'{f.name}: {form.errors["file"][0]}')
	if not body and not saved:
		note.delete()
		raise ValidationError(errors[0] if errors else 'Those files could not be added.')
	if session.group.conversation_id:
		from . import chat
		files_text = f' ({saved} file{"" if saved == 1 else "s"})' if saved else ''
		try:
			chat._say(session.group.conversation, f'📝 {chat.S.display_name(user)} shared notes{files_text} from the study session '
				f'"{session.title}". See them in the Sessions tab.')
		except Exception:
			pass                          # the notes are saved either way
	return note, errors


def follow_up(session, user, me):
	"""Fills in what the card shows after the start: who came, notes, and
	what `user` may do."""
	session.followed = True
	came = list(session.attendance.select_related('user', 'user__student_profile'))
	session.came = [a.user for a in came]
	session.i_came = any(a.user_id == user.pk for a in came)
	session.notes_list = list(session.notes_shared.select_related('author', 'author__student_profile').prefetch_related('files'))
	session.can_follow_up = can_follow_up(session)
	session.can_mark = session.can_follow_up and can_cancel(session, me)
	if session.can_mark:
		answers = {a.user_id: a.status for a in session.rsvps.all()}
		came_ids = {a.user_id for a in came}
		members = list(session.group.members.filter(status=M.ACTIVE).select_related('user'))
		order = {R.GOING: 0, R.MAYBE: 1}
		members.sort(key=lambda m: (order.get(answers.get(m.user_id), 2), (m.user.get_full_name() or m.user.username).lower()))
		session.checklist = [{'user': m.user, 'came': m.user_id in came_ids, 'said': dict(R.CHOICES).get(answers.get(m.user_id), '')}
			for m in members]
