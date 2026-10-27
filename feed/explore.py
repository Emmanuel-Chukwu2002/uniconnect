"""The Explore page (/explore/, templates/feed/explore.html): one place to
discover things to join, as tabs:

    Communities    Popular Communities (every university; most members first)
                   and Suggested Groups (your university; your department and
                   your courses first)
    Groups         more suggested groups
    People         students at your university — classmates first (same department
                   and level, shared courses); ?skill=Python lists everyone with that skill
    Events         upcoming events
    Courses        courses at your university you haven't added
    Opportunities  open opportunities at your university

The search box filters whichever tab is open. Every Join / Register / Add /
Save button works in place (the page's script posts to the same endpoints
the other pages use).
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from communities.models import Community, CommunityMember
from .models import Attendee, Event

TABS = [('communities', 'Communities'), ('groups', 'Groups'), ('people', 'People'), ('events', 'Events'),
	('courses', 'Courses'), ('opportunities', 'Opportunities')]


def _words(q):
	return q.split()[:6]


def popular_communities(user, q, limit):
	qs = (Community.objects.select_related('university')
		.annotate(n_members=Count('memberships', filter=Q(memberships__status=CommunityMember.ACTIVE), distinct=True)))
	for w in _words(q):
		qs = qs.filter(Q(name__icontains=w) | Q(description__icontains=w) | Q(topic__icontains=w))
	rows = list(qs.order_by('-n_members', 'name')[:limit])
	mine = dict(CommunityMember.objects.filter(user=user, community__in=rows).values_list('community_id', 'status'))
	for c in rows:
		c.my_state = {CommunityMember.ACTIVE: 'joined', CommunityMember.PENDING: 'requested'}.get(mine.get(c.pk), '')
	return rows


def suggested_groups(user, student, q, limit):
	from courses.models import CourseEnrollment
	from studygroups.models import StudyGroup, StudyGroupMember as M
	states = dict(M.objects.filter(user=user).values_list('group_id', 'status'))
	qs = (StudyGroup.objects.filter(university=student.university).exclude(privacy=StudyGroup.INVITE)
		.exclude(pk__in=[g for g, s in states.items() if s == M.ACTIVE])
		.select_related('department')
		.annotate(n_members=Count('members', filter=Q(members__status=M.ACTIVE), distinct=True)))
	for w in _words(q):
		qs = qs.filter(Q(name__icontains=w) | Q(course_code__icontains=w) | Q(description__icontains=w) | Q(group_type__icontains=w))
	codes = {c.upper() for c in CourseEnrollment.objects.filter(user=user).values_list('course__code', flat=True)}
	rows = list(qs.order_by('-n_members')[:200])
	# Your courses first, then your department, then the biggest.
	rows.sort(key=lambda g: (g.course_code.upper() not in codes if g.course_code else True,
		g.department_id != student.department_id, -g.n_members))
	rows = [g for g in rows if (g.is_open and not g.is_full) or states.get(g.pk)][:limit]
	for g in rows:
		g.my_state = 'requested' if states.get(g.pk) == M.PENDING else ''
	return rows


def explore_people(user, student, q, skill, limit):
	from accounts.models import StudentProfile
	from courses.models import CourseEnrollment
	from .models import Follow, ProfileSkill
	qs = (StudentProfile.objects.filter(university=student.university, user__is_active=True).exclude(user=user)
		.select_related('user', 'department', 'level'))
	from .moderation import blocked_ids
	qs = qs.exclude(user_id__in=blocked_ids(user))
	if skill:
		qs = qs.filter(user__skills__name__iexact=skill)
	for w in _words(q):
		qs = qs.filter(Q(user__first_name__icontains=w) | Q(user__last_name__icontains=w) | Q(user__username__icontains=w)
			| Q(department__name__icontains=w) | Q(user__skills__name__icontains=w))
	people = list(qs.distinct()[:400])
	my_courses = set(CourseEnrollment.objects.filter(user=user).values_list('course_id', flat=True))
	shared = {}
	if my_courses:
		for uid in CourseEnrollment.objects.filter(course_id__in=my_courses, user__in=[p.user for p in people]).values_list('user_id', flat=True):
			shared[uid] = shared.get(uid, 0) + 1
	following = dict(Follow.objects.filter(follower=user, following__in=[p.user for p in people]).values_list('following_id', 'status'))
	people.sort(key=lambda p: (-(p.department_id == student.department_id and p.level_id == student.level_id),
		-shared.get(p.user_id, 0), p.department_id != student.department_id, p.user.first_name))
	people = people[:limit]
	skills = {}
	for s in ProfileSkill.objects.filter(user__in=[p.user for p in people]).order_by('created_at'):
		skills.setdefault(s.user_id, []).append(s.name)
	for p in people:
		p.skill_list = skills.get(p.user_id, [])
		p.shared_courses = shared.get(p.user_id, 0)
		p.classmate = p.department_id == student.department_id and p.level_id == student.level_id
		p.follow_status = following.get(p.user_id, 'none')
	return people


def top_skills(student, limit=12):
	from .models import ProfileSkill
	return list(ProfileSkill.objects.filter(user__student_profile__university=student.university)
		.values_list('name', flat=True).annotate(c=Count('id')).order_by('-c')[:limit])


def upcoming_events(user, q, limit):
	qs = Event.objects.filter(date__gte=timezone.localdate()).annotate(n_going=Count('attendees'))
	for w in _words(q):
		qs = qs.filter(Q(title__icontains=w) | Q(location__icontains=w) | Q(description__icontains=w))
	rows = list(qs.order_by('date', 'time')[:limit])
	mine = set(Attendee.objects.filter(user=user, event__in=rows).values_list('event_id', flat=True))
	for e in rows:
		e.registered = e.pk in mine
		e.full = e.capacity is not None and e.n_going >= e.capacity
		e.mine = e.organizer_id == user.pk
	return rows


def explore_courses(user, student, q, limit):
	from courses.models import Course
	qs = (Course.objects.filter(university=student.university).exclude(enrollments__user=user)
		.annotate(n_students=Count('enrollments', distinct=True)))
	for w in _words(q):
		qs = qs.filter(Q(code__icontains=w) | Q(title__icontains=w))
	return sorted(qs.order_by('-n_students', 'code')[:limit * 3],
		key=lambda c: (c.department_id != student.department_id, -c.n_students))[:limit]


def explore_opportunities(user, student, q, limit):
	from opportunities.models import Opportunity, OpportunitySave
	from opportunities.views import open_filter
	qs = Opportunity.objects.filter(university=student.university).filter(open_filter())
	for w in _words(q):
		qs = qs.filter(Q(title__icontains=w) | Q(organization__icontains=w) | Q(kind__icontains=w))
	rows = list(qs.order_by('deadline', '-created_at')[:limit])
	saved = set(OpportunitySave.objects.filter(user=user, opportunity__in=rows).values_list('opportunity_id', flat=True))
	for o in rows:
		o.saved = o.pk in saved
	return rows


@login_required
def explore_page(request):
	student = getattr(request.user, 'student_profile', None)
	tab = request.GET.get('tab', 'communities')
	if tab not in dict(TABS):
		tab = 'communities'
	q = ' '.join(request.GET.get('q', '').split())[:80]
	ctx = {'tabs': TABS, 'tab': tab, 'q': q}
	if student and not q:
		from .search import trending_hashtags
		ctx['trending'] = trending_hashtags(student, limit=10)
	if student:
		if tab == 'communities':
			ctx['communities'] = popular_communities(request.user, q, 6 if not q else 20)
			ctx['groups'] = suggested_groups(request.user, student, q, 4 if not q else 10)
		elif tab == 'groups':
			ctx['groups'] = suggested_groups(request.user, student, q, 30)
		elif tab == 'people':
			skill = ' '.join(request.GET.get('skill', '').split())[:40]
			ctx['skill'] = skill
			ctx['people'] = explore_people(request.user, student, q, skill, 40)
			ctx['top_skills'] = top_skills(student)
		elif tab == 'events':
			ctx['events'] = upcoming_events(request.user, q, 30)
		elif tab == 'courses':
			ctx['courses'] = explore_courses(request.user, student, q, 30)
		else:
			ctx['opportunities'] = explore_opportunities(request.user, student, q, 30)
	return render(request, 'feed/explore.html', ctx)
