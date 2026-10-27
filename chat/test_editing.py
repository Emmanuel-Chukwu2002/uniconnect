"""Editing a sent message (chat/editing.py).  Run:  python manage.py test chat.test_editing"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from feed.models import Notification as N

from . import pins
from . import services as S
from .models import Message, MessageMention

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


@override_settings(CHANNEL_LAYERS=LAYERS)
class EditMessageTests(TestCase):
	def setUp(self):
		self.ada = User.objects.create_user('UNN-1', password='x', first_name='Ada')
		self.ben = User.objects.create_user('UNN-2', password='x', first_name='Ben')
		self.cy = User.objects.create_user('UNN-3', password='x', first_name='Cy')
		self.conv = S.create_group(self.ada, 'COS 401', [self.ada, self.ben, self.cy])
		self.ca, self.cb = Client(), Client()
		self.ca.force_login(self.ada); self.cb.force_login(self.ben)

	def edit(self, client, msg, text):
		return client.post(f'/messages/m/{msg.pk}/edit/', {'content': text}, **AJAX)

	def test_fix_a_typo(self):
		m = S.create_message(self.conv, self.ada, Message.TEXT, 'Meeting at 4pn')
		r = self.edit(self.ca, m, 'Meeting at 4pm')
		self.assertEqual(r.status_code, 200)
		self.assertTrue(r.json()['message']['edited'])
		m.refresh_from_db()
		self.assertEqual(m.content, 'Meeting at 4pm')
		self.assertIsNotNone(m.edited_at)
		hist, _ = S.history(self.conv)
		self.assertTrue([x for x in hist if x['id'] == m.pk][0]['edited'])

	def test_only_your_own_within_15_minutes(self):
		m = S.create_message(self.conv, self.ada, Message.TEXT, 'hello')
		self.assertEqual(self.edit(self.cb, m, 'hacked').status_code, 400)
		Message.objects.filter(pk=m.pk).update(created_at=timezone.now() - timedelta(minutes=16))
		r = self.edit(self.ca, m, 'too late')
		self.assertEqual(r.status_code, 400)
		self.assertIn('15 minutes', r.json()['error'])
		self.assertEqual(Message.objects.get(pk=m.pk).content, 'hello')

	def test_what_cannot_be_edited(self):
		m = S.create_message(self.conv, self.ada, Message.TEXT, 'hi')
		self.assertEqual(self.edit(self.ca, m, '   ').status_code, 400)          # empty
		Message.objects.filter(pk=m.pk).update(is_deleted=True)
		self.assertEqual(self.edit(self.ca, m, 'back').status_code, 400)
		from . import polls
		p = polls.create(self.conv, self.ada, 'Q?', ['a', 'b'])
		self.assertEqual(self.edit(self.ca, p, 'changed').status_code, 400)
		out = Client(); out.force_login(User.objects.create_user('UNN-9', password='x'))
		self.assertEqual(self.edit(out, m, 'x').status_code, 404)

	def test_unchanged_text_is_not_marked_edited(self):
		m = S.create_message(self.conv, self.ada, Message.TEXT, 'same')
		self.edit(self.ca, m, 'same')
		self.assertIsNone(Message.objects.get(pk=m.pk).edited_at)

	def test_mentions_follow_the_new_text(self):
		m = S.create_message(self.conv, self.ada, Message.TEXT, 'hi @UNN-2')
		self.assertEqual(N.objects.filter(recipient=self.ben, type=N.CHAT_MENTION).count(), 1)
		self.edit(self.ca, m, 'hi @UNN-2 and @UNN-3')
		self.assertEqual(sorted(MessageMention.objects.filter(message=m).values_list('user__username', flat=True)), ['UNN-2', 'UNN-3'])
		self.assertEqual(N.objects.filter(recipient=self.ben, type=N.CHAT_MENTION).count(), 1)    # not told twice
		self.assertEqual(N.objects.filter(recipient=self.cy, type=N.CHAT_MENTION).count(), 1)
		self.edit(self.ca, m, 'hi everyone')
		self.assertFalse(MessageMention.objects.filter(message=m).exists())

	def test_pinned_bar_shows_the_new_words(self):
		m = S.create_message(self.conv, self.ada, Message.TEXT, 'Exam on Mondy')
		pins.pin(m, self.ada)
		self.edit(self.ca, m, 'Exam on Monday')
		self.assertEqual(pins.pins(self.conv)[0]['text'], 'Exam on Monday')
