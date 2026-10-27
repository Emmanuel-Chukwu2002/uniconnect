"""Trending: the posts at your university getting the most engagement *right now*
(Home's "Trending" tab).

Every engagement event already recorded counts, with time decay — an event
half as important every HALF_LIFE_HOURS hours:

    likes (feed.Like)          1.0
    comments (feed.Comment)    2.0   (a comment takes more than a tap)
    reposts (feed.Repost)      2.5   (sharing it to your own followers)
    saves (feed.Bookmark)      1.5
    opens (feed.PostView DETAIL) 0.6
    seen in a feed (PostView FEED) 0.15

    score = Σ weight × log(1 + decayed count)   — log per signal, so no one
            signal (say, a flood of views) can carry a post on its own
    posts with views but no likes/comments/reposts/saves get a quarter of their score
    × gravity: the post's own age halves the score every POST_HALF_LIFE_HOURS

Counted honestly: only engagement in the last WINDOW_DAYS, never the author's own,
never anyone blocked by you, and never demo rows (PostView.is_simulated).
Shown only what Home would show you (feed/views.py _visible_on_home: no one
blocked either way, no posts you reported or marked Not interested, nobody you
muted, community posts only from your communities). Each post appears once.

Personal tilt: posts sharing a #hashtag with posts you marked Interested get
+15%; posts sharing one with posts you marked Not interested get −40%.
The creator is never penalised for that.
"""
import math
from datetime import timedelta

from django.utils import timezone

from .eligibility import Viewer
from .models import Feedback as F

HALF_LIFE_HOURS = 24
POST_HALF_LIFE_HOURS = 72
WINDOW_DAYS = 7
WEIGHTS = {'like': 1.0, 'comment': 2.0, 'repost': 2.5, 'save': 1.5, 'open': 0.6, 'seen': 0.15}
ENGAGEMENT = ('like', 'comment', 'repost', 'save')


def _signals(post_ids, since):
	from feed.models import Bookmark, Comment, Like, PostView, Repost
	yield 'like', Like.objects.filter(post_id__in=post_ids, created_at__gte=since).values_list('post_id', 'user_id', 'created_at')
	yield 'comment', Comment.objects.filter(post_id__in=post_ids, created_at__gte=since).values_list('post_id', 'author_id', 'created_at')
	yield 'repost', Repost.objects.filter(post_id__in=post_ids, created_at__gte=since).values_list('post_id', 'user_id', 'created_at')
	yield 'save', Bookmark.objects.filter(post_id__in=post_ids, created_at__gte=since).values_list('post_id', 'user_id', 'created_at')
	views = PostView.objects.filter(post_id__in=post_ids, created_at__gte=since, is_simulated=False)
	yield 'open', views.filter(kind=PostView.DETAIL).values_list('post_id', 'user_id', 'created_at')
	yield 'seen', views.filter(kind=PostView.FEED).values_list('post_id', 'user_id', 'created_at')


def trending_posts(user, limit=30, viewer=None, now=None):
	"""Ranked posts (each with .trend_score), most trending first."""
	v = viewer or Viewer(user)
	if not v.is_student:
		return []
	from feed.models import Bookmark, Comment, Like, Post, PostView, Repost
	from feed.views import _post_qs, _visible_on_home
	from feed.hashtags import tags_in
	now = now or timezone.now()
	since = now - timedelta(days=WINDOW_DAYS)

	# Candidates: visible posts at your university with any engagement in the window.
	active = set()
	for model, field in ((Like, 'post_id'), (Comment, 'post_id'), (Repost, 'post_id'), (Bookmark, 'post_id')):
		active |= set(model.objects.filter(created_at__gte=since).values_list(field, flat=True))
	active |= set(PostView.objects.filter(created_at__gte=since, is_simulated=False).values_list('post_id', flat=True))
	posts = list(_visible_on_home(Post.objects.filter(pk__in=active,
		author__student_profile__university_id=v.profile.university_id), v.user).only('pk', 'author_id', 'created_at', 'content'))
	if not posts:
		return []
	by_id = {p.pk: p for p in posts}
	authors = {p.pk: p.author_id for p in posts}

	decayed = {}
	for signal, rows in _signals(list(by_id), since):
		for pid, uid, when in rows:
			if uid == authors.get(pid) or uid in v.blocked:
				continue
			hours = max(0.0, (now - when).total_seconds() / 3600)
			d = decayed.setdefault(pid, {})
			d[signal] = d.get(signal, 0.0) + 0.5 ** (hours / HALF_LIFE_HOURS)

	fb = v.feedback(F.POST)
	liked_tags, disliked_tags = set(), set()
	if fb:
		for p in Post.objects.filter(pk__in=list(fb)).only('pk', 'content'):
			(liked_tags if fb[p.pk] == F.INTERESTED else disliked_tags).update(t.lower() for t in tags_in(p.content))

	scored = {}
	for pid, d in decayed.items():
		score = sum(WEIGHTS[s] * math.log1p(c) for s, c in d.items())
		if not any(d.get(s) for s in ENGAGEMENT):
			score *= 0.25                    # views alone don't make a post trend
		age_h = max(0.0, (now - by_id[pid].created_at).total_seconds() / 3600)
		score *= 0.5 ** (age_h / POST_HALF_LIFE_HOURS)
		tags = {t.lower() for t in tags_in(by_id[pid].content)}
		if tags & disliked_tags:
			score *= 0.6
		elif tags & liked_tags:
			score *= 1.15
		if score > 0:
			scored[pid] = score

	ranked = sorted(scored, key=lambda pid: (-scored[pid], -pid))[:limit]
	full = {p.pk: p for p in _post_qs(Post.objects.filter(pk__in=ranked))}
	out = []
	for pid in ranked:
		if pid in full:
			full[pid].trend_score = round(scored[pid], 4)
			out.append(full[pid])
	return out
