"""
Campus Pulse: short-lived student updates at the top of Home (it replaced
Quick access). Templates: feed/_pulse_bar.html (the bar, composer and viewer
shell), feed/_pulse_viewer.html (one update), feed/pulse_detail.html (an
update on its own page, e.g. from a notification). Script: feed/_pulse_js.html.
Styles: restyle.css ("Campus Pulse").

Types (PulseStatus.kind) and what the viewer offers on each:

    Study          Reply · Study together · Message
    Campus Life    Reply · Message
    Event          I'm interested · View event · Message
    Question       Yes / No / Not sure · Reply · (author) Mark answered
    Available      Join (study session, coding session, ...) · Message · (author) Turn off
    Find People    I'm in · Reply · Message
    Opportunity    I'm interested · Open link · Message

"Study together", "Join" and "I'm in" open a direct chat with the author and
send a short first message saying which update it's about; "Message" just
opens the chat (chat.services).

Who sees what (visible_to) is decided here, on the server:
    university   students at the author's university
    communities  active members of the update's community
    everyone     every student
plus the author, minus anyone blocked either way and anyone you muted.

The bar's order (bar_for): your own updates, then people you follow, then
your university, then your communities, then everyone else; updates you
haven't opened come before ones you have, newest first within each.
"""
from datetime import datetime, time, timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import imagekit
from .models import Event, Follow, Notification, PulseInterest, PulseReply, PulseStatus, PulseView
from .moderation import blocked_ids, is_blocked
from .notifications import notify, unnotify

P = PulseStatus

# Per type: label on the chips/circles, icon, colour name (restyle.css .pk-<colour>).
KINDS = [
	(P.STUDY, 'Study', 'bi-book', 'blue'),
	(P.CAMPUS, 'Campus Life', 'bi-tree', 'green'),
	(P.EVENT, 'Events', 'bi-calendar-event', 'purple'),
	(P.QUESTION, 'Questions', 'bi-question-circle', 'orange'),
	(P.AVAILABLE, 'Available', 'bi-person-check', 'teal'),
	(P.PEOPLE, 'Find People', 'bi-people', 'pink'),
	(P.OPPORTUNITY, 'Opportunities', 'bi-briefcase', 'amber'),
]
KIND_INFO = {k: {'key': k, 'label': label, 'icon': icon, 'colour': colour} for k, label, icon, colour in KINDS}
# What the circle under the avatar says (singular).
CIRCLE_LABEL = {P.STUDY: 'Study', P.CAMPUS: 'Campus Life', P.EVENT: 'Event', P.QUESTION: 'Question',
	P.AVAILABLE: 'Available', P.PEOPLE: 'Find People', P.OPPORTUNITY: 'Opportunity'}
# The composer's hint for each type.
PLACEHOLDERS = {
	P.STUDY: 'What are you studying? e.g. "Trying to understand BIBD. Anyone free to explain the examples?"',
	P.CAMPUS: "What's happening on campus?",
	P.EVENT: 'Anything people should know about the event (optional)',
	P.QUESTION: 'Ask a quick question, e.g. "Has COS 401 moved to another venue?"',
	P.AVAILABLE: 'Anything to add? (optional) e.g. "Library, 2nd floor"',
	P.PEOPLE: 'Who are you looking for? e.g. "Two people to build a Django project with."',
	P.OPPORTUNITY: 'Share the opportunity: internship, competition, scholarship...',
}
# The button that opens a chat with a first message, per type.
CONNECT_LABEL = {P.STUDY: ('Study together', 'bi-people'), P.PEOPLE: ("I'm in", 'bi-hand-thumbs-up')}
JOIN_LABEL = {'study': 'Join study session', 'coding': 'Join coding session', 'project': "Let's collaborate",
	'sports': "I'll play", 'other': 'Join'}
AVAILABLE_HOURS = [(1, '1 hour'), (3, '3 hours'), (6, '6 hours'), (12, '12 hours'), (24, '24 hours')]

LIFETIME = timedelta(hours=24)
QUESTION_LIFETIME = timedelta(hours=48)
ANSWERED_LINGER = timedelta(hours=3)      # an answered question stays a little while, marked Answered
EVENT_AFTER = timedelta(hours=2)          # an event update goes 2 hours after the event starts
EVENT_MAX_AHEAD = timedelta(days=30)
BAR_LIMIT = 80


# ---------------------------------------------------------------------
# Who sees what
# ---------------------------------------------------------------------

def _profile(user):
	return getattr(user, 'student_profile', None)


def my_community_ids(user):
	from communities.models import CommunityMember
	return set(CommunityMember.objects.filter(user=user, status=CommunityMember.ACTIVE).values_list('community_id', flat=True))


def visible_to(user, qs=None):
	"""Live updates `user` is allowed to see."""
	qs = (P.objects.live() if qs is None else qs)
	prof = _profile(user)
	allowed = Q(user=user) | Q(audience=P.EVERYONE) | Q(audience=P.COMMUNITIES, community_id__in=my_community_ids(user))
	if prof:
		allowed |= Q(audience=P.UNIVERSITY, university_id=prof.university_id)
	qs = qs.filter(allowed)
	hidden = blocked_ids(user)
	if hidden:
		qs = qs.exclude(user_id__in=hidden)
	return qs.exclude(user__muted_by__muter=user)


def can_see(user, status):
	return status.is_active and status.expires_at > timezone.now() and visible_to(user, P.objects.filter(pk=status.pk)).exists()


def get_visible(user, pk):
	status = get_object_or_404(P.objects.select_related('user', 'user__student_profile', 'university', 'community', 'course', 'event'), pk=pk)
	if not can_see(user, status):
		raise Http404
	return status


# ---------------------------------------------------------------------
# Lifetimes and wording
# ---------------------------------------------------------------------

def expiry_for(kind, now, event_at=None, hours=None):
	if kind == P.QUESTION:
		return now + QUESTION_LIFETIME
	if kind == P.EVENT and event_at:
		return event_at + EVENT_AFTER
	if kind == P.AVAILABLE:
		return now + timedelta(hours=hours or 3)
	return now + LIFETIME


def ago(dt, now=None):
	"""'Now', '5m', '2h', '1d'."""
	secs = int(((now or timezone.now()) - dt).total_seconds())
	if secs < 60:
		return 'Now'
	if secs < 3600:
		return f'{secs // 60}m'
	if secs < 86400:
		return f'{secs // 3600}h'
	return f'{secs // 86400}d'


def left(dt, now=None):
	"""'45m left', '18h left', '3d left'."""
	secs = max(0, int((dt - (now or timezone.now())).total_seconds()))
	if secs < 3600:
		return f'{max(1, secs // 60)}m left'
	if secs < 86400:
		return f'{secs // 3600}h left'
	return f'{secs // 86400}d left'


def when_text(dt):
	"""'Today, 4:00 PM' / 'Tomorrow, 9:30 AM' / 'Fri 31 Oct, 2:00 PM'."""
	local = timezone.localtime(dt)
	today = timezone.localdate()
	clock = local.strftime('%I:%M %p').lstrip('0')
	if local.date() == today:
		day = 'Today'
	elif local.date() == today + timedelta(days=1):
		day = 'Tomorrow'
	else:
		day = f'{local:%a} {local.day} {local:%b}'
	return f'{day}, {clock}'


def display_name(user):
	return user.get_full_name() or user.username


def photo_of(user):
	prof = _profile(user)
	return prof.profile_photo.url if prof and prof.profile_photo else ''


def initials(user):
	first = user.first_name or user.username
	return (first[:1] + (user.last_name[:1] if user.last_name else '')).upper()


# ---------------------------------------------------------------------
# The bar on Home
# ---------------------------------------------------------------------

def bar_for(user):
	"""Everything the bar needs: the circles (in order) with the flags the chips
	and the My University / My Communities / Everyone switch filter on."""
	prof = _profile(user)
	now = timezone.now()
	statuses = list(visible_to(user).select_related('user', 'user__student_profile', 'course').order_by('-created_at')[:BAR_LIMIT])
	following = set(Follow.objects.filter(follower=user, status=Follow.STATUS_ACCEPTED).values_list('following_id', flat=True))
	comms = my_community_ids(user)
	seen = set(PulseView.objects.filter(viewer=user, status__in=statuses).values_list('status_id', flat=True))
	uni_id = prof.university_id if prof else None

	circles = []
	for s in statuses:
		mine = s.user_id == user.pk
		same_uni = uni_id is not None and s.university_id == uni_id
		in_comm = s.audience == P.COMMUNITIES and s.community_id in comms
		if mine:
			rank = 0
		elif s.user_id in following:
			rank = 1
		elif same_uni:
			rank = 2
		elif in_comm:
			rank = 3
		else:
			rank = 4
		scopes = ['all']
		if same_uni or mine:
			scopes.append('uni')
		if in_comm or (mine and s.audience == P.COMMUNITIES):
			scopes.append('comm')
		info = KIND_INFO[s.kind]
		circles.append({
			'status': s, 'mine': mine, 'seen': s.pk in seen and not mine,
			'rank': rank, 'scopes': ' '.join(scopes), 'kind': info,
			'label': CIRCLE_LABEL[s.kind], 'sub': ago(s.created_at, now),
			'photo': photo_of(s.user), 'initials': initials(s.user), 'name': display_name(s.user),
			'answered': s.kind == P.QUESTION and s.is_answered,
		})
	circles.sort(key=lambda c: (c['rank'], c['seen'], -c['status'].created_at.timestamp()))
	return {
		'circles': circles,
		'kinds': KINDS,
		'has_communities': bool(comms),
		'composer': composer_context(user),
		'photo': photo_of(user), 'initials': initials(user),
	}


def composer_context(user):
	from courses.today import my_courses
	from communities.models import Community
	prof = _profile(user)
	events = Event.objects.none()
	if prof:
		events = Event.objects.filter(date__gte=timezone.localdate()).filter(
			Q(organizer__student_profile__university=prof.university) | Q(community__university=prof.university)
		).distinct().order_by('date', 'time')[:30]
	return {
		'kinds': KINDS,
		'placeholders': PLACEHOLDERS,
		'courses': my_courses(user),
		'communities': list(Community.objects.filter(pk__in=my_community_ids(user)).order_by('name')),
		'events': list(events),
		'activities': P.ACTIVITY_CHOICES,
		'hours': AVAILABLE_HOURS,
		'university': prof.university if prof else None,
	}


# ---------------------------------------------------------------------
# Posting an update
# ---------------------------------------------------------------------

class PulseForm(forms.Form):
	kind = forms.ChoiceField(choices=P.KIND_CHOICES)
	text = forms.CharField(max_length=280, required=False)
	media = forms.FileField(required=False)
	audience = forms.ChoiceField(choices=P.AUDIENCE_CHOICES, initial=P.UNIVERSITY)
	community = forms.IntegerField(required=False)
	course = forms.IntegerField(required=False)
	topic = forms.CharField(max_length=120, required=False)
	event = forms.IntegerField(required=False)
	event_title = forms.CharField(max_length=120, required=False)
	event_place = forms.CharField(max_length=120, required=False)
	event_date = forms.DateField(required=False)
	event_time = forms.TimeField(required=False)
	link = forms.URLField(max_length=300, required=False, assume_scheme='https')
	activity = forms.ChoiceField(choices=[('', '')] + P.ACTIVITY_CHOICES, required=False)
	hours = forms.TypedChoiceField(choices=[(str(h), label) for h, label in AVAILABLE_HOURS], coerce=int, required=False)

	def __init__(self, *args, user=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.user = user

	def clean(self):
		data = super().clean()
		kind = data.get('kind')
		text = (data.get('text') or '').strip()
		data['text'] = text
		now = timezone.now()

		if kind in (P.STUDY, P.CAMPUS, P.QUESTION, P.PEOPLE, P.OPPORTUNITY) and not text and not data.get('media'):
			raise forms.ValidationError('Write something first.')
		if kind == P.QUESTION and not text:
			raise forms.ValidationError('Type your question.')

		from courses.models import Course
		course = None
		if data.get('course'):
			course = Course.objects.filter(pk=data['course'], enrollments__user=self.user).first()
			if course is None:
				raise forms.ValidationError('Pick one of your courses.')
		data['course_obj'] = course

		data['community_obj'] = None
		if data.get('audience') == P.COMMUNITIES:
			from communities.models import Community
			if not data.get('community') or data['community'] not in my_community_ids(self.user):
				raise forms.ValidationError('Pick a community you belong to.')
			data['community_obj'] = Community.objects.get(pk=data['community'])

		data['event_obj'] = None
		data['event_at'] = None
		if kind == P.EVENT:
			if data.get('event'):
				ev = composer_context(self.user)['events']
				ev = next((e for e in ev if e.pk == data['event']), None)
				if ev is None:
					raise forms.ValidationError('That event is no longer coming up.')
				data['event_obj'] = ev
				data['event_title'] = data.get('event_title') or ev.title
				data['event_place'] = data.get('event_place') or ev.location
				data['event_date'] = data.get('event_date') or ev.date
				data['event_time'] = data.get('event_time') or ev.time
			if not data.get('event_title'):
				raise forms.ValidationError('Give the event a name.')
			if not data.get('event_date'):
				raise forms.ValidationError('When is the event?')
			at = datetime.combine(data['event_date'], data.get('event_time') or time(23, 59))
			at = timezone.make_aware(at) if timezone.is_naive(at) else at
			if at + EVENT_AFTER <= now:
				raise forms.ValidationError('That event is already over.')
			if at > now + EVENT_MAX_AHEAD:
				raise forms.ValidationError('Events can be shared up to 30 days ahead.')
			data['event_at'] = at
		if kind == P.AVAILABLE and not data.get('activity'):
			raise forms.ValidationError('What are you available for?')

		media = data.get('media')
		data['image'] = data['video'] = None
		if media:
			name = (media.name or '').lower()
			ext = name.rsplit('.', 1)[-1] if '.' in name else ''
			if ext in P.ALLOWED_IMAGE_EXTENSIONS:
				if media.size > 8 * 1024 * 1024:
					raise forms.ValidationError('Photos must be smaller than 8MB.')
				data['image'] = media
			elif ext in P.ALLOWED_VIDEO_EXTENSIONS:
				if media.size > 50 * 1024 * 1024:
					raise forms.ValidationError('Videos must be smaller than 50MB.')
				data['video'] = media
			else:
				raise forms.ValidationError('Add a photo (JPG, PNG, GIF, WebP) or a video (MP4, WebM, MOV).')
		return data


def _back(request, fallback='home'):
	nxt = request.POST.get('next') or request.GET.get('next')
	if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
		return redirect(nxt)
	return redirect(fallback)


@login_required
@require_POST
def pulse_create(request):
	prof = _profile(request.user)
	if prof is None:
		raise PermissionDenied
	form = PulseForm(request.POST, request.FILES, user=request.user)
	if not form.is_valid():
		errors = form.non_field_errors() or [f'{k}: {v[0]}' for k, v in form.errors.items()]
		messages.error(request, errors[0] if errors else 'Could not share that update.')
		return _back(request)
	d = form.cleaned_data
	now = timezone.now()
	status = P(
		user=request.user, kind=d['kind'], text=d['text'], university=prof.university,
		audience=d['audience'], community=d['community_obj'],
		course=d['course_obj'] if d['kind'] in (P.STUDY, P.AVAILABLE, P.QUESTION) else None,
		topic=d.get('topic') or '' if d['kind'] in (P.STUDY, P.AVAILABLE) else '',
		event=d['event_obj'], event_title=d.get('event_title') or '' if d['kind'] == P.EVENT else '',
		event_place=d.get('event_place') or '' if d['kind'] == P.EVENT else '', event_at=d['event_at'],
		link=d.get('link') or '' if d['kind'] in (P.EVENT, P.OPPORTUNITY, P.PEOPLE) else '',
		activity=d.get('activity') or '' if d['kind'] == P.AVAILABLE else '',
		created_at=now,
		expires_at=expiry_for(d['kind'], now, d['event_at'], d.get('hours')),
	)
	if d['image']:
		status.image = d['image']
		if imagekit.enabled():
			ik = imagekit.upload_images([d['image']], imagekit.STORY_FOLDER)[0]
			if ik:
				status.ik_image_file_id, status.ik_image_url = ik['fileId'], ik['url']
				status.image = None
	if d['video']:
		status.video = d['video']
	status.full_clean()
	status.save()
	messages.success(request, 'Your update is on Campus Pulse.')
	return _back(request)


# ---------------------------------------------------------------------
# Viewing one update
# ---------------------------------------------------------------------

def viewer_context(user, status):
	now = timezone.now()
	mine = status.user_id == user.pk
	info = KIND_INFO[status.kind]
	replies = list(status.replies.filter(answer='').select_related('user', 'user__student_profile').order_by('created_at')[:100])
	hidden = blocked_ids(user)
	replies = [r for r in replies if r.user_id not in hidden]
	for r in replies:
		r.ago = ago(r.created_at, now)
	answers = dict(status.replies.exclude(answer='').values('answer').annotate(n=Count('id')).values_list('answer', 'n'))
	my_answer = status.replies.filter(user=user).exclude(answer='').values_list('answer', flat=True).first() or ''
	prof = _profile(status.user)
	viewer_prof = _profile(user)
	other_uni = bool(prof and viewer_prof and prof.university_id != viewer_prof.university_id)
	connect = None
	if status.kind in CONNECT_LABEL:
		connect = CONNECT_LABEL[status.kind]
	elif status.kind == P.AVAILABLE:
		connect = (JOIN_LABEL.get(status.activity, 'Join'), 'bi-box-arrow-in-right')
	return {
		's': status, 'mine': mine, 'kind': info,
		'name': display_name(status.user), 'photo': photo_of(status.user), 'initials': initials(status.user),
		'who': ' · '.join(x for x in [
			prof.department.name if prof else '', prof.level.name if prof else '',
			prof.university.short_name if prof and other_uni else '',
		] if x),
		'other_uni': other_uni,
		'ago': ago(status.created_at, now), 'left': left(status.expires_at, now),
		'audience_text': ('Everyone' if status.audience == P.EVERYONE else
			(status.community.name if status.audience == P.COMMUNITIES and status.community else
			(status.university.short_name if status.university else 'My University'))),
		'audience_icon': {'everyone': 'bi-globe2', 'communities': 'bi-people', 'university': 'bi-building'}[status.audience],
		'event_when': when_text(status.event_at) if status.event_at else '',
		'event_past': bool(status.event_at and status.event_at <= now),
		'activity_text': status.get_activity_display() if status.activity else '',
		'until': timezone.localtime(status.expires_at).strftime('%I:%M %p').lstrip('0'),
		'replies': replies,
		'answers': [(k, label, answers.get(k, 0)) for k, label in PulseReply.ANSWER_CHOICES],
		'answer_total': sum(answers.values()),
		'my_answer': my_answer,
		'interested': status.interests.filter(user=user).exists(),
		'interest_count': status.interests.count(),
		'views_count': status.views.count() if mine else None,
		'connect': connect,
		'can_message': not mine,
		'can_reply': not mine and status.kind in (P.STUDY, P.CAMPUS, P.QUESTION, P.PEOPLE),
		'has_interest': status.kind in (P.EVENT, P.OPPORTUNITY),
	}


def render_viewer(request, status):
	return render_to_string('feed/_pulse_viewer.html', viewer_context(request.user, status), request=request)


def _is_ajax(request):
	return request.headers.get('x-requested-with') == 'XMLHttpRequest'


@login_required
def pulse_detail(request, pk):
	status = get_visible(request.user, pk)
	if _is_ajax(request):
		return JsonResponse({'html': render_viewer(request, status)})
	if status.user_id != request.user.pk:
		PulseView.objects.get_or_create(status=status, viewer=request.user)
	ctx = viewer_context(request.user, status)
	ctx['page'] = True
	return render(request, 'feed/pulse_detail.html', ctx)


@login_required
@require_POST
def pulse_seen(request, pk):
	status = get_visible(request.user, pk)
	if status.user_id != request.user.pk:
		PulseView.objects.get_or_create(status=status, viewer=request.user)
	return JsonResponse({'ok': True})


def _done(request, status):
	if _is_ajax(request):
		return JsonResponse({'html': render_viewer(request, status)})
	return redirect('pulse_detail', pk=status.pk)


def reply_message(status, text):
	"""A reply to an update, as it arrives in the author's Messages: which update it answers, then the reply."""
	about = status.text or status.event_title or status.topic or status.get_kind_display()
	quote = about if len(about) <= 80 else about[:79] + '\u2026'
	return f'Replied to your Campus Pulse update: \u201c{quote}\u201d\n{text}'


@login_required
@require_POST
def pulse_reply(request, pk):
	"""A reply goes to the author privately, in Messages (like a reply to a story),
	not onto the update for everyone to read."""
	status = get_visible(request.user, pk)
	text = (request.POST.get('text') or '').strip()[:500]
	if not text:
		if _is_ajax(request):
			return JsonResponse({'error': 'Write a reply first.'}, status=400)
		return redirect('pulse_detail', pk=pk)
	if status.user_id == request.user.pk:
		return JsonResponse({'error': "That's your own update."}, status=400)
	if is_blocked(request.user, status.user):
		return JsonResponse({'error': "You can't message this account."}, status=403)
	from chat import services as S
	from chat.models import Message
	conv, created = S.direct_conversation(request.user, status.user)
	if created:
		S.announce_new_conversation(conv)
	msg = S.create_message(conv, request.user, Message.TEXT, reply_message(status, text))
	try:
		S.broadcast_message(msg)
	except Exception:
		pass
	url = reverse('chat_conversation', args=[conv.pk])
	if _is_ajax(request):
		return JsonResponse({'sent': True, 'url': url, 'name': status.user.first_name or display_name(status.user)})
	return redirect(url)


@login_required
@require_POST
def pulse_answer(request, pk):
	"""Question quick answers: Yes / No / Not sure. Tapping your answer again removes it."""
	status = get_visible(request.user, pk)
	answer = request.POST.get('answer')
	if status.kind != P.QUESTION or answer not in dict(PulseReply.ANSWER_CHOICES):
		return JsonResponse({'error': 'Not a question.'}, status=400)
	with transaction.atomic():
		mine = PulseReply.objects.select_for_update().filter(status=status, user=request.user).exclude(answer='').first()
		if mine and mine.answer == answer:
			mine.delete()
		elif mine:
			mine.answer = answer
			mine.save(update_fields=['answer'])
		else:
			try:
				with transaction.atomic():
					PulseReply.objects.create(status=status, user=request.user, answer=answer)
			except IntegrityError:
				pass
			notify(status.user, request.user, Notification.PULSE_REPLY, pulse_status=status, replace=True)
	return _done(request, status)


@login_required
@require_POST
def pulse_answered(request, pk):
	"""The author marks their question answered (or not): an answered question
	stays a few more hours, labelled Answered, then goes."""
	status = get_visible(request.user, pk)
	if status.user_id != request.user.pk or status.kind != P.QUESTION:
		raise PermissionDenied
	now = timezone.now()
	status.is_answered = not status.is_answered
	if status.is_answered:
		status.expires_at = min(status.expires_at, now + ANSWERED_LINGER)
	else:
		status.expires_at = max(status.expires_at, status.created_at + QUESTION_LIFETIME)
	status.save(update_fields=['is_answered', 'expires_at'])
	return _done(request, status)


@login_required
@require_POST
def pulse_interest(request, pk):
	status = get_visible(request.user, pk)
	if status.kind not in (P.EVENT, P.OPPORTUNITY) or status.user_id == request.user.pk:
		return JsonResponse({'error': 'Not available here.'}, status=400)
	row = PulseInterest.objects.filter(status=status, user=request.user).first()
	if row:
		row.delete()
		unnotify(status.user, request.user, Notification.PULSE_INTEREST, pulse_status=status)
	else:
		try:
			with transaction.atomic():
				PulseInterest.objects.create(status=status, user=request.user)
		except IntegrityError:
			pass
		notify(status.user, request.user, Notification.PULSE_INTEREST, pulse_status=status, replace=True)
	return _done(request, status)


def intro_message(status, action):
	"""The first chat message for Study together / Join / I'm in."""
	course = f' ({status.course.code}{" · " + status.topic if status.topic else ""})' if status.course else (f' ({status.topic})' if status.topic else '')
	quote = status.text if len(status.text) <= 80 else status.text[:79] + '…'
	if status.kind == P.STUDY:
		return f'Hi! I saw your Study update on Campus Pulse{course}. Want to study together?'
	if status.kind == P.AVAILABLE:
		what = status.get_activity_display().lower() if status.activity else 'it'
		return f"Hi! I saw on Campus Pulse that you're available for {what}{course}. Can I join?"
	if status.kind == P.PEOPLE:
		return f'Hi! I saw your Campus Pulse update: “{quote}” — I\'m in!'
	return f'Hi! About your Campus Pulse update: “{quote}”'


@login_required
@require_POST
def pulse_connect(request, pk):
	"""Open a chat with the author. action=message just opens it; together /
	join / imin also send a short first message about the update."""
	status = get_visible(request.user, pk)
	if status.user_id == request.user.pk:
		return JsonResponse({'error': "That's your own update."}, status=400)
	if is_blocked(request.user, status.user):
		return JsonResponse({'error': "You can't message this account."}, status=403)
	from chat import services as S
	from chat.models import Message
	conv, created = S.direct_conversation(request.user, status.user)
	if created:
		S.announce_new_conversation(conv)
	if request.POST.get('action') in ('together', 'join', 'imin') and (status.kind in CONNECT_LABEL or status.kind == P.AVAILABLE):
		msg = S.create_message(conv, request.user, Message.TEXT, intro_message(status, request.POST['action']))
		try:
			S.broadcast_message(msg)
		except Exception:
			pass
	url = reverse('chat_conversation', args=[conv.pk])
	if _is_ajax(request):
		return JsonResponse({'url': url})
	return redirect(url)


@login_required
@require_POST
def pulse_remove(request, pk):
	"""The author deletes an update (for Available: turns it off)."""
	status = get_object_or_404(P, pk=pk, user=request.user)
	status.is_active = False
	status.save(update_fields=['is_active'])
	if _is_ajax(request):
		return JsonResponse({'removed': True})
	messages.success(request, 'Update removed from Campus Pulse.')
	return redirect('home')
