"""Polls in group chats (chat/polls.py).  Run:  python manage.py test chat.test_polls"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from . import services as S
from .models import ChatPoll, ChatPollVote, Message

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


@override_settings(CHANNEL_LAYERS=LAYERS)
class ChatPollTests(TestCase):
	def setUp(self):
		self.a = User.objects.create_user('ada', password='x', first_name='Ada')
		self.b = User.objects.create_user('ben', password='x', first_name='Ben')
		self.out = User.objects.create_user('cy', password='x', first_name='Cy')
		self.conv = S.create_group(self.a, 'COS 401', [self.a, self.b])
		self.ca, self.cb, self.cout = Client(), Client(), Client()
		self.ca.force_login(self.a); self.cb.force_login(self.b); self.cout.force_login(self.out)

	def make(self, multiple=False, options=('Monday', 'Tuesday', 'Friday')):
		r = self.ca.post(f'/messages/c/{self.conv.pk}/poll/', {'question': 'When do we meet?', 'option': list(options),
			'multiple': '1' if multiple else ''}, **AJAX)
		self.assertEqual(r.status_code, 200, r.content)
		return r.json()['message']

	def test_create_shows_as_a_poll_message(self):
		m = self.make()
		self.assertEqual(m['kind'], 'poll')
		self.assertEqual([o['text'] for o in m['poll']['options']], ['Monday', 'Tuesday', 'Friday'])
		self.assertFalse(m['poll']['multiple'])
		self.assertEqual(m['poll']['voters'], 0)
		msg = Message.objects.get(pk=m['id'])
		self.assertEqual(S.preview_of(msg, self.b, True)['text'], 'Poll: When do we meet?')
		# and in the chat's history
		hist, _ = S.history(self.conv)
		self.assertEqual(hist[-1]['poll']['question'], 'When do we meet?')

	def test_bad_polls_are_refused(self):
		url = f'/messages/c/{self.conv.pk}/poll/'
		self.assertEqual(self.ca.post(url, {'question': '', 'option': ['a', 'b']}, **AJAX).status_code, 400)
		self.assertEqual(self.ca.post(url, {'question': 'Q', 'option': ['only one', '']}, **AJAX).status_code, 400)
		r = self.ca.post(url, {'question': 'Q', 'option': ['Yes', 'yes']}, **AJAX)
		self.assertIn('twice', r.json()['error'])
		self.assertEqual(self.ca.post(url, {'question': 'Q', 'option': [str(i) for i in range(13)]}, **AJAX).status_code, 400)
		# not in the chat
		self.assertEqual(self.cout.post(url, {'question': 'Q', 'option': ['a', 'b']}, **AJAX).status_code, 404)
		# direct chats don't have polls
		direct, _ = S.direct_conversation(self.a, self.b)
		self.assertEqual(self.ca.post(f'/messages/c/{direct.pk}/poll/', {'question': 'Q', 'option': ['a', 'b']}, **AJAX).status_code, 400)
		self.assertFalse(ChatPoll.objects.exists())

	def test_single_choice_vote_moves(self):
		m = self.make()
		mon, tue = m['poll']['options'][0]['id'], m['poll']['options'][1]['id']
		url = f'/messages/poll/{m["id"]}/vote/'
		p = self.cb.post(url, {'option': [mon]}, **AJAX).json()['poll']
		self.assertEqual([len(o['votes']) for o in p['options']], [1, 0, 0])
		p = self.cb.post(url, {'option': [tue]}, **AJAX).json()['poll']
		self.assertEqual([len(o['votes']) for o in p['options']], [0, 1, 0])
		self.assertEqual(p['voters'], 1)
		self.assertEqual(p['options'][1]['votes'][0]['name'], 'Ben')
		# two answers in a one-answer poll
		self.assertEqual(self.cb.post(url, {'option': [mon, tue]}, **AJAX).status_code, 400)
		# taking the vote back
		p = self.cb.post(url, {}, **AJAX).json()['poll']
		self.assertEqual(p['voters'], 0)
		# outsiders can't vote
		self.assertEqual(self.cout.post(url, {'option': [mon]}, **AJAX).status_code, 404)

	def test_multiple_answers(self):
		m = self.make(multiple=True)
		ids = [o['id'] for o in m['poll']['options']]
		url = f'/messages/poll/{m["id"]}/vote/'
		self.cb.post(url, {'option': ids[:2]}, **AJAX)
		p = self.ca.post(url, {'option': [ids[1]]}, **AJAX).json()['poll']
		self.assertEqual([len(o['votes']) for o in p['options']], [1, 2, 0])
		self.assertEqual(p['voters'], 2)

	def test_end_poll(self):
		m = self.make()
		mon = m['poll']['options'][0]['id']
		self.assertEqual(self.cb.post(f'/messages/poll/{m["id"]}/close/', **AJAX).status_code, 403)   # not hers
		p = self.ca.post(f'/messages/poll/{m["id"]}/close/', **AJAX).json()['poll']
		self.assertTrue(p['closed'])
		r = self.cb.post(f'/messages/poll/{m["id"]}/vote/', {'option': [mon]}, **AJAX)
		self.assertEqual(r.status_code, 400)
		self.assertFalse(ChatPollVote.objects.exists())

	def test_reply_to_a_poll_quotes_it(self):
		m = self.make()
		reply = S.create_message(self.conv, self.b, Message.TEXT, 'Friday works', reply_to=Message.objects.get(pk=m['id']))
		data = S.serialize_message(reply)
		self.assertEqual(data['reply_to']['text'], '📊 Poll: When do we meet?')
