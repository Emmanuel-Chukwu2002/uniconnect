"""Courses to add on Course Companion, closest first (like Who to follow):

    Your coursemates take these   courses students in your department and level have added
    From your department          your department's courses
    From your faculty             other departments' courses in your faculty
    Popular at <university>       everything else

Courses already in My Courses are left out. Within a section: more of your
coursemates (then people you follow) first, then more students.
Cards: templates/courses/_pc_card.html.
"""
from django.db.models import Count

from accounts.models import StudentProfile
from feed.closeness import attach_faces, friend_ids, split
from .models import Course, CourseEnrollment

LIMIT = 600
COLOUR_HUES = {'blue': 215, 'navy': 228, 'teal': 175, 'slate': 210, 'violet': 265, 'green': 140, 'orange': 28, 'pink': 330}


def sections(student, user, my_ids):
	courses = list(Course.objects.filter(university=student.university).exclude(pk__in=my_ids)
		.select_related('department').annotate(n_students=Count('enrollments', distinct=True))
		.order_by('-n_students', 'code')[:LIMIT])
	mates = set(StudentProfile.objects.filter(department=student.department, level=student.level)
		.exclude(user=user).values_list('user_id', flat=True))
	prepare(courses, user, mates=mates)
	courses.sort(key=lambda c: (-c.n_mates, -c.known, -c.n_students))
	uni = student.university.short_name or student.university.name
	return split(courses, [
		('coursemates', 'Your coursemates take these', f'Added by {student.department.name} · {student.level.name} students',
			lambda c: c.n_mates > 0),
		('department', 'From your department', student.department.name,
			lambda c: c.department_id == student.department_id),
		('faculty', 'From your faculty', f'{student.faculty.name}, other departments',
			lambda c: c.department_id and c.department.faculty_id == student.faculty_id),
		('university', f'Popular at {uni}', 'Courses in other faculties', lambda c: True),
	])


def prepare(courses, user, mates=None, my_ids=()):
	"""Adds .known/.faces (coursemates first, then people you follow, taking it), .n_mates, .cover_hue, .mine."""
	courses = list(courses)
	if not courses:
		return courses
	if mates is None:
		me = getattr(user, 'student_profile', None)
		mates = set(StudentProfile.objects.filter(department_id=me.department_id, level_id=me.level_id)
			.exclude(user=user).values_list('user_id', flat=True)) if me else set()
	takers = {}
	for cid, uid in CourseEnrollment.objects.filter(course__in=courses).values_list('course_id', 'user_id'):
		takers.setdefault(cid, []).append(uid)
	attach_faces(courses, {cid: sorted(ids, key=lambda u: u not in mates) for cid, ids in takers.items()},
		mates | friend_ids(user))
	for c in courses:
		c.n_mates = sum(1 for u in takers.get(c.pk, []) if u in mates)
		c.cover_hue = COLOUR_HUES.get(c.colour, 215)
		c.mine = c.pk in my_ids
		if not hasattr(c, 'n_students'):
			c.n_students = len(takers.get(c.pk, []))
	return courses
