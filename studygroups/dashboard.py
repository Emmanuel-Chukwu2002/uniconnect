"""Course Companion's Study Groups page (/courses/my/groups/, courses/views.py
my_section): your study groups (Academic groups), Recent Activity, your
Leaderboard, Picked For You, Popular Groups and the Campus Leaderboard.

Study points (for the leaderboards), counted over study groups at your university:
    a post you wrote              10
    a comment you wrote            5
    an upvote on your post         2
"""
from django.db.models import Count, Q

from feed.closeness import friend_ids
from .discover import prepare
from .models import GroupComment, GroupPost, GroupPostLike, StudyGroup, StudyGroupMember as M

# Gradient tiles, as in the design: (from, to). A group keeps its colour (by id).
GRADIENTS = [
	('#ffb23f', '#ff6a3d'),   # orange
	('#7ee08a', '#2fbf71'),   # green
	('#ff7eb3', '#ff4f6d'),   # pink → red
	('#4fc3ff', '#2f6bff'),   # sky → blue
	('#c86bff', '#ff5fa2'),   # purple → pink
	('#ff9a5a', '#ff4f8b'),   # coral
	('#43e0c6', '#2b9bff'),   # teal → blue
	('#7b6bff', '#4f46e5'),   # indigo
	('#ffd23f', '#ff9f1c'),   # yellow → orange
]
POINTS = {'post': 10, 'comment': 5, 'upvote': 2}


def paint(groups):
	for g in groups:
		a, b = g.gradient
		g.grad = f'linear-gradient(135deg,{a},{b})'
		g.grad_a = a
	return groups


def _counted(qs):
	return qs.annotate(n_members=Count('members', filter=Q(members__status=M.ACTIVE), distinct=True))


def recent_activity(groups, limit=12):
	return list(GroupPost.objects.filter(group__in=groups).select_related('author', 'author__student_profile', 'group')
		.annotate(n_likes=Count('likes', distinct=True), n_comments=Count('comments', distinct=True))
		.order_by('-created_at')[:limit])


def points(groups):
	"""{user_id: points} from activity in these groups."""
	pts = {}
	for uid, n in GroupPost.objects.filter(group__in=groups).values('author').annotate(n=Count('id')).values_list('author', 'n'):
		pts[uid] = pts.get(uid, 0) + n * POINTS['post']
	for uid, n in GroupComment.objects.filter(post__group__in=groups).values('author').annotate(n=Count('id')).values_list('author', 'n'):
		pts[uid] = pts.get(uid, 0) + n * POINTS['comment']
	for uid, n in GroupPostLike.objects.filter(post__group__in=groups).values('post__author').annotate(n=Count('id')).values_list('post__author', 'n'):
		pts[uid] = pts.get(uid, 0) + n * POINTS['upvote']
	return pts


def leaderboards(student, user, groups, my_ids):
	from django.contrib.auth import get_user_model
	pts = points(groups)
	ranked = sorted(pts.items(), key=lambda kv: (-kv[1], kv[0]))
	rank = {uid: i + 1 for i, (uid, _) in enumerate(ranked)}
	dept_ids = set(get_user_model().objects.filter(student_profile__department=student.department).values_list('pk', flat=True))
	dept_ranked = [uid for uid, _ in ranked if uid in dept_ids]
	friends = friend_ids(user)
	friends_label = 'Your friends'
	if len(friends) < 3:
		# Few follows yet: rank the people in your study groups instead.
		mates = set(M.objects.filter(group__in=my_ids, status=M.ACTIVE).exclude(user=user).values_list('user_id', flat=True))
		friends_label = 'Your friends & groupmates' if friends else 'People in your study groups'
		friends = friends | set(sorted(mates, key=lambda u: -pts.get(u, 0))[:12])
	top_ids = [uid for uid, _ in ranked[:10]]
	friend_rows = sorted(((uid, pts.get(uid, 0)) for uid in friends | {user.pk}), key=lambda kv: (-kv[1], kv[0]))[:10]
	people = get_user_model().objects.select_related('student_profile').in_bulk(set(top_ids) | {uid for uid, _ in friend_rows})

	def rows(pairs):
		return [{'user': people[uid], 'points': p, 'me': uid == user.pk, 'rank': rank.get(uid)} for uid, p in pairs if uid in people]
	return {
		'my_points': pts.get(user.pk, 0),
		'campus_rank': rank.get(user.pk),
		'dept_rank': dept_ranked.index(user.pk) + 1 if user.pk in dept_ranked else None,
		'friends': rows(friend_rows),
		'friends_label': friends_label,
		'top': rows([(uid, pts[uid]) for uid in top_ids]),
		'points_rule': POINTS,
	}


def build(student, user, codes=(), only_code=''):
	"""`codes`: your courses' codes — their study groups are picked first.
	`only_code`: one course chosen with the round buttons (everything is limited to it)."""
	from courses.models import normalise_code
	base = StudyGroup.objects.filter(university=student.university, group_type=StudyGroup.ACADEMIC)
	if only_code:
		base = base.filter(course_code__iexact=only_code)
	my_ids = set(M.objects.filter(user=user, status=M.ACTIVE, group__in=base).values_list('group_id', flat=True))
	mine = paint(list(_counted(base.filter(pk__in=my_ids)).order_by('-created_at')))
	others = prepare(list(_counted(base.exclude(privacy=StudyGroup.INVITE).exclude(pk__in=my_ids))
		.select_related('department').order_by('-created_at')[:400]), user)
	mycodes = {normalise_code(c) for c in codes}
	open_ = [g for g in others if g.is_open and not g.is_full and g.my_state != 'requested']
	picked = sorted(open_, key=lambda g: (normalise_code(g.course_code or '') not in mycodes,
		g.department_id != student.department_id, -g.known, -g.n_members))[:4]
	shown = {g.pk for g in picked}
	popular = sorted((g for g in others if g.pk not in shown), key=lambda g: (-g.n_members, -g.pk))[:6]
	return {
		'my_groups': mine,
		'activity': recent_activity(list(my_ids)),
		'picked': paint(picked),
		'popular': paint(popular),
		'board': leaderboards(student, user, base, my_ids),
	}
