"""Choosing your own @username (feed/usernames.py)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import PreviousUsername
from feed.usernames import problem, suggestions

User = get_user_model()


class UsernameTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.me = self.student('UNN-2022249381', 'Emmanuel', 'Chukwu', uni, fac, dep, lvl)
		self.ada = self.student('ada_obi', 'Ada', 'Obi', uni, fac, dep, lvl)
		self.client.force_login(self.me)

	def student(self, username, first, last, uni, fac, dep, lvl):
		user = User.objects.create_user(username, password='x', first_name=first, last_name=last)
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=username, university_email=f'{username}@unn.edu.ng')
		return user

	def test_rules(self):
		self.assertIn('at least 4', problem('abc', self.me))
		self.assertIn('15 characters', problem('a' * 16, self.me))
		self.assertIn('letters, numbers and underscores', problem('emma-c', self.me))
		self.assertIn('letters, numbers and underscores', problem('emma c', self.me))
		self.assertIn('reserved', problem('Admin', self.me))
		self.assertIn('taken', problem('ADA_OBI', self.me))            # capitals don't count
		self.assertEqual(problem('emma_c', self.me), '')

	def test_check_endpoint_and_suggestions(self):
		d = self.client.get('/settings/username/check/', {'u': 'ada_obi'}).json()
		self.assertFalse(d['ok'])
		self.assertTrue(d['suggestions'])
		self.assertTrue(all(problem(s, self.me) == '' for s in d['suggestions']))
		self.assertTrue(self.client.get('/settings/username/check/', {'u': '@emma_c'}).json()['ok'])
		self.assertIn('emmanuel_chukwu', suggestions(self.me))

	def test_change_keeps_login_and_redirects_old_links(self):
		self.assertContains(self.client.get('/u/UNN-2022249381/'), 'Choose a username')
		r = self.client.post('/settings/', {'section': 'username', 'username': 'Emma_C'})
		self.me.refresh_from_db()
		self.assertEqual(self.me.username, 'Emma_C')
		self.assertTrue(self.me.check_password('x'))
		self.assertRedirects(self.client.get('/u/UNN-2022249381/'), '/u/Emma_C/', fetch_redirect_response=False)
		self.assertRedirects(self.client.get('/u/emma_c/'), '/u/Emma_C/', fetch_redirect_response=False)
		self.assertNotContains(self.client.get('/u/Emma_C/'), 'Choose a username')
		# Someone else can take the old name; then it's theirs.
		self.client.force_login(self.ada)
		self.client.post('/settings/', {'section': 'username', 'username': 'Emma_C'})
		self.ada.refresh_from_db()
		self.assertEqual(self.ada.username, 'ada_obi')                 # taken — not changed

	def test_bad_name_not_saved(self):
		self.client.post('/settings/', {'section': 'username', 'username': 'no'})
		self.me.refresh_from_db()
		self.assertEqual(self.me.username, 'UNN-2022249381')
		self.assertFalse(PreviousUsername.objects.exists())
