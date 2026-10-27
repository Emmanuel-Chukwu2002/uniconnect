"""@mentions in group chats.

Typing "@" in a group chat box (group page Chat tab, or a group in
Messages) lists the chat's members (members() below, through
/messages/c/<id>/members/ and static/js/mentions.js); picking one puts
"@username " in the box, the same as mentions in posts.

When the message is sent, record() keeps who was mentioned — only people
in that chat, never the sender — and each of them:
  * gets a notification ("Ada mentioned you in COS 401: …"), and
  * gets the chat's pop-up even if they muted the chat, and sees an "@"
    on the chat in their list until they read it (chat/services.py).
The message shows "@Their Name" highlighted (static/js/mentions.js,
UCChatMentions); a mention of you stands out more.
"""
import logging

from django.db.models import Q
from django.urls import reverse

from .models import ConversationParticipant as Participant, Message, MessageMention

log = logging.getLogger(__name__)
KINDS = (Message.TEXT, Message.IMAGE, Message.VIDEO, Message.FILE, Message.POLL)


def record(msg, already=()):
	"""Saves the mentions in `msg` and notifies those people (not the ids in
	`already` — people an edited message had mentioned before)."""
	if msg.sender_id is None or msg.kind not in KINDS or '@' not in (msg.content or ''):
		return []
	conv = msg.conversation
	if not conv.is_group:
		return []
	from feed.notifications import MENTION_RE
	names = {m.rstrip('.') for m in MENTION_RE.findall(msg.content)}
	if not names:
		return []
	people = list(Participant.objects.filter(conversation=conv, user__username__in=names)
		.exclude(user_id=msg.sender_id).select_related('user'))
	MessageMention.objects.bulk_create([MessageMention(message=msg, user=p.user) for p in people], ignore_conflicts=True)
	try:
		from feed.models import Notification as N
		from feed.notifications import notify
		for p in people:
			if p.user_id in already:
				continue
			notify(p.user, msg.sender, N.CHAT_MENTION, chat_message=msg)
	except Exception:
		log.exception('Could not notify mentions in message %s', msg.pk)
	return [p.user for p in people]


def data(msg):
	"""[{id, username, name, url}] for the message's mentions."""
	from . import services as S
	return [{'id': m.user_id, 'username': m.user.username, 'name': S.display_name(m.user),
		'url': reverse('user_profile', args=[m.user.username])} for m in msg.mentions.all()]


def members(conv, viewer, q='', limit=8):
	"""People in the chat for the @ list (not you), best matches first."""
	from . import services as S
	qs = Participant.objects.filter(conversation=conv).exclude(user=viewer).select_related('user__student_profile')
	q = (q or '').strip().lstrip('@')
	if q:
		qs = qs.filter(Q(user__username__istartswith=q) | Q(user__first_name__istartswith=q) | Q(user__last_name__istartswith=q))
	out = []
	for p in qs.order_by('user__first_name', 'user__last_name')[:limit]:
		info = S.person(p.user)
		prof = getattr(p.user, 'student_profile', None)
		out.append({'name': info['name'], 'username': p.user.username, 'photo': info['photo'],
			'verified': bool(prof and getattr(prof, 'is_verified', False)),
			'detail': 'Admin' if p.role == Participant.ADMIN else ''})
	return out


def unread_mention_ids(user):
	"""Chats where `user` was mentioned after they last read the chat."""
	from django.db.models import F
	from django.db.models.functions import Coalesce
	from . import services as S
	from django.db.models import Value
	return set(MessageMention.objects.filter(user=user, message__is_deleted=False,
		message__conversation__participants__user=user,
		message__created_at__gt=Coalesce(F('message__conversation__participants__last_read_at'), Value(S.EPOCH)))
		.values_list('message__conversation_id', flat=True))


def readable(msg, text=None):
	"""The message's text with each "@username" it mentions shown as "@Name"
	(for previews, pop-ups and notifications, which are plain text)."""
	text = msg.content if text is None else text
	if '@' not in (text or '') or not msg.pk:
		return text
	from . import services as S
	for m in msg.mentions.select_related('user'):
		text = text.replace('@' + m.user.username, '@' + S.display_name(m.user))
	return text
