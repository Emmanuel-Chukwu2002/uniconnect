"""Forwarding a chat message to other chats, like WhatsApp.

"Forward" on a message (group page Chat tab, or Messages) opens a list of
your chats (static/js/chat-forward.js); pick up to 5 and send. Each gets a
copy from you marked "Forwarded":
  * text and captions as they are (an @mention doesn't tag anyone again);
  * photos, videos, documents and voice messages share the same stored
    file — nothing is uploaded twice (deleting the original keeps the file
    while a forwarded copy still uses it: chat/consumers.py _delete);
  * a poll arrives as a new poll with the same question and options, with
    no votes yet.
You can only forward from a chat you're in, to chats you can post in.
Deleted messages and system notes can't be forwarded.
"""
from django.core.exceptions import ValidationError

from . import services as S
from .models import Conversation, ConversationParticipant as Participant, Message

MAX_TARGETS = 5


def targets(user, q=''):
	"""Your chats you can post in, for the "Forward to…" list (most recent first)."""
	rows = []
	for r in S.chat_rows(user):
		if r.get('request'):
			continue                      # message requests (chat/requests.py)
		rows.append({'id': r['id'], 'title': r['title'], 'photo': r['photo'], 'initials': r['initials'],
			'colour': r['colour'], 'is_group': r['is_group'], 'is_announcement': r.get('is_announcement', False),
			'community': r.get('community', '')})
	q = (q or '').strip().lower()
	if q:
		rows = [r for r in rows if q in r['title'].lower() or q in r['community'].lower()]
	ok = {c.pk for c in Conversation.objects.filter(pk__in=[r['id'] for r in rows]) if S.can_post(c, user)}
	return [r for r in rows if r['id'] in ok][:40]


def forward(msg, user, conversation_ids):
	"""Copies `msg` into each chat; returns the new messages."""
	if msg.is_deleted or msg.kind == Message.SYSTEM:
		raise ValidationError("This message can't be forwarded.")
	if not Participant.objects.filter(conversation_id=msg.conversation_id, user=user).exists():
		raise ValidationError("You can't forward that message.")
	ids = []
	for v in conversation_ids:
		if str(v).isdigit() and int(v) not in ids:
			ids.append(int(v))
	if not ids:
		raise ValidationError('Choose a chat to forward it to.')
	if len(ids) > MAX_TARGETS:
		raise ValidationError(f'You can forward to up to {MAX_TARGETS} chats at a time.')
	convs = list(Conversation.objects.filter(pk__in=ids, participants__user=user))
	if len(convs) != len(ids) or not all(S.can_post(c, user) for c in convs):
		raise ValidationError("You can't send messages to one of those chats.")
	if msg.kind == Message.POLL and not all(c.is_group for c in convs):
		raise ValidationError('Polls can only be forwarded to group chats.')
	made = []
	for conv in convs:
		if msg.kind == Message.POLL:
			made.append(_forward_poll(msg, user, conv))
			continue
		new = S.create_message(conv, user, msg.kind, msg.content, duration=msg.duration, forwarded=True)
		if msg.attachment:
			Message.objects.filter(pk=new.pk).update(attachment=msg.attachment.name, attachment_name=msg.attachment_name,
				attachment_size=msg.attachment_size)
		made.append(new)
	return made


def _forward_poll(msg, user, conv):
	from . import polls
	from .models import ChatPoll
	poll = ChatPoll.objects.prefetch_related('options').get(message=msg)
	new = polls.create(conv, user, poll.question, [o.text for o in poll.options.all()], multiple=poll.allow_multiple)
	Message.objects.filter(pk=new.pk).update(forwarded=True)
	return new


def broadcast(made):
	for m in made:
		m = Message.objects.select_related('sender__student_profile', 'reply_to__sender').get(pk=m.pk)
		S.broadcast_message(m)
