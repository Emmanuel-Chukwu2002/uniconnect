from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.urls import reverse
from formtools.wizard.views import SessionWizardView

from .forms import (
	Step1UniversityForm, Step2StudentInfoForm, Step3FacultyForm,
	Step4DepartmentForm, Step5LevelForm, Step6UsernameForm, Step6VerifyForm, EmailLoginForm, MatricLoginForm,
)
from .models import StudentProfile, EmailVerificationToken
from .verification import activate, can_resend, check_code, send_verification

User = get_user_model()

FORMS = [
	("university", Step1UniversityForm),
	("student_info", Step2StudentInfoForm),
	("faculty", Step3FacultyForm),
	("department", Step4DepartmentForm),
	("level", Step5LevelForm),
	("username", Step6UsernameForm),
	("verify", Step6VerifyForm),
]

STEP_TITLES = {
	"university": ("Select your university", "Every community on this platform is scoped to your university — start by telling us where you study."),
	"student_info": ("Tell us about yourself", "This information is used to create your verified student account."),
	"faculty": ("Confirm your faculty", "This determines which faculty-wide community you'll be placed into."),
	"department": ("Select your department", "You'll be automatically added to your department's community."),
	"level": ("Select your level", "Used to scope resources and events to what's relevant to you."),
	"username": ("Choose your username", "This is your @handle — how classmates find and mention you. You'll still sign in with your email or matric number."),
	"verify": ("Verify your identity", "Review your details — we'll email a verification link to confirm it's really you."),
}

STEP_NUMBERS = {"university": 1, "student_info": 2, "faculty": 3, "department": 4, "level": 5, "username": 6, "verify": 7}


# What the sign-up boxes show inside them (the design has no labels above the
# boxes) and what the browser may autofill.
FIELD_HINTS = {
	'first_name': ('First name', 'given-name'),
	'last_name': ('Surname', 'family-name'),
	'matric_number': ('Matric number', 'off'),
	'university_email': ('University email address', 'email'),
	'password1': ('Password', 'new-password'),
	'password2': ('Confirm password', 'new-password'),
}


class RegistrationWizard(SessionWizardView):
	form_list = FORMS
	template_name = "accounts/wizard_step.html"

	def get_form(self, step=None, data=None, files=None):
		form = super().get_form(step, data, files)
		for name, field in form.fields.items():
			if name in FIELD_HINTS:
				placeholder, autocomplete = FIELD_HINTS[name]
				field.widget.attrs.setdefault('placeholder', placeholder)
				field.widget.attrs.setdefault('autocomplete', autocomplete)
		return form

	def get_form_kwargs(self, step=None):
		kwargs = super().get_form_kwargs(step)
		if step in ('student_info', 'faculty'):
			data = self.get_cleaned_data_for_step('university') or {}
			kwargs['university'] = data.get('university')
		elif step == 'department':
			data = self.get_cleaned_data_for_step('faculty') or {}
			kwargs['faculty'] = data.get('faculty')
		elif step == 'level':
			data = self.get_cleaned_data_for_step('department') or {}
			kwargs['department'] = data.get('department')
		return kwargs

	def get_context_data(self, form, **kwargs):
		context = super().get_context_data(form=form, **kwargs)
		step = self.steps.current
		title, lede = STEP_TITLES[step]
		context.update({
			'step_title': title,
			'step_lede': lede,
			'step_number': STEP_NUMBERS[step],
			'total_steps': len(STEP_NUMBERS),
		})
		if step == 'username':
			context['username_suggestions'] = self._username_ideas()
		if step == 'verify':
			uni_data = self.get_cleaned_data_for_step('university') or {}
			info = self.get_cleaned_data_for_step('student_info') or {}
			fac_data = self.get_cleaned_data_for_step('faculty') or {}
			dept_data = self.get_cleaned_data_for_step('department') or {}
			lvl_data = self.get_cleaned_data_for_step('level') or {}
			context['review'] = {
				'university': uni_data.get('university'),
				'first_name': info.get('first_name'),
				'last_name': info.get('last_name'),
				'matric_number': info.get('matric_number'),
				'university_email': info.get('university_email'),
				'faculty': fac_data.get('faculty'),
				'department': dept_data.get('department'),
				'level': lvl_data.get('level'),
				'username': (self.get_cleaned_data_for_step('username') or {}).get('username'),
			}
		return context

	def _username_ideas(self):
		"""Free usernames from the name typed in step 2 (shown as tap-to-use chips)."""
		from types import SimpleNamespace
		from feed.usernames import suggestions
		info = self.get_cleaned_data_for_step('student_info') or {}
		person = SimpleNamespace(pk=None, first_name=info.get('first_name', ''), last_name=info.get('last_name', ''))
		return suggestions(person, limit=4)

	def done(self, form_list, **kwargs):
		data = self.get_all_cleaned_data()

		# Students log in with (university + matric number) or email, never
		# the username. They chose it in the "username" step; if someone took
		# it in the meantime, fall back to university + matric number (they
		# can pick another in Settings).
		from feed.usernames import problem
		chosen = data.get('username') or ''
		base_username = f"{data['university'].short_name}-{data['matric_number']}"
		base_username = ''.join(ch for ch in base_username if ch.isalnum() or ch == '-')
		username = base_username
		suffix = 1
		while User.objects.filter(username=username).exists():
			suffix += 1
			username = f"{base_username}-{suffix}"
		username_lost = bool(chosen) and bool(problem(chosen))
		if chosen and not username_lost:
			username = chosen

		user = User.objects.create_user(
			username=username,
			email=data['university_email'],
			password=data['password1'],
			first_name=data['first_name'],
			last_name=data['last_name'],
			is_active=False,  # activated once the verification link is clicked
		)

		student = StudentProfile.objects.create(
			user=user,
			university=data['university'],
			faculty=data['faculty'],
			department=data['department'],
			level=data['level'],
			matric_number=data['matric_number'],
			university_email=data['university_email'],
			is_verified=False,
		)

		EmailVerificationToken.objects.create(student=student)
		sent = send_verification(self.request, student)

		self.request.session['pending_verification_email'] = student.university_email
		self.request.session['pending_verification_student'] = student.pk
		if username_lost:
			messages.warning(self.request, f"Someone took @{chosen} while you were signing up, so your username is {username} for now — choose another in Settings after you sign in.")
		if not sent:
			messages.error(self.request, "Your account was created, but we couldn't send the verification email just now. Tap \"Send a new code\" to try again.")
		return redirect('registration_sent')


def registration_sent(request):
	""""Check your inbox": type the 6-digit code from the email (the link in
	the email works too), or ask for a new email."""
	email = request.session.get('pending_verification_email')
	student = StudentProfile.objects.filter(
		pk=request.session.get('pending_verification_student'), verification_token__isnull=False,
	).select_related('user', 'verification_token').first()

	if request.method == 'POST' and student:
		if request.POST.get('action') == 'resend':
			if not can_resend(student):
				messages.error(request, "A code was just sent — give it a minute before asking for another.")
			elif send_verification(request, student):
				messages.success(request, f"We've sent a new code to {student.university_email}.")
			else:
				messages.error(request, "We couldn't send the email just now — please try again in a moment.")
			return redirect('registration_sent')

		result = check_code(student, request.POST.get('code'))
		if result == 'ok':
			activate(student.verification_token)
			for key in ('pending_verification_email', 'pending_verification_student'):
				request.session.pop(key, None)
			messages.success(request, "Your email has been verified — you can now log in.")
			return redirect('login')
		if result == 'locked':
			messages.error(request, "Too many wrong codes. Wait 15 minutes, or use the link in the email instead.")
		else:
			messages.error(request, "That code isn't right — check the email and try again.")
		return redirect('registration_sent')

	return render(request, 'accounts/registration_sent.html', {'email': email, 'student': student})


def check_signup_username(request):
	"""GET /register/username/check/?u=<name> — the sign-up username step's live check (static/js/auth.js)."""
	from django.http import JsonResponse
	from feed.usernames import problem
	name = (request.GET.get('u') or '').strip().lstrip('@')[:30]
	why = problem(name)
	return JsonResponse({'ok': not why, 'message': why or f'@{name} is available.'})


def verify_email(request, token):
	token_obj = EmailVerificationToken.objects.filter(token=token).select_related('student__user').first()
	if not token_obj:
		return render(request, 'accounts/verify_invalid.html', status=404)

	activate(token_obj)
	messages.success(request, "Your email has been verified — you can now log in.")
	return redirect('login')


from .google_auth import google_enabled


def login_view(request):
	if request.user.is_authenticated:
		return redirect('dashboard')

	data = request.POST.copy()
	# The sign-in page has one box, "Email address or matric number": anything
	# with an @ is treated as an email, anything else as a registration number,
	# and the matching form below checks it exactly as before.
	identifier = data.get('identifier', '').strip()
	if request.method == 'POST' and identifier:
		data['login_mode'] = 'email' if '@' in identifier else 'matric'
		data['email' if '@' in identifier else 'matric_number'] = identifier

	mode = data.get('login_mode', 'email')
	email_form = EmailLoginForm()
	matric_form = MatricLoginForm()

	def sign_in(user):
		auth_login(request, user, backend='accounts.backends.MatricNumberBackend')
		# "Remember me" unticked: the sign-in ends when the browser is closed.
		if request.POST.get('identifier') is not None and not request.POST.get('remember'):
			request.session.set_expiry(0)
		return redirect('dashboard')

	if request.method == 'POST' and mode == 'email':
		email_form = EmailLoginForm(data)
		if email_form.is_valid():
			email = email_form.cleaned_data['email']
			password = email_form.cleaned_data['password']
			user = User.objects.filter(email__iexact=email).first()

			if user and user.check_password(password):
				if not user.is_active:
					messages.error(
						request,
						"Please verify your university email before logging in — "
						"check your inbox for the verification link we sent you."
					)
				else:
					return sign_in(user)
			else:
				messages.error(request, "Invalid email or password.")

	elif request.method == 'POST' and mode == 'matric':
		matric_form = MatricLoginForm(data)
		if matric_form.is_valid():
			matric_number = matric_form.cleaned_data['matric_number']
			password = matric_form.cleaned_data['password']

			candidates = StudentProfile.objects.select_related('user').filter(
				matric_number__iexact=matric_number,
			)
			matches = [c for c in candidates if c.user.check_password(password)]

			if len(matches) == 1:
				student = matches[0]
				if not student.user.is_active:
					messages.error(
						request,
						"Please verify your university email before logging in — "
						"check your inbox for the verification link we sent you."
					)
				else:
					return sign_in(student.user)
			elif len(matches) > 1:
				messages.error(
					request,
					"More than one account shares this registration number across "
					"universities — please sign in with your email instead."
				)
			else:
				messages.error(request, "Invalid registration number or password.")

	return render(request, 'accounts/login.html', {
		'email_form': email_form, 'matric_form': matric_form, 'mode': mode,
		'google_enabled': google_enabled(),
		'identifier': identifier, 'remember': request.method != 'POST' or bool(request.POST.get('remember')),
	})


@login_required
def dashboard(request):
	# Where sign-in lands. Admins who aren't students have no feed, so they go
	# straight to the admin dashboard (adminpanel); everyone else to Home.
	if not hasattr(request.user, 'student_profile'):
		from adminpanel.permissions import admin_for
		if admin_for(request.user) is not None:
			return redirect('staff_overview')
	return redirect('home')


def logout_view(request):
	auth_logout(request)
	messages.success(request, "You have been logged out.")
	return redirect('login')
