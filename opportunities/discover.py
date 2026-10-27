"""Explore on the Opportunities board, closest first (like Who to follow):

    For <your department>         it names your department (title, who can apply, description)
    Shared by your coursemates    posted by someone in your department and level
    From your department          posted by someone in your department
    From your faculty             posted by someone in your faculty
    Across <university>           everything else

Each opportunity shows once, in the first section it fits. Your own posts
are under "Posted by me". Within a section: ones people you follow saved first,
then in the board's order (newest, or deadline soonest).
Cards: templates/opportunities/_pc_card.html.
"""
from feed.closeness import attach_faces, friend_ids, hue, split
from .models import OpportunitySave

LIMIT = 600
KIND_HUES = {'internship': 215, 'job': 265, 'scholarship': 150, 'fellowship': 32, 'competition': 8, 'volunteer': 330}


def _mentions(opp, words):
	text = ' '.join((opp.title, opp.eligibility, opp.description)).lower()
	return any(w in text for w in words)


def sections(student, user, qs):
	opps = list(qs.exclude(posted_by=user).select_related('posted_by__student_profile')[:LIMIT])
	prepare(opps, user)
	opps.sort(key=lambda o: -o.known)   # stable: keeps the board's own order within
	dept = student.department.name.lower()
	words = [dept] + ([dept[:-1]] if dept.endswith('s') else [])
	uni = student.university.short_name or student.university.name

	def poster(o):
		return getattr(o.posted_by, 'student_profile', None)
	return split(opps, [
		('course', f'For {student.department.name}', 'Mentions your department', lambda o: _mentions(o, words)),
		('coursemates', 'Shared by your coursemates', f'{student.department.name} · {student.level.name}',
			lambda o: poster(o) and poster(o).department_id == student.department_id and poster(o).level_id == student.level_id),
		('department', 'From your department', f'Shared by {student.department.name} students',
			lambda o: poster(o) and poster(o).department_id == student.department_id),
		('faculty', 'From your faculty', f'Shared by students in {student.faculty.name}',
			lambda o: poster(o) and poster(o).faculty_id == student.faculty_id),
		('university', f'Across {uni}', 'Shared by students in other faculties', lambda o: True),
	])


def prepare(opps, user, friends=None):
	"""Adds .known/.faces (people you follow who saved it), .saved, .cover_hue."""
	opps = list(opps)
	if not opps:
		return opps
	friends = friend_ids(user) if friends is None else friends
	savers = {}
	for oid, uid in OpportunitySave.objects.filter(opportunity__in=opps).values_list('opportunity_id', 'user_id'):
		savers.setdefault(oid, []).append(uid)
	attach_faces(opps, savers, friends)
	for o in opps:
		o.saved = user.pk in savers.get(o.pk, [])
		o.n_saves = len(savers.get(o.pk, []))
		o.cover_hue = KIND_HUES.get(o.kind, hue(o.pk))
	return opps
