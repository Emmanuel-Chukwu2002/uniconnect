"""Pinned messages (chat/pins.py).  Run:  python manage.py test chat.test_pins"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from . import pins
from . import services as S
from .models import ConversationParticipant as P, Message

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


@override_settings(CHANNEL_LAYERS=LAYERS)
class PinTests(TestCase):
	def setUp(self):
		self.admin = User.objects.create_user('ada', password='x', first_name='Ada')
		self.ben = User.objects.create_user('ben', password='x', first_name='Ben')
		self.out = User.objects.create_user('cy', password='x', first_name='Cy')
		self.conv = S.create_group(self.admin, 'COS 401', [self.admin, self.ben])   # Ada is the chat's admin
		self.ca, self.cb, self.cout = Client(), Client(), Client()
		self.ca.force_login(self.admin); self.cb.force_login(self.ben); self.cout.force_login(self.out)

	def say(self, text, who=None):
		return S.create_message(self.conv, who or self.ben, Message.TEXT, text)

	def pin(self, client, msg, action='pin'):
		return client.post(f'/messages/m/{msg.pk}/pin/', {'action': action}, **AJAX)

	def test_admin_pins_and_everyone_sees_it(self):
		m = self.say('Assignment due Friday 5pm')
		r = self.pin(self.ca, m)
		self.assertEqual(r.status_code, 200)
		self.assertEqual(r.json()['pins'][0]['text'], 'Assignment due Friday 5pm')
		self.assertEqual(r.json()['pins'][0]['name'], 'Ben')
		# the first page of the chat brings the bar, for any member
		h = self.cb.get(f'/messages/c/{self.conv.pk}/history/').json()
		self.assertEqual([p['id'] for p in h['pins']], [m.pk])
		self.assertFalse(h['can_pin'])
		self.assertTrue([x for x in h['messages'] if x['id'] == m.pk][0]['pinned'])
		# and the chat says so
		self.assertTrue(Message.objects.filter(conversation=self.conv, kind=Message.SYSTEM, content='Ada pinned a message').exists())

	def test_members_and_outsiders_cannot_pin(self):
		m = self.say('hello')
		self.assertEqual(self.pin(self.cb, m).status_code, 403)
		self.assertEqual(self.pin(self.cout, m).status_code, 404)
		self.assertFalse(Message.objects.filter(pinned_at__isnull=False).exists())

	def test_direct_chats_either_person(self):
		conv, _ = S.direct_conversation(self.admin, self.ben)
		m = S.create_message(conv, self.admin, Message.TEXT, 'see you at 4')
		self.assertTrue(pins.can_pin(conv, self.ben))
		self.assertEqual(self.pin(self.cb, m).status_code, 200)

	def test_at_most_three_newest_first(self):
		msgs = [self.say(f'note {i}') for i in range(4)]
		for m in msgs:
			self.pin(self.ca, m)
		self.assertEqual([p['text'] for p in pins.pins(self.conv)], ['note 3', 'note 2', 'note 1'])

	def test_unpin_and_deleted_messages_leave(self):
		a, b = self.say('one'), self.say('two')
		self.pin(self.ca, a); self.pin(self.ca, b)
		self.pin(self.ca, a, 'unpin')
		self.assertEqual([p['id'] for p in pins.pins(self.conv)], [b.pk])
		Message.objects.filter(pk=b.pk).update(is_deleted=True)
		self.assertEqual(pins.pins(self.conv), [])

	def test_system_messages_cannot_be_pinned(self):
		sysmsg = S.create_message(self.conv, None, Message.SYSTEM, 'Ben joined')
		self.assertEqual(self.pin(self.ca, sysmsg).status_code, 400)

	def test_study_group_admins_can_pin(self):
		from accounts.models import University
		from studygroups.models import StudyGroup, StudyGroupMember as M
		uni = University.objects.first() or University.objects.create(name='University of Nigeria')
		g = StudyGroup.objects.create(name='COS 401', university=uni, created_by=self.admin, conversation=self.conv)
		M.objects.create(group=g, user=self.ben, role=M.ADMIN)
		self.assertTrue(pins.can_pin(self.conv, self.ben))
		P.objects.filter(conversation=self.conv, user=self.ben).update(role=P.MEMBER)
		self.assertTrue(pins.can_pin(self.conv, self.ben))
