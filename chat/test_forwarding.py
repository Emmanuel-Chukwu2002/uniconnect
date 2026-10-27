"""Forwarding messages (chat/forwarding.py).  Run:  python manage.py test chat.test_forwarding"""
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from . import polls
from . import services as S
from .models import ChatPoll, Message, MessageMention

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}
MEDIA = tempfile.mkdtemp()


@override_settings(CHANNEL_LAYERS=LAYERS, MEDIA_ROOT=MEDIA)
class ForwardTests(TestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(MEDIA, ignore_errors=True)

	def setUp(self):
		self.ada = User.objects.create_user('UNN-1', password='x', first_name='Ada')
		self.ben = User.objects.create_user('UNN-2', password='x', first_name='Ben')
		self.cy = User.objects.create_user('UNN-3', password='x', first_name='Cy')
		self.g1 = S.create_group(self.ada, 'COS 401', [self.ada, self.ben])
		self.g2 = S.create_group(self.ada, 'STA 341', [self.ada, self.cy])
		self.direct, _ = S.direct_conversation(self.ada, self.cy)
		self.client = Client(); self.client.force_login(self.ada)

	def fwd(self, msg, *to):
		return self.client.post(f'/messages/m/{msg.pk}/forward/', {'to': [c.pk for c in to]}, **AJAX)

	def test_forward_text_to_two_chats(self):
		m = S.create_message(self.g1, self.ben, Message.TEXT, 'Test moved to Friday, @UNN-2 please tell others')
		r = self.fwd(m, self.g2, self.direct)
		self.assertEqual(r.json()['sent'], 2)
		for conv in (self.g2, self.direct):
			copy = conv.messages.exclude(kind=Message.SYSTEM).last()
			self.assertEqual((copy.content, copy.sender, copy.forwarded), (m.content, self.ada, True))
			self.assertTrue(S.serialize_message(copy)['forwarded'])
		self.assertFalse(MessageMention.objects.filter(message__forwarded=True).exists())     # nobody tagged again

	def test_file_is_shared_not_copied_and_survives_deleting_the_original(self):
		up = SimpleUploadedFile('notes.pdf', b'%PDF-1.4 notes', content_type='application/pdf')
		m = S.create_message(self.g1, self.ben, Message.FILE, '', attachment=up)
		self.fwd(m, self.g2)
		copy = self.g2.messages.exclude(kind=Message.SYSTEM).last()
		self.assertEqual(copy.attachment.name, m.attachment.name)
		self.assertEqual(copy.attachment_name, 'notes.pdf')
		# Ben deletes his original: the forwarded copy still has the file.
		from .consumers import ChatConsumer
		consumer = ChatConsumer(); consumer.user = self.ben
		# The sync body of the consumer's delete (calling it through async_to_sync closes the
		# test's database connection on PostgreSQL).
		ChatConsumer._delete.func(consumer, m.pk)
		self.assertTrue(copy.attachment.storage.exists(copy.attachment.name))

	def test_poll_arrives_fresh_and_only_in_groups(self):
		p = polls.create(self.g1, self.ben, 'When do we meet?', ['Mon', 'Tue'])
		self.assertEqual(self.fwd(p, self.direct).status_code, 400)
		self.fwd(p, self.g2)
		copy = self.g2.messages.filter(kind=Message.POLL).get()
		self.assertTrue(copy.forwarded)
		self.assertEqual([o.text for o in ChatPoll.objects.get(message=copy).options.all()], ['Mon', 'Tue'])

	def test_limits(self):
		m = S.create_message(self.g1, self.ben, Message.TEXT, 'hi')
		self.assertEqual(self.fwd(m).status_code, 400)                       # nowhere
		other = S.create_group(self.ben, 'Not mine', [self.ben])
		self.assertEqual(self.fwd(m, other).status_code, 400)                # a chat you're not in
		sysmsg = S.create_message(self.g1, None, Message.SYSTEM, 'Ben joined')
		self.assertEqual(self.fwd(sysmsg, self.g2).status_code, 400)
		outsider = Client(); outsider.force_login(self.cy)
		self.assertEqual(outsider.post(f'/messages/m/{m.pk}/forward/', {'to': [self.g2.pk]}, **AJAX).status_code, 404)
		many = [S.create_group(self.ada, f'G{i}', [self.ada]) for i in range(6)]
		self.assertEqual(self.fwd(m, *many).status_code, 400)

	def test_target_list(self):
		r = self.client.get('/messages/forward/chats/?q=sta', **AJAX).json()
		self.assertEqual([c['title'] for c in r['chats']], ['STA 341'])
