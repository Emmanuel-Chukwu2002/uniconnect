"""Search (/search/, templates/feed/search.html) — the search icon in the
top bar, the "Search UniConnect..." box in the right sidebar, and the search
icon on the home tabs and profile.

    /search/?q=<words>&type=<tab>

Tabs: top (a few of each), people, posts, communities, groups, events,
opportunities (open ones), market, books. Every word must match (so "python club" finds "Python Club" but not
every post with "python"). A word starting with # matches hashtags in
posts. Same rules as the rest of the app: people, posts and books are from
your own university; communities from every university (they're shared);
community posts only from communities you belong to; groups from your
university except invite-only ones (plus any group you're in); marketplace
listings only while still for sale.

With no search yet, the page shows recent searches (kept in this browser)
and what's trending: the most used #hashtags in your university's posts
over the last two weeks.
"""
import re
from collections import Counter
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from accounts.models import StudentProfile
from bookshop.models import Book
from communities.models import Community, CommunityMember
from .models import Event, Follow, Listing, Post

TABS = [
	('top', 'Top'), ('people', 'People'), ('posts', 'Posts'), ('communities', 'Communities'), ('groups', 'Groups'),
	('events', 'Events'), ('opportunities', 'Opportunities'), ('market', 'Marketplace'), ('books', 'Books'),
]
TOP_COUNTS = {'people': 3, 'posts': 5, 'communities': 3, 'groups': 3, 'events': 3, 'opportunities': 3, 'market': 4, 'books': 3}
PAGE = 30
HASHTAG_RE = re.compile(r'(?<![\w#])#(\w{2,50})')


def _words(query):
	return [w for w in query.split() if w][:8]


def _all_words(qs, words, fields):
	"""Keep rows where every word appears in at least one of the fields."""
	for word in words:
		match = Q()
		for f in fields:
			match |= Q(**{f'{f}__icontains': word})
		qs = qs.filter(match)
	return qs


def search_people(user, student, words):
	qs = (StudentProfile.objects.filter(university=student.university, user__is_active=True)
		.select_related('user', 'department', 'level'))
	# Skills count too: "python" finds everyone with Python on their profile.
	from .moderation import blocked_ids
	qs = qs.exclude(user_id__in=blocked_ids(user))
	return _all_words(qs, words, ['user__first_name', 'user__last_name', 'user__username', 'department__name', 'level__name',
		'user__skills__name']).distinct().order_by('user__first_name', 'user__last_name')


def search_posts(user, student, words):
	mine = CommunityMember.objects.filter(user=user, status=CommunityMember.ACTIVE).values('community_id')
	qs = Post.objects.filter(
		Q(community__isnull=True, author__student_profile__university=student.university) | Q(community_id__in=mine))
	from .moderation import blocked_ids, reported_post_ids
	from .post_settings import hidden_post_ids
	qs = qs.exclude(author_id__in=blocked_ids(user)).exclude(pk__in=reported_post_ids(user) | hidden_post_ids(user))
	qs = _all_words(qs, words, ['content', 'location', 'author__first_name', 'author__last_name', 'author__username'])
	return qs.order_by('-created_at')


def search_communities(user, student, words):
	# Shared by every university; your own university's first.
	from django.db.models import Case, IntegerField, Value, When
	qs = Community.objects.select_related('university').annotate(
		mine=Case(When(university=student.university, then=Value(0)), default=Value(1), output_field=IntegerField()))
	return _all_words(qs, words, ['name', 'description', 'topic']).order_by('mine', 'name')


def search_groups(user, student, words):
	from studygroups.models import StudyGroup, StudyGroupMember
	mine = StudyGroupMember.objects.filter(user=user, status=StudyGroupMember.ACTIVE).values('group_id')
	qs = StudyGroup.objects.filter(
		(Q(university=student.university) & ~Q(privacy=StudyGroup.INVITE)) | Q(pk__in=mine)
	).annotate(n_members=Count('members', filter=Q(members__status=StudyGroupMember.ACTIVE), distinct=True))
	return _all_words(qs, words, ['name', 'course_code', 'description', 'group_type']).order_by('-n_members', 'name')


def search_events(user, student, words):
	qs = _all_words(Event.objects.all(), words, ['title', 'description', 'location', 'category'])
	today = timezone.localdate()
	# Upcoming first (soonest first), then past ones (most recent first).
	upcoming = list(qs.filter(date__gte=today).order_by('date', 'time')[:PAGE])
	past = list(qs.filter(date__lt=today).order_by('-date')[:max(0, PAGE - len(upcoming))])
	return upcoming + past


def search_market(user, student, words):
	qs = Listing.objects.filter(status=Listing.STATUS_AVAILABLE).select_related('seller').prefetch_related('images')
	return _all_words(qs, words, ['title', 'description', 'category', 'location']).order_by('-created_at')


def search_books(user, student, words):
	qs = Book.objects.filter(seller__student_profile__university=student.university, status=Book.STATUS_AVAILABLE)
	return _all_words(qs, words, ['title', 'author', 'course_code', 'description']).order_by('-created_at')


def search_opportunities(user, student, words):
	from opportunities.models import Opportunity
	from opportunities.views import open_filter
	qs = Opportunity.objects.filter(university=student.university).filter(open_filter())
	return _all_words(qs, words, ['title', 'organization', 'description', 'location', 'kind']).order_by('-created_at')


SEARCHERS = {
	'people': search_people, 'posts': search_posts, 'communities': search_communities, 'groups': search_groups,
	'events': search_events, 'opportunities': search_opportunities, 'market': search_market, 'books': search_books,
}


def trending_hashtags(student, days=14, limit=8):
	since = timezone.now() - timedelta(days=days)
	texts = Post.objects.filter(author__student_profile__university=student.university, community__isnull=True,
		created_at__gte=since, content__contains='#').values_list('content', flat=True)[:2000]
	counts = Counter()
	for text in texts:
		for tag in set(t.lower() for t in HASHTAG_RE.findall(text or '')):
			counts[tag] += 1
	return counts.most_common(limit)


def _prepare_posts(posts, user):
	from .views import _attach_bookmark_data, _attach_comment_counts, _attach_like_data, _post_qs
	posts = list(_post_qs(posts))
	posts = _attach_like_data(posts, user)
	posts = _attach_comment_counts(posts)
	return _attach_bookmark_data(posts, user)


@login_required
def search_page(request):
	user = request.user
	student = getattr(user, 'student_profile', None)
	query = request.GET.get('q', '').strip()[:100]
	tab = request.GET.get('type', 'top')
	if tab not in dict(TABS):
		tab = 'top'
	words = _words(query)

	following_ids = set(Follow.objects.filter(follower=user, status=Follow.STATUS_ACCEPTED).values_list('following_id', flat=True))
	pending_ids = set(Follow.objects.filter(follower=user, status=Follow.STATUS_PENDING).values_list('following_id', flat=True))
	results, counts = {}, {}

	if student and words:
		kinds = list(SEARCHERS) if tab == 'top' else [tab]
		for kind in kinds:
			found = SEARCHERS[kind](user, student, words)
			limit = TOP_COUNTS[kind] if tab == 'top' else PAGE
			rows = list(found[:limit + 1]) if not isinstance(found, list) else found[:limit + 1]
			counts[kind] = len(rows)
			results[kind] = rows[:limit]
		if 'posts' in results:
			results['posts'] = _prepare_posts(Post.objects.filter(pk__in=[p.pk for p in results['posts']]).order_by('-created_at'), user)

	return render(request, 'feed/search.html', {
		'query': query, 'tab': tab, 'tabs': TABS, 'results': results,
		'more': {k: counts.get(k, 0) > (TOP_COUNTS[k] if tab == 'top' else PAGE) for k in counts},
		'nothing': bool(words) and not any(results.values()),
		'trending': trending_hashtags(student) if student and not words else [],
		'following_ids': following_ids, 'pending_ids': pending_ids,
	})
