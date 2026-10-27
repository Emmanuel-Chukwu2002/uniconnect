"""Tests for UniConnect Messages.  Run:  python manage.py test chat"""
from asgiref.sync import async_to_sync, sync_to_async
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from . import services as S
from .models import Call, ChatSettings, Conversation, ConversationParticipant as P, Message
from .routing import websocket_urlpatterns

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


def _friends(*users):
	from feed.models import Follow
	for u in users:
		for v in users:
			if u != v:
				Follow.objects.get_or_create(follower=u, following=v, defaults={'status': Follow.STATUS_ACCEPTED})


class ServicesTests(TestCase):
	def setUp(self):
		self.a = User.objects.create_user('ada', password='x', first_name='Ada')
		self.b = User.objects.create_user('ben', password='x', first_name='Ben')
		self.c = User.objects.create_user('cy', password='x', first_name='Cy')
		_friends(self.a, self.b, self.c)   # friends' chats are never message requests (test_requests.py)

	def test_one_direct_chat_per_pair(self):
		c1, created1 = S.direct_conversation(self.a, self.b)
		c2, created2 = S.direct_conversation(self.b, self.a)
		self.assertTrue(created1)
		self.assertFalse(created2)
		self.assertEqual(c1.pk, c2.pk)
		self.assertEqual(c1.participants.count(), 2)

	def test_unread_and_read(self):
		conv, _ = S.direct_conversation(self.a, self.b)
		S.create_message(conv, self.b, Message.TEXT, 'hi')
		S.create_message(conv, self.b, Message.TEXT, 'there')
		self.assertEqual(S.unread_chats_count(self.a), 1)
		self.assertEqual(S.unread_chats_count(self.b), 0)  # your own messages are read
		S.mark_read(self.a, conv.pk)
		self.assertEqual(S.unread_chats_count(self.a), 0)

	def test_ticks_delivered_then_read(self):
		conv, _ = S.direct_conversation(self.a, self.b)
		msg = S.create_message(conv, self.a, Message.TEXT, 'hello')
		self.assertEqual(S.message_status(msg), 'sent')
		S.mark_delivered(self.b)
		msg.refresh_from_db()
		self.assertEqual(S.message_status(msg), 'delivered')
		S.mark_read(self.b, conv.pk)
		msg.refresh_from_db()
		self.assertEqual(S.message_status(msg), 'read')

	def test_read_receipts_off_keeps_grey_ticks(self):
		ChatSettings.objects.create(user=self.b, read_receipts=False)
		conv, _ = S.direct_conversation(self.a, self.b)
		msg = S.create_message(conv, self.a, Message.TEXT, 'hello')
		S.mark_read(self.b, conv.pk)
		msg.refresh_from_db()
		self.assertEqual(S.message_status(msg), 'delivered')
		self.assertEqual(S.unread_chats_count(self.b), 0)  # still counts as read for Ben himself

	def test_group_read_needs_everyone(self):
		group = S.create_group(self.a, 'Class', [self.b, self.c])
		msg = S.create_message(group, self.a, Message.TEXT, 'test on Friday')
		S.mark_read(self.b, group.pk)
		msg.refresh_from_db()
		self.assertIsNone(msg.read_at)
		S.mark_read(self.c, group.pk)
		msg.refresh_from_db()
		self.assertIsNotNone(msg.read_at)

	def test_announcements_only_admins_post(self):
		ann = S.create_group(self.a, 'Announcements', [self.b], is_announcement=True)
		self.assertTrue(S.can_post(ann, self.a))
		self.assertFalse(S.can_post(ann, self.b))
		self.assertFalse(S.can_post(ann, self.c))  # not a member at all


class ViewTests(TestCase):
	def setUp(self):
		self.a = User.objects.create_user('ada', password='x', first_name='Ada')
		self.b = User.objects.create_user('ben', password='x', first_name='Ben')
		self.c = User.objects.create_user('cy', password='x', first_name='Cy')
		_friends(self.a, self.b, self.c)   # friends' chats are never message requests (test_requests.py)
		self.conv, _ = S.direct_conversation(self.a, self.b)
		self.client = Client()
		self.client.force_login(self.a)

	def test_login_required(self):
		self.assertEqual(Client().get('/messages/').status_code, 302)

	def test_pages_load(self):
		for url in ['/messages/', '/messages/archived/', '/messages/communities/', '/messages/calls/', '/messages/you/', f'/messages/c/{self.conv.pk}/']:
			self.assertEqual(self.client.get(url).status_code, 200, url)

	def test_non_member_gets_404(self):
		other, _ = S.direct_conversation(self.b, self.c)
		self.assertEqual(self.client.get(f'/messages/c/{other.pk}/').status_code, 404)
		self.assertEqual(self.client.get(f'/messages/c/{other.pk}/history/').status_code, 404)
		self.assertEqual(self.client.post(f'/messages/c/{other.pk}/action/', {'action': 'pin'}).status_code, 404)

	def test_messages_are_escaped(self):
		S.create_message(self.conv, self.b, Message.TEXT, '<script>alert(1)</script>')
		html = self.client.get('/messages/').content.decode()
		self.assertNotIn('<script>alert(1)</script>', html)

	def test_pin_limit(self):
		for other in [self.b] + [User.objects.create_user(f'u{i}', password='x') for i in range(3)]:
			conv, _ = S.direct_conversation(self.a, other)
			r = self.client.post(f'/messages/c/{conv.pk}/action/', {'action': 'pin'}, **AJAX)
		self.assertEqual(r.status_code, 400)
		self.assertEqual(P.objects.filter(user=self.a, is_pinned=True).count(), 3)

	def test_upload_rejects_fake_image(self):
		from django.core.files.uploadedfile import SimpleUploadedFile
		fake = SimpleUploadedFile('x.png', b'not really a png', content_type='image/png')
		r = self.client.post(f'/messages/c/{self.conv.pk}/upload/', {'file': fake}, **AJAX)
		self.assertEqual(r.status_code, 400)

	def test_start_and_group(self):
		r = self.client.post(f'/messages/start/{self.c.pk}/', **AJAX)
		self.assertEqual(r.status_code, 200)
		r = self.client.post('/messages/groups/new/', {'name': 'Study', 'members': [self.b.pk, self.c.pk]}, **AJAX)
		group = Conversation.objects.get(name='Study')
		self.assertEqual(group.participants.count(), 3)


@override_settings(CHANNEL_LAYERS=LAYERS)
class WebSocketTests(TransactionTestCase):
	def setUp(self):
		self.a = User.objects.create_user('ada', password='x', first_name='Ada')
		self.b = User.objects.create_user('ben', password='x', first_name='Ben')
		self.c = User.objects.create_user('cy', password='x', first_name='Cy')
		_friends(self.a, self.b, self.c)   # friends' chats are never message requests (test_requests.py)
		self.conv, _ = S.direct_conversation(self.a, self.b)

	def connect(self, user):
		app = URLRouter(websocket_urlpatterns)
		comm = WebsocketCommunicator(app, '/ws/chat/')
		comm.scope['user'] = user
		return comm

	async def _expect(self, comm, kind, tries=8):
		for _ in range(tries):
			data = await comm.receive_json_from(timeout=2)
			if data.get('type') == kind:
				return data
		raise AssertionError(f'no {kind} event')

	def test_anonymous_rejected(self):
		from django.contrib.auth.models import AnonymousUser

		async def run():
			comm = self.connect(AnonymousUser())
			connected, code = await comm.connect()
			self.assertFalse(connected)
		async_to_sync(run)()

	def test_message_typing_receipts_and_presence(self):
		async def run():
			ca, cb = self.connect(self.a), self.connect(self.b)
			self.assertTrue((await ca.connect())[0])
			await self._expect(ca, 'hello')
			self.assertTrue((await cb.connect())[0])
			await self._expect(cb, 'hello')
			presence = await self._expect(ca, 'presence')
			self.assertTrue(presence['online'])

			await ca.send_json_to({'type': 'typing', 'conversation': self.conv.pk, 'state': True})
			typing = await self._expect(cb, 'typing')
			self.assertEqual(typing['user'], self.a.pk)

			await ca.send_json_to({'type': 'message', 'conversation': self.conv.pk, 'content': 'Hi Ben', 'client_id': 'abc'})
			got = await self._expect(cb, 'message')
			self.assertEqual(got['message']['content'], 'Hi Ben')
			self.assertEqual(got['message']['client_id'], 'abc')
			unread = await self._expect(cb, 'unread')
			self.assertEqual(unread['unread_chats'], 1)

			await cb.send_json_to({'type': 'read', 'conversation': self.conv.pk})
			receipt = await self._expect(ca, 'receipt')
			self.assertIn('read', [status for _, status in receipt['items']])

			await cb.disconnect()
			gone = await self._expect(ca, 'presence')
			self.assertFalse(gone['online'])
			self.assertIsNotNone(gone['last_seen'])
			await ca.disconnect()
		async_to_sync(run)()
		self.assertEqual(Message.objects.filter(content='Hi Ben').count(), 1)

	def test_cannot_post_to_other_chat(self):
		other, _ = S.direct_conversation(self.b, self.c)

		async def run():
			ca = self.connect(self.a)
			await ca.connect()
			await self._expect(ca, 'hello')
			await ca.send_json_to({'type': 'message', 'conversation': other.pk, 'content': 'sneaky'})
			err = await self._expect(ca, 'error')
			self.assertIn("can't send", err['error'])
			await ca.disconnect()
		async_to_sync(run)()
		self.assertFalse(Message.objects.filter(content='sneaky').exists())

	def test_call_flow(self):
		async def run():
			ca, cb = self.connect(self.a), self.connect(self.b)
			await ca.connect(); await self._expect(ca, 'hello')
			await cb.connect(); await self._expect(cb, 'hello')
			await ca.send_json_to({'type': 'call', 'action': 'start', 'user': self.b.pk, 'kind': 'video'})
			incoming = await self._expect(cb, 'call')
			self.assertEqual(incoming['state'], 'incoming')
			await cb.send_json_to({'type': 'call', 'action': 'accept', 'call': incoming['call']['id']})
			self.assertEqual((await self._expect(ca, 'call'))['state'], 'ringing')
			self.assertEqual((await self._expect(ca, 'call'))['state'], 'connected')
			await ca.send_json_to({'type': 'call', 'action': 'end', 'call': incoming['call']['id']})
			self.assertEqual((await self._expect(cb, 'call'))['state'], 'connected')
			self.assertEqual((await self._expect(cb, 'call'))['state'], 'ended')
			await ca.disconnect(); await cb.disconnect()
		async_to_sync(run)()
		call = Call.objects.get()
		self.assertEqual((call.status, call.kind), (Call.ANSWERED, Call.VIDEO))
