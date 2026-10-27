from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView, TemplateView

from .google_auth import google_callback, google_start

from .views import (
	RegistrationWizard, registration_sent, verify_email, login_view, dashboard, logout_view, check_signup_username,
)

urlpatterns = [
	path('', RedirectView.as_view(pattern_name='login', permanent=False), name='home_redirect'),
	path('register/', RegistrationWizard.as_view(), name='register'),
	path('register/sent/', registration_sent, name='registration_sent'),
	path('register/username/check/', check_signup_username, name='check_signup_username'),
	path('verify/<str:token>/', verify_email, name='verify_email'),
	path('login/', login_view, name='login'),
	path('login/google/', google_start, name='google_start'),
	path('login/google/callback/', google_callback, name='google_callback'),
	path('logout/', logout_view, name='logout'),

	# "Forgot password?" — Django's own reset pages, styled like the sign-in page.
	path('password/reset/', auth_views.PasswordResetView.as_view(
		template_name='accounts/password_reset.html',
		email_template_name='accounts/password_reset_email.txt',
		subject_template_name='accounts/password_reset_subject.txt',
	), name='password_reset'),
	path('password/reset/sent/', auth_views.PasswordResetDoneView.as_view(
		template_name='accounts/password_reset_done.html'), name='password_reset_done'),
	path('password/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
		template_name='accounts/password_reset_confirm.html'), name='password_reset_confirm'),
	path('password/reset/complete/', auth_views.PasswordResetCompleteView.as_view(
		template_name='accounts/password_reset_complete.html'), name='password_reset_complete'),

	# Footer pages on the sign-in page.
	path('about/', TemplateView.as_view(template_name='accounts/info_page.html', extra_context={'page': 'about'}), name='about'),
	path('help/', TemplateView.as_view(template_name='accounts/info_page.html', extra_context={'page': 'help'}), name='help'),
	path('privacy/', TemplateView.as_view(template_name='accounts/info_page.html', extra_context={'page': 'privacy'}), name='privacy'),
	path('terms/', TemplateView.as_view(template_name='accounts/info_page.html', extra_context={'page': 'terms'}), name='terms'),
	path('dashboard/', dashboard, name='dashboard'),
]
