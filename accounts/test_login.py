"""The sign-in page (run: python manage.py test accounts.test_login)."""
import base64
import json
import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings

from .models import Department, Faculty, Level, StudentProfile, University

User = get_user_model()


class LoginTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.user = User.objects.create_user('ada', email='ada@unn.edu.ng', password='pass-123')
		StudentProfile.objects.create(user=self.user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number='2019/123456', university_email='ada@unn.edu.ng')

	def post(self, **data):
		return self.client.post('/accounts/login/' if self.url is None else self.url, data)

	url = None

	def setup_url(self):
		from django.urls import reverse
		self.url = reverse('login')

	def test_page_renders_new_design(self):
		self.setup_url()
		html = self.client.get(self.url).content.decode()
		for bit in ('Welcome Back!', 'name="identifier"', 'name="password"', 'name="remember"', 'Sign Up', 'images.pexels.com',
				'Forgot password?', '/password/reset/', '/about/', '/help/', '/privacy/', '/terms/', 'Verifying student accounts'):
			self.assertIn(bit, html)
		self.assertNotIn('Continue with Google', html)    # no keys in .env: no button
		self.assertNotIn('Apple', html)

	def test_sign_in_with_email(self):
		self.setup_url()
		r = self.post(identifier='ADA@unn.edu.ng', password='pass-123', remember='1')
		self.assertRedirects(r, '/dashboard/', fetch_redirect_response=False) if r.url == '/dashboard/' else self.assertEqual(r.status_code, 302)
		self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
		self.assertFalse(self.client.session.get_expire_at_browser_close())

	def test_sign_in_with_matric_number_without_remember(self):
		self.setup_url()
		r = self.post(identifier='2019/123456', password='pass-123')
		self.assertEqual(r.status_code, 302)
		self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
		self.assertTrue(self.client.session.get_expire_at_browser_close())

	def test_wrong_password_and_bad_email(self):
		self.setup_url()
		html = self.post(identifier='2019/123456', password='nope').content.decode()
		self.assertIn('Invalid registration number or password.', html)
		self.assertIn('value="2019/123456"', html)   # what they typed stays in the box
		html = self.post(identifier='ada@unn.edu.ng', password='nope').content.decode()
		self.assertIn('Invalid email or password.', html)
		html = self.post(identifier='ada@', password='x').content.decode()
		self.assertIn('lp-error', html)
		self.assertNotIn('_auth_user_id', self.client.session)

	def test_old_two_form_posts_still_work(self):
		self.setup_url()
		r = self.post(login_mode='matric', matric_number='2019/123456', password='pass-123')
		self.assertEqual(r.status_code, 302)
		self.assertFalse(self.client.session.get_expire_at_browser_close())

	def test_footer_pages(self):
		for url, title in (('/about/', 'About UniConnect'), ('/help/', 'Help'), ('/privacy/', 'Privacy'), ('/terms/', 'Terms')):
			r = self.client.get(url)
			self.assertEqual(r.status_code, 200, url)
			self.assertContains(r, f'<h2>{title}</h2>')

	def test_forgot_password(self):
		r = self.client.post('/password/reset/', {'email': 'ada@unn.edu.ng'})
		self.assertRedirects(r, '/password/reset/sent/')
		self.assertEqual(len(mail.outbox), 1)
		link = re.search(r'http://testserver(/password/reset/\S+/)', mail.outbox[0].body).group(1)
		r = self.client.get(link, follow=True)
		self.assertContains(r, 'Choose a new password')
		r = self.client.post(r.redirect_chain[-1][0], {'new_password1': 'Fresh-pass-9876', 'new_password2': 'Fresh-pass-9876'})
		self.assertRedirects(r, '/password/reset/complete/')
		self.user.refresh_from_db()
		self.assertTrue(self.user.check_password('Fresh-pass-9876'))
		self.assertContains(self.client.get('/password/reset/x/y/'), 'This link has expired')


def fake_id_token(**claims):
	body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
	return f'h.{body}.sig'


@override_settings(GOOGLE_CLIENT_ID='cid.apps.googleusercontent.com', GOOGLE_CLIENT_SECRET='s')
class GoogleTests(TestCase):
	setUp = LoginTests.setUp

	def claims(self, **extra):
		c = {'aud': 'cid.apps.googleusercontent.com', 'iss': 'https://accounts.google.com', 'email': 'ada@unn.edu.ng', 'email_verified': True}
		c.update(extra)
		return fake_id_token(**c)

	def start(self, remember=True):
		r = self.client.get('/login/google/' + ('?remember=1' if remember else ''))
		self.assertTrue(r.url.startswith('https://accounts.google.com/o/oauth2/v2/auth?'))
		self.assertIn('redirect_uri=http%3A%2F%2Ftestserver%2Flogin%2Fgoogle%2Fcallback%2F', r.url)
		return re.search(r'state=([^&]+)', r.url).group(1)

	def test_button_shows_with_keys(self):
		self.assertContains(self.client.get('/login/'), 'Continue with Google')

	def test_google_signs_in_existing_student(self):
		state = self.start()
		with mock.patch('accounts.google_auth._exchange_code', return_value=self.claims()):
			r = self.client.get('/login/google/callback/', {'state': state, 'code': 'c'})
		self.assertEqual(r.status_code, 302)
		self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
		self.assertFalse(self.client.session.get_expire_at_browser_close())

	def test_google_refuses_unknown_wrong_state_and_bad_token(self):
		state = self.start()
		with mock.patch('accounts.google_auth._exchange_code', return_value=self.claims(email='stranger@gmail.com')):
			html = self.client.get('/login/google/callback/', {'state': state, 'code': 'c'}, follow=True).content.decode()
		self.assertIn('No UniConnect account uses stranger@gmail.com', html)
		state = self.start()
		with mock.patch('accounts.google_auth._exchange_code', return_value=self.claims(aud='someone-else')):
			self.client.get('/login/google/callback/', {'state': state, 'code': 'c'})
		self.start()
		with mock.patch('accounts.google_auth._exchange_code', return_value=self.claims()):
			self.client.get('/login/google/callback/', {'state': 'forged', 'code': 'c'})
		self.assertNotIn('_auth_user_id', self.client.session)


class SignUpTests(TestCase):
	"""Sign-up uses the same frame as sign-in; the steps themselves are unchanged."""
	def setUp(self):
		from django.core.cache import cache
		cache.clear()
		self.uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		self.fac = Faculty.objects.create(university=self.uni, name='Sciences')
		self.dep = Department.objects.create(faculty=self.fac, name='Computer Science')
		self.lvl = Level.objects.create(department=self.dep, name='400 Level')

	def step(self, name, **fields):
		data = {'registration_wizard-current_step': name}
		data.update({f'{name}-{k}': v for k, v in fields.items()})
		return self.client.post('/register/', data)

	def test_full_sign_up_in_the_new_frame(self):
		html = self.client.get('/register/').content.decode()
		for bit in ('id="lpPanel"', 'lp-intro', 'Create your account', 'Step 1 of 7', 'data-lp-swap', 'Sign In', 'js/auth.js'):
			self.assertIn(bit, html)
		html = self.step('university', university=self.uni.pk).content.decode()
		self.assertIn('Step 2 of 7', html)
		self.assertIn('placeholder="Matric number"', html)
		self.assertIn('Must end in @unn.edu.ng', html)
		html = self.step('student_info', first_name='Ada', last_name='Obi', matric_number='2020/1', university_email='ada@gmail.com',
			password1='Strong-pass-55', password2='Strong-pass-55').content.decode()
		self.assertIn('ending in @unn.edu.ng', html)      # checks unchanged
		self.step('student_info', first_name='Ada', last_name='Obi', matric_number='2020/1', university_email='ada@unn.edu.ng',
			password1='Strong-pass-55', password2='Strong-pass-55')
		html = self.client.post('/register/', {'registration_wizard-current_step': 'faculty', 'wizard_goto_step': 'student_info'}).content.decode()
		self.assertIn('Step 2 of 7', html)                # Back works
		self.step('student_info', first_name='Ada', last_name='Obi', matric_number='2020/1', university_email='ada@unn.edu.ng',
			password1='Strong-pass-55', password2='Strong-pass-55')
		self.step('faculty', faculty=self.fac.pk)
		self.step('department', department=self.dep.pk)
		html = self.step('level', level=self.lvl.pk).content.decode()
		self.assertIn('Step 6 of 7', html)
		self.assertIn('Choose your username', html)
		self.assertIn('data-name="ada_obi"', html)        # an idea from her name
		User.objects.create_user('taken_name', password='x')
		self.assertIn('That username has been taken', self.step('username', username='Taken_Name').content.decode())
		self.assertIn('letters, numbers and underscores', self.step('username', username='ada-obi').content.decode())
		html = self.step('username', username='@ada_obi').content.decode()
		self.assertIn('Step 7 of 7', html)
		self.assertIn('@ada_obi', html)                   # on the review list
		self.assertIn('ada@unn.edu.ng', html)             # review list
		r = self.step('verify', confirm='on')
		self.assertRedirects(r, '/register/sent/')
		self.assertContains(self.client.get('/register/sent/'), 'ada@unn.edu.ng')
		user = User.objects.get(email='ada@unn.edu.ng')
		self.assertEqual(user.username, 'ada_obi')
		self.check_email(user)
		self.assertFalse(user.is_active)
		self.assertEqual(len(mail.outbox), 1)
		link = re.search(r'http://testserver(/verify/\S+/)', mail.outbox[0].body).group(1)
		self.assertRedirects(self.client.get(link), '/login/')
		user.refresh_from_db()
		self.assertTrue(user.is_active)
		self.assertContains(self.client.get('/verify/nope/'), 'Verification link not found', status_code=404)

	def check_email(self, user):
		msg = mail.outbox[0]
		code = re.search(r'\b(\d{6})\b', msg.body).group(1)
		self.assertEqual(msg.to, ['ada@unn.edu.ng'])
		self.assertIn(code, msg.subject)
		self.assertIn(code, msg.alternatives[0][0])                 # HTML version too
		self.assertIn('/verify/', msg.body)
		self.code = code

	def sign_up(self):
		self.step('university', university=self.uni.pk)
		self.step('student_info', first_name='Ada', last_name='Obi', matric_number='2020/1', university_email='ada@unn.edu.ng',
			password1='Strong-pass-55', password2='Strong-pass-55')
		self.step('faculty', faculty=self.fac.pk)
		self.step('department', department=self.dep.pk)
		self.step('level', level=self.lvl.pk)
		self.step('username', username='ada_obi')
		self.step('verify', confirm='on')
		self.check_email(User.objects.get(email='ada@unn.edu.ng'))

	def test_username_taken_meanwhile_goes_back(self):
		self.step('university', university=self.uni.pk)
		self.step('student_info', first_name='Ada', last_name='Obi', matric_number='2020/1', university_email='ada@unn.edu.ng',
			password1='Strong-pass-55', password2='Strong-pass-55')
		self.step('faculty', faculty=self.fac.pk)
		self.step('department', department=self.dep.pk)
		self.step('level', level=self.lvl.pk)
		self.step('username', username='ada_obi')
		User.objects.create_user('ADA_OBI', password='x')          # someone grabs it before she confirms
		html = self.step('verify', confirm='on').content.decode()
		self.assertIn('Choose your username', html)                  # sent back to pick another
		self.assertIn('That username has been taken', html)
		self.assertFalse(User.objects.filter(email='ada@unn.edu.ng').exists())
		self.step('username', username='ada_obi2')
		self.step('verify', confirm='on')
		self.assertEqual(User.objects.get(email='ada@unn.edu.ng').username, 'ada_obi2')

	def test_live_check(self):
		User.objects.create_user('taken_name', password='x')
		self.assertFalse(self.client.get('/register/username/check/', {'u': 'TAKEN_NAME'}).json()['ok'])
		self.assertTrue(self.client.get('/register/username/check/', {'u': 'free_name'}).json()['ok'])

	def test_code_activates_account(self):
		self.sign_up()
		html = self.client.get('/register/sent/').content.decode()
		self.assertIn('name="code"', html)
		wrong = '000000' if self.code != '000000' else '111111'
		html = self.client.post('/register/sent/', {'code': wrong}, follow=True).content.decode()
		self.assertIn('That code isn&#x27;t right', html)
		self.assertFalse(User.objects.get(email='ada@unn.edu.ng').is_active)
		r = self.client.post('/register/sent/', {'code': self.code[:3] + ' ' + self.code[3:]}, follow=True)
		self.assertEqual(r.redirect_chain[-1][0], '/login/')
		self.assertContains(r, 'Your email has been verified')
		self.assertTrue(User.objects.get(email='ada@unn.edu.ng').is_active)
		r = self.client.post('/login/', {'identifier': 'ada@unn.edu.ng', 'password': 'Strong-pass-55'})
		self.assertEqual(r.status_code, 302)

	def test_resend_and_lockout(self):
		self.sign_up()
		html = self.client.post('/register/sent/', {'action': 'resend'}, follow=True).content.decode()
		self.assertIn('give it a minute', html)                      # just sent: wait
		self.assertEqual(len(mail.outbox), 1)
		from django.core.cache import cache
		cache.delete_many([k for k in ('verify-resend:%d' % User.objects.get(email='ada@unn.edu.ng').student_profile.pk,)])
		html = self.client.post('/register/sent/', {'action': 'resend'}, follow=True).content.decode()
		self.assertIn('sent a new code to ada@unn.edu.ng', html)
		self.assertEqual(len(mail.outbox), 2)
		self.assertIn(self.code, mail.outbox[1].body)                 # same code
		wrong = '000000' if self.code != '000000' else '111111'
		for _ in range(5):
			self.client.post('/register/sent/', {'code': wrong})
		html = self.client.post('/register/sent/', {'code': self.code}, follow=True).content.decode()
		self.assertIn('Too many wrong codes', html)                  # even the right code waits now
		self.assertFalse(User.objects.get(email='ada@unn.edu.ng').is_active)

	def test_email_failure_does_not_break_sign_up(self):
		from unittest import mock
		# assertLogs: the expected "could not be sent" error is checked, not printed in the test output.
		with mock.patch('accounts.verification.send_mail', side_effect=OSError('no network')), \
				self.assertLogs('accounts.verification', level='ERROR') as logs:
			self.step('university', university=self.uni.pk)
			self.step('student_info', first_name='Ada', last_name='Obi', matric_number='2020/1', university_email='ada@unn.edu.ng',
				password1='Strong-pass-55', password2='Strong-pass-55')
			self.step('faculty', faculty=self.fac.pk)
			self.step('department', department=self.dep.pk)
			self.step('level', level=self.lvl.pk)
			self.step('username', username='ada_obi')
			html = self.client.post('/register/', {'registration_wizard-current_step': 'verify', 'verify-confirm': 'on'}, follow=True).content.decode()
		self.assertIn('could not be sent', logs.output[0])
		self.assertIn("couldn&#x27;t send the verification email", html)
		self.assertIn('send a new code', html)
