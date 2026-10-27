"""
Pages for UniConnect Messages. Each tab (Chats, Updates, Communities,
Calls, You) is a normal page, so links and refresh always work;
static/js/chat/navigation.js then swaps between them without a full
reload. A conversation page shows the chat list beside it on wide
screens and on its own (with a back button) on phones.

Everything checks membership: you can only open, read or post in
conversations you belong to (404 otherwise).
"""
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from feed.models import Follow, Story, StoryView

from . import services as S
from .models import (
	Call, ChatSettings, Community, CommunityMember, Conversation, ConversationParticipant as Participant, Message,
)

User = get_user_model()
MAX_PINNED = 3


def _base_context(request, tab, **extra):
	user = request.user
	settings_obj = ChatSettings.for_user(user)
	parts = Participant.objects.filter(user=user)
	ctx = {
		'tab': tab, 'me': S.person(user), 'chat_settings': settings_obj,
		'unread_chats': S.unread_chats_count(user),
		'archived_count': parts.filter(is_archived=True).count(),
		'groups_count': parts.filter(is_archived=False, conversation__kind=Conversation.GROUP).count(),
	}
	ctx.update(extra)
	return ctx


def _conversation_for(request, conversation_id):
	conv = Conversation.objects.filter(pk=conversation_id, participants__user=request.user).select_related('community').first()
	if not conv:
		raise Http404('Conversation not found')
	return conv


# ---------------------------------------------------------------------
# Chats
# ---------------------------------------------------------------------

@login_required
def chats(request):
	rows = S.chat_rows(request.user)
	ctx = _base_context(request, 'chats', rows=rows, **_list_counts(rows))
	ctx['open_filter'] = 'requests' if request.GET.get('filter') == 'requests' else 'all'
	return render(request, 'chat/chats.html', ctx)


def _list_counts(rows):
	"""The Unread and Message requests chip counts."""
	return {'unread_filter_count': sum(1 for r in rows if (r['unread'] or r['marked_unread']) and not r.get('request')),
		'request_count': sum(1 for r in rows if r.get('request'))}


@login_required
def archived(request):
	rows = S.chat_rows(request.user, archived=True)
	return render(request, 'chat/archived.html', _base_context(request, 'chats', rows=rows))


def _starred_ids(user, ids):
	from .models import StarredMessage
	return list(StarredMessage.objects.filter(user=user, message_id__in=[i for i in ids if i]).values_list('message_id', flat=True))


def _conversation_context(request, conv):
	user = request.user
	from . import pins
	S.unmute_expired(user)
	info = S.title_and_avatar(conv, user)
	messages, has_more = S.history(conv)
	part = S.participant(conv, user)
	members = [S.person(p.user) for p in conv.participants.select_related('user__student_profile')]
	if conv.is_group:
		for m in members:   # the green dot on a member's avatar in the chat
			m['online'] = S.presence_of(User.objects.get(pk=m['id']))['online']
	presence = None
	if info['other'] and not info['is_self']:
		presence = S.presence_of(User.objects.get(pk=info['other']['id']))
	subtitle = ''
	if conv.is_group:
		names = sorted(('You' if m['id'] == user.pk else m['name'].split()[0]) for m in members)
		subtitle = ', '.join(names)
	elif info['is_self']:
		subtitle = 'Message yourself'
	return {
		'conversation': conv, 'conv_info': info, 'participant': part, 'members': members,
		'can_post': S.can_post(conv, user), 'presence': presence, 'subtitle': subtitle,
		'is_request': part is not None and part.request_state == Participant.REQUEST_PENDING,
		'conv_data': {
			'id': conv.pk, 'is_group': conv.is_group, 'is_self': info['is_self'], 'other': info['other'],
			'messages': messages, 'has_more': has_more, 'members': {m['id']: m for m in members},
			'presence': presence, 'can_post': S.can_post(conv, user),
			'unread_from': part.last_read_at.isoformat() if part and part.last_read_at else None,
			'pinned': part.is_pinned, 'archived': part.is_archived, 'favourite': part.is_favourite, 'muted': part.is_muted,
			'muted_until': part.muted_until.isoformat() if part.is_muted and part.muted_until else None,
			'pins': pins.pins(conv), 'can_pin': pins.can_pin(conv, user),
			'starred': _starred_ids(user, [m['id'] for m in messages]),
		},
	}


@login_required
def conversation(request, conversation_id):
	conv = _conversation_for(request, conversation_id)
	rows = S.chat_rows(request.user, archived=Participant.objects.get(conversation=conv, user=request.user).is_archived)
	ctx = _base_context(request, 'chats', rows=rows, **_conversation_context(request, conv))
	ctx.update(_list_counts(rows))
	if ctx['participant'].request_state == Participant.REQUEST_PENDING:
		ctx['open_filter'] = 'requests'
	return render(request, 'chat/conversation.html', ctx)


@login_required
def conversation_history(request, conversation_id):
	conv = _conversation_for(request, conversation_id)
	try:
		before = int(request.GET.get('before', 0)) or None
	except ValueError:
		before = None
	messages, has_more = S.history(conv, before_id=before)
	data = {'messages': messages, 'has_more': has_more,
		'starred': _starred_ids(request.user, [m['id'] for m in messages])}       # your stars on this page
	if not before:                    # the first page also brings the pinned bar
		from . import pins
		data.update(pins=pins.pins(conv), can_pin=pins.can_pin(conv, request.user))
	return JsonResponse(data)


@login_required
def conversation_info(request, conversation_id):
	"""Contact / group info panel."""
	conv = _conversation_for(request, conversation_id)
	ctx = _conversation_context(request, conv)
	ctx['me'] = S.person(request.user)
	if not conv.is_group and ctx['conv_info']['other']:
		other = User.objects.get(pk=ctx['conv_info']['other']['id'])
		ctx['about'] = S.about(other)
		ctx['other_user'] = other
	ctx['media'] = conv.messages.filter(kind=Message.IMAGE, is_deleted=False).order_by('-created_at')[:9]
	return render(request, 'chat/_info.html', ctx)


@login_required
@require_POST
def upload(request, conversation_id):
	"""Photos, documents and voice messages (sent over HTTP because they
	are files), then broadcast over the WebSocket like any message."""
	conv = _conversation_for(request, conversation_id)
	if not S.can_post(conv, request.user):
		return JsonResponse({'error': "You can't send messages to this chat."}, status=403)
	f = request.FILES.get('file')
	if not f:
		return JsonResponse({'error': 'Choose a file to send.'}, status=400)
	if f.size > 25 * 1024 * 1024:
		return JsonResponse({'error': 'Files must be 25 MB or smaller.'}, status=400)
	ext = os.path.splitext(f.name)[1].lower().lstrip('.')
	requested = request.POST.get('kind')
	if requested == 'audio':
		if ext not in Message.AUDIO_EXTENSIONS:
			return JsonResponse({'error': 'Unsupported audio format.'}, status=400)
		kind = Message.AUDIO
	elif ext in Message.IMAGE_EXTENSIONS:
		kind = Message.IMAGE
	elif ext in Message.VIDEO_EXTENSIONS:
		kind = Message.VIDEO                 # plays in the chat
	else:
		kind = Message.FILE
	if kind == Message.IMAGE:
		from PIL import Image
		try:
			Image.open(f).verify()
			f.seek(0)
		except Exception:
			return JsonResponse({'error': "That file isn't a valid image."}, status=400)
	try:
		duration = max(0, min(int(float(request.POST.get('duration') or 0)), 3600))
	except ValueError:
		duration = 0
	caption = (request.POST.get('caption') or '').strip()[:Message.MAX_LENGTH]
	msg = S.create_message(conv, request.user, kind, caption, attachment=f, duration=duration,
		reply_to=S.reply_target(conv, request.POST.get('reply_to')))
	msg = Message.objects.select_related('sender__student_profile', 'reply_to__sender').get(pk=msg.pk)
	S.broadcast_message(msg)
	return JsonResponse({'message': S.serialize_message(msg)})


@login_required
@require_POST
def chat_action(request, conversation_id):
	"""Pin, archive, favourite, mute, mark unread — your own settings for
	one chat (other people never see them)."""
	conv = _conversation_for(request, conversation_id)
	part = Participant.objects.get(conversation=conv, user=request.user)
	action = request.POST.get('action')
	if action in ('accept_request', 'decline_request'):
		# Message requests (chat/requests.py): Accept moves it to your chats; Delete hides it.
		from . import requests as R
		if part.request_state != Participant.REQUEST_PENDING:
			return JsonResponse({'error': "This isn't a message request any more."}, status=400)
		(R.accept if action == 'accept_request' else R.decline)(part)
		if action == 'accept_request':
			changed = S.mark_read(request.user, conv.pk)      # now they can see it was read
			S.broadcast_receipts(changed)
		unread = S.unread_chats_count(request.user)
		S.send_to_group(S.group_user(request.user.pk), {'type': 'unread', 'conversation': conv.pk, 'unread_chats': unread})
		return JsonResponse({'ok': True, 'action': action, 'unread_chats': unread, 'requests': R.pending_count(request.user)})
	toggles = {
		'pin': ('is_pinned', True), 'unpin': ('is_pinned', False),
		'archive': ('is_archived', True), 'unarchive': ('is_archived', False),
		'favourite': ('is_favourite', True), 'unfavourite': ('is_favourite', False),
		'mute': ('is_muted', True), 'unmute': ('is_muted', False),   # mute: for = 8h / 1w / always
		'mark_unread': ('marked_unread', True), 'mark_read': ('marked_unread', False),
	}
	if action not in toggles:
		return JsonResponse({'error': 'Unknown action.'}, status=400)
	field, value = toggles[action]
	if action == 'pin' and Participant.objects.filter(user=request.user, is_pinned=True).exclude(pk=part.pk).count() >= MAX_PINNED:
		return JsonResponse({'error': f'You can only pin up to {MAX_PINNED} chats.'}, status=400)
	setattr(part, field, value)
	if action == 'mute':
		length = request.POST.get('for') or 'always'
		if length not in S.MUTE_FOR:
			return JsonResponse({'error': 'Choose how long to mute it for.'}, status=400)
		S.mute(part, length)
	elif action == 'unmute':
		part.muted_until = None
	if action == 'archive':
		part.is_pinned = False  # archived chats can't stay pinned
	part.save()
	if action == 'mark_read':
		changed = S.mark_read(request.user, conv.pk)
		S.broadcast_receipts(changed)
	S.send_to_group(S.group_user(request.user.pk), {
		'type': 'unread', 'conversation': conv.pk, 'unread_chats': S.unread_chats_count(request.user),
	})
	return JsonResponse({'ok': True, 'action': action, 'unread_chats': S.unread_chats_count(request.user),
		'muted_until': part.muted_until.isoformat() if part.is_muted and part.muted_until else None})


@login_required
def chat_row(request, conversation_id):
	"""One chat-list row, for a chat that just appeared (new message from
	someone new, a group you were added to...)."""
	conv = _conversation_for(request, conversation_id)
	part = Participant.objects.get(conversation=conv, user=request.user)
	row = next((r for r in S.chat_rows(request.user, archived=part.is_archived) if r['id'] == conv.pk), None)
	if row is None:
		raise Http404
	return JsonResponse({'html': render_to_string('chat/_chat_row.html', {'row': row, 'me': S.person(request.user)}, request), 'archived': part.is_archived})


# ---------------------------------------------------------------------
# New chats and groups
# ---------------------------------------------------------------------

def _snippet(text, q, width=48):
	"""A short piece of `text` around the first match of `q`, with the
	match wrapped in <mark> (everything else escaped)."""
	from django.utils.html import escape
	from django.utils.safestring import mark_safe
	text = ' '.join((text or '').split())
	i = text.lower().find(q.lower())
	if i < 0:
		return escape(text[:width * 2])
	start = max(0, i - width)
	end = min(len(text), i + len(q) + width)
	before, match, after = text[start:i], text[i:i + len(q)], text[i + len(q):end]
	return mark_safe(('…' if start else '') + escape(before) + '<mark>' + escape(match) + '</mark>' + escape(after) + ('…' if end < len(text) else ''))


@login_required
def search(request):
	"""The search box at the top of Chats. It only looks through your own
	chats: the chat list is filtered in the browser (chatlist.js), and this
	adds archived chats whose name matches and messages in your chats that
	contain the words. It never lists new people — start a new chat with +.
	Returns {"html": ...}."""
	q = ' '.join((request.GET.get('q') or '').split())[:80]
	if not q:
		return JsonResponse({'html': '', 'count': 0})
	user = request.user
	conv_ids = S.user_conversation_ids(user)

	found = (Message.objects.filter(conversation_id__in=conv_ids, is_deleted=False)
		.exclude(kind=Message.SYSTEM)
		.filter(Q(content__icontains=q) | Q(attachment_name__icontains=q))
		.select_related('sender', 'conversation').order_by('-created_at')[:40])
	titles, message_rows = {}, []
	for m in found:
		conv = m.conversation
		if conv.pk not in titles:
			titles[conv.pk] = S.title_and_avatar(conv, user)
		info = titles[conv.pk]
		who = 'You' if m.sender_id == user.pk else (S.display_name(m.sender).split()[0] if m.sender and conv.is_group else '')
		message_rows.append({
			'id': m.pk, 'conversation': conv.pk, 'info': info, 'time': m.created_at, 'who': who,
			'icon': {'image': 'bi-camera-fill', 'file': 'bi-file-earmark-fill', 'audio': 'bi-mic-fill'}.get(m.kind, ''),
			'snippet': _snippet(m.content or m.attachment_name, q),
		})

	# Only people you've already chatted with (Messages is for your private chats):
	# chats in the list are found by the list filter above (chatlist.js); this adds
	# your archived chats whose name matches, which aren't in the list.
	archived = []
	words = q.lower().split()
	for part in (Participant.objects.filter(user=user, is_archived=True)
			.select_related('conversation').order_by('-conversation__last_message_at')[:200]):
		info = S.title_and_avatar(part.conversation, user)
		name = info['title'].lower() + ' ' + ((info.get('other') or {}).get('username') or '').lower()
		if all(w in name for w in words):
			archived.append({'conversation': part.conversation_id, 'info': info})
			if len(archived) == 8:
				break
	html = render_to_string('chat/_search_results.html', {'q': q, 'archived': archived, 'messages': message_rows}, request=request)
	return JsonResponse({'html': html, 'count': len(archived) + len(message_rows)})


@login_required
def people(request):
	"""People you can message: everyone on UniConnect, people you
	follow and already chat with first."""
	q = (request.GET.get('q') or '').strip()
	user = request.user
	qs = User.objects.filter(is_active=True).select_related('student_profile').exclude(pk=user.pk)
	if q:
		qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(username__icontains=q))
	followed = set(Follow.objects.filter(follower=user, status=Follow.STATUS_ACCEPTED).values_list('following_id', flat=True))
	conv_ids = Participant.objects.filter(user=user, conversation__kind=Conversation.DIRECT).values_list('conversation_id', flat=True)
	chatted = set(Participant.objects.filter(conversation_id__in=conv_ids).values_list('user_id', flat=True))
	candidates = list(qs.order_by('first_name', 'last_name')[:400])
	candidates.sort(key=lambda u: (u.pk not in chatted, u.pk not in followed, S.display_name(u).lower()))
	results = []
	for u in candidates[:40]:
		p = S.person(u)
		p['about'] = S.about(u)
		results.append(p)
	return JsonResponse({'people': results, 'me': {**S.person(user), 'about': 'Message yourself'}})


@login_required
@require_POST
def start_direct(request, user_id):
	other = get_object_or_404(User, pk=user_id, is_active=True)
	from feed.moderation import is_blocked
	if is_blocked(request.user, other):
		if request.headers.get('x-requested-with') == 'XMLHttpRequest':
			return JsonResponse({'error': "You can't message this account."}, status=403)
		raise PermissionDenied("You can't message this account.")
	conv, created = S.direct_conversation(request.user, other)
	if created:
		S.announce_new_conversation(conv)
	url = reverse('chat_conversation', args=[conv.pk])
	if request.headers.get('x-requested-with') == 'XMLHttpRequest':
		return JsonResponse({'url': url, 'conversation': conv.pk})
	return redirect(url)


@login_required
@require_POST
def new_group(request):
	name = (request.POST.get('name') or '').strip()
	if not name:
		return JsonResponse({'error': 'Give the group a name.'}, status=400)
	ids = [int(i) for i in request.POST.getlist('members') if str(i).isdigit()]
	members = list(User.objects.filter(pk__in=ids, is_active=True))
	if not members:
		return JsonResponse({'error': 'Add at least one person.'}, status=400)
	conv = S.create_group(request.user, name, members)
	S.announce_new_conversation(conv)
	return JsonResponse({'url': reverse('chat_conversation', args=[conv.pk]), 'conversation': conv.pk})


# ---------------------------------------------------------------------
# Updates (status = UniConnect Stories)
# ---------------------------------------------------------------------

@login_required
def updates(request):
	"""Status updates (Stories) were replaced by Home's Today strip; old links go to Chats."""
	return redirect('messages')


def _community_cards(user):
	memberships = CommunityMember.objects.filter(user=user).select_related('community')
	cards = []
	for m in memberships:
		community = m.community
		convs = list(community.conversations.order_by('-is_announcement', '-last_message_at'))
		mine = set(Participant.objects.filter(user=user, conversation__in=convs).values_list('conversation_id', flat=True))
		groups = []
		for c in convs:
			last = c.messages.order_by('-created_at').select_related('sender').first()
			groups.append({
				'conv': c, 'joined': c.pk in mine, 'last': last,
				'preview': S.preview_of(last, user, True) if last else None,
			})
		cards.append({'community': community, 'role': m.role, 'groups': groups})
	return cards


@login_required
def communities(request):
	return render(request, 'chat/communities.html', _base_context(request, 'communities', cards=_community_cards(request.user)))


@login_required
@require_POST
def new_community(request):
	name = (request.POST.get('name') or '').strip()[:80]
	if not name:
		return JsonResponse({'error': 'Give the community a name.'}, status=400)
	community = Community.objects.create(name=name, description=(request.POST.get('description') or '').strip()[:300], created_by=request.user)
	CommunityMember.objects.create(community=community, user=request.user, role=CommunityMember.ADMIN)
	# Every community has an Announcements group that all members are in.
	announcements = S.create_group(request.user, 'Announcements', [], community=community, is_announcement=True)
	S.announce_new_conversation(announcements)
	return JsonResponse({'url': reverse('chat_community', args=[community.pk])})


def _community_for(request, community_id):
	member = CommunityMember.objects.filter(community_id=community_id, user=request.user).select_related('community').first()
	if not member:
		raise Http404
	return member.community, member


@login_required
def community_detail(request, community_id):
	community, member = _community_for(request, community_id)
	card = next(c for c in _community_cards(request.user) if c['community'].pk == community.pk)
	members = [S.person(m.user) | {'role': m.role} for m in community.members.select_related('user__student_profile')]
	return render(request, 'chat/community_detail.html', _base_context(
		request, 'communities', card=card, members=members, is_admin=member.role == CommunityMember.ADMIN,
	))


@login_required
@require_POST
def community_new_group(request, community_id):
	community, member = _community_for(request, community_id)
	name = (request.POST.get('name') or '').strip()
	if not name:
		return JsonResponse({'error': 'Give the group a name.'}, status=400)
	conv = S.create_group(request.user, name, [], community=community, description=(request.POST.get('description') or ''))
	S.announce_new_conversation(conv)
	return JsonResponse({'url': reverse('chat_conversation', args=[conv.pk])})


@login_required
@require_POST
def community_join_group(request, community_id, conversation_id):
	community, member = _community_for(request, community_id)
	conv = get_object_or_404(Conversation, pk=conversation_id, community=community, is_announcement=False)
	part, created = Participant.objects.get_or_create(conversation=conv, user=request.user, defaults={'last_read_at': timezone.now()})
	if created:
		msg = S.create_message(conv, None, Message.SYSTEM, f'{S.display_name(request.user)} joined')
		S.announce_new_conversation(conv)
		S.broadcast_message(msg)
	return JsonResponse({'url': reverse('chat_conversation', args=[conv.pk])})


@login_required
@require_POST
def community_add_members(request, community_id):
	community, member = _community_for(request, community_id)
	if member.role != CommunityMember.ADMIN:
		return JsonResponse({'error': 'Only community admins can add members.'}, status=403)
	ids = [int(i) for i in request.POST.getlist('members') if str(i).isdigit()]
	announcements = community.conversations.filter(is_announcement=True).first()
	added = 0
	for u in User.objects.filter(pk__in=ids, is_active=True):
		_, created = CommunityMember.objects.get_or_create(community=community, user=u)
		if created:
			added += 1
			if announcements:
				Participant.objects.get_or_create(conversation=announcements, user=u)
	if announcements and added:
		S.announce_new_conversation(announcements)
	return JsonResponse({'added': added, 'url': reverse('chat_community', args=[community.pk])})


# ---------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------

@login_required
def calls(request):
	user = request.user
	items = []
	for call in Call.objects.filter(Q(caller=user) | Q(callee=user)).select_related(
			'caller__student_profile', 'callee__student_profile')[:100]:
		outgoing = call.caller_id == user.pk
		other = call.callee if outgoing else call.caller
		missed = not outgoing and call.status in (Call.MISSED, Call.DECLINED)
		items.append({'call': call, 'person': S.person(other), 'outgoing': outgoing, 'missed': missed})
	return render(request, 'chat/calls.html', _base_context(request, 'calls', items=items))


# ---------------------------------------------------------------------
# You (profile + settings)
# ---------------------------------------------------------------------

@login_required
def you(request):
	student = getattr(request.user, 'student_profile', None)
	return render(request, 'chat/you.html', _base_context(request, 'you', student=student, about_text=S.about(request.user)))


@login_required
@require_POST
def update_settings(request):
	s = ChatSettings.for_user(request.user)
	field = request.POST.get('field')
	value = request.POST.get('value', '')
	if field == 'about':
		value = value.strip()[:140]
		if not value:
			return JsonResponse({'error': "About can't be empty."}, status=400)
		s.about = value
	elif field in ('read_receipts', 'enter_to_send', 'sounds'):
		setattr(s, field, value in ('1', 'true', 'on'))
	elif field == 'last_seen_visibility' and value in (ChatSettings.EVERYONE, ChatSettings.NOBODY):
		s.last_seen_visibility = value
	elif field == 'wallpaper' and value in dict(ChatSettings.WALLPAPERS):
		s.wallpaper = value
	else:
		return JsonResponse({'error': 'Unknown setting.'}, status=400)
	s.save()
	return JsonResponse({'ok': True, 'field': field, 'value': getattr(s, field)})


# ---------------------------------------------------------------------
# Polls in group chats (chat/polls.py, static/js/chat-polls.js)
# ---------------------------------------------------------------------

@login_required
@require_POST
def poll_create(request, conversation_id):
	from django.core.exceptions import ValidationError
	from . import polls
	conv = _conversation_for(request, conversation_id)
	if not S.can_post(conv, request.user):
		return JsonResponse({'error': "You can't send messages to this chat."}, status=403)
	try:
		msg = polls.create(conv, request.user, request.POST.get('question'), request.POST.getlist('option'),
			multiple=request.POST.get('multiple') in ('1', 'on', 'true'),
			reply_to=S.reply_target(conv, request.POST.get('reply_to')))
	except ValidationError as e:
		return JsonResponse({'error': e.messages[0]}, status=400)
	msg = Message.objects.select_related('sender__student_profile', 'reply_to__sender').get(pk=msg.pk)
	S.broadcast_message(msg)
	return JsonResponse({'message': S.serialize_message(msg)})


@login_required
@require_POST
def poll_vote(request, message_id):
	from django.core.exceptions import ValidationError
	from . import polls
	poll = polls.poll_for(request.user, message_id)
	if poll is None:
		raise Http404('Poll not found')
	try:
		polls.vote(poll, request.user, request.POST.getlist('option'))
	except ValidationError as e:
		return JsonResponse({'error': e.messages[0]}, status=400)
	polls.broadcast(poll)
	return JsonResponse({'poll': polls.for_message(poll.message)})


@login_required
@require_POST
def poll_close(request, message_id):
	from django.core.exceptions import ValidationError
	from . import polls
	poll = polls.poll_for(request.user, message_id)
	if poll is None:
		raise Http404('Poll not found')
	try:
		polls.close(poll, request.user)
	except ValidationError as e:
		return JsonResponse({'error': e.messages[0]}, status=403)
	polls.broadcast(poll)
	return JsonResponse({'poll': polls.for_message(poll.message)})


# ---------------------------------------------------------------------
# Pinned messages (chat/pins.py, static/js/chat-pins.js)
# ---------------------------------------------------------------------

@login_required
@require_POST
def message_pin(request, message_id):
	from django.core.exceptions import ValidationError
	from . import pins
	msg = Message.objects.select_related('conversation').filter(pk=message_id, conversation__participants__user=request.user).first()
	if msg is None:
		raise Http404('Message not found')
	if not pins.can_pin(msg.conversation, request.user):
		return JsonResponse({'error': 'Only group admins can pin messages.'}, status=403)
	try:
		if request.POST.get('action') == 'unpin':
			pins.unpin(msg, request.user)
		else:
			pins.pin(msg, request.user)
	except ValidationError as e:
		return JsonResponse({'error': e.messages[0]}, status=400)
	pins.broadcast(msg.conversation)
	return JsonResponse({'pins': pins.pins(msg.conversation)})


@login_required
def conversation_members(request, conversation_id):
	"""GET ?q= — people in this group chat for the @ list (static/js/mentions.js)."""
	from . import mentions
	conv = _conversation_for(request, conversation_id)
	people = mentions.members(conv, request.user, request.GET.get('q', '')) if conv.is_group else []
	return JsonResponse({'people': people})


@login_required
@require_POST
def message_edit(request, message_id):
	"""Edit your own message (chat/editing.py)."""
	from django.core.exceptions import ValidationError
	from . import editing
	msg = Message.objects.filter(pk=message_id, conversation__participants__user=request.user).first()
	if msg is None:
		raise Http404('Message not found')
	try:
		editing.edit(msg, request.user, request.POST.get('content'))
	except ValidationError as e:
		return JsonResponse({'error': e.messages[0]}, status=400)
	editing.broadcast(msg)
	msg = Message.objects.select_related('sender__student_profile', 'reply_to__sender').get(pk=msg.pk)
	return JsonResponse({'message': S.serialize_message(msg)})


# ---------------------------------------------------------------------
# Forwarding (chat/forwarding.py, static/js/chat-forward.js)
# ---------------------------------------------------------------------

@login_required
def forward_targets(request):
	from . import forwarding
	return JsonResponse({'chats': forwarding.targets(request.user, request.GET.get('q', ''))})


@login_required
@require_POST
def message_forward(request, message_id):
	from django.core.exceptions import ValidationError
	from . import forwarding
	msg = Message.objects.filter(pk=message_id, conversation__participants__user=request.user).first()
	if msg is None:
		raise Http404('Message not found')
	try:
		made = forwarding.forward(msg, request.user, request.POST.getlist('to'))
	except ValidationError as e:
		return JsonResponse({'error': e.messages[0]}, status=400)
	forwarding.broadcast(made)
	n = len(made)
	return JsonResponse({'sent': n, 'message': f'Forwarded to {n} chat{"" if n == 1 else "s"}.'})


# ---------------------------------------------------------------------
# Starred messages (Messages > Starred)
# ---------------------------------------------------------------------

@login_required
@require_POST
def message_star(request, message_id):
	"""Star or unstar a message (yours to find later; nobody else sees it)."""
	from .models import StarredMessage
	msg = Message.objects.filter(pk=message_id, conversation__participants__user=request.user, is_deleted=False).exclude(
		kind=Message.SYSTEM).first()
	if msg is None:
		raise Http404('Message not found')
	want = request.POST.get('star')
	have = StarredMessage.objects.filter(user=request.user, message=msg)
	starred = not have.exists() if want not in ('0', '1') else want == '1'
	if starred:
		StarredMessage.objects.get_or_create(user=request.user, message=msg)
	else:
		have.delete()
	if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
		return JsonResponse({'starred': starred, 'message': msg.pk})
	return redirect(request.POST.get('next') or reverse('chat_starred'))


def _open_url(msg):
	"""Where "Go to message" goes: the chat in Messages, at that message (group chats too)."""
	return reverse('chat_conversation', args=[msg.conversation_id]) + f'?m={msg.pk}'


@login_required
def starred(request):
	from .mentions import readable
	from .models import StarredMessage
	stars = (StarredMessage.objects.filter(user=request.user, message__is_deleted=False,
			message__conversation__participants__user=request.user)
		.select_related('message', 'message__sender', 'message__sender__student_profile', 'message__conversation')
		.order_by('-created_at')[:200])
	q = ' '.join((request.GET.get('q') or '').split())[:80]
	items = []
	for st in stars:
		m = st.message
		text = readable(m) if m.content else ''
		if q and q.lower() not in (text or '').lower() and q.lower() not in (m.attachment_name or '').lower():
			continue
		info = S.title_and_avatar(m.conversation, request.user)
		items.append({'message': m, 'text': text, 'chat': info['title'], 'is_group': info['is_group'],
			'sender': S.person(m.sender) if m.sender_id else None, 'mine': m.sender_id == request.user.pk,
			'url': _open_url(m), 'preview': S.preview_of(m, request.user, False)})
	return render(request, 'chat/starred.html', _base_context(request, 'chats', items=items, q=q))
