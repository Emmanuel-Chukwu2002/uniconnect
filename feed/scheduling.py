"""Scheduled posts (the composer's clock button) and the Scheduled list.

A scheduled post is saved straight away, with all its photos, poll and
location, but with is_scheduled=True and created_at set to the chosen
time. Post.objects (PublishedPostManager in models.py) leaves it out until
that time, so it shows up in Home, profiles, search and hashtags exactly
when it's due, in the right place. Nothing has to run for that.

What does wait for the time: telling @mentioned people. publish_due()
does that (and marks the post as published) the first time anyone loads
a page or the bell checks after the time (feed/context_processors.py,
feed/views.py notifications_count), or when
`python manage.py publish_scheduled_posts` runs.

    /post/scheduled/                    your scheduled posts
    /post/scheduled/<id>/now/           POST: post it now
    /post/scheduled/<id>/time/          POST: change the time
    /post/scheduled/<id>/delete/        POST: delete it
"""
from datetime import datetime, timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Post

MIN_AHEAD = timedelta(minutes=5)
MAX_AHEAD = timedelta(days=30)
INPUT_FORMAT = '%Y-%m-%dT%H:%M'


def check_time(value):
	"""The scheduled time, or a ValidationError explaining what's wrong."""
	if value is None:
		return None
	if timezone.is_naive(value):
		value = timezone.make_aware(value)
	now = timezone.now()
	if value < now + MIN_AHEAD - timedelta(seconds=30):
		raise forms.ValidationError('Pick a time at least 5 minutes from now.')
	if value > now + MAX_AHEAD:
		raise forms.ValidationError('You can schedule up to 30 days ahead.')
	return value


def schedule(post, when):
	"""Turn a saved post into a scheduled one going out at `when` (also
	used to change the time). A poll keeps its length: it opens when the
	post goes out."""
	from .models import PostPoll
	shift = when - Post.all_objects.get(pk=post.pk).created_at
	Post.all_objects.filter(pk=post.pk).update(is_scheduled=True, created_at=when)
	post.is_scheduled, post.created_at = True, when
	for poll in PostPoll.objects.filter(post_id=post.pk):
		poll.closes_at += shift
		poll.save(update_fields=['closes_at'])


def publish_due():
	"""Finish posts whose time has come: tell anyone they @mention."""
	from .notifications import notify_mentions
	due = list(Post.all_objects.filter(is_scheduled=True, created_at__lte=timezone.now()).select_related('author')[:50])
	for post in due:
		# Claim it first, so two requests at once can't both notify.
		if Post.all_objects.filter(pk=post.pk, is_scheduled=True).update(is_scheduled=False):
			notify_mentions(post.content, post.author, post)
	return len(due)


def _thread_parts(post):
	"""The scheduled posts of `post`'s thread that go out with it (feed/threads.py)."""
	return list(Post.all_objects.filter(thread_root=post, is_scheduled=True, created_at__gte=post.created_at)
		.order_by('thread_index'))


def _move(post, when):
	"""A scheduled post — and the rest of its thread — to a new time."""
	parts = _thread_parts(post)
	schedule(post, when)
	for i, part in enumerate(parts):
		schedule(part, when + timedelta(seconds=i + 1))


def _mine(request, post_id):
	return get_object_or_404(Post.all_objects, pk=post_id, author=request.user, is_scheduled=True, created_at__gt=timezone.now())


def _with_saved_text(drafts):
	from django.utils.timesince import timesince

	from .drafts import draft_payload
	drafts = list(drafts)
	now = timezone.now()
	for d in drafts:
		d.saved_text = 'just now' if (now - d.updated_at).total_seconds() < 60 else f'{timesince(d.updated_at, now, depth=1)} ago'
		# For opening it in the pop-up composer (static/js/compose-tools.js).
		d.json_id = f'draft-data-{d.pk}'
		d.data = draft_payload(d)
		d.media_count = len(d.data['media'])
		d.has_video = any(m['type'].startswith('video/') for m in d.data['media'])
		d.thread_size = len(d.thread_parts or []) + 1 if d.thread_parts else 0
	return drafts


@login_required
def scheduled_list(request, tab='scheduled'):
	""""Unsent posts": the Scheduled tab here, the Drafts tab from feed/drafts.py."""
	from .models import PostDraft
	# A scheduled thread shows once, as its first post.
	posts = list(Post.all_objects.filter(author=request.user, is_scheduled=True, created_at__gt=timezone.now())
		.exclude(thread_root__is_scheduled=True, thread_root__created_at__gt=timezone.now())
		.select_related('community').prefetch_related('media_items').order_by('created_at'))
	for p in posts:
		p.thread_count = len(_thread_parts(p)) if not p.thread_root_id else 0
	return render(request, 'feed/scheduled.html', {
		'tab': tab, 'drafts': _with_saved_text(PostDraft.objects.filter(user=request.user).select_related('community').prefetch_related('media')),
		'posts': posts,
		'min_time': timezone.localtime(timezone.now() + MIN_AHEAD).strftime(INPUT_FORMAT),
		'max_time': timezone.localtime(timezone.now() + MAX_AHEAD).strftime(INPUT_FORMAT),
	})


@login_required
@require_POST
def post_now(request, post_id):
	post = _mine(request, post_id)
	now = timezone.now()
	parts = _thread_parts(post)
	Post.all_objects.filter(pk=post.pk).update(created_at=now)
	Post.all_objects.filter(pk__in=[p.pk for p in parts]).update(created_at=now)
	publish_due()
	messages.success(request, 'Posted.')
	return redirect('post_detail', post_id=post.pk)


@login_required
@require_POST
def change_time(request, post_id):
	post = _mine(request, post_id)
	try:
		when = check_time(datetime.strptime(request.POST.get('when', ''), INPUT_FORMAT))
	except (ValueError, forms.ValidationError) as e:
		messages.error(request, e.messages[0] if isinstance(e, forms.ValidationError) else 'Pick a date and time.')
		return redirect('scheduled_posts')
	_move(post, when)
	messages.success(request, f'Rescheduled for {timezone.localtime(when):%a %d %b, %I:%M %p}.'.replace(' 0', ' '))
	return redirect('scheduled_posts')


@login_required
@require_POST
def delete_scheduled(request, post_id):
	_mine(request, post_id).delete()
	messages.success(request, 'Scheduled post deleted.')
	return redirect('scheduled_posts')


# ---------------------------------------------------------------------
# Location (the composer's pin button)
# ---------------------------------------------------------------------
@login_required
def place_suggestions(request):
	"""GET /places/?q=lib — places to tag: ones people at your university
	tagged before (most used first), event venues, and event locations."""
	from collections import Counter

	from django.db.models import Count
	from django.http import JsonResponse

	from .models import Event, Venue
	q = ' '.join((request.GET.get('q') or '').split())[:60]
	student = getattr(request.user, 'student_profile', None)
	counts = Counter()
	posts = Post.objects.exclude(location='')
	if student:
		posts = posts.filter(author__student_profile__university=student.university)
	if q:
		posts = posts.filter(location__icontains=q)
	for row in posts.values('location').annotate(n=Count('id')).order_by('-n')[:12]:
		counts[row['location']] += row['n'] * 3
	for model, field in ((Venue, 'name'), (Event, 'location')):
		qs = model.objects.exclude(**{field: ''})
		if q:
			qs = qs.filter(**{f'{field}__icontains': q})
		for name in qs.values_list(field, flat=True)[:30]:
			counts[name] += 1
	seen, places = set(), []
	for name, _ in counts.most_common():
		key = name.strip().lower()
		if key and key not in seen:
			seen.add(key)
			places.append(name.strip())
		if len(places) >= 8:
			break
	return JsonResponse({'places': places})
