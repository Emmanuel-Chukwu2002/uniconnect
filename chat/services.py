"""
The Messages logic, shared by the pages (views.py) and the WebSocket
consumer (consumers.py). Everything here is plain synchronous Django;
the consumer calls it through database_sync_to_async.

Channel-layer groups used for real-time events:
    user_<id>   every open tab of one user (badges, calls, new chats)
    conv_<id>   everyone in one conversation (messages, typing, ticks,
                reactions, presence of its members)
"""
import hashlib
import os
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import (
	ChatSettings, CommunityMember, Conversation, ConversationParticipant as Participant, Message, MessageReaction,
	UserPresence,
)

User = get_user_model()
EPOCH = timezone.datetime(2000, 1, 1, tzinfo=timezone.get_current_timezone())

# Avatar colours for people without a photo (picked from their id, so
# each person always gets the same one).
AVATAR_COLOURS = ['#4a6cf7', '#6e5bd6', '#d6604b', '#2f80c9', '#c94f86', '#cc8a1f', '#2179ff', '#8a5bd6']
# Name colours for senders inside groups (like WhatsApp).
NAME_COLOURS = ['#4a6cf7', '#c0492f', '#6c4bd1', '#b8590b', '#1b74c4', '#b23a7a', '#2f8fd6', '#8c6bd6']


# ---------------------------------------------------------------------
# People
# ---------------------------------------------------------------------

def group_user(user_id):
	return f'user_{user_id}'


def group_conv(conversation_id):
	return f'conv_{conversation_id}'


def display_name(user):
	return (user.get_full_name() or user.username).strip()


def initials(name):
	parts = [p for p in name.replace('.', ' ').split() if p]
	return (''.join(p[0] for p in parts[:2]) or '?').upper()


def colour_for(user_id, palette=AVATAR_COLOURS):
	return palette[int(hashlib.md5(str(user_id).encode()).hexdigest(), 16) % len(palette)]


def person(user):
	"""What templates and JS need to draw someone."""
	profile = getattr(user, 'student_profile', None)
	photo = profile.profile_photo.url if profile and profile.profile_photo else ''
	name = display_name(user)
	return {
		'id': user.pk, 'name': name, 'username': user.username, 'photo': photo,
		'initials': initials(name), 'colour': colour_for(user.pk), 'name_colour': colour_for(user.pk, NAME_COLOURS),
	}


def about(user):
	settings_obj = getattr(user, 'chat_settings', None)
	if settings_obj and settings_obj.about:
		return settings_obj.about
	profile = getattr(user, 'student_profile', None)
	return (profile.bio if profile and profile.bio else 'Hey there! I am using UniConnect.')


def presence_of(user, viewer=None):
	"""{'online': bool, 'last_seen': iso or None}. Respects the person's
	"last seen" privacy setting."""
	pres = UserPresence.objects.filter(user=user).first()
	hide = ChatSettings.objects.filter(user=user, last_seen_visibility=ChatSettings.NOBODY).exists()
	if not pres:
		return {'online': False, 'last_seen': None}
	return {
		'online': pres.is_online and not hide,
		'last_seen': None if hide or not pres.last_seen else pres.last_seen.isoformat(),
	}


# ---------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------

def participant(conversation, user):
	return Participant.objects.filter(conversation=conversation, user=user).first()


def user_conversation_ids(user):
	return list(Participant.objects.filter(user=user).values_list('conversation_id', flat=True))


def direct_conversation(user_a, user_b):
	"""The one direct chat between two people (created the first time).
	Messaging yourself is allowed, like WhatsApp's "Message yourself"."""
	key = Conversation.make_direct_key(user_a.pk, user_b.pk)
	with transaction.atomic():
		conv, created = Conversation.objects.get_or_create(
			direct_key=key, defaults={'kind': Conversation.DIRECT, 'created_by': user_a},
		)
		if created:
			for u in {user_a.pk: user_a, user_b.pk: user_b}.values():
				Participant.objects.get_or_create(conversation=conv, user=u)
	return conv, created


def create_group(creator, name, members, community=None, is_announcement=False, description=''):
	with transaction.atomic():
		conv = Conversation.objects.create(
			kind=Conversation.GROUP, name=name.strip()[:80], description=description[:300], created_by=creator,
			community=community, is_announcement=is_announcement, last_message_at=timezone.now(),
		)
		Participant.objects.create(conversation=conv, user=creator, role=Participant.ADMIN, last_read_at=timezone.now())
		for m in members:
			if m.pk != creator.pk:
				Participant.objects.get_or_create(conversation=conv, user=m)
		create_message(conv, None, Message.SYSTEM, f'{display_name(creator)} created {"this" if not is_announcement else "the announcements"} group "{conv.name}"')
	return conv


def other_member(conversation, user):
	"""The other person in a direct chat (yourself for "Message yourself")."""
	for p in conversation.participants.all():
		if p.user_id != user.pk:
			return p.user
	return user


def title_and_avatar(conversation, user):
	if conversation.is_group:
		return {
			'title': conversation.name, 'photo': conversation.avatar.url if conversation.avatar else '',
			'initials': initials(conversation.name), 'colour': '#e1e7fe', 'is_group': True,
			'is_announcement': conversation.is_announcement, 'is_self': False, 'other': None,
		}
	other = other_member(conversation, user)
	p = person(other)
	is_self = other.pk == user.pk
	return {
		'title': f'{p["name"]} (You)' if is_self else p['name'], 'photo': p['photo'], 'initials': p['initials'],
		'colour': p['colour'], 'is_group': False, 'is_announcement': False, 'is_self': is_self, 'other': p,
	}


def can_post(conversation, user):
	part = participant(conversation, user)
	if not part:
		return False
	if conversation.is_announcement:
		if part.role == Participant.ADMIN:
			return True
		return bool(conversation.community_id) and CommunityMember.objects.filter(
			community_id=conversation.community_id, user=user, role=CommunityMember.ADMIN,
		).exists()
	return True


# ---------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------

def reply_target(conversation, reply_to_id):
	"""The message being replied to — only one in the same chat, not deleted."""
	try:
		rid = int(reply_to_id or 0)
	except (TypeError, ValueError):
		return None
	if not rid:
		return None
	return Message.objects.filter(pk=rid, conversation=conversation, is_deleted=False).exclude(kind=Message.SYSTEM).first()


def create_message(conversation, sender, kind=Message.TEXT, content='', attachment=None, duration=0, reply_to=None, forwarded=False):
	now = timezone.now()
	msg = Message(conversation=conversation, sender=sender, kind=kind, content=content[:Message.MAX_LENGTH], duration=duration,
		reply_to=reply_to, forwarded=forwarded)
	if attachment is not None:
		msg.attachment = attachment
		msg.attachment_name = os.path.basename(getattr(attachment, 'name', ''))[:200]
		msg.attachment_size = getattr(attachment, 'size', 0) or 0
	msg.full_clean(exclude=['attachment'] if attachment is None else None)
	msg.save()
	Conversation.objects.filter(pk=conversation.pk).update(last_message_at=msg.created_at)
	if sender is not None:
		# Your own message counts as read by you, and a chat you write in
		# is no longer "marked unread".
		Participant.objects.filter(conversation=conversation, user=sender).update(
			last_read_at=now, last_delivered_at=now, last_read_receipt_at=now, marked_unread=False,
		)
		if '@' in (msg.content or '') and not forwarded:      # a forwarded message doesn't tag anyone again
			from .mentions import record
			record(msg)                     # @mentions in group chats (chat/mentions.py)
		if conversation.kind == Conversation.DIRECT:
			from .requests import on_message
			on_message(msg)                 # message requests (chat/requests.py)
	return msg


def message_status(msg):
	if msg.read_at:
		return 'read'
	if msg.delivered_at:
		return 'delivered'
	return 'sent'


def reactions_summary(msg):
	summary = {}
	for r in msg.reactions.all():
		item = summary.setdefault(r.emoji, {'emoji': r.emoji, 'count': 0, 'users': []})
		item['count'] += 1
		item['users'].append(r.user_id)
	return sorted(summary.values(), key=lambda x: -x['count'])


def serialize_message(msg):
	sender = person(msg.sender) if msg.sender_id else None
	data = {
		'id': msg.pk, 'conversation': msg.conversation_id, 'kind': msg.kind,
		'sender': sender, 'content': '' if msg.is_deleted else msg.content,
		'created_at': msg.created_at.isoformat(), 'status': message_status(msg),
		'is_deleted': msg.is_deleted, 'reactions': [] if msg.is_deleted else reactions_summary(msg),
		'attachment': None, 'duration': msg.duration, 'pinned': bool(msg.pinned_at) and not msg.is_deleted,
		'edited': bool(msg.edited_at) and not msg.is_deleted,
		'forwarded': msg.forwarded and not msg.is_deleted,
	}
	if msg.attachment and not msg.is_deleted:
		data['attachment'] = {'url': msg.attachment.url, 'name': msg.attachment_name, 'size': msg.attachment_size}
	data['mentions'] = []
	if '@' in (msg.content or '') and not msg.is_deleted and msg.pk:
		from .mentions import data as mention_data
		data['mentions'] = mention_data(msg)
	if msg.kind == Message.POLL and not msg.is_deleted:
		from . import polls
		data['poll'] = polls.for_message(msg)
	data['reply_to'] = None
	if msg.reply_to_id and not msg.is_deleted:
		r = msg.reply_to
		if r is not None:
			text = 'This message was deleted' if r.is_deleted else (r.content or {
				Message.IMAGE: 'Photo', Message.VIDEO: 'Video', Message.FILE: r.attachment_name or 'Document', Message.AUDIO: 'Voice message'}.get(r.kind, ''))
			if r.kind == Message.POLL and not r.is_deleted:
				text = '📊 Poll: ' + text
			data['reply_to'] = {'id': r.pk, 'name': display_name(r.sender) if r.sender_id else '', 'sender': r.sender_id,
				'kind': r.kind, 'text': ' '.join(text.split())[:140]}
	return data


def history(conversation, before_id=None, limit=50):
	qs = (conversation.messages.select_related('sender', 'sender__student_profile', 'reply_to', 'reply_to__sender')
		.prefetch_related('reactions').order_by('-created_at', '-id'))
	if before_id:
		qs = qs.filter(id__lt=before_id)
	msgs = list(qs.prefetch_related('mentions__user')[:limit + 1])
	has_more = len(msgs) > limit
	return [serialize_message(m) for m in reversed(msgs[:limit])], has_more


def preview_of(msg, viewer, is_group):
	"""The grey line under a chat's name: icon (Bootstrap icon class),
	sender prefix and text."""
	if msg is None:
		return {'icon': '', 'prefix': '', 'text': '', 'mine': False, 'status': ''}
	mine = msg.sender_id == viewer.pk
	prefix = ''
	if is_group and msg.sender_id and not mine and msg.kind != Message.SYSTEM:
		prefix = (msg.sender.first_name or msg.sender.username) + ': '
	icon, text = '', msg.content
	if '@' in (text or '') and msg.kind != Message.SYSTEM and not msg.is_deleted:
		from .mentions import readable
		text = readable(msg)              # "@UNN-2022…" → "@Ada Obi"
	if msg.is_deleted:
		icon, text = 'bi-slash-circle', 'This message was deleted' if not mine else 'You deleted this message'
	elif msg.kind == Message.IMAGE:
		icon, text = 'bi-camera-fill', msg.content or 'Photo'
	elif msg.kind == Message.VIDEO:
		icon, text = 'bi-camera-video-fill', msg.content or 'Video'
	elif msg.kind == Message.FILE:
		icon, text = 'bi-file-earmark-fill', msg.attachment_name or 'Document'
	elif msg.kind == Message.POLL:
		icon, text = 'bi-bar-chart-fill', 'Poll: ' + msg.content
	elif msg.kind == Message.AUDIO:
		m, s = divmod(msg.duration or 0, 60)
		icon, text = 'bi-mic-fill', f'Voice message ({m}:{s:02d})'
	return {
		'icon': icon, 'prefix': prefix, 'text': ' '.join(text.split())[:120], 'mine': mine and msg.kind != Message.SYSTEM,
		'status': message_status(msg) if mine else '',
	}


def unread_for(part):
	"""Unread messages in one chat for one participant."""
	since = part.last_read_at or EPOCH
	return part.conversation.messages.filter(created_at__gt=since, is_deleted=False).exclude(
		sender=part.user).exclude(kind=Message.SYSTEM).count()


def _unread_subquery(user):
	return (Message.objects.filter(
		conversation=OuterRef('conversation'), is_deleted=False,
		created_at__gt=Coalesce(OuterRef('last_read_at'), Value(EPOCH)),
	).exclude(sender=user).exclude(kind=Message.SYSTEM)
		.values('conversation').annotate(c=Count('id')).values('c'))


def chat_rows(user, archived=False):
	"""Everything the chat list shows, newest first, pinned on top."""
	unmute_expired(user)
	if not archived:
		# Your own chat is always there, like WhatsApp's "Message yourself".
		direct_conversation(user, user)
	from .mentions import unread_mention_ids
	mentioned = unread_mention_ids(user)
	unread_sq = _unread_subquery(user)
	last_sq = Message.objects.filter(conversation=OuterRef('conversation')).order_by('-created_at', '-id').values('id')[:1]
	parts = list(
		Participant.objects.filter(user=user, is_archived=archived)
		.exclude(request_state=Participant.REQUEST_DECLINED)        # deleted message requests
		.select_related('conversation', 'conversation__community')
		.prefetch_related('conversation__participants__user__student_profile')
		.annotate(unread=Coalesce(Subquery(unread_sq), 0), last_id=Subquery(last_sq))
	)
	last_msgs = Message.objects.select_related('sender').in_bulk([p.last_id for p in parts if p.last_id])
	conv_ids = [p.conversation_id for p in parts]
	latest_reaction = {}
	for r in (MessageReaction.objects.filter(message__conversation_id__in=conv_ids)
			.select_related('user', 'message').order_by('-created_at')[:200]):
		latest_reaction.setdefault(r.message.conversation_id, r)
	online = set(UserPresence.objects.filter(connections__gt=0).values_list('user_id', flat=True))

	rows = []
	for p in parts:
		conv = p.conversation
		msg = last_msgs.get(p.last_id)
		info = title_and_avatar(conv, user)
		preview = preview_of(msg, user, conv.is_group)
		if info['is_self'] and not msg:
			preview['text'] = 'Message yourself'
		when = msg.created_at if msg else conv.created_at
		react = latest_reaction.get(conv.pk)
		if react and (not msg or react.created_at > msg.created_at):
			who = 'You' if react.user_id == user.pk else (react.user.first_name or react.user.username)
			target = ' '.join((react.message.content or 'a message').split())[:40]
			preview = {'icon': '', 'prefix': '', 'text': f'{who} reacted {react.emoji} to "{target}"', 'mine': False, 'status': ''}
			when = react.created_at
		rows.append({
			'id': conv.pk, **info, 'preview': preview, 'last_id': msg.pk if msg else '', 'time': when, 'sort_time': when,
			'unread': p.unread, 'marked_unread': p.marked_unread, 'pinned': p.is_pinned,
			'mention': conv.pk in mentioned, 'muted': p.is_muted, 'muted_until': p.muted_until if p.is_muted else None, 'favourite': p.is_favourite, 'archived': p.is_archived,
			'community': conv.community.name if conv.community_id else '',
			'request': p.request_state == Participant.REQUEST_PENDING,           # under "Message requests" (chat/requests.py)
			'online': bool(info['other'] and info['other']['id'] in online and not info['is_self']),
		})
	rows.sort(key=lambda r: r['sort_time'], reverse=True)
	rows.sort(key=lambda r: not r['pinned'])
	return rows


# ---------------------------------------------------------------------
# Muting a chat for a while (Mute notifications → 8 hours / 1 week / Always)
# ---------------------------------------------------------------------

MUTE_FOR = {'8h': timedelta(hours=8), '1w': timedelta(weeks=1), 'always': None}


def mute(part, length):
	"""Mutes `part`'s chat for `length` (a MUTE_FOR key)."""
	if length not in MUTE_FOR:
		raise ValueError(length)
	delta = MUTE_FOR[length]
	part.is_muted = True
	part.muted_until = timezone.now() + delta if delta else None


def unmute_expired(user=None):
	"""Mutes whose time is up end here. Called before anything that counts
	or shows muted chats, so a chat unmutes on time without a timer."""
	qs = Participant.objects.filter(is_muted=True, muted_until__isnull=False, muted_until__lte=timezone.now())
	if user is not None:
		qs = qs.filter(user=user)
	return qs.update(is_muted=False, muted_until=None)


def unread_chats_count(user):
	"""Chats (not messages) with something unread — the unread badge on
	the Chats tab and on UniConnect's Messages link. Archived and muted
	chats don't count, like WhatsApp."""
	unmute_expired(user)
	return (Participant.objects.filter(user=user, is_archived=False, is_muted=False)
		.exclude(request_state__in=[Participant.REQUEST_PENDING, Participant.REQUEST_DECLINED])   # message requests
		.annotate(unread=Coalesce(Subquery(_unread_subquery(user)), 0))
		.filter(Q(unread__gt=0) | Q(marked_unread=True)).count())


# ---------------------------------------------------------------------
# Ticks (delivered / read)
# ---------------------------------------------------------------------

def _recompute(conversation_ids):
	"""Set delivered_at/read_at on messages once EVERY other member has
	received/read them. Returns {conv_id: [(message_id, status), ...]}."""
	changed = {}
	now = timezone.now()
	no_receipts = set(ChatSettings.objects.filter(read_receipts=False).values_list('user_id', flat=True))
	for conv_id in set(conversation_ids):
		parts = list(Participant.objects.filter(conversation_id=conv_id))
		pending = Message.objects.filter(conversation_id=conv_id, read_at__isnull=True).exclude(
			kind=Message.SYSTEM).exclude(sender__isnull=True)
		for sender_id in set(pending.values_list('sender_id', flat=True)):
			others = [p for p in parts if p.user_id != sender_id]
			if not others:  # "Message yourself": instantly read
				ids = list(pending.filter(sender_id=sender_id).values_list('id', flat=True))
				Message.objects.filter(id__in=ids).update(delivered_at=now, read_at=now, is_read=True)
				changed.setdefault(conv_id, []).extend((i, 'read') for i in ids)
				continue
			delivered = [p.last_delivered_at for p in others]
			read = [p.last_read_receipt_at for p in others]
			if all(delivered):
				ids = list(pending.filter(sender_id=sender_id, delivered_at__isnull=True, created_at__lte=min(delivered)).values_list('id', flat=True))
				if ids:
					Message.objects.filter(id__in=ids).update(delivered_at=now)
					changed.setdefault(conv_id, []).extend((i, 'delivered') for i in ids)
			# If the SENDER has read receipts off, they don't get blue ticks either.
			if all(read) and sender_id not in no_receipts:
				ids = list(pending.filter(sender_id=sender_id, created_at__lte=min(read)).values_list('id', flat=True))
				if ids:
					Message.objects.filter(id__in=ids).update(read_at=now, is_read=True, delivered_at=Coalesce('delivered_at', Value(now)))
					changed.setdefault(conv_id, []).extend((i, 'read') for i in ids)
	return changed


def mark_delivered(user, conversation_ids=None, up_to=None):
	up_to = up_to or timezone.now()
	qs = Participant.objects.filter(user=user)
	if conversation_ids is not None:
		qs = qs.filter(conversation_id__in=conversation_ids)
	qs.filter(Q(last_delivered_at__isnull=True) | Q(last_delivered_at__lt=up_to)).update(last_delivered_at=up_to)
	return _recompute(qs.values_list('conversation_id', flat=True))


def mark_read(user, conversation_id):
	now = timezone.now()
	receipts = ChatSettings.for_user(user).read_receipts
	if Participant.objects.filter(user=user, conversation_id=conversation_id, request_state=Participant.REQUEST_PENDING).exists():
		receipts = False             # a message request: they can't see you've read it until you accept
	fields = {'last_read_at': now, 'last_delivered_at': now, 'marked_unread': False}
	if receipts:
		fields['last_read_receipt_at'] = now
	Participant.objects.filter(user=user, conversation_id=conversation_id).update(**fields)
	return _recompute([conversation_id])


# ---------------------------------------------------------------------
# Sending events from normal (sync) Django code, e.g. views
# ---------------------------------------------------------------------

def send_to_group(group, payload):
	layer = get_channel_layer()
	if layer is not None:
		async_to_sync(layer.group_send)(group, {'type': 'chat.event', 'payload': payload})


def broadcast_message(msg):
	send_to_group(group_conv(msg.conversation_id), {'type': 'message', 'message': serialize_message(msg)})
	push_unread_counts(msg.conversation_id, exclude_user=msg.sender_id)


def push_unread_counts(conversation_id, exclude_user=None):
	"""After a new message, every other member's tabs get their new
	"chats with unread messages" total (the unread badges)."""
	for uid in Participant.objects.filter(conversation_id=conversation_id).exclude(user_id=exclude_user).values_list('user_id', flat=True):
		user = User(pk=uid)
		send_to_group(group_user(uid), {'type': 'unread', 'unread_chats': unread_chats_count(user)})


def broadcast_receipts(changed):
	for conv_id, items in changed.items():
		send_to_group(group_conv(conv_id), {'type': 'receipt', 'conversation': conv_id, 'items': items})


def announce_new_conversation(conversation):
	"""Tell every member's open tabs to start listening to a new chat."""
	layer = get_channel_layer()
	if layer is None:
		return
	for user_id in conversation.participants.values_list('user_id', flat=True):
		async_to_sync(layer.group_send)(group_user(user_id), {'type': 'chat.join', 'conversation': conversation.pk})


def announce_status(story):
	"""A new status (story): light up the Updates tab for the people who
	follow the poster or chat with them."""
	from feed.models import Follow
	poster = story.user
	ids = set(Follow.objects.filter(following=poster, status=Follow.STATUS_ACCEPTED).values_list('follower_id', flat=True))
	conv_ids = Participant.objects.filter(user=poster).values_list('conversation_id', flat=True)
	ids |= set(Participant.objects.filter(conversation_id__in=conv_ids).values_list('user_id', flat=True))
	ids.discard(poster.pk)
	payload = {'type': 'status', 'user': person(poster)}
	for uid in ids:
		send_to_group(group_user(uid), payload)


# ---------------------------------------------------------------------
# "New message" pop-ups on every page (feed/views.py notifications_count,
# static/js/app.js): messages that arrived since the page last asked, in
# chats you haven't muted, newest first.
# ---------------------------------------------------------------------
def new_message_popups(user, since, limit=3):
	from django.urls import reverse
	unmute_expired(user)
	# Muted chats stay quiet — except a message that @mentions you (chat/mentions.py).
	quiet = Participant.objects.filter(user=user).filter(Q(is_muted=True) | Q(is_archived=True)
		| Q(request_state__in=[Participant.REQUEST_PENDING, Participant.REQUEST_DECLINED])).values('conversation_id')
	msgs = (Message.objects.filter(conversation__participants__user=user, created_at__gt=since, is_deleted=False)
		.filter(~Q(conversation_id__in=quiet) | Q(mentions__user=user))
		.exclude(sender=user).exclude(sender__isnull=True).exclude(kind=Message.SYSTEM)
		.select_related('sender', 'sender__student_profile', 'conversation').order_by('-created_at')[:limit])
	out = []
	for m in msgs:
		conv = m.conversation
		try:
			group = conv.study_group
		except Exception:
			group = None
		title = (group.title if group is not None else conv.name) if conv.is_group else display_name(m.sender)
		url = reverse('chat_conversation', args=[conv.pk])            # every chat opens in Messages
		prev = preview_of(m, user, conv.is_group)
		mentioned = m.mentions.filter(user=user).exists() if '@' in (m.content or '') else False
		out.append({'conversation': conv.pk, 'title': title, 'url': url, 'sender': person(m.sender), 'mention': mentioned,
			'text': ('@ ' if mentioned else '') + (display_name(m.sender) + ': ' if conv.is_group else '') + prev['text']})
	return out
