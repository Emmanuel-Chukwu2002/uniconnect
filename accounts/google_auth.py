"""Sign in with Google (the "Continue with Google" button on the sign-in page).

Only for students who already have a UniConnect account: Google tells us the
person's email address, and if a verified, active account uses that email
(its sign-in email or its university email) they are signed in. Nobody is
created here — new students still register with their matric number.

Switched on by two lines in the .env file next to manage.py (never put the
values in code):
    GOOGLE_CLIENT_ID=....apps.googleusercontent.com
    GOOGLE_CLIENT_SECRET=...
Make them at https://console.cloud.google.com/apis/credentials (an "OAuth
client ID" of type "Web application") and add this "Authorised redirect URI":
    http://127.0.0.1:8000/login/google/callback/
(and the same path on your real domain when the site goes live).
Without both values the button isn't shown and these pages just go back to
the sign-in page.
"""
import base64
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
ISSUERS = ('accounts.google.com', 'https://accounts.google.com')
SESSION_KEY = 'google_oauth_state'


def google_enabled():
	return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def _callback_url(request):
	return request.build_absolute_uri(reverse('google_callback'))


def google_start(request):
	if not google_enabled():
		return redirect('login')
	state = secrets.token_urlsafe(24)
	request.session[SESSION_KEY] = {'state': state, 'remember': request.GET.get('remember') == '1'}
	params = {
		'client_id': settings.GOOGLE_CLIENT_ID,
		'redirect_uri': _callback_url(request),
		'response_type': 'code',
		'scope': 'openid email',
		'state': state,
		'prompt': 'select_account',
	}
	return redirect(f'{AUTH_URL}?{urllib.parse.urlencode(params)}')


def _exchange_code(request, code):
	"""Swaps the one-time code for Google's ID token (sent straight to Google over HTTPS)."""
	body = urllib.parse.urlencode({
		'code': code,
		'client_id': settings.GOOGLE_CLIENT_ID,
		'client_secret': settings.GOOGLE_CLIENT_SECRET,
		'redirect_uri': _callback_url(request),
		'grant_type': 'authorization_code',
	}).encode()
	req = urllib.request.Request(TOKEN_URL, data=body, headers={'Content-Type': 'application/x-www-form-urlencoded'})
	with urllib.request.urlopen(req, timeout=10) as resp:
		return json.load(resp).get('id_token', '')


def _claims(id_token):
	# The token came directly from Google's token endpoint over HTTPS, so
	# (as Google's docs allow) its contents are read without re-checking
	# the signature; the audience and issuer are still checked below.
	payload = id_token.split('.')[1]
	payload += '=' * (-len(payload) % 4)
	return json.loads(base64.urlsafe_b64decode(payload))


def google_callback(request):
	saved = request.session.pop(SESSION_KEY, None)
	if not google_enabled():
		return redirect('login')
	if request.GET.get('error'):
		messages.error(request, "Google sign-in was cancelled.")
		return redirect('login')
	if not saved or not secrets.compare_digest(saved['state'], request.GET.get('state', '')) or not request.GET.get('code'):
		messages.error(request, "That Google sign-in link has expired — please try again.")
		return redirect('login')
	try:
		claims = _claims(_exchange_code(request, request.GET['code']))
	except (urllib.error.URLError, ValueError, IndexError, KeyError, TimeoutError):
		messages.error(request, "Couldn't reach Google just now — please try again, or sign in with your password.")
		return redirect('login')

	email = (claims.get('email') or '').strip()
	if (claims.get('aud') != settings.GOOGLE_CLIENT_ID or claims.get('iss') not in ISSUERS
			or not claims.get('email_verified') or not email):
		messages.error(request, "Google didn't confirm an email address for that account.")
		return redirect('login')

	User = get_user_model()
	users = list(User.objects.filter(Q(email__iexact=email) | Q(student_profile__university_email__iexact=email)).distinct()[:2])
	if len(users) != 1:
		messages.error(request, f"No UniConnect account uses {email}. Sign up with your matric number first, or sign in with your password.")
		return redirect('login')
	user = users[0]
	if not user.is_active:
		messages.error(request, "Please verify your university email before logging in — check your inbox for the verification link we sent you.")
		return redirect('login')

	auth_login(request, user, backend='accounts.backends.MatricNumberBackend')
	if not saved.get('remember'):
		request.session.set_expiry(0)
	return redirect('dashboard')
