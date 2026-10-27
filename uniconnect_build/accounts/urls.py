from django.urls import path
from django.views.generic import RedirectView

from .views import (
	RegistrationWizard, registration_sent, verify_email, login_view, dashboard, logout_view,
)

urlpatterns = [
	path('', RedirectView.as_view(pattern_name='login', permanent=False), name='home_redirect'),
	path('register/', RegistrationWizard.as_view(), name='register'),
	path('register/sent/', registration_sent, name='registration_sent'),
	path('verify/<str:token>/', verify_email, name='verify_email'),
	path('login/', login_view, name='login'),
	path('logout/', logout_view, name='logout'),
	path('dashboard/', dashboard, name='dashboard'),
]
