"""Blocking and reporting.

Blocking (Block in feed/models.py) works both ways: once either person
blocks the other, neither sees the other's posts (Home, Search, Explore,
communities), profile, follow button or "who to follow" card, they can't
start a chat with each other, notifications between them stop, and any
follows between them are removed. Unblocking undoes only the block.

    /u/<username>/block/             POST: block / unblock (the profile's ... menu and a post's ... menu)
    /post/<id>/report/               report a post (reason + optional details)
    /u/<username>/report/            report an account
    /moderation/                     staff only: open reports, grouped by post
    /moderation/<report id>/<action>/  POST, staff: remove (delete the post) or dismiss
    /report/<kind>/<id>/             report a comment, listing, book, event, group or community
The admin dashboard (adminpanel/, /staff/) reviews every kind of report.

A post you reported disappears from your own Home straight away.
"""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Block, Follow, Post, Report

User = get_user_model()


def blocked_ids(user):
	"""Ids of everyone `user` blocked or was blocked by (cached per request user)."""
	if not getattr(user, 'is_authenticated', False):
		return set()
	cached = getattr(user, '_blocked_ids', None)
	if cached is None:
		pairs = Block.objects.filter(Q(blocker=user) | Q(blocked=user)).values_list('blocker_id', 'blocked_id')
		cached = {b if a == user.pk else a for a, b in pairs}
		user._blocked_ids = cached
	return cached


def is_blocked(a, b):
	"""True if either of the two users blocked the other."""
	if a is None or b is None:
		return False
	a_id, b_id = getattr(a, 'pk', a), getattr(b, 'pk', b)
	return Block.objects.filter(Q(blocker_id=a_id, blocked_id=b_id) | Q(blocker_id=b_id, blocked_id=a_id)).exists()


def reported_post_ids(user):
	if not getattr(user, 'is_authenticated', False):
		return set()
	return set(Report.objects.filter(reporter=user, post__isnull=False).values_list('post_id', flat=True))


def hide_blocked(qs, user, field='author_id'):
	"""Drop rows whose `field` points at someone blocked either way."""
	ids = blocked_ids(user)
	return qs.exclude(**{f'{field}__in': ids}) if ids else qs


def _back(request, fallback):
	nxt = request.POST.get('next') or request.GET.get('next')
	if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
		return redirect(nxt)
	return redirect(fallback)


@login_required
@require_POST
def block_toggle(request, username):
	target = get_object_or_404(User, username=username)
	if target.pk == request.user.pk:
		raise PermissionDenied("You can't block yourself.")
	existing = Block.objects.filter(blocker=request.user, blocked=target).first()
	name = target.get_full_name() or target.username
	if existing:
		existing.delete()
		blocked, msg = False, f'You unblocked {name}.'
	else:
		Block.objects.create(blocker=request.user, blocked=target)
		Follow.objects.filter(Q(follower=request.user, following=target) | Q(follower=target, following=request.user)).delete()
		blocked, msg = True, f'You blocked {name}. You won’t see each other’s posts or profiles.'
	if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
		return JsonResponse({'blocked': blocked, 'message': msg})
	messages.success(request, msg)
	return _back(request, reverse('user_profile', args=[target.username]))


def _report_form(request, target_user, post=None):
	if request.method == 'POST':
		reason = request.POST.get('reason')
		if reason not in dict(Report.REASON_CHOICES):
			messages.error(request, 'Choose why you are reporting this.')
		else:
			# Reporting the same thing again updates your open report rather
			# than adding another (blank details keep what you wrote before).
			# adminpanel/services.py file_report records what and whose university it is.
			from adminpanel.content import KINDS
			from adminpanel.services import file_report
			details = (request.POST.get('details') or '').strip()[:1000]
			file_report(request.user, KINDS['posts'] if post else KINDS['users'], post or target_user, reason, details)
			if request.POST.get('also_block') and target_user.pk != request.user.pk:
				Block.objects.get_or_create(blocker=request.user, blocked=target_user)
				Follow.objects.filter(Q(follower=request.user, following=target_user) | Q(follower=target_user, following=request.user)).delete()
			messages.success(request, 'Thanks — our team will review it. ' + ("You won't see this post any more." if post else ''))
			return redirect('home')
	return render(request, 'feed/report.html', {
		'post': post, 'target': target_user, 'reasons': Report.REASONS,
		'already_blocked': Block.objects.filter(blocker=request.user, blocked=target_user).exists(),
	})


@login_required
def report_post(request, post_id):
	post = get_object_or_404(Post.objects.select_related('author', 'author__student_profile'), pk=post_id)
	if post.author_id == request.user.pk:
		messages.info(request, "That's your own post — you can delete it from its menu instead.")
		return redirect('post_detail', post_id=post.pk)
	return _report_form(request, post.author, post)


# Reporting anything else: a comment, listing, book, event, group or community
# (/report/<kind>/<id>/). Same form; the report goes to the admin dashboard's queue.
REPORTABLE = {'comment': 'comments', 'listing': 'listings', 'book': 'books', 'event': 'events',
	'group': 'groups', 'community': 'communities'}


@login_required
def report_item(request, kind, pk):
	from adminpanel.content import KINDS
	from adminpanel.services import file_report
	if kind not in REPORTABLE:
		raise Http404
	k = KINDS[REPORTABLE[kind]]
	obj = k.get(pk)
	owner = k.owner(obj) if obj is not None else None
	if obj is None or owner is None:
		raise Http404
	if owner.pk == request.user.pk:
		messages.info(request, f"That's your own {k.noun}.")
		return redirect(k.url(obj) or 'home')
	item = {'noun': k.noun, 'title': k.title(obj), 'url': k.url(obj)}
	if request.method == 'POST':
		reason = request.POST.get('reason')
		if reason not in dict(Report.REASON_CHOICES):
			messages.error(request, 'Choose why you are reporting this.')
		else:
			file_report(request.user, k, obj, reason, (request.POST.get('details') or '').strip())
			if request.POST.get('also_block'):
				Block.objects.get_or_create(blocker=request.user, blocked=owner)
				Follow.objects.filter(Q(follower=request.user, following=owner) | Q(follower=owner, following=request.user)).delete()
			messages.success(request, 'Thanks — our team will review it.')
			return redirect(item['url'] or 'home')
	return render(request, 'feed/report.html', {
		'item': item, 'target': owner, 'reasons': Report.REASONS,
		'already_blocked': Block.objects.filter(blocker=request.user, blocked=owner).exists(),
	})


@login_required
def report_user(request, username):
	target = get_object_or_404(User, username=username)
	if target.pk == request.user.pk:
		raise Http404
	return _report_form(request, target)


# ---------------------------------------------------------------------
# Staff review
# ---------------------------------------------------------------------
def _staff(request):
	if not request.user.is_staff:
		raise PermissionDenied('Only UniConnect staff can review reports.')


@login_required
def moderation_page(request):
	_staff(request)
	status = request.GET.get('status', Report.OPEN)
	if status not in dict(Report.STATUS_CHOICES):
		status = Report.OPEN
	reports = list(Report.objects.filter(status=status, target_type__in=[Report.T_POST, Report.T_USER]).select_related(
		'reporter', 'post', 'post__author', 'reported_user', 'reported_user__student_profile', 'reviewed_by')[:300])
	# One card per post (or per reported account), most-reported first.
	groups = {}
	for r in reports:
		key = ('post', r.post_id) if r.post_id else ('user', r.reported_user_id, r.pk if status != Report.OPEN else 0)
		g = groups.setdefault(key, {'post': r.post, 'user': r.reported_user, 'snapshot': r.post_snapshot, 'reports': [], 'first': r})
		g['reports'].append(r)
	cards = sorted(groups.values(), key=lambda g: (-len(g['reports']), g['first'].created_at))
	for g in cards:
		counts = {}
		for r in g['reports']:
			counts[r.get_reason_display()] = counts.get(r.get_reason_display(), 0) + 1
		g['reasons'] = sorted(counts.items(), key=lambda x: -x[1])
	open_count = Report.objects.filter(status=Report.OPEN, target_type__in=[Report.T_POST, Report.T_USER]).count()
	return render(request, 'feed/moderation.html', {'cards': cards, 'status': status,
		'statuses': Report.STATUS_CHOICES, 'open_count': open_count})


@login_required
@require_POST
def moderation_action(request, report_id, action):
	_staff(request)
	report = get_object_or_404(Report, pk=report_id)
	same = Report.objects.filter(status=Report.OPEN)
	same = same.filter(post_id=report.post_id) if report.post_id else same.filter(reported_user=report.reported_user, target_type=Report.T_USER)
	now = timezone.now()
	if action == 'remove' and report.post_id:
		post = report.post
		same.update(status=Report.REMOVED, reviewed_by=request.user, reviewed_at=now)
		post.delete()
		messages.success(request, 'Post removed. Everyone who reported it is marked as handled.')
	elif action == 'dismiss':
		same.update(status=Report.DISMISSED, reviewed_by=request.user, reviewed_at=now)
		messages.success(request, 'Marked as no action needed.')
	else:
		raise Http404
	return redirect('moderation')
