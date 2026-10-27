"""
"Top stories": the posts people at your university are engaging with
most right now. Shown in the right sidebar (under Events) and on the
Top Stories page.

Ranking: posts from the last 7 days with the most readers first, then
the most engagement (likes + 2 × comments, since a comment takes more
than a tap), then the newest. If that gives fewer than 4 posts, the window widens to
30 days and then to all posts, so the box is never empty on a quiet
campus.

"Readers" is the number of different people who have engaged with a
post (liked, commented on or saved it). UniConnect doesn't record who
merely scrolled past a post, so this is the honest count of people we
know read it.
"""
import re
from datetime import timedelta

from django.db.models import Count, F
from django.utils import timezone

from .models import Bookmark, Comment, Like, Post

WINDOWS_DAYS = (7, 30, None)
MIN_STORIES = 4
CANDIDATES = 60  # most-engaged posts considered before ranking by readers


def time_ago(dt, now=None):
	"""'Just now', '21 min ago', '1 hour ago', '5 hours ago', '2 days ago', '3 Oct'."""
	now = now or timezone.now()
	secs = max(0, int((now - dt).total_seconds()))
	if secs < 60:
		return 'Just now'
	mins = secs // 60
	if mins < 60:
		return f'{mins} min ago'
	hours = mins // 60
	if hours < 24:
		return f"{hours} hour{'' if hours == 1 else 's'} ago"
	days = hours // 24
	if days < 7:
		return f"{days} day{'' if days == 1 else 's'} ago"
	local = timezone.localtime(dt)
	return f'{local.day} {local:%b}' + ('' if local.year == timezone.localtime(now).year else f' {local.year}')


def headline(post):
	"""The post's first line of text, or 'Photo from Ada Obi' for a post with no text."""
	for line in (post.content or '').splitlines():
		line = re.sub(r'\s+', ' ', line).strip()
		if line:
			return line[:140]
	name = post.author.get_full_name() or post.author.username
	has_video = bool(post.video) or any(m.is_video for m in post.media_items.all())
	return f"{'Video' if has_video else 'Photo'} from {name}"


def top_stories(user, limit=8):
	student = getattr(user, 'student_profile', None)
	if student is None:
		return []
	base = (
		Post.objects.filter(author__student_profile__university=student.university)
		.annotate(n_likes=Count('likes', distinct=True), n_comments=Count('comments', distinct=True))
		.annotate(score=F('n_likes') + 2 * F('n_comments'))
		.filter(score__gt=0)
		.select_related('author')
		.prefetch_related('media_items')
		.order_by('-score', '-created_at')
	)
	# Never anyone blocked either way, nor posts you hid or reported.
	from .moderation import blocked_ids, reported_post_ids
	from .post_settings import hidden_post_ids
	base = base.exclude(author_id__in=blocked_ids(user)).exclude(pk__in=reported_post_ids(user) | hidden_post_ids(user))
	now = timezone.now()
	posts = []
	for days in WINDOWS_DAYS:
		qs = base if days is None else base.filter(created_at__gte=now - timedelta(days=days))
		posts = list(qs[:CANDIDATES])
		if len(posts) >= MIN_STORIES:
			break

	ids = [p.pk for p in posts]
	readers = {pk: set() for pk in ids}
	for model in (Like, Comment, Bookmark):
		user_field = 'author_id' if model is Comment else 'user_id'
		for post_id, uid in model.objects.filter(post_id__in=ids).values_list('post_id', user_field):
			readers[post_id].add(uid)
	posts.sort(key=lambda p: (len(readers[p.pk]), p.score, p.created_at), reverse=True)
	posts = posts[:limit]

	return [{
		'post': p,
		'headline': headline(p),
		'time_ago': time_ago(p.created_at, now),
		'readers': len(readers[p.pk]),
		'readers_text': f"{len(readers[p.pk]):,} reader{'' if len(readers[p.pk]) == 1 else 's'}",
	} for p in posts]


# ---------------------------------------------------------------------
# "Trending" cards at the top of the Top Stories page: the hashtags most
# used at your university lately (last 7 days, widening to 30 days and then
# all time when it's quiet), as soft pastel cards with an icon.
# ---------------------------------------------------------------------
# (words in the tag, Bootstrap icon) — the first match picks the icon.
TOPIC_ICONS = [
	(('exam', 'test', 'sta', 'mth', 'math', 'quiz', 'revision'), 'bi-pencil-square'),
	(('project', 'fyp', 'research'), 'bi-kanban-fill'),
	(('siwes', 'intern', 'job', 'career', 'hiring'), 'bi-briefcase-fill'),
	(('dept', 'department', 'faculty', 'week'), 'bi-building-fill'),
	(('tech', 'code', 'coding', 'django', 'python', 'computer', 'csc', 'cos', 'hack', 'ai'), 'bi-laptop-fill'),
	(('hostel', 'room', 'block'), 'bi-house-heart-fill'),
	(('music', 'cultur', 'dance', 'concert', 'party'), 'bi-music-note-beamed'),
	(('sport', 'football', 'match', 'game', 'fifa'), 'bi-trophy-fill'),
	(('mech', 'engineer', 'mee', 'eee'), 'bi-gear-wide-connected'),
	(('book', 'library', 'read', 'note'), 'bi-book-half'),
	(('food', 'suya', 'canteen'), 'bi-cup-hot-fill'),
]
TONES = ['cream', 'pink', 'blue', 'green', 'lilac', 'peach']


def _label(original):
	"""'ExamSeason' → 'Exam Season'; 'siwes' → 'Siwes'; 'STA341' → 'STA341'."""
	if original.islower():
		return original[:1].upper() + original[1:]
	return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', original)


def trending_topics(user, limit=8):
	from collections import Counter
	from .search import HASHTAG_RE
	student = getattr(user, 'student_profile', None)
	if student is None:
		return []
	now = timezone.now()
	counts, forms = Counter(), {}
	for days in WINDOWS_DAYS:
		qs = Post.objects.filter(author__student_profile__university=student.university, community__isnull=True, content__contains='#')
		if days is not None:
			qs = qs.filter(created_at__gte=now - timedelta(days=days))
		counts.clear()
		for text in qs.values_list('content', flat=True)[:3000]:
			for t in set(HASHTAG_RE.findall(text or '')):
				counts[t.lower()] += 1
				forms.setdefault(t.lower(), Counter())[t] += 1
		if len(counts) >= 3:
			break
	topics = []
	for i, (tag, n) in enumerate(counts.most_common(limit)):
		icon = next((ic for words, ic in TOPIC_ICONS if any(w in tag for w in words)), 'bi-hash')
		topics.append({'tag': tag, 'label': _label(max(forms[tag].items(), key=lambda kv: (kv[1], not kv[0].islower()))[0]), 'count': n,
			'icon': icon, 'tone': TONES[i % len(TONES)]})
	return topics
