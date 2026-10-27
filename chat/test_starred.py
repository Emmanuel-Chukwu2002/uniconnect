"""Starred messages.  Run:  python manage.py test chat.test_starred"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from . import services as S
from .models import Message, StarredMessage

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


@override_settings(CHANNEL_LAYERS=LAYERS)
class StarTests(TestCase):
	def setUp(self):
		self.ada = User.objects.create_user('UNN-1', password='x', first_name='Ada')
		self.ben = User.objects.create_user('UNN-2', password='x', first_name='Ben')
		self.cy = User.objects.create_user('UNN-3', password='x', first_name='Cy')
		self.conv = S.create_group(self.ada, 'COS 401', [self.ada, self.ben])
		self.m = S.create_message(self.conv, self.ben, Message.TEXT, 'Exam venue: LT 2, 9am. Bring your ID card.')
		self.client = Client(); self.client.force_login(self.ada)

	def star(self, msg, value=None, client=None):
		data = {} if value is None else {'star': value}
		return (client or self.client).post(f'/messages/m/{msg.pk}/star/', data, **AJAX)

	def test_star_toggle_and_history(self):
		self.assertTrue(self.star(self.m).json()['starred'])
		h = self.client.get(f'/messages/c/{self.conv.pk}/history/').json()
		self.assertEqual(h['starred'], [self.m.pk])
		self.assertFalse(self.star(self.m).json()['starred'])            # tap again: unstar
		self.assertTrue(self.star(self.m, '1').json()['starred'])
		self.assertTrue(self.star(self.m, '1').json()['starred'])        # setting it twice is fine
		self.assertEqual(StarredMessage.objects.count(), 1)

	def test_private_and_listed(self):
		self.star(self.m, '1')
		page = self.client.get('/messages/starred/').content.decode()
		self.assertIn('Exam venue: LT 2', page)
		self.assertIn('COS 401', page)
		self.assertIn(f'?m={self.m.pk}', page)
		ben = Client(); ben.force_login(self.ben)
		self.assertNotIn('Exam venue', ben.get('/messages/starred/').content.decode())    # only you see your stars
		self.assertEqual(ben.get(f'/messages/c/{self.conv.pk}/history/').json()['starred'], [])
		self.assertIn('Exam venue', self.client.get('/messages/starred/?q=venue').content.decode())
		self.assertNotIn('Exam venue', self.client.get('/messages/starred/?q=football').content.decode())

	def test_outsiders_deleted_and_system(self):
		cy = Client(); cy.force_login(self.cy)
		self.assertEqual(self.star(self.m, '1', client=cy).status_code, 404)
		sysmsg = S.create_message(self.conv, None, Message.SYSTEM, 'Ben joined')
		self.assertEqual(self.star(sysmsg, '1').status_code, 404)
		self.star(self.m, '1')
		Message.objects.filter(pk=self.m.pk).update(is_deleted=True)
		self.assertNotIn('Exam venue', self.client.get('/messages/starred/').content.decode())

	def test_unstar_from_the_list_page(self):
		self.star(self.m, '1')
		r = self.client.post(f'/messages/m/{self.m.pk}/star/', {'star': '0', 'next': '/messages/starred/'})
		self.assertRedirects(r, '/messages/starred/', fetch_redirect_response=False)
		self.assertFalse(StarredMessage.objects.exists())
