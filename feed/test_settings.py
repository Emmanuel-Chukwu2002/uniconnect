"""The Settings page (run: python manage.py test feed.test_settings)."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from .models import Notification
from .notifications import notify

User = get_user_model()


class SettingsTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		self.dep = Department.objects.create(faculty=fac, name='Computer Science')
		other = Department.objects.create(faculty=fac, name='Physics')
		self.l400 = Level.objects.create(department=self.dep, name='400 Level')
		self.l500 = Level.objects.create(department=self.dep, name='500 Level')
		self.other_level = Level.objects.create(department=other, name='100 Level')
		self.me = self.student('ada', uni, fac)
		self.friend = self.student('ben', uni, fac)
		self.client.force_login(self.me)

	def student(self, name, uni, fac):
		user = User.objects.create_user(name, email=f'{name}@unn.edu.ng', password='Old-pass-123', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=self.dep, level=self.l400,
			matric_number=name, university_email=f'{name}@unn.edu.ng', is_verified=True)
		return user

	def post(self, **data):
		return self.client.post('/settings/', data)

	def test_menu_and_screens(self):
		html = self.client.get('/settings/').content.decode()
		for bit in ('Account &amp; Profile', 'Notifications', 'Privacy &amp; Security', 'Appearance', 'Help &amp; Support', 'Log Out',
				'?s=account', '?s=security', '?s=delete', 'Delete account', '@ada', 'st-menu'):
			self.assertIn(bit, html)
		self.assertNotIn('name="section"', html)       # the menu has no forms
		screens = {
			'account': ('st-account', 'ada@unn.edu.ng', 'Computer Science', '500 Level'),
			'notifications': ('st-notifications', 'value="likes"'),
			'security': ('st-privacy', 'st-password', 'st-sessions'),
			'appearance': ('st-appearance', 'data-theme="dark"', 'js-st-size', 'data-font="inter"', 'data-font="default"'),
			'delete': ('st-delete', 'Delete my account', 'name="password"'),
			'help': ('st-help', 'Help centre'),
		}
		for key, bits in screens.items():
			html = self.client.get(f'/settings/?s={key}').content.decode()
			self.assertIn('Back to Settings', html)
			for bit in bits:
				self.assertIn(bit, html, key)
		self.assertNotIn('100 Level', self.client.get('/settings/?s=account').content.decode())   # only your department's levels

	def test_account_name_and_level(self):
		self.assertRedirects(self.post(section='account', first_name='Adaeze', last_name='Obi', level=self.l500.pk), '/settings/?s=account')
		self.me.refresh_from_db()
		self.assertEqual(self.me.get_full_name(), 'Adaeze Obi')
		self.assertEqual(self.me.student_profile.level, self.l500)
		r = self.post(section='account', first_name='A', last_name='B', level=self.other_level.pk)
		self.assertEqual(r.status_code, 200)            # another department's level is refused
		self.me.student_profile.refresh_from_db()
		self.assertEqual(self.me.student_profile.level, self.l500)

	def test_password_change_keeps_this_session_and_ends_others(self):
		other = Client()
		other.force_login(self.me)
		self.assertEqual(other.get('/settings/').status_code, 200)
		r = self.post(section='password', old_password='wrong', new_password1='Brand-new-456', new_password2='Brand-new-456')
		self.assertContains(r, 'st-error')
		r = self.post(section='password', old_password='Old-pass-123', new_password1='Brand-new-456', new_password2='Brand-new-456')
		self.assertRedirects(r, '/settings/?s=security')
		self.assertEqual(self.client.get('/settings/').status_code, 200)   # still signed in here
		self.assertEqual(other.get('/settings/').status_code, 302)         # signed out there
		self.me.refresh_from_db()
		self.assertTrue(self.me.check_password('Brand-new-456'))

	def test_switches_save_quietly(self):
		profile = self.me.student_profile
		r = self.client.post('/settings/', {'section': 'privacy', 'show_date_of_birth': 'on'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		self.assertEqual(r.json(), {'ok': True})
		profile.refresh_from_db()
		self.assertTrue(profile.show_date_of_birth)
		# Everything on except likes.
		on = ['comments', 'mentions', 'reposts', 'followers', 'events', 'marketplace', 'communities', 'groups', 'courses', 'reminders']
		r = self.client.post('/settings/', {'section': 'notifications', 'on': on}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		self.assertEqual(r.json(), {'ok': True})
		profile.refresh_from_db()
		self.assertEqual(profile.muted_notifications, sorted([Notification.LIKE_POST, Notification.LIKE_COMMENT]))
		self.assertIsNone(notify(self.me, self.friend, Notification.LIKE_POST))       # muted: nothing recorded
		self.assertIsNotNone(notify(self.me, self.friend, Notification.FOLLOW_REQUEST))  # never muted
		self.assertIsNotNone(notify(self.me, self.friend, Notification.MENTION))
		html = self.client.get('/settings/?s=notifications').content.decode()
		self.assertIn('value="likes" class="st-switch" >', html)                        # shown off
		self.assertIn('value="mentions" class="st-switch" checked', html)

	def test_sign_out_other_devices(self):
		other = Client()
		other.force_login(self.me)
		friend = Client()
		friend.force_login(self.friend)
		self.assertRedirects(self.post(section='sessions'), '/settings/?s=security')
		self.assertEqual(other.get('/settings/').status_code, 302)
		self.assertEqual(self.client.get('/settings/').status_code, 200)
		self.assertEqual(friend.get('/settings/').status_code, 200)        # other people untouched

	def test_delete_account_needs_password(self):
		r = self.post(section='delete', password='nope')
		self.assertContains(r, "That password isn")
		self.assertTrue(User.objects.filter(pk=self.me.pk).exists())
		r = self.post(section='delete', password='Old-pass-123')
		self.assertRedirects(r, '/login/')
		self.assertFalse(User.objects.filter(pk=self.me.pk).exists())
		self.assertFalse(StudentProfile.objects.filter(matric_number='ada').exists())
