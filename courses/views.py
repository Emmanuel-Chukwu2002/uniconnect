"""Course Companion pages (templates/courses/). See models.py.

    /courses/                         My Courses, search, Quick Access
    /courses/new/                     POST code + title: add a missing course (and add it to My Courses)
    /courses/my/<section>/            Quick Access: notes | questions | groups | past, across My Courses
    /courses/<id>/?tab=notes|questions|past|groups
    /courses/<id>/add/  remove/       POST: add to / remove from My Courses
    /courses/<id>/upload/             POST: upload notes or a past question
    /courses/<id>/files/<m>/          download (students of the course's university)
    /courses/<id>/files/<m>/delete/   POST (uploader)
    /courses/<id>/ask/                POST: ask a question
    /courses/<id>/q/<q>/              a question and its answers; POST answers there
    /courses/<id>/q/<q>/accept/<a>/   POST (asker): mark the answer that helped
    /courses/<id>/q/<q>/delete/       POST (asker)
"""
import os
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from feed.models import Notification as N
from feed.notifications import notify
from studygroups.models import StudyGroup, StudyGroupMember
from .models import Course, CourseAnswer, CourseEnrollment, CourseMaterial, CourseQuestion, normalise_code

SECTIONS = [('notes', 'Notes', 'bi-journal-text'), ('questions', 'Questions', 'bi-question-lg'),
	('groups', 'Study Groups', 'bi-people'), ('past', 'Past Questions', 'bi-file-earmark-check')]
SECTION_KEYS = [s[0] for s in SECTIONS]
INLINE = {'pdf', 'png', 'jpg', 'jpeg', 'webp', 'txt'}


def _student(request):
	student = getattr(request.user, 'student_profile', None)
	if student is None:
		raise Http404('Only students can use Course Companion.')
	return student


def _course(request, pk):
	return get_object_or_404(Course.objects.select_related('department'), pk=pk, university=_student(request).university)


def _with_counts(qs):
	return qs.annotate(n_students=Count('enrollments', distinct=True))


def _attach_group_counts(courses, university):
	"""Adds .n_groups (Academic groups with the same course code)."""
	courses = list(courses)
	codes = {c.code.upper() for c in courses}
	counts = {}
	for code in (StudyGroup.objects.filter(university=university).exclude(privacy=StudyGroup.INVITE)
			.values_list('course_code', flat=True)):
		if code and code.upper() in codes:
			counts[code.upper()] = counts.get(code.upper(), 0) + 1
	for c in courses:
		c.n_groups = counts.get(c.code.upper(), 0)
	return courses


@login_required
def index(request):
	"""My Courses, Quick Access, then courses to add in sections closest first
	(courses/discover.py) as cards; ?section=<key> shows one section in full; ?q= searches."""
	from django.core.paginator import Paginator
	from feed.closeness import SECTION_PAGE, overview
	from . import discover
	student = _student(request)
	q = ' '.join(request.GET.get('q', '').split())[:60]
	my_ids = set(CourseEnrollment.objects.filter(user=request.user).values_list('course_id', flat=True))

	def cards(courses):
		return _attach_group_counts(discover.prepare(courses, request.user, my_ids=my_ids), student.university)
	ctx = {'q': q, 'my_ids': my_ids, 'sections': SECTIONS}
	if q:
		qs = Course.objects.filter(university=student.university)
		code = normalise_code(q)
		for word in q.split():
			qs = qs.filter(Q(code__icontains=word) | Q(title__icontains=word) | Q(code__icontains=normalise_code(word)))
		results = cards(_with_counts(qs | Course.objects.filter(university=student.university, code__iexact=code))
			.distinct().order_by('code')[:30])
		suggest = code if re.fullmatch(r'[A-Z]{2,5} \d{3,4}[A-Z]?', code) and not any(c.code == code for c in results) else ''
		return render(request, 'courses/index.html', dict(ctx, items=results, suggest_code=suggest))
	parts = discover.sections(student, request.user, my_ids)
	one = next((p for p in parts if p[0] == request.GET.get('section')), None)
	if one:
		page = Paginator(one[3], SECTION_PAGE).get_page(request.GET.get('page'))
		return render(request, 'courses/index.html', dict(ctx, page=page, items=cards(list(page)),
			section={'key': one[0], 'title': one[1], 'sub': one[2]}, total=len(one[3])))
	mine = cards(_with_counts(Course.objects.filter(pk__in=my_ids)).order_by('code'))
	return render(request, 'courses/index.html', dict(ctx, mine=mine, groups=overview(parts, cards)))


@login_required
@require_POST
def new_course(request):
	student = _student(request)
	code = normalise_code(request.POST.get('code', ''))[:20]
	title = ' '.join(request.POST.get('title', '').split())[:120]
	if len(code) < 4 or not title:
		messages.error(request, 'Give the course code and its title, e.g. COS 401 — Data Structures.')
		return redirect(reverse('courses') + (f'?q={code}' if code else ''))
	course, created = Course.objects.get_or_create(university=student.university, code=code,
		defaults={'title': title, 'department': student.department, 'created_by': request.user})
	CourseEnrollment.objects.get_or_create(user=request.user, course=course)
	messages.success(request, f'{course.code} added to My Courses.' if created else f'{course.code} was already here — added to My Courses.')
	return redirect(course)


@login_required
@require_POST
def enroll(request, pk):
	course = _course(request, pk)
	CourseEnrollment.objects.get_or_create(user=request.user, course=course)
	if request.headers.get('X-Requested-With') == 'XMLHttpRequest':   # Add buttons on the Explore page
		from django.http import JsonResponse
		return JsonResponse({'state': 'added'})
	messages.success(request, f'{course.code} added to My Courses.')
	return redirect(request.POST.get('next') if (request.POST.get('next') or '').startswith('/') else course)


@login_required
@require_POST
def unenroll(request, pk):
	course = _course(request, pk)
	CourseEnrollment.objects.filter(user=request.user, course=course).delete()
	messages.success(request, f'{course.code} removed from My Courses.')
	return redirect(course)


# ---------------------------------------------------------------------
# One course
# ---------------------------------------------------------------------
def _groups_for(courses, university, user):
	codes = [c.code for c in courses]
	q = Q()
	for code in codes:
		q |= Q(course_code__iexact=code)
	if not codes:
		return []
	groups = list(StudyGroup.objects.filter(q, university=university).exclude(privacy=StudyGroup.INVITE)
		.annotate(n_members=Count('members', filter=Q(members__status=StudyGroupMember.ACTIVE), distinct=True))
		.order_by('-n_members'))
	states = dict(StudyGroupMember.objects.filter(user=user, group__in=groups).values_list('group_id', 'status'))
	for g in groups:
		g.my_state = {'active': 'joined', 'pending': 'requested'}.get(states.get(g.pk), '')
	return groups


@login_required
def detail(request, pk):
	student = _student(request)
	course = _course(request, pk)
	tab = request.GET.get('tab', 'notes')
	if tab not in SECTION_KEYS:
		tab = 'notes'
	enrolled = CourseEnrollment.objects.filter(user=request.user, course=course).exists()
	context = {
		'course': course, 'tab': tab, 'sections': SECTIONS, 'enrolled': enrolled,
		'n_students': course.enrollments.count(),
		'counts': {
			'notes': course.materials.filter(kind=CourseMaterial.NOTES).count(),
			'past': course.materials.filter(kind=CourseMaterial.PAST_QUESTION).count(),
			'questions': course.questions.count(),
		},
	}
	if tab in ('notes', 'past'):
		kind = CourseMaterial.NOTES if tab == 'notes' else CourseMaterial.PAST_QUESTION
		qs = course.materials.filter(kind=kind).select_related('uploaded_by')
		context['materials'] = qs.order_by('-year', '-created_at') if tab == 'past' else qs
		context['kind'] = kind
	elif tab == 'questions':
		context['questions'] = (course.questions.select_related('author', 'author__student_profile')
			.annotate(n_answers=Count('answers'), solved=Count('answers', filter=Q(answers__is_accepted=True))))
	else:
		context['groups'] = _groups_for([course], student.university, request.user)
	context['counts']['groups'] = len(context['groups']) if 'groups' in context else course.study_groups().exclude(privacy=StudyGroup.INVITE).count()
	return render(request, 'courses/detail.html', context)


@login_required
@require_POST
def upload(request, pk):
	course = _course(request, pk)
	kind = request.POST.get('kind') if request.POST.get('kind') in dict(CourseMaterial.KIND_CHOICES) else CourseMaterial.NOTES
	tab = 'past' if kind == CourseMaterial.PAST_QUESTION else 'notes'
	back = f'{course.get_absolute_url()}?tab={tab}'
	f = request.FILES.get('file')
	title = ' '.join(request.POST.get('title', '').split())[:150]
	year = request.POST.get('year', '').strip()
	if not f:
		messages.error(request, 'Choose a file to upload.')
		return redirect(back)
	material = CourseMaterial(course=course, uploaded_by=request.user, kind=kind, file=f,
		file_name=f.name.rsplit('/', 1)[-1][:150], size=f.size, title=title or f.name.rsplit('.', 1)[0][:150],
		year=int(year) if year.isdigit() and 1980 <= int(year) <= 2100 else None)
	try:
		material.full_clean(exclude=['uploaded_by'])
	except Exception as e:
		msgs = getattr(e, 'message_dict', {}).get('file') or ['That file can’t be uploaded.']
		messages.error(request, msgs[0])
		return redirect(back)
	material.save()
	CourseEnrollment.objects.get_or_create(user=request.user, course=course)
	messages.success(request, 'Uploaded — thanks for sharing!')
	return redirect(back)


@login_required
def download(request, pk, material_id):
	course = _course(request, pk)
	m = get_object_or_404(CourseMaterial, pk=material_id, course=course)
	try:
		handle = m.file.open('rb')
	except (FileNotFoundError, OSError):
		raise Http404('That file is missing.')
	CourseMaterial.objects.filter(pk=m.pk).update(downloads=F('downloads') + 1)
	return FileResponse(handle, as_attachment=m.extension not in INLINE, filename=m.file_name or os.path.basename(m.file.name))


@login_required
@require_POST
def delete_material(request, pk, material_id):
	course = _course(request, pk)
	m = get_object_or_404(CourseMaterial, pk=material_id, course=course, uploaded_by=request.user)
	tab = 'past' if m.kind == CourseMaterial.PAST_QUESTION else 'notes'
	m.file.delete(save=False)
	m.delete()
	messages.success(request, 'File deleted.')
	return redirect(f'{course.get_absolute_url()}?tab={tab}')


# ---------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------
@login_required
@require_POST
def ask(request, pk):
	course = _course(request, pk)
	title = ' '.join(request.POST.get('title', '').split())[:200]
	body = (request.POST.get('body') or '').strip()[:4000]
	if len(title) < 8:
		messages.error(request, 'Write your question in a sentence (at least a few words).')
		return redirect(f'{course.get_absolute_url()}?tab=questions')
	question = CourseQuestion.objects.create(course=course, author=request.user, title=title, body=body)
	CourseEnrollment.objects.get_or_create(user=request.user, course=course)
	return redirect(question)


@login_required
def question(request, pk, question_id):
	course = _course(request, pk)
	q = get_object_or_404(CourseQuestion.objects.select_related('author', 'author__student_profile'), pk=question_id, course=course)
	if request.method == 'POST':
		body = (request.POST.get('body') or '').strip()[:4000]
		if body:
			answer = CourseAnswer.objects.create(question=q, author=request.user, body=body)
			notify(q.author, request.user, N.COURSE_ANSWER, course_question=q)
			return redirect(f'{q.get_absolute_url()}#a{answer.pk}')
		messages.error(request, 'Write your answer first.')
		return redirect(q)
	answers = list(q.answers.select_related('author', 'author__student_profile'))
	return render(request, 'courses/question.html', {'course': course, 'q': q, 'answers': answers,
		'is_asker': q.author_id == request.user.pk})


@login_required
@require_POST
def accept(request, pk, question_id, answer_id):
	course = _course(request, pk)
	q = get_object_or_404(CourseQuestion, pk=question_id, course=course, author=request.user)
	a = get_object_or_404(CourseAnswer, pk=answer_id, question=q)
	was = a.is_accepted
	q.answers.update(is_accepted=False)
	if not was:
		CourseAnswer.objects.filter(pk=a.pk).update(is_accepted=True)
	return redirect(f'{q.get_absolute_url()}#a{a.pk}')


@login_required
@require_POST
def delete_question(request, pk, question_id):
	course = _course(request, pk)
	get_object_or_404(CourseQuestion, pk=question_id, course=course, author=request.user).delete()
	messages.success(request, 'Question deleted.')
	return redirect(f'{course.get_absolute_url()}?tab=questions')


@login_required
@require_POST
def delete_answer(request, pk, question_id, answer_id):
	course = _course(request, pk)
	q = get_object_or_404(CourseQuestion, pk=question_id, course=course)
	get_object_or_404(CourseAnswer, pk=answer_id, question=q, author=request.user).delete()
	return redirect(q)


# ---------------------------------------------------------------------
# Quick Access: one section across all My Courses
# ---------------------------------------------------------------------
@login_required
def my_section(request, section):
	student = _student(request)
	if section not in SECTION_KEYS:
		raise Http404
	courses = list(Course.objects.filter(enrollments__user=request.user).order_by('code'))
	only = request.GET.get('course')
	shown = [c for c in courses if str(c.pk) == only] or courses
	context = {'section': section, 'label': dict((k, l) for k, l, _ in SECTIONS)[section], 'sections': SECTIONS,
		'courses': courses, 'only': only if any(str(c.pk) == only for c in courses) else ''}
	if section in ('notes', 'past'):
		kind = CourseMaterial.NOTES if section == 'notes' else CourseMaterial.PAST_QUESTION
		context['materials'] = (CourseMaterial.objects.filter(course__in=shown, kind=kind)
			.select_related('course', 'uploaded_by').order_by('-created_at')[:100])
	elif section == 'questions':
		context['questions'] = (CourseQuestion.objects.filter(course__in=shown).select_related('course', 'author', 'author__student_profile')
			.annotate(n_answers=Count('answers'), solved=Count('answers', filter=Q(answers__is_accepted=True)))[:100])
	else:
		# Study Groups: the dashboard look (studygroups/dashboard.py). Your courses are the round buttons.
		from studygroups import dashboard
		one = next((c for c in courses if str(c.pk) == only), None)
		context.update(dashboard.build(student, request.user, codes=[c.code for c in courses], only_code=one.code if one else ''))
		context['one'] = one
		return render(request, 'courses/study_groups.html', context)
	return render(request, 'courses/section.html', context)



# ---------------------------------------------------------------------
# Home's Today strip (courses/today.py): deadlines and the question of the day
# ---------------------------------------------------------------------
def _back(request):
	nxt = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('home')
	return nxt if nxt.startswith('/') else reverse('home')


@login_required
@require_POST
def deadline_add(request):
	"""Add an exam, test or assignment date for one of your courses — everyone taking it sees it."""
	from datetime import datetime
	from django.utils import timezone
	from .models import Deadline
	student = _student(request)
	course = get_object_or_404(Course, pk=request.POST.get('course') or 0, university=student.university, enrollments__user=request.user)
	kind = request.POST.get('kind') if request.POST.get('kind') in dict(Deadline.KIND_CHOICES) else Deadline.EXAM
	try:
		day = datetime.strptime(request.POST.get('date', ''), '%Y-%m-%d').date()
		at = datetime.strptime(request.POST.get('time') or '09:00', '%H:%M').time()
	except ValueError:
		messages.error(request, 'Pick a date for the deadline.')
		return redirect(_back(request))
	due = timezone.make_aware(datetime.combine(day, at))
	if due < timezone.now():
		messages.error(request, 'That date has already passed.')
		return redirect(_back(request))
	Deadline.objects.create(course=course, kind=kind, title=(request.POST.get('title') or '').strip()[:100], due_at=due, created_by=request.user)
	messages.success(request, f'Added — everyone taking {course.code} will see the countdown.')
	return redirect(_back(request))


@login_required
@require_POST
def deadline_delete(request, deadline_id):
	from .models import Deadline
	get_object_or_404(Deadline, pk=deadline_id, created_by=request.user).delete()
	messages.success(request, 'Deadline removed.')
	return redirect(_back(request))


@login_required
@require_POST
def daily_answer(request, question_id):
	"""Answer today's question (once a day). AJAX gets the result card back; otherwise back to Home."""
	from django.db import IntegrityError
	from django.http import JsonResponse
	from django.template.loader import render_to_string
	from django.utils import timezone
	from .models import DailyAnswer, DailyQuestion
	from . import today as T
	q = get_object_or_404(DailyQuestion.objects.select_related('course'), pk=question_id, course__enrollments__user=request.user)
	day = timezone.localdate()
	if T.question_for(q.course, day) != q:
		raise Http404('That question is not today\'s any more.')
	choice = request.POST.get('choice', '')
	if choice in dict(q.options):
		try:
			DailyAnswer.objects.get_or_create(question=q, user=request.user, day=day, defaults={'choice': choice})
		except IntegrityError:
			pass
	q.my_answer = DailyAnswer.objects.filter(question=q, user=request.user, day=day).first()
	q.stats = T.results(q, day) if q.my_answer else None
	if request.headers.get('x-requested-with') == 'XMLHttpRequest':
		return JsonResponse({'html': render_to_string('feed/_today_question.html', {'q': q}, request=request),
			'right': bool(q.my_answer and q.my_answer.is_correct)})
	return redirect(_back(request))
