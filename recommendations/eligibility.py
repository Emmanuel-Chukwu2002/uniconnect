"""Who a student is, for recommendations — and the student eligibility rule.

THE RULE. Another student can only reach you through a student-based
recommendation (People You May Know, "from people you know", "popular with
your faculty") if at least one of these holds:

    1. you follow them (an accepted follow: a pending request isn't a follow yet)
    2. you are both in the same faculty
    3. you are both in the same department

Faculty and department are rows tied to one university (accounts.Faculty /
accounts.Department), so "same faculty" also means "same university".

Content is not a student: a book, listing, event, group or community is
recommended if the student may *access* it (each feature's own rules in
engine.py). The rule decides which students' relationships and activity may
*count* towards it: the creator's closeness only counts if the creator is
eligible, and social proof ("popular with people you know") only counts
activity by eligible students.

Viewer gathers everything about the requesting student once per request, so
the features don't each re-query it.
"""
from functools import cached_property

from django.db.models import Q

from accounts.models import StudentProfile


class Viewer:
	def __init__(self, user):
		self.user = user
		try:
			self.profile = user.student_profile if getattr(user, 'is_authenticated', False) else None
		except StudentProfile.DoesNotExist:
			self.profile = None

	@property
	def is_student(self):
		return self.profile is not None

	# --- relationships -------------------------------------------------
	@cached_property
	def following(self):
		"""Accepted follows only."""
		from feed.models import Follow
		return set(Follow.objects.filter(follower=self.user, status=Follow.STATUS_ACCEPTED).values_list('following_id', flat=True))

	@cached_property
	def requested(self):
		"""Follow requests still waiting for approval."""
		from feed.models import Follow
		return set(Follow.objects.filter(follower=self.user, status=Follow.STATUS_PENDING).values_list('following_id', flat=True))

	@cached_property
	def blocked(self):
		"""Blocked either way (feed/moderation.py)."""
		from feed.moderation import blocked_ids
		return set(blocked_ids(self.user))

	@cached_property
	def muted(self):
		from feed.post_settings import muted_ids
		return set(muted_ids(self.user))

	@cached_property
	def hidden_people(self):
		"""People never shown to this student in recommendations."""
		return self.blocked | self.muted

	# --- the eligibility rule -----------------------------------------
	def eligible_q(self, prefix=''):
		"""Q for StudentProfile (or anything with a student profile at `prefix`)
		matching students who satisfy the rule. Never matches anyone when the
		requester has no student profile."""
		p = prefix
		if not self.is_student:
			return Q(pk__in=[])
		return (Q(**{f'{p}user_id__in': self.following})
			| Q(**{f'{p}faculty_id': self.profile.faculty_id})
			| Q(**{f'{p}department_id': self.profile.department_id}))

	@cached_property
	def eligible_ids(self):
		"""User ids of every eligible student (active accounts, not blocked or muted, not you)."""
		if not self.is_student:
			return set()
		ids = set(StudentProfile.objects.filter(self.eligible_q(), user__is_active=True).values_list('user_id', flat=True))
		ids.discard(self.user.pk)
		return ids - self.hidden_people

	def is_eligible(self, other_profile):
		"""The rule for one StudentProfile (no query)."""
		if not self.is_student or other_profile is None or other_profile.user_id == self.user.pk:
			return False
		return (other_profile.user_id in self.following
			or other_profile.faculty_id == self.profile.faculty_id
			or other_profile.department_id == self.profile.department_id)

	def closeness(self, other_user_id, profiles):
		"""How close an eligible student is, 0..1 (0 = not eligible). `profiles`
		maps user id -> (faculty_id, department_id)."""
		if other_user_id == self.user.pk or other_user_id in self.hidden_people:
			return 0.0
		fac, dept = profiles.get(other_user_id, (None, None))
		score = 0.0
		if other_user_id in self.following:
			score = 1.0
		if dept is not None and dept == self.profile.department_id:
			score = max(score, 0.8)
		elif fac is not None and fac == self.profile.faculty_id:
			score = max(score, 0.6)
		return score

	# --- academic context ---------------------------------------------
	@cached_property
	def course_codes(self):
		"""Your courses, normalised ('COS401')."""
		from courses.models import CourseEnrollment
		return {norm_code(c) for c in CourseEnrollment.objects.filter(user=self.user).values_list('course__code', flat=True)}

	@cached_property
	def community_ids(self):
		"""Communities you're a member of (active)."""
		from communities.models import CommunityMember
		return set(CommunityMember.objects.filter(user=self.user, status=CommunityMember.ACTIVE).values_list('community_id', flat=True))

	# --- explicit feedback --------------------------------------------
	def feedback(self, item_type):
		from .feedback import feedback_map
		cache = self.__dict__.setdefault('_feedback', {})
		if item_type not in cache:
			cache[item_type] = feedback_map(self.user, item_type)
		return cache[item_type]


def norm_code(code):
	return ''.join((code or '').upper().split())


def profiles_of(user_ids):
	"""user id -> (faculty_id, department_id), one query."""
	return {u: (f, d) for u, f, d in StudentProfile.objects.filter(user_id__in=set(user_ids))
		.values_list('user_id', 'faculty_id', 'department_id')}
