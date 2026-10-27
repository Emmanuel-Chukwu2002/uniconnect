"""Read-only "View Platform" for admins who aren't students.

UniConnect shows everyone their own university, so an admin-only account (no
StudentProfile) would see empty pages. When such an admin chooses a university
on /staff/view/, this middleware lends them a temporary, never-saved student
profile at that university for the request, so every page shows what a student
there sees. It is strictly read-only:

* Forms and actions (POST etc.) are refused outside /staff/ and sign-out, so
  they can't post, like, comment, follow, join or message.
* Every other request runs in a database transaction that is rolled back, so
  page views, story views and recommendation signals they trigger leave no
  trace in students' feeds or in the statistics.

Students who are also admins never go through this: they use their real profile.
University-scoped admins can only view their own university."""
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect

SESSION_KEY = 'staff_view_uni'
ALWAYS_ALLOWED = ('/staff/', '/admin/', '/logout', '/static/', '/media/')


def allowed_university(admin, uni_id):
	"""The University an admin may view (their own if they are scoped to one)."""
	from accounts.models import University
	if admin is None:
		return None
	if admin.university_id:
		return admin.university
	return University.objects.filter(pk=uni_id).first() if uni_id else None


def typical_place(uni):
	"""(faculty_id, department_id, level_id) most students at uni have, or the first
	level set up there if it has no students yet; None if it has no levels at all."""
	from django.db.models import Count
	from accounts.models import Level, StudentProfile
	top = (StudentProfile.objects.filter(university=uni).values('faculty_id', 'department_id', 'level_id')
		.annotate(n=Count('pk')).order_by('-n').first())
	if top:
		return top['faculty_id'], top['department_id'], top['level_id']
	lvl = Level.objects.filter(department__faculty__university=uni).select_related('department').order_by('pk').first()
	return (lvl.department.faculty_id, lvl.department_id, lvl.pk) if lvl else None


def viewing_university(request):
	"""The university this request is viewing as an admin, or None."""
	return getattr(request, 'staff_view', None)


class StaffViewMiddleware:
	def __init__(self, get_response):
		self.get_response = get_response

	def __call__(self, request):
		request.staff_view = None
		user = getattr(request, 'user', None)
		path = request.path
		if (user is None or not user.is_authenticated or path.startswith(ALWAYS_ALLOWED)
				or SESSION_KEY not in request.session or hasattr(user, 'student_profile')):
			return self.get_response(request)

		from accounts.models import StudentProfile
		from .permissions import admin_for
		admin = admin_for(user)
		uni = allowed_university(admin, request.session.get(SESSION_KEY))
		if uni is None:
			request.session.pop(SESSION_KEY, None)
			return self.get_response(request)

		# A stand-in profile for this request only (never saved). Pages filter by the
		# university, and some by department and level ("Your coursemates", group
		# forms), so it takes the most common ones there: a typical student's view.
		place = typical_place(uni)
		if place is None:              # no departments set up yet: nothing to view
			request.session.pop(SESSION_KEY, None)
			return self.get_response(request)
		profile = StudentProfile(user=user, university=uni, faculty_id=place[0], department_id=place[1], level_id=place[2])
		profile._staff_view = True
		user._state.fields_cache['student_profile'] = profile
		request.staff_view = uni

		if request.method not in ('GET', 'HEAD', 'OPTIONS'):
			msg = "You're viewing as an admin, so this is read-only. Use the admin dashboard to take action."
			if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', ''):
				return JsonResponse({'ok': False, 'error': msg}, status=403)
			messages.info(request, msg)
			back = request.META.get('HTTP_REFERER') or '/home/'
			return redirect(back if back.startswith(('/', request.build_absolute_uri('/'))) else '/home/')

		with transaction.atomic():
			response = self.get_response(request)
			if hasattr(response, 'render') and callable(response.render) and not getattr(response, 'is_rendered', True):
				response.render()
			transaction.set_rollback(True)
		return response
