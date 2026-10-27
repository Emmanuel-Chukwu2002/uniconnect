"""Message requests, like Facebook Messenger.

When someone you don't follow sends you a private message, the chat goes
to "Message requests" (the chip after Favourites) instead of your chats:
  * no unread badge, sound or pop-up, and they can't see that you read it;
  * Accept moves it to your chats (so does replying);
  * Delete hides it — if they write again, it comes back as a request.
Group chats and chats with people you follow are never requests, and a
chat you've already written in isn't either. The sender isn't told.
Stored on ConversationParticipant.request_state.
"""
from feed.models import Follow
from .models import Conversation, ConversationParticipant as Participant, Message

PENDING = Participant.REQUEST_PENDING
ACCEPTED = Participant.REQUEST_ACCEPTED
DECLINED = Participant.REQUEST_DECLINED
HIDDEN = (PENDING, DECLINED)       # not in your chats list or counts


def follows(user_id, other_id):
	return Follow.objects.filter(follower_id=user_id, following_id=other_id, status=Follow.STATUS_ACCEPTED).exists()


def on_message(msg):
	"""After a message is saved (chat/services.py create_message)."""
	conv = msg.conversation
	if conv.kind != Conversation.DIRECT or msg.sender_id is None or msg.kind == Message.SYSTEM:
		return
	parts = list(Participant.objects.filter(conversation=conv))
	if len(parts) < 2:                # "Message yourself"
		return
	for part in parts:
		if part.user_id == msg.sender_id:
			if part.request_state in HIDDEN:          # replying accepts it
				Participant.objects.filter(pk=part.pk).update(request_state=ACCEPTED)
			continue
		if part.request_state == ACCEPTED or part.request_state == PENDING:
			continue
		if part.request_state == '':
			wrote = Message.objects.filter(conversation=conv, sender_id=part.user_id).exists()
			if wrote or follows(part.user_id, msg.sender_id):
				continue
		Participant.objects.filter(pk=part.pk).update(request_state=PENDING)   # new, or back after Delete


def is_request(part):
	return bool(part) and part.request_state == PENDING


def accept(part):
	Participant.objects.filter(pk=part.pk).update(request_state=ACCEPTED)
	part.request_state = ACCEPTED


def decline(part):
	"""Delete the request: it disappears from your requests."""
	Participant.objects.filter(pk=part.pk).update(request_state=DECLINED, is_pinned=False, marked_unread=False)
	part.request_state = DECLINED


def pending_count(user):
	return Participant.objects.filter(user=user, request_state=PENDING).count()
