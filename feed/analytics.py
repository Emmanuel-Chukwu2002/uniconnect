"""Post analytics, like X's post activity.

Counting (PostView in models.py):
    POST /posts/seen/          ids of post cards that were on screen (static/js/post-views.js)
    post_detail                opening a post (record_detail below)
Each person counts once per post per day per kind; the author never counts.

Showing (only to the author):
    /post/<id>/analytics/      one post: impressions, people reached,
                               engagements and rate, a daily chart, the
                               breakdown, and who it reached
    /analytics/                all your posts over the last 28 days

Words used on the pages:
    Impressions   times the post was seen (one per person per day, feed + opened)
    Reach         different people who saw it
    Engagements   likes + replies + reposts + quotes + bookmarks + poll votes
    Engagement rate   engagements ÷ impressions
"""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Bookmark, Comment, Follow, Like, Post, PostPoll, PostPollVote, PostView, Repost, VideoView

OVERVIEW_DAYS = 28


def _today():
	return timezone.localdate()


def record(user, post_ids, kind=PostView.FEED):
	"""Store views of these posts by `user` (skipping their own posts)."""
	if not getattr(user, 'is_authenticated', False) or not post_ids:
		return 0
	ids = list(Post.objects.filter(pk__in=post_ids).exclude(author=user).values_list('pk', flat=True))
	day = _today()
	PostView.objects.bulk_create([PostView(post_id=i, user=user, kind=kind, day=day) for i in ids], ignore_conflicts=True)
	return len(ids)


def record_detail(user, post):
	if post.author_id != getattr(user, 'pk', None):
		record(user, [post.pk], PostView.DETAIL)


@login_required
@require_POST
def posts_seen(request):
	ids = []
	for raw in (request.POST.get('ids') or '').split(',')[:100]:
		if raw.strip().isdigit():
			ids.append(int(raw))
	return JsonResponse({'recorded': record(request.user, ids)})


# ---------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------
def engagement_counts(post_ids):
	"""{post_id: {'likes': n, 'replies': n, 'reposts': n, 'quotes': n, 'bookmarks': n, 'votes': n}}"""
	out = {pid: {'likes': 0, 'replies': 0, 'reposts': 0, 'quotes': 0, 'bookmarks': 0, 'votes': 0} for pid in post_ids}
	for key, qs, field in (
		('likes', Like.objects, 'post_id'),
		('replies', Comment.objects, 'post_id'),
		('reposts', Repost.objects, 'post_id'),
		('bookmarks', Bookmark.objects, 'post_id'),
		('votes', PostPollVote.objects, 'poll__post_id'),
		('quotes', Post.objects.filter(is_quote=True), 'quote_of_id'),
	):
		for row in qs.filter(**{f'{field}__in': post_ids}).values(field).annotate(n=Count('pk')):
			out[row[field]][key] = row['n']
	for counts in out.values():
		counts['total'] = sum(counts.values())
	return out


def view_counts(post_ids, since=None):
	"""{post_id: {'impressions': n, 'reach': n, 'opens': n}}"""
	qs = PostView.objects.filter(post_id__in=post_ids)
	if since:
		qs = qs.filter(day__gte=since)
	out = {pid: {'impressions': 0, 'reach': 0, 'opens': 0} for pid in post_ids}
	for row in qs.values('post_id').annotate(
			impressions=Count('pk'), reach=Count('user', distinct=True), opens=Count('pk', filter=Q(kind=PostView.DETAIL))):
		out[row['post_id']].update(impressions=row['impressions'], reach=row['reach'], opens=row['opens'])
	return out


def rate(engagements, impressions):
	"""'4.2%' — or '–' before anyone has seen it."""
	if not impressions or engagements > impressions:
		# Nobody seen yet — or an older post whose likes came before views
		# were counted, which would give a meaningless 250%.
		return '–'
	pct = 100 * engagements / impressions
	return f'{pct:.1f}%' if pct < 10 else f'{pct:.0f}%'


def daily_bars(qs, start, days):
	"""Impressions per day as bars for the chart: [{'day', 'n', 'pct', 'label', 'short'}]."""
	counts = {row['day']: row['n'] for row in qs.filter(day__gte=start).values('day').annotate(n=Count('pk'))}
	rows = [(start + timedelta(days=i)) for i in range(days)]
	top = max([counts.get(d, 0) for d in rows] + [0])
	scale = nice_max(top)
	return [{
		'day': d, 'n': counts.get(d, 0), 'pct': round(100 * counts.get(d, 0) / scale, 1) if scale else 0,
		'label': d.strftime('%a %d %b').replace(' 0', ' '), 'short': d.strftime('%d').lstrip('0'),
	} for d in rows], scale


def nice_max(n):
	"""A clean top for the y-axis: 4 -> 5, 13 -> 15, 72 -> 80, 340 -> 400."""
	if n <= 0:
		return 0
	for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000):
		top = -(-n // step) * step
		if top / step <= 5:
			return top
	return n


def compact(n):
	if n < 1000:
		return str(n)
	if n < 10000:
		return f'{n / 1000:.1f}'.rstrip('0').rstrip('.') + 'K'
	return f'{n // 1000}K'


# ---------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------
@login_required
def post_analytics(request, post_id):
	post = get_object_or_404(Post.objects.select_related('author'), pk=post_id)
	if post.author_id != request.user.pk:
		raise PermissionDenied('Only the person who posted this can see its activity.')
	eng = engagement_counts([post.pk])[post.pk]
	views = view_counts([post.pk])[post.pk]
	posted = timezone.localdate(post.created_at)
	days = max(1, min(14, (_today() - posted).days + 1))
	bars, scale = daily_bars(PostView.objects.filter(post=post), _today() - timedelta(days=days - 1), days)

	# Who it reached: followers vs not, and your own department.
	viewers = set(PostView.objects.filter(post=post).values_list('user_id', flat=True))
	followers = set(Follow.objects.filter(following=request.user, status=Follow.STATUS_ACCEPTED, follower_id__in=viewers)
		.values_list('follower_id', flat=True))
	student = getattr(request.user, 'student_profile', None)
	same_dept = 0
	if student and viewers:
		from accounts.models import StudentProfile
		same_dept = StudentProfile.objects.filter(user_id__in=viewers, department_id=student.department_id).count()

	def share(n):
		return round(100 * n / len(viewers)) if viewers else 0

	has_video = bool(post.video) or any(m.is_video for m in post.media_items.all())
	breakdown = [
		('bi-heart', 'Likes', eng['likes']),
		('bi-chat', 'Replies', eng['replies']),
		('bi-repeat', 'Reposts', eng['reposts']),
		('bi-quote', 'Quotes', eng['quotes']),
		('bi-bookmark', 'Bookmarks', eng['bookmarks']),
	]
	if PostPoll.objects.filter(post=post).exists():
		breakdown.append(('bi-bar-chart-steps', 'Poll votes', eng['votes']))
	breakdown.append(('bi-box-arrow-up-right', 'Opened the post', views['opens']))
	if has_video:
		breakdown.append(('bi-play-circle', 'Video views', VideoView.objects.filter(post=post).count()))
	return render(request, 'feed/post_analytics.html', {
		'post': post, 'eng': eng, 'views': views, 'rate': rate(eng['total'], views['impressions']),
		'bars': bars, 'scale': scale, 'scale_mid': scale // 2 if scale else 0, 'days': days,
		'chart_note': 'Since it was posted today' if days == 1 else f'Last {days} days',
		'breakdown': breakdown, 'reach_total': len(viewers),
		'audience': [('Follow you', share(len(followers))), ('Don’t follow you yet', share(len(viewers) - len(followers))),
			('In your department', share(same_dept))],
	})


@login_required
def analytics_overview(request):
	start = _today() - timedelta(days=OVERVIEW_DAYS - 1)
	posts = list(Post.objects.filter(author=request.user).order_by('-created_at')[:60])
	ids = [p.pk for p in posts]
	eng = engagement_counts(ids)
	views = view_counts(ids)
	for p in posts:
		p.eng, p.v = eng[p.pk], views[p.pk]
		p.rate = rate(p.eng['total'], p.v['impressions'])
	bars, scale = daily_bars(PostView.objects.filter(post__author=request.user), start, OVERVIEW_DAYS)
	period_ids = [p.pk for p in posts if timezone.localdate(p.created_at) >= start] or []
	recent_views = view_counts(ids, since=start)
	impressions = sum(v['impressions'] for v in recent_views.values())
	reach = PostView.objects.filter(post__author=request.user, day__gte=start).values('user').distinct().count()
	engagements = sum(eng[i]['total'] for i in period_ids)
	new_followers = Follow.objects.filter(following=request.user, status=Follow.STATUS_ACCEPTED,
		created_at__date__gte=start).count()
	top = max(posts, key=lambda p: (p.v['impressions'], p.eng['total']), default=None)
	return render(request, 'feed/analytics.html', {
		'posts': posts, 'shown': posts if request.GET.get('all') else posts[:20], 'bars': bars, 'scale': scale, 'scale_mid': scale // 2 if scale else 0, 'days': OVERVIEW_DAYS,
		'chart_note': f'All your posts, last {OVERVIEW_DAYS} days',
		'tiles': [
			('Impressions', compact(impressions), 'Times your posts were seen'),
			('People reached', compact(reach), 'Different people who saw them'),
			('Engagements', compact(engagements), f'On posts from the last {OVERVIEW_DAYS} days'),
			('New followers', compact(new_followers), f'In the last {OVERVIEW_DAYS} days'),
		],
		'top': top if top and top.v['impressions'] else None,
	})
