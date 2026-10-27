"""Who may do what in the admin dashboard — checked on the server for every page
and every action (hiding a button is never the protection).

Roles (adminpanel.models.AdminRole):

                         Super    University  Moderator   Support
                         Admin    Admin                   Staff
  view dashboard          yes      yes         yes         yes
  view users              yes      yes         yes         yes
  private details*        yes      yes         -           yes
  verify students         yes      yes         -           yes
  warn                    yes      yes         yes         -
  suspend / reactivate    yes      yes         -           -
  review reports          yes      yes         yes         -
  remove content          yes      yes         yes         -
  universities: add/edit  yes      -           -           -
  faculties/departments   yes      own uni     -           -
  official timetable      yes      own uni     -           -
  announcements           all      own uni     -           -
  analytics               yes      own uni     yes         -
  admin logs              yes      own uni     -           -
  assign roles            yes      mods/support of own uni   -
  * university email, matric number, date of birth

Scope: a University Admin only ever sees and acts on their own university's
students and content. Moderators and Support Staff with a university are
limited the same way; without one they work across universities. Super Admins
see everything. Scope is applied to every queryset (scope_q) and every single
object (in_scope), so a URL for another university's record returns 404.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q

from .models import AdminRole as R

VIEW = 'view'
VIEW_USERS = 'view_users'
PRIVATE = 'private_details'
VERIFY = 'verify'
WARN = 'warn'
SUSPEND = 'suspend'
REVIEW = 'review_reports'
REMOVE = 'remove_content'
UNIVERSITIES = 'manage_universities'
STRUCTURE = 'manage_structure'
ANNOUNCE = 'announce'
ANNOUNCE_ALL = 'announce_all'
ANALYTICS = 'analytics'
LOGS = 'logs'
ROLES = 'assign_roles'
TIMETABLE = 'official_timetable'

PERMS = {
	R.SUPER_ADMIN: {VIEW, VIEW_USERS, PRIVATE, VERIFY, WARN, SUSPEND, REVIEW, REMOVE, UNIVERSITIES, STRUCTURE,
		ANNOUNCE, ANNOUNCE_ALL, ANALYTICS, LOGS, ROLES, TIMETABLE},
	R.UNIVERSITY_ADMIN: {VIEW, VIEW_USERS, PRIVATE, VERIFY, WARN, SUSPEND, REVIEW, REMOVE, STRUCTURE, ANNOUNCE,
		ANALYTICS, LOGS, ROLES, TIMETABLE},
	R.MODERATOR: {VIEW, VIEW_USERS, WARN, REVIEW, REMOVE, ANALYTICS},
	R.SUPPORT: {VIEW, VIEW_USERS, PRIVATE, VERIFY},
}
# Roles a University Admin may hand out (always within their own university).
UNI_ADMIN_CAN_ASSIGN = {R.MODERATOR, R.SUPPORT}


class Admin:
	"""The signed-in administrator: role, scope and permissions."""

	def __init__(self, user, role, university=None):
		self.user = user
		self.role = role
		self.university = university if role != R.SUPER_ADMIN else None
		self.perms = PERMS[role]

	@property
	def role_label(self):
		return dict(R.ROLE_CHOICES)[self.role]

	@property
	def university_id(self):
		return self.university.pk if self.university else None

	@property
	def is_super(self):
		return self.role == R.SUPER_ADMIN

	def can(self, perm):
		return perm in self.perms

	def require(self, perm):
		if not self.can(perm):
			raise PermissionDenied('Your admin role does not allow this.')

	def scope_q(self, field):
		"""Q limiting a queryset to this admin's university. `field` is the lookup
		of a University (e.g. 'student_profile__university')."""
		if self.university is None:
			return Q()
		return Q(**{field: self.university})

	def in_scope(self, university_id):
		return self.university is None or university_id == self.university.pk


def admin_for(user):
	"""Admin for this user, or None if they may not use the dashboard."""
	if not getattr(user, 'is_authenticated', False) or not user.is_active:
		return None
	if user.is_superuser:
		return Admin(user, R.SUPER_ADMIN)
	role = getattr(user, '_admin_role_cache', None)
	if role is None:
		role = R.objects.select_related('university').filter(user=user).first() or False
		user._admin_role_cache = role
	if role:
		return Admin(user, role.role, role.university)
	if user.is_staff:
		return Admin(user, R.MODERATOR)          # staff before roles existed: platform-wide moderator
	return None


def admin_required(perm=VIEW):
	"""View decorator: signed in, a dashboard role, and `perm`. Passes request.admin."""
	def wrap(view):
		@login_required
		@wraps(view)
		def inner(request, *args, **kwargs):
			admin = admin_for(request.user)
			if admin is None:
				raise PermissionDenied('The admin dashboard is for UniConnect staff.')
			admin.require(perm)
			request.admin = admin
			return view(request, *args, **kwargs)
		return inner
	return wrap
