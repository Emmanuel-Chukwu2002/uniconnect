"""Hashtag pages (/hashtag/<tag>/, templates/feed/hashtag.html).

Every #tag in a post links here (the `post_text` filter in
templatetags/post_extras.py). The page shows the posts with that tag that
you could see on Home — your university's posts plus posts in communities
you're in, minus anyone blocked or muted and posts you hid or reported —
with two tabs:

    Top     most liked first (then newest)
    Latest  newest first

and, at the top, how many posts and people used the tag and which tags are
often used with it. Trending tags (Search, Explore) link here too.
"""
import re
from collections import Counter

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import Http404
from django.shortcuts import redirect, render

from .models import Follow, Post

TAG_RE = re.compile(r'(?<![\w#&/])#(\w{2,50})')
PAGE = 30


def tags_in(text):
	"""Lower-case tags in a post, in order, without repeats."""
	seen = []
	for t in TAG_RE.findall(text or ''):
		t = t.lower()
		if t not in seen:
			seen.append(t)
	return seen


def tag_posts(user, student, tag):
	"""Posts with #tag that `user` could see on Home."""
	from .views import _visible_on_home
	qs = Post.objects.filter(author__student_profile__university=student.university, content__icontains='#' + tag)
	# icontains narrows it down; the regex keeps whole tags only (#python, not #pythonista).
	qs = qs.filter(content__iregex=r'(^|[^\w#&/])#' + tag + r'(\W|$)')
	return _visible_on_home(qs, user)


@login_required
def hashtag_page(request, tag):
	clean = tag.lower().lstrip('#')
	if not re.fullmatch(r'\w{2,50}', clean):
		raise Http404
	if clean != tag:
		return redirect('hashtag', tag=clean)
	student = getattr(request.user, 'student_profile', None)
	if student is None:
		raise Http404
	sort = 'latest' if request.GET.get('sort') == 'latest' else 'top'
	base = tag_posts(request.user, student, clean)
	people = base.values('author_id').distinct().count()
	total = base.count()
	if sort == 'top':
		qs = base.annotate(n_likes=Count('likes', distinct=True)).order_by('-n_likes', '-created_at')
	else:
		qs = base.order_by('-created_at')
	from .search import _prepare_posts
	ids = list(qs.values_list('pk', flat=True)[:PAGE])
	by_id = {p.pk: p for p in _prepare_posts(Post.objects.filter(pk__in=ids), request.user)}
	posts = [by_id[i] for i in ids if i in by_id]
	# Tags people use alongside this one.
	related = Counter()
	for text in base.values_list('content', flat=True)[:500]:
		for t in tags_in(text):
			if t != clean:
				related[t] += 1
	return render(request, 'feed/hashtag.html', {
		'tag': clean, 'sort': sort, 'posts': posts, 'total': total, 'people': people,
		'related': [t for t, _ in related.most_common(8)],
		'following_ids': set(Follow.objects.filter(follower=request.user, status=Follow.STATUS_ACCEPTED).values_list('following_id', flat=True)),
		'pending_ids': set(Follow.objects.filter(follower=request.user, status=Follow.STATUS_PENDING).values_list('following_id', flat=True)),
	})
