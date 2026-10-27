"""
"Who to follow": students at your university you don't follow yet
(and haven't asked to follow). Used by the right sidebar box (first 4)
and the Who to follow page (everyone, 20 per page), so both show
people in the same order: your own department first, then by name.
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import JsonResponse

from accounts.models import StudentProfile
from .models import Follow

SIDEBAR_COUNT = 4


from .moderation import blocked_ids


def people_to_follow(user, query=''):
	student = getattr(user, 'student_profile', None)
	if student is None:
		return StudentProfile.objects.none()
	followed = Follow.objects.filter(follower=user).values_list('following_id', flat=True)
	qs = (
		StudentProfile.objects.filter(university=student.university, user__is_active=True)
		.exclude(user=user).exclude(user_id__in=followed).exclude(user_id__in=blocked_ids(user))
		.select_related('user', 'department', 'level')
		.annotate(same_dept=Case(When(department_id=student.department_id, then=Value(1)), default=Value(0), output_field=IntegerField()))
		.order_by('-same_dept', 'user__first_name', 'user__last_name', 'user__username')
	)
	query = (query or '').strip()
	if query:
		for word in query.split():
			qs = qs.filter(Q(user__first_name__icontains=word) | Q(user__last_name__icontains=word) | Q(user__username__icontains=word) | Q(department__name__icontains=word))
	return qs


# ---------------------------------------------------------------------
# The Who to follow page, in groups (templates/feed/who_to_follow.html):
# closest first — your coursemates, then your department, faculty,
# university, and students at other universities. Inside each group,
# people more of your friends follow come first ("2 mutual connections").
# ---------------------------------------------------------------------

PREVIEW = 3          # cards shown per group before "See all"
SECTION_PAGE = 24    # cards per page on a group's "See all"


def _candidates(user):
	"""Everyone you might follow: active students, not you, not already
	followed or requested, not blocked either way."""
	asked = Follow.objects.filter(follower=user).values_list('following_id', flat=True)
	return (StudentProfile.objects.filter(user__is_active=True).exclude(user=user)
		.exclude(user_id__in=asked).exclude(user_id__in=blocked_ids(user))
		.select_related('user', 'department', 'level', 'faculty', 'university'))


def sections_for(user):
	"""[(key, title, subtitle, queryset)] — the groups, closest first."""
	me = getattr(user, 'student_profile', None)
	if me is None:
		return []
	base = _candidates(user)
	uni = me.university.short_name or me.university.name
	return [
		('coursemates', 'Your coursemates', f'{me.department.name} · {me.level.name}',
			base.filter(university=me.university, department=me.department, level=me.level)),
		('department', 'From your department', f'{me.department.name}, other levels',
			base.filter(university=me.university, department=me.department).exclude(level=me.level)),
		('faculty', 'From your faculty', f'{me.faculty.name}, other departments',
			base.filter(university=me.university, faculty=me.faculty).exclude(department=me.department)),
		('university', f'Across {uni}', 'Students in other faculties at your university',
			base.filter(university=me.university).exclude(faculty=me.faculty)),
		('elsewhere', 'At other universities', 'Students elsewhere on UniConnect',
			base.exclude(university=me.university)),
	]


def ranked(user, qs):
	"""People more of your friends follow first, then by name."""
	from django.db.models import Count
	friends = Follow.objects.filter(follower=user, status=Follow.STATUS_ACCEPTED).values('following_id')
	return qs.annotate(mutual=Count('user__followers', distinct=True,
		filter=Q(user__followers__status=Follow.STATUS_ACCEPTED, user__followers__follower_id__in=friends))
	).order_by('-mutual', 'user__first_name', 'user__last_name', 'user__username')


def with_mutual_faces(user, people):
	"""Adds .mutual_faces: up to two of your friends who follow each person."""
	people = list(people)
	if not people:
		return people
	friends = list(Follow.objects.filter(follower=user, status=Follow.STATUS_ACCEPTED).values_list('following_id', flat=True))
	rows = (Follow.objects.filter(following_id__in=[p.user_id for p in people], follower_id__in=friends,
		status=Follow.STATUS_ACCEPTED).select_related('follower', 'follower__student_profile').order_by('-created_at'))
	faces = {}
	for f in rows:
		faces.setdefault(f.following_id, [])
		if len(faces[f.following_id]) < 2:
			faces[f.following_id].append(f.follower)
	for p in people:
		p.cover_hue = (p.user_id * 47) % 360          # a steady colour for people without a cover photo
		p.mutual_faces = faces.get(p.user_id, [])
		if not hasattr(p, 'mutual'):
			p.mutual = len(p.mutual_faces)
	return people


def mention_suggestions(user, query, limit=6):
	"""People to suggest after "@" in a post or comment box: students at your
	university (never anyone blocked either way), people you follow first,
	then your department, then names that start with what you typed."""
	student = getattr(user, 'student_profile', None)
	if student is None:
		return []
	query = (query or '').strip().lstrip('@')[:30]
	following = set(Follow.objects.filter(follower=user, status=Follow.STATUS_ACCEPTED).values_list('following_id', flat=True))
	qs = (StudentProfile.objects.filter(university=student.university, user__is_active=True)
		.exclude(user=user).exclude(user_id__in=blocked_ids(user))
		.select_related('user', 'department'))
	if query:
		for word in query.replace('_', ' ').split():
			qs = qs.filter(Q(user__first_name__icontains=word) | Q(user__last_name__icontains=word) | Q(user__username__icontains=word))
	elif following:
		qs = qs.filter(user_id__in=following)
	else:
		qs = qs.filter(department_id=student.department_id)
	q = query.lower()

	def rank(p):
		u = p.user
		starts = any(x.lower().startswith(q) for x in (u.first_name, u.last_name, u.username) if x) if q else True
		return (u.pk not in following, not starts, p.department_id != student.department_id, (u.first_name or u.username).lower())
	people = sorted(qs[:200], key=rank)[:limit]
	return [{
		'username': p.user.username,
		'name': p.user.get_full_name() or p.user.username,
		'photo': p.profile_photo.url if p.profile_photo else '',
		'detail': ('You follow · ' if p.user_id in following else '') + (p.department.name if p.department_id else ''),
		'verified': bool(getattr(p, 'is_verified', False)),
	} for p in people]


@login_required
def mention_search(request):
	"""GET /people/mention/?q=ad — JSON for the @mention suggestions (static/js/mentions.js)."""
	return JsonResponse({'people': mention_suggestions(request.user, request.GET.get('q', ''))})
