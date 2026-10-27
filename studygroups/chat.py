"""Keeps each group's chat in Messages in step with its members.
Uses the chat app's own services, so the chat behaves like any group chat
(live updates, unread badges). If something goes wrong with the chat, the
group itself still works; the error is logged."""
import logging

from chat import services as S
from chat.models import ConversationParticipant as Participant, Message

log = logging.getLogger(__name__)


def _say(conv, text):
	msg = S.create_message(conv, None, Message.SYSTEM, text)
	S.broadcast_message(msg)


def create_chat(group):
	try:
		conv = S.create_group(group.created_by, group.title[:80], [group.created_by],
			description=f'Group chat for {group.title}.'[:300])
		group.conversation = conv
		group.save(update_fields=['conversation'])
		S.announce_new_conversation(conv)
	except Exception:
		log.exception('Could not create the chat for group %s', group.pk)


def add_member(group, user):
	conv = group.conversation
	if conv is None:
		return
	try:
		_, created = Participant.objects.get_or_create(conversation=conv, user=user)
		if created:
			_say(conv, f'{S.display_name(user)} joined the group')
			S.announce_new_conversation(conv)
	except Exception:
		log.exception('Could not add %s to the chat of group %s', user.pk, group.pk)


def remove_member(group, user, removed=False):
	conv = group.conversation
	if conv is None:
		return
	try:
		if Participant.objects.filter(conversation=conv, user=user).delete()[0]:
			_say(conv, f'{S.display_name(user)} {"was removed from" if removed else "left"} the group')
	except Exception:
		log.exception('Could not remove %s from the chat of group %s', user.pk, group.pk)


def rename(group):
	if group.conversation_id:
		type(group.conversation).objects.filter(pk=group.conversation_id).update(name=group.title[:80])
