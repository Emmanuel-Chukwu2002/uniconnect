"""Bookmark folders, like X's (BookmarkFolder in models.py).

Putting a post in a folder: "Save to folder" in a post's ... menu, or "Add to
folder" on the note that pops up after bookmarking (static/js/bookmark-folders.js).
Both open the folder picker, which uses:

    GET  /bookmarks/folders/?post=<id>       folders, and which one the post is in (JSON)
    POST /bookmarks/folders/put/             post + folder ('' = no folder); bookmarks it if it wasn't
    POST /bookmarks/folders/new/             name (+ post: put it straight in)

The Bookmarks page (feed/views.py bookmarks_page) shows the folders as chips
above the saved posts: /bookmarks/?folder=<id>. There a folder can be renamed
or deleted (its posts stay bookmarked, back in "All"):

    POST /bookmarks/folders/<id>/rename/
    POST /bookmarks/folders/<id>/delete/

Everything is private: only your own folders and bookmarks are ever read.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from .interactions import log_interaction
from .models import Bookmark, BookmarkFolder, Interaction, Post


def folders_for(user):
	"""The user's folders, each with .n (how many posts are in it)."""
	return list(BookmarkFolder.objects.filter(user=user).annotate(n=Count('bookmarks')).order_by('name'))


def clean_name(name, user, exclude=None):
	"""(name, error) for a new or renamed folder."""
	name = ' '.join((name or '').split())
	if not name:
		return '', 'Give the folder a name.'
	if len(name) > BookmarkFolder.NAME_LENGTH:
		return '', f'Folder names can be up to {BookmarkFolder.NAME_LENGTH} characters.'
	same = BookmarkFolder.objects.filter(user=user, name__iexact=name)
	if exclude:
		same = same.exclude(pk=exclude.pk)
	if same.exists():
		return '', f'You already have a folder called “{name}”.'
	return name, ''


def _folder_json(f):
	return {'id': f.pk, 'name': f.name, 'n': getattr(f, 'n', 0)}


def _visible_post(user, post_id):
	from .moderation import blocked_ids
	post = get_object_or_404(Post, pk=post_id)
	if post.author_id in blocked_ids(user):
		return None
	return post


def _save(user, post, folder):
	"""Bookmarks `post` (if it isn't yet) and puts it in `folder` (None = no folder)."""
	bookmark, created = Bookmark.objects.get_or_create(user=user, post=post, defaults={'folder': folder})
	if created:
		log_interaction(user, Interaction.ITEM_POST, post.pk, Interaction.ACTION_BOOKMARK)
	elif bookmark.folder_id != (folder.pk if folder else None):
		bookmark.folder = folder
		bookmark.save(update_fields=['folder'])
	return bookmark


def _done(bookmark, folder):
	where = f'Saved to {folder.name}.' if folder else 'Saved to Bookmarks (no folder).'
	return JsonResponse({'ok': True, 'bookmarked': True, 'post': bookmark.post_id,
		'folder': _folder_json(folder) if folder else None, 'message': where})


@login_required
def folder_list(request):
	current = None
	post_id = request.GET.get('post')
	if post_id and str(post_id).isdigit():
		current = Bookmark.objects.filter(user=request.user, post_id=int(post_id)).first()
	return JsonResponse({
		'folders': [_folder_json(f) for f in folders_for(request.user)],
		'bookmarked': current is not None, 'current': current.folder_id if current else None,
		'max': BookmarkFolder.MAX,
	})


@login_required
@require_POST
def put_in_folder(request):
	if not str(request.POST.get('post') or '').isdigit():
		return JsonResponse({'error': 'Which post?'}, status=400)
	post = _visible_post(request.user, int(request.POST['post']))
	if post is None:
		return JsonResponse({'error': 'You can’t save this post.'}, status=403)
	folder = None
	if request.POST.get('folder'):
		folder = BookmarkFolder.objects.filter(user=request.user, pk=request.POST['folder']).first() \
			if str(request.POST['folder']).isdigit() else None
		if folder is None:
			return JsonResponse({'error': 'That folder doesn’t exist any more.'}, status=404)
	return _done(_save(request.user, post, folder), folder)


@login_required
@require_POST
def new_folder(request):
	if BookmarkFolder.objects.filter(user=request.user).count() >= BookmarkFolder.MAX:
		return JsonResponse({'error': f'You can have up to {BookmarkFolder.MAX} folders.'}, status=400)
	name, error = clean_name(request.POST.get('name'), request.user)
	if error:
		return JsonResponse({'error': error}, status=400)
	post = None
	if str(request.POST.get('post') or '').isdigit():
		post = _visible_post(request.user, int(request.POST['post']))
		if post is None:
			return JsonResponse({'error': 'You can’t save this post.'}, status=403)
	folder = BookmarkFolder.objects.create(user=request.user, name=name)
	if post:
		return _done(_save(request.user, post, folder), folder)
	return JsonResponse({'ok': True, 'folder': _folder_json(folder), 'url': reverse('bookmarks') + f'?folder={folder.pk}'})


@login_required
@require_POST
def rename_folder(request, folder_id):
	folder = get_object_or_404(BookmarkFolder, pk=folder_id, user=request.user)
	name, error = clean_name(request.POST.get('name'), request.user, exclude=folder)
	if error:
		messages.error(request, error)
	else:
		folder.name = name
		folder.save(update_fields=['name'])
		messages.success(request, 'Folder renamed.')
	return redirect(reverse('bookmarks') + f'?folder={folder.pk}')


@login_required
@require_POST
def delete_folder(request, folder_id):
	folder = get_object_or_404(BookmarkFolder, pk=folder_id, user=request.user)
	n = folder.bookmarks.count()
	folder.delete()          # its bookmarks stay (folder -> NULL)
	kept = '' if not n else (' Its post is still in your bookmarks.' if n == 1 else f' Its {n} posts are still in your bookmarks.')
	messages.success(request, 'Folder deleted.' + kept)
	return redirect('bookmarks')
