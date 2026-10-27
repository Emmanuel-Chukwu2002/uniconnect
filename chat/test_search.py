"""Search in Messages (run: python manage.py test chat.test_search)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from . import services as S
from .models import Message

User = get_user_model()


class ChatSearchTests(TestCase):
	def setUp(self):
		self.a = User.objects.create_user('ada', password='x', first_name='Ada', last_name='Obi')
		self.b = User.objects.create_user('ben', password='x', first_name='Ben', last_name='Eze')
		self.c = User.objects.create_user('cy', password='x', first_name='Cynthia', last_name='Okafor')
		self.d = User.objects.create_user('dan', password='x', first_name='Daniel', last_name='Bello')
		self.chat, _ = S.direct_conversation(self.a, self.b)
		self.hit = S.create_message(self.chat, self.b, Message.TEXT, 'The project <defence> is on Friday at 10am')
		S.create_message(self.chat, self.a, Message.TEXT, 'Nothing to see')
		gone = S.create_message(self.chat, self.b, Message.TEXT, 'defence secret deleted')
		gone.is_deleted = True
		gone.save()
		other, _ = S.direct_conversation(self.c, self.d)          # not my chat
		S.create_message(other, self.c, Message.TEXT, 'defence plans for others')
		self.client.force_login(self.a)

	def search(self, q):
		return self.client.get('/messages/search/', {'q': q}).json()

	def test_messages_found_only_in_my_chats_with_highlight(self):
		res = self.search('defence')
		html = res['html']
		self.assertIn('Messages', html)
		self.assertIn(f'?m={self.hit.pk}', html)
		self.assertIn('<mark>defence</mark>', html)
		self.assertIn('&lt;', html)                          # message text is escaped
		self.assertNotIn('secret deleted', html)             # deleted messages hidden
		self.assertNotIn('for others', html)                 # someone else's chat
		self.assertEqual(res['count'], 1)

	def test_only_people_already_chatted_with(self):
		res = self.search('cynthia')                                   # never chatted: not offered
		self.assertEqual(res['count'], 0)
		self.assertNotIn('Cynthia', res['html'])
		self.assertEqual(self.search('ben')['count'], 0)              # in the list: the list filter shows it
		from .models import ConversationParticipant
		ConversationParticipant.objects.filter(conversation=self.chat, user=self.a).update(is_archived=True)
		res = self.search('ben')                                       # archived: found here
		self.assertIn('Archived chats', res['html'])
		self.assertIn(f'/messages/c/{self.chat.pk}/', res['html'])
		self.assertEqual(res['count'], 1)

	def test_empty_query_and_page_markup(self):
		self.assertEqual(self.search('   '), {'html': '', 'count': 0})
		html = self.client.get('/messages/').content.decode()
		self.assertIn('js-wa-search-results', html)
		self.assertIn('Search your chats and messages', html)
