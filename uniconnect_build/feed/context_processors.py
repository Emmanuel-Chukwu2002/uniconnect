from django.utils import timezone

from accounts.models import StudentProfile
from .models import Event, Follow


def sidebar_widgets(request):
	"""Makes the right-sidebar 'Events' and 'Who to follow' data available
	on every page that uses the app shell, not just the home view —
	otherwise those widgets would silently go empty on every other page."""
	user = getattr(request, 'user', None)

	if user is None or not user.is_authenticated:
		return {}

	events = Event.objects.filter(date__gte=timezone.now().date()).select_related('organizer')[:3]

	suggestions = []
	student = getattr(user, 'student_profile', None)
	if student:
		already_following_ids = Follow.objects.filter(follower=user).values_list('following_id', flat=True)
		suggestions = StudentProfile.objects.filter(
			university=student.university
		).exclude(user=user).exclude(user_id__in=list(already_following_ids)).select_related(
			'user', 'department', 'level'
		)[:5]

	return {'events': events, 'suggestions': suggestions}
