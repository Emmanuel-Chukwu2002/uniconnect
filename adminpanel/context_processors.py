"""For every signed-in page: the admin-dashboard link, live announcements and
unacknowledged warnings (shown as banners at the top of the app, feed/base_app.html)."""
from django.db.models import Q
from django.utils import timezone


def admin_bits(request):
	user = getattr(request, 'user', None)
	if user is None or not user.is_authenticated:
		return {}
	from .models import AccountAction, Announcement
	from .permissions import admin_for
	admin = admin_for(user)
	prof = getattr(user, 'student_profile', None)
	now = timezone.now()
	audience = Q(audience=Announcement.EVERYONE)
	if prof is not None:
		audience |= Q(audience=Announcement.UNIVERSITY, university_id=prof.university_id)
	live = list(Announcement.objects.filter(audience, is_published=True, starts_at__lte=now)
		.filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now)).order_by('-starts_at')[:3])
	warnings = list(AccountAction.objects.filter(user=user, kind=AccountAction.WARNING, acknowledged_at__isnull=True)[:3])
	return {'staff_admin': admin, 'live_announcements': live, 'my_warnings': warnings}
