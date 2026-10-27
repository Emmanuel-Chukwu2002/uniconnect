"""Discover on the Groups page, closest first (like Who to follow):

    For your class        your department and level
    Your department       your department, other levels or all levels
    Your faculty          other departments in your faculty
    Around <university>   everything else — hostels, clubs, other faculties

Groups you're already in are left out (they're under "My groups").
Within a section: groups more people you follow are in first, then bigger,
then newer. Cards: templates/studygroups/_pc_card.html.
"""
from django.db.models import Count, Q

from feed.closeness import attach_faces, friend_ids, hue, split
from .models import StudyGroup, StudyGroupMember as M

LIMIT = 600   # groups looked at for the sections
TYPE_HUES = {'academic': 215, 'project': 265, 'departmental': 8, 'hostel': 150, 'social': 330, 'professional': 32}


def _counted(qs):
	return qs.annotate(n_members=Count('members', filter=Q(members__status=M.ACTIVE), distinct=True))


def candidates(student, user, kind=''):
	mine = M.objects.filter(user=user, status=M.ACTIVE).values('group_id')
	qs = (StudyGroup.objects.filter(university=student.university).exclude(privacy=StudyGroup.INVITE)
		.exclude(pk__in=mine).select_related('department', 'department__faculty', 'level'))
	if kind:
		qs = qs.filter(group_type=kind)
	return _counted(qs)


def sections(student, user, kind=''):
	groups = list(candidates(student, user, kind).order_by('-created_at')[:LIMIT])
	prepare(groups, user)
	groups.sort(key=lambda g: (-g.known, not g.is_open or g.is_full, -g.n_members))
	uni = student.university.short_name or student.university.name
	dept, level, fac = student.department_id, student.level_id, student.faculty_id
	return split(groups, [
		('class', 'For your class', f'{student.department.name} · {student.level.name}',
			lambda g: g.department_id == dept and g.level_id == level),
		('department', 'Your department', f'{student.department.name}, every level',
			lambda g: g.department_id == dept),
		('faculty', 'Your faculty', f'{student.faculty.name}, other departments',
			lambda g: g.department_id and g.department.faculty_id == fac),
		('campus', f'Around {uni}', 'Hostels, clubs and groups in other faculties', lambda g: True),
	])


def prepare(groups, user, friends=None):
	"""Adds what a card shows: .known/.faces (people you follow in it), .my_state, .cover_hue."""
	groups = list(groups)
	if not groups:
		return groups
	friends = friend_ids(user) if friends is None else friends
	members, states = {}, {}
	for gid, uid, status in M.objects.filter(group__in=groups).values_list('group_id', 'user_id', 'status'):
		if status == M.ACTIVE:
			members.setdefault(gid, []).append(uid)
		if uid == user.pk:
			states[gid] = status
	attach_faces(groups, members, friends)
	for g in groups:
		g.my_state = {M.ACTIVE: 'joined', M.PENDING: 'requested'}.get(states.get(g.pk), '')
		g.cover_hue = TYPE_HUES.get(g.group_type, hue(g.pk))
		if not hasattr(g, 'n_members'):
			g.n_members = len(members.get(g.pk, []))
	return groups
