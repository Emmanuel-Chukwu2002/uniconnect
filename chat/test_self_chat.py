"""Message yourself, like WhatsApp: your own chat is always in the list.
Run: python manage.py test chat.test_self_chat"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from . import services as S
from .models import Conversation, Message

User = get_user_model()


class SelfChatTests(TestCase):
	def setUp(self):
		self.me = User.objects.create_user('ada', password='x', first_name='Ada', last_name='Obi')
		self.client.force_login(self.me)

	def test_own_chat_always_listed(self):
		html = self.client.get('/messages/').content.decode()
		conv = Conversation.objects.get(direct_key=f'{self.me.pk}:{self.me.pk}')
		self.assertEqual(conv.participants.count(), 1)
		self.assertIn('Ada Obi (You)', html)
		self.assertIn('Message yourself', html)
		self.client.get('/messages/')
		self.assertEqual(Conversation.objects.filter(direct_key=f'{self.me.pk}:{self.me.pk}').count(), 1)   # only one

	def test_note_to_self_is_read_at_once(self):
		conv, _ = S.direct_conversation(self.me, self.me)
		S.create_message(conv, self.me, Message.TEXT, 'Buy the F-table')
		row = next(r for r in S.chat_rows(self.me) if r['id'] == conv.pk)
		self.assertTrue(row['is_self'])
		self.assertEqual(row['preview']['text'], 'Buy the F-table')
		self.assertEqual(row['unread'], 0)
