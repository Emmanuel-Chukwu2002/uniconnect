"""Pinned messages, like WhatsApp's: up to 3 messages held in a bar at the
top of a chat, so the important ones (meeting time, assignment link) don't
get lost under new messages.

Who can pin:
    group chats   the chat's admins, and the admins of the study group the
                  chat belongs to (studygroups.StudyGroup.conversation)
    direct chats  either person
Pinning a 4th message unpins the oldest one. Deleting a pinned message
unpins it. Every change is sent to everyone in the chat ('pins' event) and
noted in the chat ("Ada pinned a message").

The bar is drawn by static/js/chat-pins.js on the group page's Chat tab
(group-chat.js) and in Messages (chat/conversation.js).
"""
from django.core.exceptions import ValidationError
from django.utils import timezone

from . import services as S
from .models import ConversationParticipant as Participant, Message

MAX_PINS = 3


def can_pin(conv, user):
	part = Participant.objects.filter(conversation=conv, user=user).first()
	if part is None:
		return False
	if not conv.is_group or part.role == Participant.ADMIN:
		return True
	try:
		group = conv.study_group
	except Exception:
		group = None
	if group is None:
		return False
	from studygroups.models import StudyGroupMember as M
	return M.objects.filter(group=group, user=user, status=M.ACTIVE, role__in=[M.OWNER, M.ADMIN]).exists()


def short_text(msg):
	if msg.kind == Message.POLL:
		text = '📊 Poll: ' + msg.content
	else:
		text = msg.content or {Message.IMAGE: '📷 Photo', Message.VIDEO: '🎥 Video', Message.AUDIO: '🎤 Voice message',
			Message.FILE: '📄 ' + (msg.attachment_name or 'Document')}.get(msg.kind, '')
	return ' '.join(text.split())[:160]


def pins(conv):
	"""The pinned messages, newest pin first."""
	msgs = (Message.objects.filter(conversation=conv, pinned_at__isnull=False, is_deleted=False)
		.select_related('sender', 'pinned_by').order_by('-pinned_at'))
	return [{
		'id': m.pk, 'name': S.display_name(m.sender) if m.sender_id else '', 'sender': m.sender_id,
		'kind': m.kind, 'text': short_text(m), 'pinned_by': S.display_name(m.pinned_by) if m.pinned_by_id else '',
	} for m in msgs]


def _note(conv, text):
	msg = S.create_message(conv, None, Message.SYSTEM, text)
	S.broadcast_message(msg)


def pin(msg, user):
	if msg.is_deleted or msg.kind == Message.SYSTEM:
		raise ValidationError("That message can't be pinned.")
	if msg.pinned_at:
		return
	msg.pinned_at, msg.pinned_by = timezone.now(), user
	msg.save(update_fields=['pinned_at', 'pinned_by'])
	extra = Message.objects.filter(conversation_id=msg.conversation_id, pinned_at__isnull=False).order_by('-pinned_at')[MAX_PINS:]
	Message.objects.filter(pk__in=[m.pk for m in extra]).update(pinned_at=None, pinned_by=None)
	_note(msg.conversation, f'{S.display_name(user)} pinned a message')


def unpin(msg, user):
	if not msg.pinned_at:
		return
	Message.objects.filter(pk=msg.pk).update(pinned_at=None, pinned_by=None)
	_note(msg.conversation, f'{S.display_name(user)} unpinned a message')


def broadcast(conv):
	S.send_to_group(S.group_conv(conv.pk), {'type': 'pins', 'conversation': conv.pk, 'pins': pins(conv)})
