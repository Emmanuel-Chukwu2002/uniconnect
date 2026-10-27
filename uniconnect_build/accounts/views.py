from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.shortcuts import render, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from formtools.wizard.views import SessionWizardView

from .forms import (
	Step1UniversityForm, Step2StudentInfoForm, Step3FacultyForm,
	Step4DepartmentForm, Step5LevelForm, Step6VerifyForm, EmailLoginForm, MatricLoginForm,
)
from .models import StudentProfile, EmailVerificationToken

User = get_user_model()

FORMS = [
	("university", Step1UniversityForm),
	("student_info", Step2StudentInfoForm),
	("faculty", Step3FacultyForm),
	("department", Step4DepartmentForm),
	("level", Step5LevelForm),
	("verify", Step6VerifyForm),
]

STEP_TITLES = {
	"university": ("Select your university", "Every community on this platform is scoped to your university — start by telling us where you study."),
	"student_info": ("Tell us about yourself", "This information is used to create your verified student account."),
	"faculty": ("Confirm your faculty", "This determines which faculty-wide community you'll be placed into."),
	"department": ("Select your department", "You'll be automatically added to your department's community."),
	"level": ("Select your level", "Used to scope resources and events to what's relevant to you."),
	"verify": ("Verify your identity", "Review your details — we'll email a verification link to confirm it's really you."),
}

STEP_NUMBERS = {"university": 1, "student_info": 2, "faculty": 3, "department": 4, "level": 5, "verify": 6}


class RegistrationWizard(SessionWizardView):
	form_list = FORMS
	template_name = "accounts/wizard_step.html"

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
			'total_steps': 6,
		})
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
			}
		return context

	def done(self, form_list, **kwargs):
		data = self.get_all_cleaned_data()

		# Students log in with (university + matric number), never this
		# username — it just needs to be globally unique for Django's
		# built-in User table.
		base_username = f"{data['university'].short_name}-{data['matric_number']}"
		base_username = ''.join(ch for ch in base_username if ch.isalnum() or ch == '-')
		username = base_username
		suffix = 1
		while User.objects.filter(username=username).exists():
			suffix += 1
			username = f"{base_username}-{suffix}"

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

		token = EmailVerificationToken.objects.create(student=student)
		verify_url = self.request.build_absolute_uri(
			reverse('verify_email', kwargs={'token': token.token})
		)
		message = render_to_string('accounts/verification_email.txt', {
			'student': student, 'verify_url': verify_url,
		})
		send_mail(
			subject="Verify your UniConnect student account",
			message=message,
			from_email=None,
			recipient_list=[student.university_email],
		)

		self.request.session['pending_verification_email'] = student.university_email
		return redirect('registration_sent')


def registration_sent(request):
	email = request.session.get('pending_verification_email')
	return render(request, 'accounts/registration_sent.html', {'email': email})


def verify_email(request, token):
	token_obj = EmailVerificationToken.objects.filter(token=token).select_related('student__user').first()
	if not token_obj:
		return render(request, 'accounts/verify_invalid.html', status=404)

	student = token_obj.student
	student.is_verified = True
	student.save(update_fields=['is_verified'])
	student.user.is_active = True
	student.user.save(update_fields=['is_active'])
	token_obj.delete()

	messages.success(request, "Your email has been verified — you can now log in.")
	return redirect('login')


def login_view(request):
	if request.user.is_authenticated:
		return redirect('dashboard')

	mode = request.POST.get('login_mode', 'email')
	email_form = EmailLoginForm()
	matric_form = MatricLoginForm()

	if request.method == 'POST' and mode == 'email':
		email_form = EmailLoginForm(request.POST)
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
					auth_login(request, user, backend='accounts.backends.MatricNumberBackend')
					return redirect('dashboard')
			else:
				messages.error(request, "Invalid email or password.")

	elif request.method == 'POST' and mode == 'matric':
		matric_form = MatricLoginForm(request.POST)
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
					auth_login(request, student.user, backend='accounts.backends.MatricNumberBackend')
					return redirect('dashboard')
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
	})


@login_required
def dashboard(request):
	return redirect('home')


def logout_view(request):
	auth_logout(request)
	messages.success(request, "You have been logged out.")
	return redirect('login')
