"""@mention suggestions (feed/people.py mention_search)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import Block, Follow

User = get_user_model()


class MentionTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		far = University.objects.create(name='University of Lagos', short_name='UNILAG', email_domain='unilag.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		cs = Department.objects.create(faculty=fac, name='Computer Science')
		eco = Department.objects.create(faculty=fac, name='Economics')
		lvl = Level.objects.create(department=cs, name='400 Level')
		self.me = self.student('me', 'Emma', uni, fac, cs, lvl)
		self.ada = self.student('ada1', 'Ada', uni, fac, eco, lvl)
		self.adam = self.student('adam2', 'Adamu', uni, fac, cs, lvl)
		self.bada = self.student('bada3', 'Obada', uni, fac, cs, lvl)
		self.lagos = self.student('ada9', 'Adaeze', far, fac, cs, lvl)
		self.client.force_login(self.me)

	def student(self, username, first, uni, fac, dep, lvl):
		user = User.objects.create_user(username, password='x', first_name=first, last_name='Okeke')
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=username, university_email=f'{username}@{uni.email_domain}')
		return user

	def names(self, q):
		return [p['username'] for p in self.client.get('/people/mention/', {'q': q}).json()['people']]

	def test_order_and_scope(self):
		# Starts-with beats contains; same department first; other universities never.
		self.assertEqual(self.names('ada'), ['adam2', 'ada1', 'bada3'])
		Follow.objects.create(follower=self.me, following=self.ada, status=Follow.STATUS_ACCEPTED)
		self.assertEqual(self.names('ada')[0], 'ada1')                       # people you follow first
		self.assertEqual(self.names(''), ['ada1'])                           # just "@": people you follow

	def test_blocked_and_self_left_out(self):
		Block.objects.create(blocker=self.adam, blocked=self.me)
		self.assertNotIn('adam2', self.names('ada'))
		self.assertNotIn('me', self.names('emma'))

	def test_json_shape(self):
		p = self.client.get('/people/mention/', {'q': 'obada'}).json()['people'][0]
		self.assertEqual(p['name'], 'Obada Okeke')
		self.assertIn('Computer Science', p['detail'])
