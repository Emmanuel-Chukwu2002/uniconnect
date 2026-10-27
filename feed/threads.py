"""Threads — several connected posts, like X.

Writing one: the composer's + button (static/js/compose-tools.js) adds
another box under the post; each box is sent as `thread_part`. The first
post is saved as usual (with its photos, poll, place...), then each part
becomes a Post with thread_root = the first post and thread_index 1, 2, 3...
(compose_post in feed/views.py calls add_parts below).

Adding to one later: "Add another post" under your thread on its post page
opens the composer with ?thread=<first post id>; what you write goes on the
end of the thread.

Showing:
    Home, profiles, communities   only the first post, with "Show this thread"
    the post page                 the whole thread, joined by a line
    search, hashtags, bookmarks   any post; a later one says "Part of a thread"

Scheduling the first post schedules the whole thread (each part a second
after the one before, so they keep their order).

Editing one post of a thread is like editing any post (feed/views.py
edit_post); the edit page says which post of the thread it is.

Deleting (remove below):
    a later post          just that post goes; the others stay in order
    the first post        you choose: just that post — the next one becomes
                          the start of the thread — or the whole thread
"""
from datetime import timedelta

from django.db.models import Count, IntegerField, Max, OuterRef, Subquery
from django.db.models.functions import Coalesce

from .models import Post

MAX_PARTS = 24          # posts after the first; 25 in a thread at most
MAX_LENGTH = Post.MAX_CONTENT_LENGTH


def with_thread_size(qs):
	"""Adds post.thread_size: how many published posts follow it in its thread."""
	parts = (Post.objects.filter(thread_root=OuterRef('pk')).order_by().values('thread_root')
		.annotate(n=Count('pk')).values('n'))
	return qs.annotate(thread_size=Coalesce(Subquery(parts, output_field=IntegerField()), 0))


def clean_parts(values, already=0, files=None):
	"""The + boxes: (parts, error). Each part is {'text', 'files'} — its words
	and its own photos or video (`files[i]` for box i; the same rules as a
	post: up to 4 photos or 1 video). Boxes with neither are skipped; with an
	error the parts still come back, so the composer can show them again."""
	from django.core.exceptions import ValidationError
	from .drafts import _clean_media
	files = files or {}
	parts, error = [], ''
	for i, v in enumerate(values):
		text = (v or '').strip()
		mine = [f for f in files.get(i, []) if f]
		if not text and not mine:
			continue
		try:
			mine = _clean_media(mine)
		except ValidationError as e:
			error = error or f'Post {len(parts) + 2} in the thread: {e.messages[0]}'
			mine = []
		parts.append({'text': text, 'files': mine})
	if any(len(p['text']) > MAX_LENGTH for p in parts):
		return parts, f'Each post in a thread can be up to {MAX_LENGTH} characters.'
	if already + len(parts) > MAX_PARTS:
		return parts, f'A thread can have up to {MAX_PARTS + 1} posts.'
	return parts, error


def root_for(user, value):
	"""The thread `user` is adding to (?thread=<id>): their own first post, already out."""
	if not str(value or '').isdigit():
		return None
	return Post.objects.filter(pk=int(value), author=user, thread_root__isnull=True).select_related('community').first()


def parts_count(root):
	return Post.all_objects.filter(thread_root=root).count()


def next_index(root):
	return (Post.all_objects.filter(thread_root=root).aggregate(m=Max('thread_index'))['m'] or 0) + 1


def add_parts(root, parts, when=None, after=None):
	"""Saves `parts` on the end of `root`'s thread. `after` is the post they
	follow (the one just written, if it's itself a part). Mentions are told
	now, or when a scheduled thread goes out (feed/scheduling.py)."""
	from .notifications import notify_mentions
	from .scheduling import schedule
	index = next_index(root)
	start = when or (after or root).created_at
	made = []
	from .link_previews import attach
	from .views import _create_post_media
	for i, part in enumerate(parts):
		if isinstance(part, str):                 # just words (older callers)
			part = {'text': part, 'files': []}
		text = part['text']
		post = Post.objects.create(author=root.author, content=text, community=root.community,
			thread_root=root, thread_index=index + i)
		if part['files']:
			_create_post_media(post, part['files'])   # its own photos or video
		attach(post)
		if when:
			schedule(post, start + timedelta(seconds=i + 1))
		else:
			notify_mentions(text, root.author, post)
		made.append(post)
	return made


def thread_of(post):
	"""(first post, every published post of the thread in order) — or (post, []) if it isn't one."""
	root = post.thread_root if post.thread_root_id else post
	parts = list(Post.objects.filter(thread_root=root).order_by('thread_index', 'created_at'))
	if not parts:
		return post, []
	return root, [root] + parts


def position(post):
	"""(n, total) — post n of the thread's total — or None if it isn't in one."""
	root = post.thread_root if post.thread_root_id else post
	ids = [root.pk] + list(Post.all_objects.filter(thread_root=root).order_by('thread_index', 'created_at').values_list('pk', flat=True))
	if len(ids) < 2:
		return None
	return ids.index(post.pk) + 1, len(ids)


def remove(post, whole=False):
	"""Deletes `post` from its thread without breaking the rest.

	The first post with whole=False: the next post (by place in the thread)
	becomes the first and the rest point at it. Returns the first post of
	what's left of the thread, or None when nothing is left."""
	from django.db import transaction
	if post.thread_root_id:                       # a later post: just that one
		root = post.thread_root
		post.delete()
		return root
	parts = list(Post.all_objects.filter(thread_root=post).order_by('thread_index', 'created_at'))
	if whole or not parts:
		post.delete()                             # the parts go with it (on_delete=CASCADE)
		return None
	with transaction.atomic():
		new_root = parts[0]
		Post.all_objects.filter(pk=new_root.pk).update(thread_root=None, thread_index=0)
		Post.all_objects.filter(pk__in=[p.pk for p in parts[1:]]).update(thread_root=new_root)
		post.delete()
	new_root.refresh_from_db()
	return new_root
