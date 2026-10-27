"""Message requests, like Messenger (chat/requests.py).
Run: python manage.py test chat.test_requests"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from feed.models import Follow
from . import services as S
from .models import ConversationParticipant as P, Message

User = get_user_model()


class MessageRequestTests(TestCase):
	def setUp(self):
		self.me = User.objects.create_user('ada', password='x', first_name='Ada')
		self.stranger = User.objects.create_user('ben', password='x', first_name='Ben')
		self.friend = User.objects.create_user('cy', password='x', first_name='Cy')
		Follow.objects.create(follower=self.me, following=self.friend, status=Follow.STATUS_ACCEPTED)
		self.client.force_login(self.me)

	def send(self, sender, to, text='Hi'):
		conv, _ = S.direct_conversation(sender, to)
		S.create_message(conv, sender, Message.TEXT, text)
		return conv

	def part(self, conv, user):
		return P.objects.get(conversation=conv, user=user)

	def test_stranger_message_is_a_request(self):
		conv = self.send(self.stranger, self.me)
		self.assertEqual(self.part(conv, self.me).request_state, P.REQUEST_PENDING)
		self.assertEqual(self.part(conv, self.stranger).request_state, '')            # the sender's chat is normal
		self.assertEqual(S.unread_chats_count(self.me), 0)                               # no badge
		self.assertEqual(S.new_message_popups(self.me, timezone.now() - timedelta(minutes=5)), [])   # no pop-up
		row = next(r for r in S.chat_rows(self.me) if r['id'] == conv.pk)
		self.assertTrue(row['request'])
		html = self.client.get('/messages/').content.decode()
		self.assertIn('data-filter="requests">Message requests <span class="wa-chip-count js-wa-requests-chip">1</span>', html)
		self.assertIn('data-request="1"', html)
		html = self.client.get(f'/messages/c/{conv.pk}/').content.decode()
		self.assertIn('Ben wants to send you a message', html)
		self.assertIn('data-filter="requests">', html)

	def test_people_you_follow_and_groups_are_not_requests(self):
		conv = self.send(self.friend, self.me)
		self.assertEqual(self.part(conv, self.me).request_state, '')
		self.assertEqual(S.unread_chats_count(self.me), 1)
		group = S.create_group(self.stranger, 'Study', [self.me])
		S.create_message(group, self.stranger, Message.TEXT, 'hello all')
		self.assertEqual(self.part(group, self.me).request_state, '')

	def test_no_read_receipt_until_accepted(self):
		conv = self.send(self.stranger, self.me)
		S.mark_read(self.me, conv.pk)
		me = self.part(conv, self.me)
		self.assertIsNotNone(me.last_read_at)
		self.assertIsNone(me.last_read_receipt_at)                                       # Ben can't see it was read

	def test_accept_moves_it_to_chats(self):
		conv = self.send(self.stranger, self.me)
		r = self.client.post(f'/messages/c/{conv.pk}/action/', {'action': 'accept_request'})
		self.assertEqual(r.json()['requests'], 0)
		self.assertEqual(self.part(conv, self.me).request_state, P.REQUEST_ACCEPTED)
		self.assertIsNotNone(self.part(conv, self.me).last_read_receipt_at)
		S.create_message(conv, self.stranger, Message.TEXT, 'Thanks')
		self.assertEqual(self.part(conv, self.me).request_state, P.REQUEST_ACCEPTED)  # stays accepted
		self.assertEqual(S.unread_chats_count(self.me), 1)

	def test_replying_accepts(self):
		conv = self.send(self.stranger, self.me)
		S.create_message(conv, self.me, Message.TEXT, 'Hello Ben')
		self.assertEqual(self.part(conv, self.me).request_state, P.REQUEST_ACCEPTED)

	def test_delete_hides_until_they_write_again(self):
		conv = self.send(self.stranger, self.me)
		self.client.post(f'/messages/c/{conv.pk}/action/', {'action': 'decline_request'})
		self.assertFalse(any(r['id'] == conv.pk for r in S.chat_rows(self.me)))
		self.assertEqual(self.client.post(f'/messages/c/{conv.pk}/action/', {'action': 'accept_request'}).status_code, 400)
		S.create_message(conv, self.stranger, Message.TEXT, 'Please reply')
		self.assertEqual(self.part(conv, self.me).request_state, P.REQUEST_PENDING)      # back as a request

	def test_chat_you_already_wrote_in_is_not_a_request(self):
		conv, _ = S.direct_conversation(self.me, self.stranger)
		S.create_message(conv, self.me, Message.TEXT, 'Hi Ben')
		S.create_message(conv, self.stranger, Message.TEXT, 'Hi Ada')
		self.assertEqual(self.part(conv, self.me).request_state, '')

	def test_requests_are_not_forward_targets(self):
		conv = self.send(self.stranger, self.me)
		from .forwarding import targets
		self.assertNotIn(conv.pk, [t['id'] for t in targets(self.me)])
