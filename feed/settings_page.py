"""The Settings page (/settings/, templates/feed/settings.html).

One page, one small form per section. Each form says which section it is
(a hidden "section" field), so saving one never touches the others:

    username       your @handle (X's rules, feed/usernames.py)
    account        name and level (university, faculty, department, matric
                   number and email are fixed: they were verified at sign-up)
    password       change password (stays signed in here, signs out elsewhere)
    privacy        show date of birth on the profile
    notifications  which kinds of notification to receive
    sessions       sign out on every other device
    delete         delete the account (needs the password)

Light/Dark mode is chosen in the browser (static/js/app.js keeps it in
localStorage), so that section has no form.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.sessions.models import Session
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import Level, StudentProfile
from .models import Notification as N
from .usernames import is_matric_style

# Settings > Notifications: each switch covers one or more notification types.
# Follow requests are left out on purpose — every follow needs approval, so
# switching those off would leave people waiting forever.
NOTIFICATION_GROUPS = [
	('likes', 'Likes', 'When someone likes your post or comment', 'bi-heart', [N.LIKE_POST, N.LIKE_COMMENT]),
	('comments', 'Comments and replies', 'When someone comments on your post or replies to you', 'bi-chat', [N.COMMENT, N.REPLY]),
	('mentions', 'Mentions', 'When someone @mentions you (posts, comments and group chats)', 'bi-at', [N.MENTION, N.CHAT_MENTION]),
	('reposts', 'Reposts and quotes', 'When someone reposts or quotes your post', 'bi-repeat', [N.REPOST, N.QUOTE]),
	('followers', 'New followers', 'When someone follows you or accepts your request', 'bi-person-plus', [N.FOLLOW, N.FOLLOW_ACCEPTED]),
	('events', 'Events', 'When someone registers for your event', 'bi-calendar-event', [N.EVENT_REGISTER]),
	('marketplace', 'Marketplace', 'When someone adds your listing to their cart', 'bi-shop', [N.LISTING_CART]),
	('communities', 'Communities', 'Joins, join requests and approvals', 'bi-people', [N.COMMUNITY_JOIN, N.COMMUNITY_REQUEST, N.COMMUNITY_ACCEPTED]),
	('groups', 'Groups', 'Announcements, study sessions, join requests and approvals', 'bi-collection', [N.GROUP_ANNOUNCEMENT, N.GROUP_REQUEST, N.GROUP_ACCEPTED, N.GROUP_SESSION, N.SESSION_REMINDER, N.SESSION_CHANGED]),
	('courses', 'Course Companion', 'Answers to your course questions, and classes your department cancels or moves', 'bi-mortarboard', [N.COURSE_ANSWER, N.CLASS_CHANGED]),
	('reminders', 'Class reminders', '15 minutes before each class on your timetable', 'bi-alarm', [N.CLASS_REMINDER]),
]


class AccountForm(forms.Form):
	first_name = forms.CharField(max_length=100, label='First name')
	last_name = forms.CharField(max_length=100, label='Surname')
	level = forms.ModelChoiceField(queryset=Level.objects.none(), label='Level', empty_label=None)

	def __init__(self, *args, student, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['level'].queryset = Level.objects.filter(department=student.department)


class DeleteAccountForm(forms.Form):
	password = forms.CharField(widget=forms.PasswordInput, label='Your password')

	def __init__(self, *args, user, **kwargs):
		self.user = user
		super().__init__(*args, **kwargs)

	def clean_password(self):
		if not self.user.check_password(self.cleaned_data['password']):
			raise forms.ValidationError("That password isn't right.")
		return self.cleaned_data['password']


def _sign_out_other_devices(request):
	"""Ends every other signed-in session of this user; returns how many."""
	count = 0
	for s in Session.objects.filter(expire_date__gt=timezone.now()).exclude(session_key=request.session.session_key).iterator():
		if str(s.get_decoded().get('_auth_user_id')) == str(request.user.pk):
			s.delete()
			count += 1
	return count


# Settings opens on a menu (Account & Profile, Notifications, ...); each item
# opens its own screen at /settings/?s=<panel>. Which screen each form is on:
PANEL_OF_SECTION = {
	'account': 'account', 'username': 'account', 'notifications': 'notifications',
	'password': 'security', 'privacy': 'security', 'sessions': 'security', 'delete': 'delete',
}
PANELS = {
	'account': 'Account & Profile', 'notifications': 'Notifications', 'security': 'Privacy & Security',
	'appearance': 'Appearance', 'help': 'Help & Support', 'delete': 'Delete account',
}


def _back_to(section):
	return redirect(f"{reverse('account_settings')}?s={PANEL_OF_SECTION[section]}")


@login_required
def settings_page(request):
	user = request.user
	student = get_object_or_404(StudentProfile.objects.select_related('university', 'faculty', 'department', 'level'), user=user)
	muted = set(student.muted_notifications or [])
	section = request.POST.get('section') if request.method == 'POST' else None

	account_form = AccountForm(
		request.POST if section == 'account' else None, student=student,
		initial={'first_name': user.first_name, 'last_name': user.last_name, 'level': student.level_id},
	)
	password_form = PasswordChangeForm(user, request.POST if section == 'password' else None)
	delete_form = DeleteAccountForm(request.POST if section == 'delete' else None, user=user)

	if section == 'account' and account_form.is_valid():
		user.first_name = account_form.cleaned_data['first_name'].strip()
		user.last_name = account_form.cleaned_data['last_name'].strip()
		user.save(update_fields=['first_name', 'last_name'])
		student.level = account_form.cleaned_data['level']
		student.save(update_fields=['level'])
		messages.success(request, 'Account details saved.')
		return _back_to('account')

	username_error = ''
	if section == 'username':
		from . import usernames
		new = (request.POST.get('username') or '').strip().lstrip('@')
		if new == user.username:
			return _back_to('username')
		username_error = usernames.problem(new, user)
		if not username_error:
			usernames.change(user, new)
			messages.success(request, f'Your username is now @{new}.')
			return _back_to('username')
		messages.error(request, username_error)

	if section == 'password' and password_form.is_valid():
		password_form.save()
		update_session_auth_hash(request, password_form.user)   # stay signed in on this device
		messages.success(request, 'Password changed. Any other devices have been signed out.')
		return _back_to('password')

	# The switches save themselves as they're flipped (settings.html script):
	# those requests just get {"ok": true}, no page and no pop-up message.
	quiet = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

	if section == 'privacy':
		student.show_date_of_birth = bool(request.POST.get('show_date_of_birth'))
		student.save(update_fields=['show_date_of_birth'])
		if quiet:
			return JsonResponse({'ok': True})
		messages.success(request, 'Privacy settings saved.')
		return _back_to('privacy')

	if section == 'notifications':
		chosen = set(request.POST.getlist('on'))
		student.muted_notifications = sorted(t for key, _, _, _, types in NOTIFICATION_GROUPS if key not in chosen for t in types)
		student.save(update_fields=['muted_notifications'])
		if quiet:
			return JsonResponse({'ok': True})
		messages.success(request, 'Notification settings saved.')
		return _back_to('notifications')

	if section == 'sessions':
		n = _sign_out_other_devices(request)
		messages.success(request, f'Signed out of {n} other device{"" if n == 1 else "s"}.' if n else 'You were not signed in anywhere else.')
		return _back_to('sessions')

	if section == 'delete' and delete_form.is_valid():
		logout(request)
		user.delete()   # removes the profile, posts, comments, messages ... with it
		messages.success(request, 'Your account has been deleted.')
		return redirect('login')

	if section in ('account', 'password', 'delete'):
		messages.error(request, 'Please fix the highlighted fields.')

	groups = [
		{'key': key, 'label': label, 'help': help_text, 'icon': icon, 'on': not any(t in muted for t in types)}
		for key, label, help_text, icon, types in NOTIFICATION_GROUPS
	]
	from .models import Block
	blocked = list(Block.objects.filter(blocker=user).select_related('blocked', 'blocked__student_profile'))
	from .models import Mute
	muted = list(Mute.objects.filter(muter=user).select_related('muted', 'muted__student_profile'))
	return render(request, 'feed/settings.html', {
		'student': student,
		'blocked_accounts': blocked,
		'username_error': username_error,
		'username_value': (request.POST.get('username') or '').strip().lstrip('@') if section == 'username' else user.username,
		'username_is_default': is_matric_style(user.username),
		'muted_accounts': muted,
		'account_form': account_form,
		'password_form': password_form,
		'delete_form': delete_form,
		'notification_groups': groups,
		'open_section': section,
		'panel': PANEL_OF_SECTION.get(section) or (request.GET.get('s') if request.GET.get('s') in PANELS else ''),
		'panel_title': PANELS.get(PANEL_OF_SECTION.get(section) or request.GET.get('s'), 'Settings'),
	})
