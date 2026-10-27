"""The sign-up verification email: a 6-digit code (typed on the "Check your
inbox" screen) plus a link that does the same thing.

The code is worked out from the account's verification token and the site's
SECRET_KEY, so nothing new is stored in the database. Guessing is limited to
MAX_TRIES wrong codes per TRY_WINDOW, and a new email can be asked for once
per RESEND_WAIT.

Whether the email really leaves the computer depends on the EMAIL_* lines in
.env (see uniconnect/settings.py); without them it's printed in the terminal
that runs the server.
"""
import hashlib
import hmac
import logging

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

log = logging.getLogger(__name__)

MAX_TRIES = 5
TRY_WINDOW = 15 * 60
RESEND_WAIT = 60


def code_for(token_obj):
	digest = hmac.new(settings.SECRET_KEY.encode(), f'verify:{token_obj.token}'.encode(), hashlib.sha256).hexdigest()
	return str(int(digest, 16) % 1_000_000).zfill(6)


def send_verification(request, student):
	"""Emails the code and link. Returns False if the email couldn't be sent."""
	token_obj = student.verification_token
	context = {
		'student': student,
		'code': code_for(token_obj),
		'verify_url': request.build_absolute_uri(reverse('verify_email', kwargs={'token': token_obj.token})),
	}
	try:
		send_mail(
			subject=f"{context['code']} is your UniConnect verification code",
			message=render_to_string('accounts/verification_email.txt', context),
			html_message=render_to_string('accounts/verification_email.html', context),
			from_email=None,
			recipient_list=[student.university_email],
		)
	except Exception:  # SMTP refused, wrong password, no internet ...
		log.exception('Verification email to %s could not be sent', student.university_email)
		return False
	cache.set(f'verify-resend:{student.pk}', True, RESEND_WAIT)
	return True


def can_resend(student):
	return not cache.get(f'verify-resend:{student.pk}')


def check_code(student, typed):
	"""'ok', 'wrong' or 'locked' (too many wrong tries — wait, or use the link)."""
	key = f'verify-tries:{student.pk}'
	tries = cache.get(key, 0)
	if tries >= MAX_TRIES:
		return 'locked'
	typed = ''.join(ch for ch in (typed or '') if ch.isdigit())
	if hmac.compare_digest(typed, code_for(student.verification_token)):
		cache.delete(key)
		return 'ok'
	cache.set(key, tries + 1, TRY_WINDOW)
	return 'locked' if tries + 1 >= MAX_TRIES else 'wrong'


def activate(token_obj):
	student = token_obj.student
	student.is_verified = True
	student.save(update_fields=['is_verified'])
	student.user.is_active = True
	student.user.save(update_fields=['is_active'])
	token_obj.delete()
	return student
