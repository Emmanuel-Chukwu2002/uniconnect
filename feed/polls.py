"""Polls in feed posts (PostPoll in feed/models.py), like X polls.

    create_poll(post, options, days)   called by compose_post when the composer's poll is on
    poll_state(poll, user)             what the post card shows (templates/feed/_post_poll.html)
    /post/<id>/poll/vote/              POST option: vote (once; votes are final)

Like X: the post's author can't vote in their own poll and sees the
results from the start; everyone else votes once, then sees the results.
Once the poll closes everyone sees the final results.
"""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Post, PostPoll, PostPollOption, PostPollVote


def create_poll(post, options, days):
	days = days if days in (1, 3, 7) else 1
	poll = PostPoll.objects.create(post=post, closes_at=timezone.now() + timedelta(days=days))
	PostPollOption.objects.bulk_create([PostPollOption(poll=poll, text=t, position=i) for i, t in enumerate(options[:4])])
	return poll


def time_left(poll):
	secs = int((poll.closes_at - timezone.now()).total_seconds())
	if secs <= 0:
		return 'Final results'
	for size, unit in ((86400, 'day'), (3600, 'hour'), (60, 'minute')):
		if secs >= size:
			n = secs // size
			return f'{n} {unit}{"" if n == 1 else "s"} left'
	return 'Less than a minute left'


def poll_state(poll, user):
	options = list(poll.options.annotate(n=Count('votes')))
	total = sum(o.n for o in options)
	mine = PostPollVote.objects.filter(poll=poll, user=user).values_list('option_id', flat=True).first() if getattr(user, 'is_authenticated', False) else None
	closed = poll.is_closed
	is_author = getattr(user, 'pk', None) == poll.post.author_id
	show = bool(mine) or closed or is_author
	top = max((o.n for o in options), default=0)
	for o in options:
		o.percent = round(100 * o.n / total) if total else 0
		o.mine = o.pk == mine
		o.leading = bool(total) and o.n == top
	return {'poll': poll, 'options': options, 'total': total, 'voted': bool(mine), 'closed': closed,
		'show_results': show, 'is_author': is_author, 'can_vote': not show, 'time_left': time_left(poll)}


@login_required
@require_POST
def vote(request, post_id):
	post = get_object_or_404(Post.objects.select_related('poll'), pk=post_id)
	poll = getattr(post, 'poll', None)
	if poll is None:
		return JsonResponse({'error': 'This post has no poll.'}, status=404)
	option = PostPollOption.objects.filter(pk=request.POST.get('option') or 0, poll=poll).first()
	error = ''
	if option is None:
		error = 'Choose one of the options.'
	elif poll.is_closed:
		error = 'This poll has closed.'
	elif post.author_id == request.user.pk:
		error = "You can't vote in your own poll."
	else:
		try:
			with transaction.atomic():
				PostPollVote.objects.create(poll=poll, option=option, user=request.user)
		except IntegrityError:
			error = 'You already voted in this poll.'
	if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
		html = render_to_string('feed/_post_poll.html', {'post': post, 'pp': poll_state(poll, request.user)}, request=request)
		return JsonResponse({'html': html, 'error': error}, status=400 if error else 200)
	return redirect('post_detail', post_id=post.pk)
