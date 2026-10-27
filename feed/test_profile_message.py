"""The profile's Message button opens a chat with that person (chat/views.py start_direct)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from chat.models import Conversation

User = get_user_model()


class ProfileMessageTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.ada, self.ben = [self.student(n, uni, fac, dep, lvl) for n in ('ada', 'ben')]
		self.client.force_login(self.ada)

	def student(self, name, uni, fac, dep, lvl):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	def test_button_opens_one_chat_with_them(self):
		html = self.client.get('/u/ben/').content.decode()
		self.assertEqual(html.count(f'action="/messages/start/{self.ben.pk}/"'), 2)     # desktop + phone layouts
		r = self.client.post(f'/messages/start/{self.ben.pk}/')
		conv = Conversation.objects.get()
		self.assertRedirects(r, f'/messages/c/{conv.pk}/', fetch_redirect_response=False) if '/c/' in r.url else self.assertEqual(r.status_code, 302)
		self.client.post(f'/messages/start/{self.ben.pk}/')                           # again: same chat, not a new one
		self.assertEqual(Conversation.objects.count(), 1)
		self.assertNotIn('/messages/start/', self.client.get('/u/ada/').content.decode())   # no button on your own profile
