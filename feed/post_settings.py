"""The rest of a post's "..." menu.

On someone else's post:
    /post/<id>/hide/          POST: "Not interested in this post" (toggle, so the card can offer Undo)
    /u/<username>/mute/       POST: "Mute @user" — their posts and reposts leave your Home
                              (still on their profile; they aren't told). Settings lists who you muted.
On your own post:
    /post/<id>/settings/      who can reply (everyone / people you follow / people you mention)
                              and a content disclosure label (paid promotion / made with AI)
    /post/<id>/mute-replies/  POST: stop (or restart) notifications for comments on it
"""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Follow, HiddenPost, Mute, Post

User = get_user_model()


def _ajax(request):
	return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _back(request, fallback='home'):
	nxt = request.POST.get('next') or request.GET.get('next')
	if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
		return redirect(nxt)
	return redirect(fallback)


def muted_ids(user):
	if not getattr(user, 'is_authenticated', False):
		return set()
	return set(Mute.objects.filter(muter=user).values_list('muted_id', flat=True))


def hidden_post_ids(user):
	if not getattr(user, 'is_authenticated', False):
		return set()
	return set(HiddenPost.objects.filter(user=user).values_list('post_id', flat=True))


def mentioned_usernames(text):
	from .notifications import MENTION_RE
	return {m.rstrip('.').lower() for m in MENTION_RE.findall(text or '')}


def can_reply(post, user):
	"""(allowed, note) — note explains who can reply when it isn't everyone."""
	if post.reply_policy == Post.REPLY_EVERYONE:
		return True, ''
	name = post.author.first_name or post.author.username
	if post.reply_policy == Post.REPLY_FOLLOWING:
		ok = user.pk == post.author_id or Follow.objects.filter(
			follower_id=post.author_id, following=user, status=Follow.STATUS_ACCEPTED).exists()
		return ok, f'Only people {name} follows can reply.'
	ok = user.pk == post.author_id or user.username.lower() in mentioned_usernames(post.content)
	return ok, f'Only people {name} mentioned can reply.'


@login_required
@require_POST
def hide_post(request, post_id):
	post = get_object_or_404(Post, pk=post_id)
	row = HiddenPost.objects.filter(user=request.user, post=post).first()
	if row:
		row.delete()
		hidden = False
	else:
		if post.author_id == request.user.pk:
			raise PermissionDenied
		HiddenPost.objects.create(user=request.user, post=post)
		from recommendations.feedback import clear_post_interest
		clear_post_interest(request.user, post.pk)     # Not interested replaces an earlier Interested
		hidden = True
	if _ajax(request):
		return JsonResponse({'hidden': hidden})
	messages.success(request, "You won't see this post any more." if hidden else 'Post brought back.')
	return _back(request)


@login_required
@require_POST
def mute_toggle(request, username):
	target = get_object_or_404(User, username=username)
	if target.pk == request.user.pk:
		raise PermissionDenied("You can't mute yourself.")
	row = Mute.objects.filter(muter=request.user, muted=target).first()
	if row:
		row.delete()
		muted, msg = False, f'You unmuted @{target.username}.'
	else:
		Mute.objects.create(muter=request.user, muted=target)
		muted, msg = True, f"You muted @{target.username}. Their posts won't show on your Home."
	if _ajax(request):
		return JsonResponse({'muted': muted, 'message': msg})
	messages.success(request, msg)
	return _back(request)


def _own_post(request, post_id):
	post = get_object_or_404(Post.objects.select_related('author'), pk=post_id)
	if post.author_id != request.user.pk:
		raise PermissionDenied('Only the person who posted this can change it.')
	return post


@login_required
def post_settings(request, post_id):
	post = _own_post(request, post_id)
	section = request.GET.get('s') if request.GET.get('s') in ('reply', 'disclosure') else 'reply'
	if request.method == 'POST':
		if 'reply_policy' in request.POST and request.POST['reply_policy'] in dict(Post.REPLY_CHOICES):
			post.reply_policy = request.POST['reply_policy']
			post.save(update_fields=['reply_policy'])
			messages.success(request, f'Who can reply: {post.get_reply_policy_display()}.')
		elif 'disclosure' in request.POST and request.POST['disclosure'] in dict(Post.DISCLOSURE_CHOICES):
			post.disclosure = request.POST['disclosure']
			post.save(update_fields=['disclosure'])
			messages.success(request, f'Label: {post.get_disclosure_display()}.' if post.disclosure else 'Label removed.')
		return _back(request) if request.POST.get('next') else redirect('post_detail', post_id=post.pk)
	return render(request, 'feed/post_settings.html', {
		'post': post, 'section': section, 'mentioned': sorted(mentioned_usernames(post.content)),
		'reply_options': [
			(Post.REPLY_EVERYONE, 'Everyone', 'bi-globe2', 'Anyone who can see the post'),
			(Post.REPLY_FOLLOWING, 'People you follow', 'bi-person-check', 'Only accounts you follow'),
			(Post.REPLY_MENTIONED, 'Only people you mention', 'bi-at', 'Only the @people named in the post'),
		],
		'disclosure_options': [
			('', 'No label', 'bi-dash-circle', ''),
			(Post.DISCLOSE_PROMO, 'Paid promotion', 'bi-megaphone', "You were paid or given something to post this (e.g. a brand or a business on campus)"),
			(Post.DISCLOSE_AI, 'Made with AI', 'bi-stars', 'The photo, video or text was made or heavily edited with AI'),
		],
	})


@login_required
@require_POST
def mute_replies(request, post_id):
	post = _own_post(request, post_id)
	post.replies_muted = not post.replies_muted
	post.save(update_fields=['replies_muted'])
	msg = "You won't be notified about replies to this post." if post.replies_muted else "You'll be notified about replies again."
	if _ajax(request):
		return JsonResponse({'muted': post.replies_muted, 'message': msg})
	messages.success(request, msg)
	return _back(request)
