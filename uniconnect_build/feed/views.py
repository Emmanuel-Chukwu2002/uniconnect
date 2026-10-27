from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from accounts.models import StudentProfile
from .models import Event, Follow

User = get_user_model()


def _is_ajax(request):
	return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


@login_required
def home(request):
	return render(request, 'feed/home.html')


@login_required
def events_list(request):
	all_events = Event.objects.filter(date__gte=timezone.now().date()).select_related('organizer')
	return render(request, 'feed/events_list.html', {'all_events': all_events})


@login_required
def follow_toggle(request, user_id):
	if request.method != 'POST':
		return redirect('home')

	target = get_object_or_404(User, pk=user_id)
	following = False

	if target.id != request.user.id:
		follow, created = Follow.objects.get_or_create(follower=request.user, following=target)
		if not created:
			follow.delete()
			following = False
		else:
			following = True

	if _is_ajax(request):
		return JsonResponse({'following': following})

	return redirect('home')


@login_required
def coming_soon(request, title, icon, description=''):
	"""A shared, honest placeholder for nav items whose real feature
	hasn't been built yet — keeps navigation whole (no dead links or
	404s) without pretending functionality exists."""
	return render(request, 'feed/coming_soon.html', {
		'title': title, 'icon': icon, 'description': description,
	})
