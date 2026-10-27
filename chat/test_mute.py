"""Muting a chat for 8 hours / 1 week / always.  Run:  python manage.py test chat.test_mute"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from . import services as S
from .models import ConversationParticipant as P, Message

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


@override_settings(CHANNEL_LAYERS=LAYERS)
class MuteForTests(TestCase):
	def setUp(self):
		self.a = User.objects.create_user('ada', password='x', first_name='Ada')
		self.b = User.objects.create_user('ben', password='x', first_name='Ben')
		self.conv = S.create_group(self.b, 'Study', [self.a, self.b])
		self.client = Client(); self.client.force_login(self.a)
		self.url = f'/messages/c/{self.conv.pk}/action/'

	def part(self):
		return P.objects.get(conversation=self.conv, user=self.a)

	def test_mute_for_8_hours_and_a_week(self):
		r = self.client.post(self.url, {'action': 'mute', 'for': '8h'}, **AJAX).json()
		p = self.part()
		self.assertTrue(p.is_muted)
		self.assertAlmostEqual((p.muted_until - timezone.now()).total_seconds(), 8 * 3600, delta=60)
		self.assertTrue(r['muted_until'])
		self.client.post(self.url, {'action': 'mute', 'for': '1w'}, **AJAX)
		self.assertAlmostEqual((self.part().muted_until - timezone.now()).days, 6, delta=1)

	def test_always_and_old_callers(self):
		self.client.post(self.url, {'action': 'mute', 'for': 'always'}, **AJAX)
		self.assertTrue(self.part().is_muted)
		self.assertIsNone(self.part().muted_until)
		self.client.post(self.url, {'action': 'unmute'}, **AJAX)
		self.client.post(self.url, {'action': 'mute'}, **AJAX)          # no length: until you unmute
		self.assertTrue(self.part().is_muted)
		self.assertIsNone(self.part().muted_until)

	def test_bad_length(self):
		self.assertEqual(self.client.post(self.url, {'action': 'mute', 'for': '3 years'}, **AJAX).status_code, 400)
		self.assertFalse(self.part().is_muted)

	def test_unmute_clears_the_time(self):
		self.client.post(self.url, {'action': 'mute', 'for': '8h'}, **AJAX)
		self.client.post(self.url, {'action': 'unmute'}, **AJAX)
		p = self.part()
		self.assertFalse(p.is_muted)
		self.assertIsNone(p.muted_until)

	def test_muted_chat_is_quiet_then_comes_back_on_time(self):
		self.client.post(self.url, {'action': 'mute', 'for': '8h'}, **AJAX)
		since = timezone.now() - timedelta(seconds=5)
		S.create_message(self.conv, self.b, Message.TEXT, 'Meeting moved to 4pm')
		self.assertEqual(S.unread_chats_count(self.a), 0)
		self.assertEqual(S.new_message_popups(self.a, since), [])
		# ...eight hours later
		P.objects.filter(conversation=self.conv, user=self.a).update(muted_until=timezone.now() - timedelta(minutes=1))
		self.assertEqual(S.unread_chats_count(self.a), 1)
		self.assertFalse(self.part().is_muted)
		self.assertEqual(len(S.new_message_popups(self.a, since)), 1)

	def test_chat_list_row_knows_when(self):
		self.client.post(self.url, {'action': 'mute', 'for': '8h'}, **AJAX)
		row = [r for r in S.chat_rows(self.a) if r['id'] == self.conv.pk][0]
		self.assertTrue(row['muted'])
		self.assertIsNotNone(row['muted_until'])
		html = self.client.get('/messages/').content.decode()
		self.assertIn('data-muted-until=', html)
		self.assertIn('Muted until', html)
