"""Notifications: creating them, and turning the stored rows into the
grouped, worded list the notifications page and panel show.

Creating: the views call notify() right after the thing happened (a
like, a comment, a follow request...) and unnotify() when it's undone
(an unlike, a cancelled request), the same way they call
log_interaction() for the recommender. Both are fail-safe: a problem
with a notification never breaks the action itself.

Showing: build_entries() groups rows Facebook-style and writes each
entry's sentence ("Amaka, Tunde and 2 other people liked your photo.").
The wording lives here, in one place, not in the templates.
"""
import logging
import re

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import Notification

logger = logging.getLogger(__name__)
N = Notification


# ---------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------

def _group_key(type, post=None, comment=None, event=None, listing=None, community=None, study_group=None, course_question=None, pulse_status=None):
	"""Rows that should be shown together share a key. Empty = never grouped."""
	if type == N.LIKE_POST:
		return f'like_post:{post.pk}'
	if type == N.COMMENT:
		return f'comment:{post.pk}'
	if type == N.LIKE_COMMENT:
		return f'like_comment:{comment.pk}'
	if type == N.REPLY:
		return f'reply:{comment.parent_id}'
	if type == N.EVENT_REGISTER:
		return f'event_register:{event.pk}'
	if type == N.LISTING_CART:
		return f'listing_cart:{listing.pk}'
	if type == N.REPOST:
		return f'repost:{post.pk}'
	if type == N.COMMUNITY_JOIN:
		return f'community_join:{community.pk}'
	if type == N.COMMUNITY_REQUEST:
		return f'community_request:{community.pk}'
	if type == N.GROUP_REQUEST:
		return f'group_request:{study_group.pk}'
	if type == N.COURSE_ANSWER:
		return f'course_answer:{course_question.pk}'
	if type in (N.PULSE_REPLY, N.PULSE_INTEREST):
		return f'{type}:{pulse_status.pk}'
	return ''  # quotes: each one is its own post, so its own entry  # follow requests, follows, mentions: always on their own


def notify(recipient, actor, type, post=None, comment=None, event=None, listing=None, community=None, replace=False,
		study_group=None, group_post=None, course_question=None, chat_message=None, group_session=None, pulse_status=None):
	"""Record that `actor` did `type` to something of `recipient`'s.
	Nothing is recorded for your own actions. replace=True first removes
	an earlier identical notification (liking, unliking and liking again
	should leave one notification, not two)."""
	if recipient is None or actor is None or recipient.pk == actor.pk:
		return None
	if is_muted(recipient, type):
		return None
	from .moderation import is_blocked
	if is_blocked(recipient, actor):
		return None
	try:
		if replace:
			unnotify(recipient, actor, type, post=post, comment=comment, event=event, listing=listing, community=community,
				study_group=study_group, group_post=group_post, course_question=course_question, group_session=group_session,
				pulse_status=pulse_status)
		return Notification.objects.create(
			recipient=recipient, actor=actor, type=type,
			post=post, comment=comment, event=event, listing=listing, community=community,
			study_group=study_group, group_post=group_post, course_question=course_question, chat_message=chat_message,
			group_session=group_session, pulse_status=pulse_status,
			group_key=_group_key(type, post, comment, event, listing, community, study_group, course_question, pulse_status),
		)
	except Exception:
		logger.exception('Could not create %s notification', type)
		return None


def is_muted(recipient, type):
	"""True if the recipient switched this kind of notification off in
	Settings > Notifications (StudentProfile.muted_notifications)."""
	try:
		return type in (recipient.student_profile.muted_notifications or [])
	except Exception:   # no student profile (e.g. an admin account)
		return False


def unnotify(recipient, actor, type, **targets):
	"""Remove the notification for something that was undone."""
	if recipient is None or actor is None:
		return
	try:
		filters = {k: v for k, v in targets.items() if v is not None}
		Notification.objects.filter(recipient=recipient, actor=actor, type=type, **filters).delete()
	except Exception:
		logger.exception('Could not remove %s notification', type)


# @username — usernames here look like "UNN-2022249381", so letters,
# digits, "_", "-" and "." are all allowed. A trailing "." is sentence
# punctuation, not part of the name.
MENTION_RE = re.compile(r'(?<![\w@])@([\w.\-]+)')


def notify_mentions(text, actor, post, comment=None, skip=()):
	"""Notify everyone @mentioned in `text` (a post's or a comment's).
	`skip` holds users already notified about this same thing (say, the
	post's author, who already gets "commented on your post")."""
	if not text:
		return
	names = {m.rstrip('.') for m in MENTION_RE.findall(text)}
	if not names:
		return
	skip_ids = {getattr(u, 'pk', u) for u in skip}
	for user in get_user_model().objects.filter(username__in=names):
		if user.pk not in skip_ids:
			notify(user, actor, N.MENTION, post=post, comment=comment)


# ---------------------------------------------------------------------
# Counting and reading
# ---------------------------------------------------------------------

def unread_count(user):
	"""What the bell's badge shows: unread entries as the list groups
	them (five likes on one photo count once, like Facebook)."""
	if not getattr(user, 'is_authenticated', False):
		return 0
	unread = Notification.objects.filter(recipient=user, is_read=False)
	grouped = unread.exclude(group_key='').values('group_key').distinct().count()
	single = unread.filter(group_key='').count()
	return grouped + single


def badge_text(count):
	return '99+' if count > 99 else str(count)


# Tabs on the Notifications page: (key, label, icon, the types it shows).
# "all" shows everything.
TABS = [
	('all', 'All', 'bi-bell', None),
	('mentions', 'Mentions', 'bi-at', [N.MENTION, N.REPLY, N.CHAT_MENTION]),
	('activity', 'Activity', 'bi-heart', [N.LIKE_POST, N.LIKE_COMMENT, N.COMMENT, N.REPOST, N.QUOTE,
		N.FOLLOW_REQUEST, N.FOLLOW, N.FOLLOW_ACCEPTED, N.PULSE_REPLY, N.PULSE_INTEREST]),
	('groups', 'Groups & Courses', 'bi-collection', [N.COMMUNITY_JOIN, N.COMMUNITY_REQUEST, N.COMMUNITY_ACCEPTED,
		N.GROUP_REQUEST, N.GROUP_ACCEPTED, N.GROUP_ANNOUNCEMENT, N.COURSE_ANSWER, N.CLASS_REMINDER, N.CLASS_CHANGED,
		N.GROUP_SESSION, N.SESSION_REMINDER, N.SESSION_CHANGED]),
	('market', 'Events & Market', 'bi-shop', [N.EVENT_REGISTER, N.LISTING_CART]),
]
TAB_TYPES = {key: types for key, _, _, types in TABS}


def unread_by_tab(user):
	"""{'all': 5, 'mentions': 1, ...}: unread entries per tab, counted the
	way the bell counts them (grouped rows count once)."""
	rows = list(Notification.objects.filter(recipient=user, is_read=False).values_list('type', 'group_key', 'pk'))
	counts = {}
	for key, types in TAB_TYPES.items():
		keys = {(gk or f'single:{pk}') for t, gk, pk in rows if types is None or t in types}
		counts[key] = len(keys)
	return counts


def recent_for(user, limit=150, types=None):
	qs = Notification.objects.filter(recipient=user)
	if types:
		qs = qs.filter(type__in=types)
	return list(
		qs
		.select_related('actor', 'actor__student_profile', 'post', 'post__author', 'post__quote_of', 'comment', 'comment__post', 'event', 'listing', 'community', 'study_group', 'group_post', 'course_question', 'course_question__course', 'class_slot', 'class_slot__course', 'chat_message', 'chat_message__conversation', 'group_session', 'group_session__group', 'pulse_status')
		.prefetch_related('post__media_items', 'post__quote_of__media_items')
		.order_by('-created_at')[:limit]
	)


def group_members(notification):
	"""Every row shown as part of the same entry as `notification`."""
	if not notification.group_key:
		return Notification.objects.filter(pk=notification.pk)
	return Notification.objects.filter(
		recipient=notification.recipient_id, group_key=notification.group_key, is_read=notification.is_read,
	)


def target_url(n):
	"""Where clicking a notification goes: the thing it's about."""
	if n.pulse_status_id:
		return reverse('pulse_detail', args=[n.pulse_status_id])
	if n.comment_id:
		# Opens the post with its comments showing that exact comment.
		return reverse('post_detail', args=[n.comment.post_id]) + f'?comment={n.comment_id}'
	if n.post_id:
		return reverse('post_detail', args=[n.post_id])
	if n.type == N.FOLLOW_REQUEST:
		return reverse('follow_requests')
	if n.type in (N.FOLLOW, N.FOLLOW_ACCEPTED):
		return reverse('user_profile', args=[n.actor.username])
	if n.event_id:
		return reverse('events') + '?tab=attendees'
	if n.listing_id:
		return reverse('listing_detail', args=[n.listing_id])
	if n.group_session_id:
		return reverse('group_detail', args=[n.group_session.group_id]) + f'?tab=sessions#s{n.group_session_id}'
	if n.chat_message_id:
		# @mentioned in a group chat: open that chat at the message.
		return reverse('chat_conversation', args=[n.chat_message.conversation_id]) + f'?m={n.chat_message_id}'
	if n.type in (N.CLASS_REMINDER, N.CLASS_CHANGED):
		return reverse('timetable') + (f'?day={n.class_slot.day}' if n.class_slot_id else '')
	if n.course_question_id:
		return reverse('course_question', args=[n.course_question.course_id, n.course_question_id])
	if n.study_group_id:
		url = reverse('group_detail', args=[n.study_group_id])
		if n.type == N.GROUP_REQUEST:
			return url + '?tab=members'
		if n.group_post_id:
			return url + f'?tab=posts#p{n.group_post_id}'
		return url
	if n.community_id:
		# Join requests and new members: the Members tab (requests are at its top).
		if n.type in (N.COMMUNITY_REQUEST, N.COMMUNITY_JOIN):
			return reverse('community_detail', args=[n.community_id]) + '?tab=members'
		return reverse('community_detail', args=[n.community_id])
	return reverse('notifications')


# ---------------------------------------------------------------------
# Wording and grouping
# ---------------------------------------------------------------------

# The small badge on the avatar for each type: icon + colour name
# (colours are in app.css as .notif-badge-<colour>).
BADGES = {
	N.LIKE_POST: ('bi-heart-fill', 'red'),
	N.LIKE_COMMENT: ('bi-heart-fill', 'red'),
	N.COMMENT: ('bi-chat-fill', 'green'),
	N.REPLY: ('bi-reply-fill', 'green'),
	N.MENTION: ('bi-at', 'purple'),
	N.FOLLOW_REQUEST: ('bi-person-plus-fill', 'blue'),
	N.FOLLOW: ('bi-person-plus-fill', 'blue'),
	N.FOLLOW_ACCEPTED: ('bi-person-check-fill', 'blue'),
	N.EVENT_REGISTER: ('bi-calendar-event-fill', 'orange'),
	N.LISTING_CART: ('bi-cart-fill', 'teal'),
	N.REPOST: ('bi-repeat', 'green'),
	N.QUOTE: ('bi-quote', 'blue'),
	N.COMMUNITY_JOIN: ('bi-people-fill', 'purple'),
	N.COMMUNITY_REQUEST: ('bi-person-plus-fill', 'purple'),
	N.COMMUNITY_ACCEPTED: ('bi-people-fill', 'green'),
	N.GROUP_REQUEST: ('bi-person-plus-fill', 'teal'),
	N.GROUP_ACCEPTED: ('bi-collection-fill', 'green'),
	N.GROUP_ANNOUNCEMENT: ('bi-megaphone-fill', 'orange'),
	N.COURSE_ANSWER: ('bi-mortarboard-fill', 'blue'),
	N.CLASS_REMINDER: ('bi-alarm-fill', 'orange'),
	N.CLASS_CHANGED: ('bi-calendar-x-fill', 'orange'),
	N.CHAT_MENTION: ('bi-at', 'purple'),
	N.GROUP_SESSION: ('bi-calendar-event-fill', 'teal'),
	N.SESSION_REMINDER: ('bi-alarm-fill', 'orange'),
	N.SESSION_CHANGED: ('bi-calendar2-range-fill', 'teal'),
	N.PULSE_REPLY: ('bi-fire', 'orange'),
	N.PULSE_INTEREST: ('bi-star-fill', 'orange'),
}


def display_name(user):
	return user.get_full_name() or user.username


def short_time(dt):
	"""Facebook-style age: 'now', '24m', '3h', '2d', '5w', '1y'."""
	seconds = max(0, int((timezone.now() - dt).total_seconds()))
	for unit, size in (('y', 31536000), ('w', 604800), ('d', 86400), ('h', 3600), ('m', 60)):
		if seconds >= size:
			return f'{seconds // size}{unit}'
	return 'now'


def time_ago(dt):
	"""'2 days ago', '5 minutes ago', 'just now' (the hover popup's style)."""
	if (timezone.now() - dt).total_seconds() < 60:
		return 'just now'
	return f'{timesince(dt, depth=1)} ago'


def snippet(text, limit=60):
	text = ' '.join((text or '').split())
	return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def post_noun(post):
	"""'video', 'photo' or 'post', from what the post actually contains."""
	if post is None:
		return 'post'
	media = list(post.media_items.all())
	if post.video or any(m.is_video for m in media):
		return 'video'
	if post.image or media:
		return 'photo'
	return 'post'


def comment_quote(comment):
	"""': "Nice one!"' or ' with a photo', for the end of a sentence."""
	if comment is None:
		return ''
	if (comment.content or '').strip():
		return format_html(': “{}”', snippet(comment.content))
	if comment.video:
		return mark_safe(' with a video')
	if comment.image:
		return mark_safe(' with a photo')
	return ''


def actors_html(names):
	"""'<b>A</b>', '<b>A</b> and <b>B</b>', '<b>A</b>, <b>B</b> and <b>C</b>',
	'<b>A</b>, <b>B</b> and 2 other people'."""
	bold = [format_html('<strong>{}</strong>', name) for name in names]
	if len(bold) == 1:
		return bold[0]
	if len(bold) == 2:
		return format_html('{} and {}', bold[0], bold[1])
	if len(bold) == 3:
		return format_html('{}, {} and {}', bold[0], bold[1], bold[2])
	others = len(bold) - 2
	return format_html('{}, {} and {} other {}', bold[0], bold[1], others, 'person' if others == 1 else 'people')


def sentence(type, members, actors):
	n = members[0]  # newest
	who = actors_html(actors)
	single = len(actors) == 1
	if type == N.LIKE_POST:
		return format_html('{} liked your {}.', who, post_noun(n.post))
	if type == N.LIKE_COMMENT:
		return format_html('{} liked your comment{}', who, comment_quote(n.comment) if single else '.')
	if type == N.COMMENT:
		if single and len(members) == 1:
			return format_html('{} commented on your {}{}', who, post_noun(n.post), comment_quote(n.comment))
		return format_html('{} commented on your {}.', who, post_noun(n.post))
	if type == N.REPLY:
		if single and len(members) == 1:
			return format_html('{} replied to your comment{}', who, comment_quote(n.comment))
		return format_html('{} replied to your comment.', who)
	if type == N.MENTION:
		if n.comment_id:
			return format_html('{} mentioned you in a comment{}', who, comment_quote(n.comment))
		return format_html('{} mentioned you in a {}: “{}”', who, post_noun(n.post), snippet(n.post.content if n.post else ''))
	if type in (N.GROUP_SESSION, N.SESSION_REMINDER, N.SESSION_CHANGED):
		s = n.group_session
		if s is None:
			return format_html('{} scheduled a study session.', who)
		from studygroups.sessions import when_text
		if type == N.SESSION_REMINDER:
			where = format_html(' at <strong>{}</strong>', s.place) if s.place else (' online' if s.link else '')
			return format_html('Your study session <strong>{}</strong> starts at {}{}.', s.title,
				timezone.localtime(s.starts_at).strftime('%I:%M %p').lstrip('0'), where)
		gone = ' (cancelled)' if s.is_cancelled else ''
		if type == N.SESSION_CHANGED:
			where = format_html(' · {}', s.place) if s.place else (' · online' if s.link else '')
			return format_html('{} changed the study session <strong>{}</strong> — now {}{}{}', who, s.title, when_text(s), where, gone)
		return format_html('{} scheduled a study session in <strong>{}</strong>: “{}” — {}{}', who, s.group.title, s.title, when_text(s), gone)
	if type == N.CHAT_MENTION:
		m = n.chat_message
		if m is None or m.is_deleted:
			return format_html('{} mentioned you in a group chat.', who)
		conv = m.conversation
		try:
			where = conv.study_group.title if conv.study_group else conv.name
		except Exception:
			where = conv.name
		from chat.mentions import readable
		return format_html('{} mentioned you in <strong>{}</strong>: “{}”', who, where or 'a group chat', snippet(readable(m)))
	if type in (N.PULSE_REPLY, N.PULSE_INTEREST):
		st = n.pulse_status
		what = format_html('your Campus Pulse <strong>{}</strong> update', st.get_kind_display()) if st else 'your Campus Pulse update'
		if type == N.PULSE_INTEREST:
			return format_html('{} {} interested in {}.', who, 'is' if single else 'are', what)
		return format_html('{} replied to {}.', who, what)
	if type == N.FOLLOW_REQUEST:
		return format_html('{} requested to follow you.', who)
	if type == N.FOLLOW:
		return format_html('{} started following you.', who)
	if type == N.FOLLOW_ACCEPTED:
		return format_html('{} accepted your follow request.', who)
	if type == N.EVENT_REGISTER:
		return format_html('{} registered for your event <strong>{}</strong>.', who, n.event.title)
	if type == N.LISTING_CART:
		return format_html('{} added your listing <strong>{}</strong> to their cart.', who, n.listing.title)
	if type == N.REPOST:
		return format_html('{} reposted your {}.', who, post_noun(n.post))
	if type == N.QUOTE:
		# n.post is the quote itself; what was quoted is n.post.quote_of.
		original = n.post.quote_of if n.post else None
		words = snippet(n.post.content if n.post else '')
		if not words:
			return format_html('{} quoted your {}.', who, post_noun(original))
		return format_html('{} quoted your {}: “{}”', who, post_noun(original), words)
	if type == N.COMMUNITY_JOIN:
		return format_html('{} joined <strong>{}</strong>.', who, n.community.name if n.community else 'your community')
	if type == N.COMMUNITY_REQUEST:
		return format_html('{} asked to join <strong>{}</strong>.', who, n.community.name if n.community else 'your community')
	if type == N.COMMUNITY_ACCEPTED:
		return format_html('{} approved your request to join <strong>{}</strong>.', who, n.community.name if n.community else 'a community')
	if type == N.CLASS_REMINDER:
		s = n.class_slot
		if s is None:
			return mark_safe('A class on your timetable is starting soon.')
		from courses.reminders import clock, kind_word, todays
		o = todays(s, timezone.localtime(n.created_at).date())     # moved classes: the new time
		what = format_html('<strong>{}</strong> {}', s.short, kind_word(s)) if kind_word(s) else format_html('<strong>{}</strong>', s.short)
		where = format_html(' in <strong>{}</strong>', o.venue) if o.venue else ''
		return format_html('Your {} starts at {}{}.', what, clock(o.start), where)
	if type == N.CLASS_CHANGED:
		# The department cancelled or moved one week's class (courses/official.py).
		s = n.class_slot
		day = (n.group_key or '').rsplit(':', 1)[-1]
		c = s.changes.filter(date=day).first() if s is not None and len(day) == 10 else None
		if c is None:
			return mark_safe('Your department changed a class on your timetable.')
		from courses.reminders import clock, kind_word
		what = format_html('<strong>{}</strong> {}', s.short, kind_word(s)) if kind_word(s) else format_html('<strong>{}</strong>', s.short)
		when = f'{c.date:%a} {c.date.day} {c.date:%b}'
		if c.status == c.CANCELLED:
			return format_html('Your department cancelled {} on {}.', what, when)
		nd = c.new_date or c.date
		where = format_html(' in <strong>{}</strong>', c.new_venue) if c.new_venue else ''
		return format_html('Your department moved {} on {} to {} {} {}, {}{}.', what, when, nd.strftime('%a'), nd.day,
			nd.strftime('%b'), clock(c.new_start or s.start), where)
	if type == N.COURSE_ANSWER:
		q = n.course_question
		if q is None:
			return format_html('{} answered your question.', who)
		return format_html('{} answered your question in <strong>{}</strong>: “{}”', who, q.course.code, snippet(q.title))
	if type in (N.GROUP_REQUEST, N.GROUP_ACCEPTED, N.GROUP_ANNOUNCEMENT):
		group = n.study_group.title if n.study_group else 'a group'
		if type == N.GROUP_REQUEST:
			return format_html('{} asked to join <strong>{}</strong>.', who, group)
		if type == N.GROUP_ACCEPTED:
			return format_html('{} approved your request to join <strong>{}</strong>.', who, group)
		words = snippet(n.group_post.body if n.group_post else '')
		if words:
			return format_html('{} posted an announcement in <strong>{}</strong>: “{}”', who, group, words)
		return format_html('{} posted an announcement in <strong>{}</strong>.', who, group)
	return format_html('{} interacted with your content.', who)


def build_entries(notifications):
	"""Group rows (newest first) into entries ready for the template.
	Rows group when they share a non-empty group_key and read state;
	each entry is placed where its newest row was."""
	groups = {}
	for n in notifications:
		key = (n.group_key, n.is_read) if n.group_key else ('single', n.pk)
		groups.setdefault(key, []).append(n)

	entries = []
	for members in groups.values():
		newest = members[0]
		actors, seen = [], set()
		for m in members:
			if m.actor_id not in seen:
				seen.add(m.actor_id)
				actors.append(m.actor)
		icon, colour = BADGES.get(newest.type, ('bi-bell-fill', 'blue'))
		profile = getattr(newest.actor, 'student_profile', None)
		photo = profile.profile_photo.url if profile and profile.profile_photo else ''
		# A class reminder isn't from a person: show the alarm, not your own face.
		icon_avatar = {N.CLASS_REMINDER: 'bi-alarm', N.CLASS_CHANGED: 'bi-calendar-x'}.get(newest.type, '')
		if icon_avatar:
			photo = ''
		first_name = newest.actor.first_name or newest.actor.username
		entries.append({
			'id': newest.pk,
			'actor_id': newest.actor_id,
			'ids': ','.join(str(m.pk) for m in members),
			'type': newest.type,
			'message': sentence(newest.type, members, [display_name(a) for a in actors]),
			'time': short_time(newest.created_at),
			'time_ago': time_ago(newest.created_at),
			'timestamp': newest.created_at,
			'is_read': newest.is_read,
			'avatar_url': photo,
			'initials': (first_name[:1] + (newest.actor.last_name[:1] if newest.actor.last_name else '')).upper(),
			'icon_avatar': icon_avatar,
			'badge_icon': icon,
			'badge_colour': colour,
			'url': reverse('notification_open', args=[newest.pk]),
			'is_follow_request': newest.type == N.FOLLOW_REQUEST,
			'follow_id': None,  # filled in by the view for still-pending requests
		})
	return entries


def mark_read(user, ids):
	"""Mark these notifications (the recipient's own only) as read."""
	return Notification.objects.filter(recipient=user, pk__in=ids, is_read=False).update(is_read=True)


def parse_ids(raw):
	"""'12,13,14' (from an entry's data-ids) -> [12, 13, 14]; junk is ignored."""
	return [int(part) for part in str(raw or '').split(',') if part.strip().isdigit()]
