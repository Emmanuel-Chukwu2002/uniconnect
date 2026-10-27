"""Skills on profiles (templates/feed/_profile_skills.html):

    /profile/skills/add/              POST name: add a skill to your profile
    /profile/skills/<id>/remove/      POST: remove one of yours
    /profile/skills/<id>/endorse/     POST: endorse someone else's skill (again to take it back)

Skills are also searchable: Search > People and Explore > People match them.
All three answer with JSON when called from the page's script, and redirect
back to the profile otherwise.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import ProfileSkill, SkillEndorsement

# Offered in the "Add a skill" box (plus the most common skills at your university).
COMMON = ['Python', 'JavaScript', 'Django', 'React', 'Java', 'C++', 'SQL', 'Data analysis', 'Machine learning',
	'Excel', 'Figma', 'UI/UX design', 'Graphic design', 'Video editing', 'Photography', 'Content writing',
	'Public speaking', 'Leadership', 'Project management', 'Digital marketing', 'Accounting', 'Research',
	'AutoCAD', 'MATLAB', 'Statistics', 'French', 'Event planning', 'Customer service']


def clean_name(raw):
	return ' '.join((raw or '').split())[:40]


def skills_for(profile_user, viewer):
	"""The profile's skills with .n (endorsements) and .mine (viewer endorsed it)."""
	skills = list(ProfileSkill.objects.filter(user=profile_user).annotate(n=Count('endorsements')).order_by('-n', 'created_at'))
	mine = set(SkillEndorsement.objects.filter(user=viewer, skill__in=skills).values_list('skill_id', flat=True))
	for s in skills:
		s.mine = s.pk in mine
	return skills


def suggestions(user):
	student = getattr(user, 'student_profile', None)
	have = {n.lower() for n in ProfileSkill.objects.filter(user=user).values_list('name', flat=True)}
	popular = []
	if student:
		popular = list(ProfileSkill.objects.filter(user__student_profile__university=student.university)
			.values_list('name', flat=True).annotate(c=Count('id')).order_by('-c')[:30])
	seen, out = set(), []
	for name in popular + COMMON:
		if name.lower() not in seen and name.lower() not in have:
			seen.add(name.lower())
			out.append(name)
	return out[:40]


def _block(request):
	"""The re-rendered skills block for the signed-in user's own profile."""
	return render_to_string('feed/_profile_skills.html', {
		'skills': skills_for(request.user, request.user), 'is_own': True, 'profile_user': request.user,
		'skill_suggestions': suggestions(request.user), 'skills_max': ProfileSkill.MAX,
	}, request=request)


def _ajax(request):
	return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


@login_required
@require_POST
def add_skill(request):
	name = clean_name(request.POST.get('name'))
	error = ''
	if len(name) < 2:
		error = 'Type a skill, e.g. Python or Public speaking.'
	elif ProfileSkill.objects.filter(user=request.user).count() >= ProfileSkill.MAX:
		error = f'You can list up to {ProfileSkill.MAX} skills — remove one first.'
	elif ProfileSkill.objects.filter(user=request.user, name__iexact=name).exists():
		error = f'“{name}” is already on your profile.'
	else:
		ProfileSkill.objects.create(user=request.user, name=name)
	if _ajax(request):
		return JsonResponse({'html': _block(request), 'error': error}, status=400 if error else 200)
	if error:
		messages.error(request, error)
	return redirect(reverse('profile') + '#skills')


@login_required
@require_POST
def remove_skill(request, skill_id):
	ProfileSkill.objects.filter(pk=skill_id, user=request.user).delete()
	if _ajax(request):
		return JsonResponse({'html': _block(request)})
	return redirect(reverse('profile') + '#skills')


@login_required
@require_POST
def endorse_skill(request, skill_id):
	skill = get_object_or_404(ProfileSkill.objects.select_related('user'), pk=skill_id)
	if skill.user_id == request.user.pk:
		endorsed = False
	else:
		row, created = SkillEndorsement.objects.get_or_create(skill=skill, user=request.user)
		if not created:
			row.delete()
		endorsed = created
	if _ajax(request):
		return JsonResponse({'endorsed': endorsed, 'count': skill.endorsements.count()})
	return redirect(reverse('user_profile', args=[skill.user.username]) + '#skills')
