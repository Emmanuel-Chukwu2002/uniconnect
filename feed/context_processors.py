from django.db.models import Sum
from django.utils import timezone

from accounts.models import StudentProfile
from .models import CartItem, Event, Follow
from .notifications import badge_text, unread_count
from .imagekit import MAX_VIDEO_MB, enabled as imagekit_enabled
from .people import SIDEBAR_COUNT, people_to_follow
from .top_stories import top_stories


def sidebar_widgets(request):
	"""Makes the right-sidebar 'Events' and 'Who to follow' data available
	on every page that uses the app shell, not just the home view —
	otherwise those widgets would silently go empty on every other page."""
	user = getattr(request, 'user', None)

	if user is None or not user.is_authenticated:
		return {}

	# Housekeeping: drop any event whose date/time has already passed,
	# so a finished event disappears app-wide shortly after it happens
	# instead of lingering until someone next opens the Events page.
	Event.delete_expired()

	events = Event.objects.filter(date__gte=timezone.now().date()).select_related('organizer')[:3]

	# "Who to follow" box: 4 people; "Show More" opens the full page
	# (feed/people.py has the rules, shared with that page).
	# People You May Know (recommendations/people.py): only students you could know —
	# same faculty or department — ranked by mutual connections, shared courses, ...
	from recommendations.people import people_you_may_know
	people = people_you_may_know(user, limit=SIDEBAR_COUNT + 1)
	suggestions = people[:SIDEBAR_COUNT]
	suggestions_more = len(people) > SIDEBAR_COUNT

	cart_count = CartItem.objects.filter(user=user).aggregate(total=Sum('quantity'))['total'] or 0

	# "Send to" row of the share sheet (base.html, so every signed-in
	# page): people this student follows (accepted follows only), most
	# recently followed first. One small query, capped at 15 people.
	share_contacts = (
		Follow.objects.filter(follower=user, status=Follow.STATUS_ACCEPTED)
		.select_related('following', 'following__student_profile')
		.order_by('-created_at')[:15]
	)

	# The bell's unread badge, rendered server-side so it's right on
	# first paint; app.js keeps it current after that (polling).
	from courses.reminders import due_reminders, pop_up
	# Class reminders due now (courses/reminders.py); new ones pop up on this page (base.html).
	new_reminders = [pop_up(n) for n in due_reminders(user)]
	from studygroups import sessions as group_sessions        # study sessions starting soon
	new_reminders += [group_sessions.pop_up(n) for n in group_sessions.due_reminders(user)]
	from .scheduling import publish_due
	publish_due()                # scheduled posts that just went out: tell anyone they mention
	notifications_unread = unread_count(user)

	# Right sidebar "Top stories" box (feed/top_stories.py): 4 shown,
	# up to 4 more behind "Show more".
	stories = top_stories(user, limit=8)

	# Which of their own posts is pinned to their profile: the post menu
	# (_post_menu.html) shows "Unpin" on that one, "Pin" on the rest.
	from .models import PinnedPost
	my_pinned_post_id = PinnedPost.objects.filter(user=user).values_list('post_id', flat=True).first()

	# Posts you marked Interested: the post menu shows "Interested ✓" on them.
	from recommendations.models import Feedback
	rec_interested_posts = set(Feedback.objects.filter(user=user, item_type=Feedback.POST, value=Feedback.INTERESTED)
		.values_list('item_id', flat=True))

	return {
		'rec_interested_posts': rec_interested_posts,
		'new_class_reminders': new_reminders,
		'my_pinned_post_id': my_pinned_post_id,
		'events': events, 'suggestions': suggestions, 'cart_count': cart_count,
		'top_stories': stories, 'suggestions_more': suggestions_more,
		'imagekit_enabled': imagekit_enabled(), 'video_max_mb': MAX_VIDEO_MB,
		'share_contacts': share_contacts,
		'notifications_unread': notifications_unread,
		'notifications_badge': badge_text(notifications_unread),
	}
