from django import forms
from django.contrib.auth import get_user_model

from .models import University, Faculty, Department, Level, StudentProfile

User = get_user_model()


class Step1UniversityForm(forms.Form):
	university = forms.ModelChoiceField(
		queryset=University.objects.filter(is_active=True),
		label="Select your university",
		empty_label="Choose your university…",
	)


class Step2StudentInfoForm(forms.Form):
	first_name = forms.CharField(max_length=100, label="First name")
	last_name = forms.CharField(max_length=100, label="Surname")
	matric_number = forms.CharField(max_length=50, label="Matriculation number")
	university_email = forms.EmailField(label="University email address")
	password1 = forms.CharField(widget=forms.PasswordInput, label="Password")
	password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

	def __init__(self, *args, university=None, **kwargs):
		self.university = university
		super().__init__(*args, **kwargs)
		if university and university.matric_format_hint:
			self.fields['matric_number'].help_text = f"Format example: {university.matric_format_hint}"
		if university:
			self.fields['university_email'].help_text = f"Must end in @{university.email_domain}"

	def clean_university_email(self):
		email = self.cleaned_data['university_email'].strip().lower()
		if self.university and not email.endswith('@' + self.university.email_domain.lower()):
			raise forms.ValidationError(
				f"Please use your official university email address, ending in @{self.university.email_domain}."
			)
		if User.objects.filter(email__iexact=email).exists():
			raise forms.ValidationError("An account with this email already exists.")
		return email

	def clean_matric_number(self):
		matric = self.cleaned_data['matric_number'].strip()
		if self.university and StudentProfile.objects.filter(
			university=self.university, matric_number__iexact=matric
		).exists():
			raise forms.ValidationError(
				"This matric number is already registered at your university. "
				"If this is you, try logging in instead."
			)
		return matric

	def clean_password2(self):
		p1 = self.cleaned_data.get('password1')
		p2 = self.cleaned_data.get('password2')
		if p1 and p2 and p1 != p2:
			raise forms.ValidationError("The two password fields didn't match.")
		return p2


class Step3FacultyForm(forms.Form):
	faculty = forms.ModelChoiceField(
		queryset=Faculty.objects.none(),
		label="Select your faculty",
		empty_label="Choose your faculty…",
	)

	def __init__(self, *args, university=None, **kwargs):
		super().__init__(*args, **kwargs)
		if university:
			self.fields['faculty'].queryset = Faculty.objects.filter(university=university)


class Step4DepartmentForm(forms.Form):
	department = forms.ModelChoiceField(
		queryset=Department.objects.none(),
		label="Select your department",
		empty_label="Choose your department…",
	)

	def __init__(self, *args, faculty=None, **kwargs):
		super().__init__(*args, **kwargs)
		if faculty:
			self.fields['department'].queryset = Department.objects.filter(faculty=faculty)


class Step5LevelForm(forms.Form):
	level = forms.ModelChoiceField(
		queryset=Level.objects.none(),
		label="Select your level",
		empty_label="Choose your level…",
	)

	def __init__(self, *args, department=None, **kwargs):
		super().__init__(*args, **kwargs)
		if department:
			self.fields['level'].queryset = Level.objects.filter(department=department)


class Step6VerifyForm(forms.Form):
	confirm = forms.BooleanField(
		label="I confirm the information above is correct",
		required=True,
	)


class EmailLoginForm(forms.Form):
	email = forms.EmailField(label="University email address")
	password = forms.CharField(widget=forms.PasswordInput, label="Password")


class MatricLoginForm(forms.Form):
	matric_number = forms.CharField(max_length=50, label="Registration number")
	password = forms.CharField(widget=forms.PasswordInput, label="Password")
