"""@mentions in group chats (chat/mentions.py).  Run:  python manage.py test chat.test_mentions"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from feed.models import Notification as N

from . import services as S
from .models import ConversationParticipant as P, Message, MessageMention

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


@override_settings(CHANNEL_LAYERS=LAYERS)
class ChatMentionTests(TestCase):
	def setUp(self):
		self.ada = User.objects.create_user('UNN-1', password='x', first_name='Ada', last_name='Obi')
		self.ben = User.objects.create_user('UNN-2', password='x', first_name='Ben', last_name='Eze')
		self.cy = User.objects.create_user('UNN-3', password='x', first_name='Cy', last_name='Uba')
		self.out = User.objects.create_user('UNN-9', password='x', first_name='Out')
		self.conv = S.create_group(self.ada, 'COS 401', [self.ada, self.ben, self.cy])
		self.client = Client(); self.client.force_login(self.ben)

	def test_mention_is_saved_and_notified(self):
		msg = S.create_message(self.conv, self.ada, Message.TEXT, 'Hi @UNN-2, did you see the slides? cc @UNN-9 @UNN-1')
		# only people in the chat, never the sender
		self.assertEqual(list(MessageMention.objects.filter(message=msg).values_list('user__username', flat=True)), ['UNN-2'])
		n = N.objects.get(recipient=self.ben, type=N.CHAT_MENTION)
		self.assertEqual(n.chat_message_id, msg.pk)
		self.assertFalse(N.objects.filter(recipient=self.out).exists())
		data = S.serialize_message(msg)
		self.assertEqual(data['mentions'][0]['name'], 'Ben Eze')
		self.assertEqual(data['mentions'][0]['url'], '/u/UNN-2/')
		page = self.client.get('/notifications/').content.decode()
		self.assertIn('mentioned you in <strong>COS 401</strong>: “Hi @Ben Eze, did you see', page)
		self.assertEqual(S.preview_of(msg, self.cy, True)['text'], 'Hi @Ben Eze, did you see the slides? cc @UNN-9 @UNN-1')

	def test_notification_opens_the_chat_at_the_message(self):
		from feed.notifications import target_url
		msg = S.create_message(self.conv, self.ada, Message.TEXT, '@UNN-2 your turn')
		n = N.objects.get(recipient=self.ben, type=N.CHAT_MENTION)
		self.assertEqual(target_url(n), f'/messages/c/{self.conv.pk}/?m={msg.pk}')

	def test_no_mentions_in_direct_chats_or_system_notes(self):
		direct, _ = S.direct_conversation(self.ada, self.ben)
		S.create_message(direct, self.ada, Message.TEXT, 'hey @UNN-2')
		S.create_message(self.conv, None, Message.SYSTEM, '@UNN-2 joined')
		self.assertFalse(MessageMention.objects.exists())

	def test_muted_chat_still_pops_up_for_a_mention(self):
		P.objects.filter(conversation=self.conv, user=self.ben).update(is_muted=True)
		since = timezone.now() - timedelta(seconds=5)
		S.create_message(self.conv, self.ada, Message.TEXT, 'quiet message')
		self.assertEqual(S.new_message_popups(self.ben, since), [])
		S.create_message(self.conv, self.ada, Message.TEXT, '@UNN-2 please reply')
		pops = S.new_message_popups(self.ben, since)
		self.assertEqual(len(pops), 1)
		self.assertTrue(pops[0]['mention'])
		self.assertTrue(pops[0]['text'].startswith('@ '))

	def test_chat_list_shows_at_until_read(self):
		S.create_message(self.conv, self.ada, Message.TEXT, '@UNN-2 look')
		row = [r for r in S.chat_rows(self.ben) if r['id'] == self.conv.pk][0]
		self.assertTrue(row['mention'])
		self.assertFalse([r for r in S.chat_rows(self.cy) if r['id'] == self.conv.pk][0]['mention'])
		S.mark_read(self.ben, self.conv.pk)
		self.assertFalse([r for r in S.chat_rows(self.ben) if r['id'] == self.conv.pk][0]['mention'])

	def test_members_list_for_the_at_box(self):
		r = self.client.get(f'/messages/c/{self.conv.pk}/members/?q=a', **AJAX).json()
		self.assertEqual([p['username'] for p in r['people']], ['UNN-1'])           # Ada, not yourself
		self.assertEqual(r['people'][0]['detail'], 'Admin')
		everyone = self.client.get(f'/messages/c/{self.conv.pk}/members/', **AJAX).json()['people']
		self.assertEqual(sorted(p['username'] for p in everyone), ['UNN-1', 'UNN-3'])
		out = Client(); out.force_login(self.out)
		self.assertEqual(out.get(f'/messages/c/{self.conv.pk}/members/').status_code, 404)
