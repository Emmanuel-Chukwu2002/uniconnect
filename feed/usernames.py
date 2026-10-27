"""Choosing your own @username (Settings > Account & Profile > Username), X's rules:

  * 4 to 15 characters
  * only letters, numbers and underscores (_)
  * nobody else has it — capitals don't count, so "Ada_O" and "ada_o" are the same name
  * not a reserved word (admin, uniconnect, settings, ...)

Signing in never uses the username (it's email or matric number), so
changing it can't lock anyone out. New accounts still start with the
university + matric number (accounts/views.py); choosing a username also
stops showing your matric number as your @handle.

    GET  /settings/username/check/?u=<name>   JSON {ok, message, suggestions} for the live check
    POST /settings/  section=username          save it (feed/settings_page.py)

The old name is kept in PreviousUsername so old /u/<old>/ links still
reach the profile until someone else takes that name.
"""
import random
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from .models import PreviousUsername

User = get_user_model()

MIN_LEN, MAX_LEN = 4, 15
VALID = re.compile(r'^[A-Za-z0-9_]+$')
RESERVED = {
	'admin', 'administrator', 'root', 'staff', 'moderator', 'moderation', 'support', 'help', 'helpdesk',
	'uniconnect', 'official', 'system', 'security', 'settings', 'account', 'accounts', 'login', 'logout', 'signup',
	'register', 'home', 'explore', 'search', 'notifications', 'messages', 'profile', 'bookmarks', 'communities',
	'groups', 'events', 'marketplace', 'bookshop', 'courses', 'timetable', 'hashtag', 'about', 'privacy', 'terms',
	'null', 'none', 'undefined', 'everyone', 'here', 'unn', 'unilag', 'student', 'students',
}


def is_matric_style(username):
	"""True for the starting usernames like "UNN-2022249381" (university + matric number)."""
	return bool(re.fullmatch(r'[A-Za-z]{2,10}-\d[\w\-]*', username or ''))


def taken(name, user=None):
	qs = User.objects.filter(username__iexact=name)
	if user is not None:
		qs = qs.exclude(pk=user.pk)
	return qs.exists()


def problem(name, user=None):
	"""Why `name` can't be used (a sentence), or '' if it can."""
	if not name:
		return 'Enter a username.'
	if len(name) < MIN_LEN:
		return f'Your username must be at least {MIN_LEN} characters.'
	if len(name) > MAX_LEN:
		return f'Your username must be {MAX_LEN} characters or fewer.'
	if not VALID.match(name):
		return 'Use only letters, numbers and underscores (_).'
	if name.lower() in RESERVED:
		return 'That username is reserved. Try another one.'
	if taken(name, user):
		return 'That username has been taken. Please choose another.'
	return ''


def suggestions(user, base='', limit=4):
	"""Free usernames built from the person's name (or what they typed)."""
	first = re.sub(r'\W', '', user.first_name or '').lower()
	last = re.sub(r'\W', '', user.last_name or '').lower()
	typed = re.sub(r'\W', '', base or '').lower()
	rng = random.Random(f'{user.pk}{typed}')
	ideas = []
	stems = [s for s in (typed, f'{first}_{last}', f'{first}{last}', f'{first}{last[:1]}', f'{last}_{first}', first) if s]
	for stem in stems:
		stem = stem[:MAX_LEN]
		ideas.append(stem)
		for _ in range(2):
			n = str(rng.randint(1, 999))
			ideas.append(stem[:MAX_LEN - len(n)] + n)
	out = []
	for name in ideas:
		if name not in out and not problem(name, user):
			out.append(name)
		if len(out) >= limit:
			break
	return out


def change(user, new):
	"""Set the new username and remember the old one. Returns the old one."""
	old = user.username
	if old == new:
		return old
	if old.lower() != new.lower():
		PreviousUsername.objects.create(user=user, username=old)
	PreviousUsername.objects.filter(username__iexact=new).delete()   # the name is someone's (yours) for real now
	user.username = new
	user.save(update_fields=['username'])
	return old


def redirect_target(username):
	"""The current username of whoever last used `username`, if nobody has it now."""
	prev = PreviousUsername.objects.filter(username__iexact=username).select_related('user').first()
	return prev.user.username if prev else None


@login_required
def check_username(request):
	name = (request.GET.get('u') or '').strip().lstrip('@')
	if name.lower() == request.user.username.lower() and name:
		return JsonResponse({'ok': True, 'same': True, 'message': "That's your username now.", 'suggestions': []})
	why = problem(name, request.user)
	return JsonResponse({
		'ok': not why, 'message': why or f'@{name} is available.',
		'suggestions': [] if not why else suggestions(request.user, name if VALID.match(name or '') else ''),
	})
