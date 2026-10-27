"""Editing a sent chat message, like WhatsApp: your own text (or a photo,
video or document's caption), within 15 minutes of sending it. Everyone in
the chat sees the new words straight away (event 'edited') with "edited"
beside the time. Polls, voice messages, deleted messages and system notes
can't be edited.

@mentions are worked out again from the new text; only people newly
mentioned get a notification. A pinned message's text in the pinned bar
updates too.
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from . import services as S
from .models import Message, MessageMention

EDIT_WINDOW = timedelta(minutes=15)
EDITABLE = (Message.TEXT, Message.IMAGE, Message.VIDEO, Message.FILE)


def can_edit(msg, user):
	return (msg.sender_id == user.pk and not msg.is_deleted and msg.kind in EDITABLE
		and timezone.now() - msg.created_at <= EDIT_WINDOW)


def edit(msg, user, text):
	if msg.sender_id != user.pk:
		raise ValidationError('You can only edit your own messages.')
	if msg.is_deleted or msg.kind not in EDITABLE:
		raise ValidationError("This message can't be edited.")
	if timezone.now() - msg.created_at > EDIT_WINDOW:
		raise ValidationError('Messages can only be edited for 15 minutes after sending.')
	text = (text or '').strip()
	if not text and msg.kind == Message.TEXT:
		raise ValidationError("A message can't be empty — delete it instead.")
	if len(text) > Message.MAX_LENGTH:
		raise ValidationError(f'Messages can be up to {Message.MAX_LENGTH} characters.')
	if text == msg.content:
		return msg
	before = set(msg.mentions.values_list('user_id', flat=True))
	msg.content, msg.edited_at = text, timezone.now()
	msg.save(update_fields=['content', 'edited_at', 'updated_at'])
	MessageMention.objects.filter(message=msg).delete()
	if '@' in text:
		from .mentions import record
		record(msg, already=before)
	return msg


def broadcast(msg):
	msg = Message.objects.select_related('sender__student_profile', 'reply_to__sender').get(pk=msg.pk)
	S.send_to_group(S.group_conv(msg.conversation_id), {'type': 'edited', 'conversation': msg.conversation_id,
		'message': S.serialize_message(msg)})
	if msg.pinned_at:
		from . import pins
		pins.broadcast(msg.conversation)
