"""People You May Know.

Candidates must satisfy the eligibility rule (eligibility.py). People you
already follow (or asked to follow) are left out — following is the action
this list leads to — so in practice suggestions are students in your faculty
or department. Also left out: you, anyone blocked either way, anyone you
muted, deactivated accounts, and anyone you dismissed with Not interested.

Ranking (all from data the app already has):
    mutual connections   people you follow who follow them (accepted follows)
    follows you          they follow you and you don't follow back
    same class           same department and level
    shared courses       courses you both take (courses.CourseEnrollment)
    same department / same faculty
    interest             you marked one of their posts Interested

Nothing private is shown: the reason line uses counts ("3 mutual connections",
"Takes 2 of your courses"), never names or other people's data.
Following uses the existing follow request (feed: /follow/<id>/), never automatic.
"""
from django.db.models import Count

from accounts.models import StudentProfile
from .eligibility import Viewer
from .models import Feedback as F

POOL = 500


def people_you_may_know(user, limit=8, viewer=None):
	v = viewer or Viewer(user)
	if not v.is_student:
		return []
	from feed.models import Follow, Post
	dismissed = {i for i, val in v.feedback(F.USER).items() if val == F.NOT_INTERESTED}
	excluded = {v.user.pk} | v.following | v.requested | v.hidden_people | dismissed
	me = v.profile
	people = list(StudentProfile.objects.filter(v.eligible_q(), user__is_active=True)
		.exclude(user_id__in=excluded)
		.select_related('user', 'department', 'level', 'faculty')
		.order_by('-created_at')[:POOL])
	if not people:
		return []
	ids = [p.user_id for p in people]

	mutual = dict(Follow.objects.filter(follower_id__in=v.following, following_id__in=ids, status=Follow.STATUS_ACCEPTED)
		.values('following_id').annotate(n=Count('follower_id', distinct=True)).values_list('following_id', 'n'))
	follows_me = set(Follow.objects.filter(follower_id__in=ids, following=v.user, status=Follow.STATUS_ACCEPTED)
		.values_list('follower_id', flat=True))
	shared = {}
	from courses.models import CourseEnrollment
	my_courses = CourseEnrollment.objects.filter(user=v.user).values('course_id')
	for uid, n in (CourseEnrollment.objects.filter(user_id__in=ids, course_id__in=my_courses)
			.values('user_id').annotate(n=Count('course_id', distinct=True)).values_list('user_id', 'n')):
		shared[uid] = n
	liked_posts = [i for i, val in v.feedback(F.POST).items() if val == F.INTERESTED]
	liked_authors = set(Post.objects.filter(pk__in=liked_posts, author_id__in=ids).values_list('author_id', flat=True))

	for p in people:
		m, s = mutual.get(p.user_id, 0), shared.get(p.user_id, 0)
		same_dept = p.department_id == me.department_id
		same_class = same_dept and p.level_id == me.level_id
		parts = {
			'mutual': 0.35 * min(1.0, m / 3),
			'follows_you': 0.25 if p.user_id in follows_me else 0.0,
			'class': 0.10 if same_class else 0.0,
			'courses': 0.20 * min(1.0, s / 3),
			'department': 0.20 if same_dept else 0.0,
			'faculty': 0.10 if p.faculty_id == me.faculty_id else 0.0,
			'interest': 0.15 if p.user_id in liked_authors else 0.0,
		}
		p.pymk_score = sum(parts.values())
		p.mutual = m
		if p.user_id in follows_me:
			p.pymk_reason = 'Follows you'
		elif m:
			p.pymk_reason = f'{m} mutual connection{"s" if m != 1 else ""}'
		elif same_class:
			p.pymk_reason = 'In your class'
		elif s:
			p.pymk_reason = f'Takes {s} of your courses'
		elif same_dept:
			p.pymk_reason = 'In your department'
		else:
			p.pymk_reason = 'In your faculty'
	people.sort(key=lambda p: (-p.pymk_score, p.user.first_name.lower(), p.user.username))
	return people[:limit]
