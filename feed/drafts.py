"""Drafts — unfinished posts (PostDraft).

Closing the composer with something typed asks "Save this post?" —
Save draft / Discard / Keep editing (static/js/compose-tools.js). Saving
posts the composer's form here. Drafts keep everything: the text, poll
choices and length, location, community, the scheduled time (if one was
picked), up to 4 photos or 1 video (PostDraftMedia), the rest of a thread
(the + boxes) and, for "Add another post", the thread it goes on. Opening a draft
puts all of it back in the composer (draft_payload below).

    POST /post/drafts/save/           save (or update, with draft_id) — JSON
    GET  /post/drafts/                the Drafts tab of "Unsent posts" (Scheduled is the other tab)
    GET  /post/new/?draft=<id>        open a draft in the composer (feed/views.py compose_post)
    POST /post/drafts/<id>/delete/

Posting or scheduling a draft deletes it (compose_post).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from datetime import datetime

from django.core.exceptions import ValidationError

from .models import Post, PostDraft, PostDraftMedia, validate_image_size, validate_video_size

INPUT_FORMAT = '%Y-%m-%dT%H:%M'


def draft_payload(draft):
	"""Everything the composer needs to reopen a draft (static/js/compose-tools.js fillDraft)."""
	when = ''
	if draft.schedule_at and draft.schedule_at > timezone.now():
		when = timezone.localtime(draft.schedule_at).strftime(INPUT_FORMAT)
	return {
		'id': draft.pk, 'content': draft.content, 'poll': draft.poll_options, 'poll_days': draft.poll_days,
		'location': draft.location, 'schedule_at': when,
		'thread': draft.thread_parts or [], 'thread_root': draft.thread_root_id,
		'media': [_media_json(m) for m in draft.media.all() if not m.part],
		# The + boxes' own photos/videos: {"1": [...], "2": [...]} (box number, from 1).
		'thread_media': {str(k): v for k, v in _part_media(draft).items()},
	}


def _media_json(m):
	return {'url': m.file.url, 'name': m.name or m.file.name.rsplit('/', 1)[-1], 'type': m.content_type}


def _part_media(draft):
	out = {}
	for m in draft.media.all():
		if m.part:
			out.setdefault(m.part, []).append(_media_json(m))
	return out


def _clean_media(files):
	"""The composer's files, checked like a post's: up to 4 photos, or one video."""
	files = [f for f in files if f and f.size][:4]
	kinds = []
	for f in files:
		ext = f.name.rsplit('.', 1)[-1].lower() if '.' in f.name else ''
		if ext in Post.ALLOWED_IMAGE_EXTENSIONS:
			validate_image_size(f)
			kinds.append('image')
		elif ext in Post.ALLOWED_VIDEO_EXTENSIONS:
			validate_video_size(f)
			kinds.append('video')
		else:
			raise ValidationError('Only photos (jpg, png, gif, webp) and videos (mp4, mov, webm) can be saved.')
	if 'video' in kinds and len(kinds) > 1:
		raise ValidationError('A post can have photos or one video, not both.')
	return files


def poll_choices(data):
	out, seen = [], set()
	for i in range(1, 5):
		text = ' '.join((data.get(f'poll_option_{i}') or '').split())[:25]
		if text and text.lower() not in seen:
			seen.add(text.lower())
			out.append(text)
	return out


def draft_for(user, draft_id):
	if not str(draft_id or '').isdigit():
		return None
	return PostDraft.objects.filter(pk=int(draft_id), user=user).select_related('community').first()


@login_required
@require_POST
def save_draft(request):
	data = request.POST
	content = (data.get('content') or '').strip()[:500]
	choices = poll_choices(data) if data.get('poll') else []
	location = ' '.join((data.get('location') or '').split())[:80]
	try:
		files = _clean_media(request.FILES.getlist('media'))
	except ValidationError as e:
		return JsonResponse({'error': e.messages[0]}, status=400)
	from .threads import MAX_PARTS, root_for
	# The + boxes: words and their own photos/video; empty boxes are dropped.
	parts, part_files = [], []
	for i, text in enumerate(data.getlist('thread_part')):
		text = (text or '').strip()[:500]
		try:
			mine = _clean_media(request.FILES.getlist(f'thread_media_{i}'))
		except ValidationError as e:
			return JsonResponse({'error': f'Post {i + 2} in the thread: {e.messages[0]}'}, status=400)
		if text or mine:
			parts.append(text)
			part_files.append(mine)
	parts, part_files = parts[:MAX_PARTS], part_files[:MAX_PARTS]
	if not content and not choices and not files and not parts:
		return JsonResponse({'error': 'Write something first — an empty post can’t be saved.'}, status=400)
	draft = draft_for(request.user, data.get('draft_id'))
	if draft is None:
		if PostDraft.objects.filter(user=request.user).count() >= PostDraft.MAX:
			return JsonResponse({'error': f'You have {PostDraft.MAX} drafts — delete some first.'}, status=400)
		draft = PostDraft(user=request.user)
	community_id = data.get('community')
	if community_id and str(community_id).isdigit():
		from communities.models import CommunityMember
		if CommunityMember.objects.filter(user=request.user, community_id=int(community_id), status=CommunityMember.ACTIVE).exists():
			draft.community_id = int(community_id)
	draft.content, draft.poll_options, draft.location = content, choices, location
	draft.thread_parts = parts
	draft.thread_root = root_for(request.user, data.get('thread'))
	try:
		draft.poll_days = int(data.get('poll_days') or 1) if int(data.get('poll_days') or 1) in (1, 3, 7) else 1
	except ValueError:
		draft.poll_days = 1
	# The scheduled time, if one was picked and it's still ahead. It's
	# checked properly (5 minutes – 30 days) when the post is scheduled.
	draft.schedule_at = None
	if data.get('schedule_at'):
		try:
			when = timezone.make_aware(datetime.strptime(data.get('schedule_at', ''), INPUT_FORMAT))
			if when > timezone.now():
				draft.schedule_at = when
		except ValueError:
			pass
	draft.save()
	# Photos and videos: the composer always sends all of them (the ones
	# reopened from the draft too), so the saved set is replaced.
	draft.media.all().delete()
	for part, group in enumerate([files] + part_files):
		for i, f in enumerate(group):
			PostDraftMedia.objects.create(draft=draft, file=f, name=f.name[:120],
				content_type=(getattr(f, 'content_type', '') or '')[:60], order=i, part=part)
	return JsonResponse({'ok': True, 'id': draft.pk, 'count': PostDraft.objects.filter(user=request.user).count()})


@login_required
def drafts_page(request):
	from .scheduling import scheduled_list
	return scheduled_list(request, tab='drafts')


@login_required
@require_POST
def delete_draft(request, draft_id):
	get_object_or_404(PostDraft, pk=draft_id, user=request.user).delete()
	messages.success(request, 'Draft deleted.')
	return redirect('post_drafts')
