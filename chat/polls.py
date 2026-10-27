"""Polls in group chats, like WhatsApp's.

Making one: "Poll" in the chat's + / attach menu (static/js/chat-polls.js)
sends the question and 2-12 options to /messages/c/<id>/poll/. It arrives
as a message of kind 'poll' with its ChatPoll; everyone sees it live.

Voting: tapping an option. A single-choice poll moves your vote; with
"more than one answer" each tap adds or removes that option. Every vote
is sent to everyone in the chat straight away (event 'poll'), so the bars
and counts move on their own. Votes are not anonymous — "View votes"
lists who chose what, as on WhatsApp.

Closing: whoever made the poll (or a chat admin) can end it; after that
the results stay but nobody can vote.

Polls are for group chats only.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import services as S
from .models import ChatPoll, ChatPollOption, ChatPollVote, ConversationParticipant as Participant, Message

MAX_QUESTION = 200
MAX_OPTION = 100


def clean(question, options):
	"""(question, options) tidied, or ValidationError saying what's wrong."""
	question = ' '.join((question or '').split())
	if not question:
		raise ValidationError('Write the question.')
	if len(question) > MAX_QUESTION:
		raise ValidationError(f'The question can be up to {MAX_QUESTION} characters.')
	seen, kept = set(), []
	for o in options or []:
		o = ' '.join((o or '').split())
		if not o:
			continue
		if len(o) > MAX_OPTION:
			raise ValidationError(f'Each option can be up to {MAX_OPTION} characters.')
		if o.lower() in seen:
			raise ValidationError(f'“{o}” is in the list twice.')
		seen.add(o.lower())
		kept.append(o)
	if len(kept) < 2:
		raise ValidationError('Add at least two options.')
	if len(kept) > ChatPoll.MAX_OPTIONS:
		raise ValidationError(f'A poll can have up to {ChatPoll.MAX_OPTIONS} options.')
	return question, kept


def create(conv, user, question, options, multiple=False, reply_to=None):
	question, options = clean(question, options)
	if not conv.is_group:
		raise ValidationError('Polls are for group chats.')
	with transaction.atomic():
		msg = S.create_message(conv, user, Message.POLL, question, reply_to=reply_to)
		poll = ChatPoll.objects.create(message=msg, question=question, allow_multiple=bool(multiple))
		ChatPollOption.objects.bulk_create([ChatPollOption(poll=poll, text=t, order=i) for i, t in enumerate(options)])
	return msg


def data(poll):
	"""What the chat draws: the options with who voted for each."""
	options = []
	voters = set()
	for o in poll.options.all():
		votes = [v for v in o.votes.all()]
		voters.update(v.user_id for v in votes)
		options.append({'id': o.pk, 'text': o.text,
			'votes': [{'id': v.user_id, 'name': S.display_name(v.user)} for v in votes]})
	return {
		'id': poll.pk, 'question': poll.question, 'multiple': poll.allow_multiple,
		'closed': poll.closed_at is not None, 'by': poll.message.sender_id,
		'options': options, 'voters': len(voters),
	}


def for_message(msg):
	try:
		poll = msg.poll
	except ChatPoll.DoesNotExist:
		return None
	poll = ChatPoll.objects.prefetch_related('options__votes__user').select_related('message').get(pk=poll.pk)
	return data(poll)


def poll_for(user, message_id):
	"""The poll in message `message_id`, if `user` is in that chat (else None)."""
	poll = ChatPoll.objects.select_related('message__conversation').filter(message_id=message_id).first()
	if not poll or not Participant.objects.filter(conversation=poll.message.conversation, user=user).exists():
		return None
	return poll


def vote(poll, user, option_ids):
	"""Sets `user`'s answer to exactly `option_ids` (empty: takes their vote back)."""
	if poll.closed_at:
		raise ValidationError('This poll has ended.')
	if poll.message.is_deleted:
		raise ValidationError('This poll was deleted.')
	wanted = set()
	valid = set(poll.options.values_list('pk', flat=True))
	for v in option_ids:
		if str(v).isdigit() and int(v) in valid:
			wanted.add(int(v))
	if not poll.allow_multiple and len(wanted) > 1:
		raise ValidationError('Choose one answer.')
	with transaction.atomic():
		ChatPollVote.objects.filter(option__poll=poll, user=user).exclude(option_id__in=wanted).delete()
		have = set(ChatPollVote.objects.filter(option__poll=poll, user=user).values_list('option_id', flat=True))
		ChatPollVote.objects.bulk_create([ChatPollVote(option_id=o, user=user) for o in wanted - have])


def can_close(poll, user):
	if poll.message.sender_id == user.pk:
		return True
	return Participant.objects.filter(conversation_id=poll.message.conversation_id, user=user, role=Participant.ADMIN).exists()


def close(poll, user):
	if not can_close(poll, user):
		raise ValidationError('Only the person who made the poll can end it.')
	if not poll.closed_at:
		poll.closed_at = timezone.now()
		poll.save(update_fields=['closed_at'])


def broadcast(poll):
	"""Everyone in the chat gets the new counts."""
	S.send_to_group(S.group_conv(poll.message.conversation_id), {
		'type': 'poll', 'conversation': poll.message.conversation_id, 'message': poll.message_id,
		'poll': for_message(poll.message),
	})
