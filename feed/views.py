from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.timesince import timesince

from accounts.models import StudentProfile
from communities.models import Community, CommunityMember
from .interactions import log_interaction
from .notifications import (
	badge_text, build_entries, group_members, mark_read, notify, notify_mentions, parse_ids,
	recent_for, target_url, unnotify, unread_count,
	TABS as NOTIFICATION_TABS, TAB_TYPES as NOTIFICATION_TAB_TYPES, unread_by_tab as notification_unread_by_tab,
)
from .forms import EventForm, ListingForm, PostForm, PostEditForm, ProfileEditForm, StoryForm, VenueForm
from .models import (
	Attendee, Bookmark, CartItem, Comment, CommentLike, Event, EventSave, Follow, PinnedPost, ProfileSkill, Interaction, Like, Listing, ListingImage,
	Notification, Post, PostMedia, Recommendation, Repost, Story, StoryView, Venue, VideoView, Block,
)
from . import imagekit
from .moderation import blocked_ids, is_blocked, reported_post_ids

User = get_user_model()


def _is_ajax(request):
	return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _has_video(queryset):
	"""Posts with a video attached — backs the 'Media' tab on both the
	Home feed and Profile. Media is video-only (a separate lane from
	ordinary posts, including image posts), matching UnifyApp's
	dedicated Videos tab. Checks both the legacy single `video` field
	(posts from before multi-attachment support) and a video inside any
	of the post's PostMedia rows."""
	return queryset.filter(
		Q(video__isnull=False, video__gt='')
		| Q(media_items__video__isnull=False, media_items__video__gt='')
		| Q(media_items__ik_url__gt='')
	).distinct()


def _attach_like_data(posts, user):
	"""Evaluates `posts` and attaches `.likes_count`, `.user_has_liked`
	and `.recent_likers` (up to 3, most-recently-liked first — what the
	post card's avatar stack and "Liked by ..." line render) to each
	one. One extra query total, regardless of how many posts there
	are — not one query per post."""
	posts = list(posts)
	post_ids = [p.id for p in posts]

	likes = Like.objects.filter(post_id__in=post_ids).select_related(
		'user', 'user__student_profile'
	).order_by('-created_at')

	counts_by_post = {}
	likers_by_post = {}
	liked_post_ids = set()
	for like in likes:
		counts_by_post[like.post_id] = counts_by_post.get(like.post_id, 0) + 1
		bucket = likers_by_post.setdefault(like.post_id, [])
		if len(bucket) < 3:
			bucket.append(like.user)
		if like.user_id == user.id:
			liked_post_ids.add(like.post_id)

	# "N views" on video posts (VideoView) — one more query in total.
	views_by_post = dict(
		VideoView.objects.filter(post_id__in=post_ids).values('post_id').annotate(n=Count('id')).values_list('post_id', 'n')
	)

	for post in posts:
		post.likes_count = counts_by_post.get(post.id, 0)
		post.user_has_liked = post.id in liked_post_ids
		post.recent_likers = likers_by_post.get(post.id, [])
		post.video_views_count = views_by_post.get(post.id, 0)

	# Repost counts and "did I repost this" travel with the like data, so
	# every page that draws post cards gets them without extra wiring.
	_attach_repost_data(posts, user)
	return posts


def _attach_bookmark_data(posts, user):
	"""Evaluates `posts` and attaches `.user_has_bookmarked` to each
	one — whether `user` (always the logged-in viewer, never anyone
	else — bookmarks are private) has saved it. One extra query total,
	same pattern as _attach_like_data above."""
	posts = list(posts)
	post_ids = [p.id for p in posts]

	bookmarked_post_ids = set(
		Bookmark.objects.filter(user=user, post_id__in=post_ids).values_list('post_id', flat=True)
	)

	for post in posts:
		post.user_has_bookmarked = post.id in bookmarked_post_ids

	return posts


# ---------------------------------------------------------------------
# Reposts and quotes (X-style)
#
# A simple repost is a Repost row pointing at the original Post — no
# copy. A quote is a new Post whose quote_of points at the original.
# The number beside the repost icon counts both, like X's.
# ---------------------------------------------------------------------

def _post_qs(qs):
	"""Everything a post card needs, including the post it quotes, in a
	fixed number of queries however many posts there are. post.thread_size:
	how many posts follow it in its thread (feed/threads.py)."""
	from .threads import with_thread_size
	return with_thread_size(qs).select_related(
		'author', 'author__student_profile', 'author__student_profile__university', 'community', 'poll', 'link_preview',
		'quote_of', 'quote_of__author', 'quote_of__author__student_profile',
	).prefetch_related('media_items', 'quote_of__media_items')


def _visible_on_home(qs, user):
	"""Home shows ordinary posts, plus community posts only from the
	communities `user` is a member of (like X)."""
	mine = CommunityMember.objects.filter(user=user, status=CommunityMember.ACTIVE).values('community_id')
	qs = qs.filter(Q(community__isnull=True) | Q(community_id__in=mine))
	# Nothing from people blocked either way, and no posts you reported.
	hidden_people, reported = blocked_ids(user), reported_post_ids(user)
	if hidden_people:
		qs = qs.exclude(author_id__in=hidden_people).exclude(quote_of__author_id__in=hidden_people)
	if reported:
		qs = qs.exclude(pk__in=reported)
	# ...nor posts you said you're not interested in, nor anyone you muted.
	from .post_settings import hidden_post_ids, muted_ids
	hidden, muted = hidden_post_ids(user), muted_ids(user)
	if hidden:
		qs = qs.exclude(pk__in=hidden)
	if muted:
		qs = qs.exclude(author_id__in=muted)
	return qs


def _posting_community(request, community_id):
	"""The community a new post goes into (from the composer's hidden
	`community` field): only one you're an active member of. Returns None
	for an ordinary post; raises PermissionDenied otherwise."""
	if not community_id:
		return None
	try:
		community_id = int(community_id)
	except (TypeError, ValueError):
		raise PermissionDenied('Unknown community.')
	membership = CommunityMember.objects.select_related('community').filter(
		community_id=community_id, user=request.user, status=CommunityMember.ACTIVE,
	).first()
	if membership is None:
		raise PermissionDenied('Join this community to post in it.')
	return membership.community


def _attach_repost_data(posts, user):
	"""Attaches `.reposts_count` (reposts + quotes of the post) and
	`.user_has_reposted` (whether `user` has simply reposted it) to each
	post. Two queries in total. The database is the only source of these
	numbers — the page's JavaScript just shows what the server returns."""
	posts = list(posts)
	ids = [p.id for p in posts]
	if not ids:
		return posts
	reposts = dict(Repost.objects.filter(post_id__in=ids).values('post_id').annotate(n=Count('id')).values_list('post_id', 'n'))
	quotes = dict(Post.objects.filter(quote_of_id__in=ids).values('quote_of_id').annotate(n=Count('id')).values_list('quote_of_id', 'n'))
	mine = set()
	if getattr(user, 'is_authenticated', False):
		mine = set(Repost.objects.filter(user=user, post_id__in=ids).values_list('post_id', flat=True))
	for p in posts:
		p.reposts_count = reposts.get(p.id, 0) + quotes.get(p.id, 0)
		p.user_has_reposted = p.id in mine
	return posts


def _repost_total(post):
	return Repost.objects.filter(post=post).count() + Post.objects.filter(quote_of=post).count()


def _same_university(user, post):
	"""The feed's visibility rule: students see (and so can repost or
	quote) posts by students at their own university — and posts in
	communities, which are shared by every university."""
	mine = getattr(user, 'student_profile', None)
	if mine and post.community_id:
		return True
	theirs = getattr(post.author, 'student_profile', None)
	return bool(mine and theirs and mine.university_id == theirs.university_id)


def _shareable_post_or_404(user, post_id):
	post = get_object_or_404(Post.objects.select_related('author', 'author__student_profile'), pk=post_id)
	if not _same_university(user, post):
		raise Http404('Post not found.')
	return post


def _with_reposts(posts, reposts, base_qs, viewer):
	"""Mixes reposts into a feed, X-style, with each post shown ONCE.

	`posts` are the feed's own posts; `reposts` the Repost rows that
	should also put a post in this feed. A post shows at its most recent
	moment — when it was posted, or the latest repost — and a reposted
	one carries `.repost_by` (who to name: you, if you reposted it, else
	the latest reposter) and `.repost_others` (how many more reposted
	it). Reposted posts that aren't in `posts` are fetched from `base_qs`
	(which applies the feed's visibility rules)."""
	by_id = {p.id: p for p in posts}
	when = {p.id: p.created_at for p in by_id.values()}
	rows = list(reposts.select_related('user', 'user__student_profile').order_by('-created_at', '-id'))
	missing = {r.post_id for r in rows} - set(by_id)
	if missing:
		for p in base_qs.filter(id__in=missing):
			by_id[p.id] = p
	grouped = {}
	for r in rows:
		if r.post_id in by_id:
			grouped.setdefault(r.post_id, []).append(r)
	for pid, rs in grouped.items():
		post = by_id[pid]
		shown = next((r for r in rs if r.user_id == viewer.id), rs[0])
		post.repost_by = shown.user
		post.repost_others = len(rs) - 1
		if pid not in when or rs[0].created_at > when[pid]:
			when[pid] = rs[0].created_at
	# A stable sort on time alone: posts with no reposts keep exactly the
	# order the feed query gave them (ties included), as before reposts.
	return sorted(by_id.values(), key=lambda p: when.get(p.id, p.created_at), reverse=True)


def _profile_timeline(profile_user, own_posts):
	"""A profile's timeline: `own_posts` plus the posts profile_user
	reposted (each shown with "<name> reposted" above it), newest first by
	when they were posted or reposted. A post appears once — at its latest
	moment — even if they both posted/quoted and reposted it."""
	items = {}
	for p in own_posts:
		items[p.id] = (p.created_at, p)
	reposts = Repost.objects.filter(user=profile_user).select_related(
		'post', 'post__author', 'post__author__student_profile',
		'post__quote_of', 'post__quote_of__author', 'post__quote_of__author__student_profile',
	).prefetch_related('post__media_items', 'post__quote_of__media_items')
	for r in reposts:
		p = items[r.post_id][1] if r.post_id in items else r.post
		if r.post_id not in items or r.created_at > items[r.post_id][0]:
			p.repost_by = profile_user
			p.repost_others = 0
			items[r.post_id] = (r.created_at, p)
	# Stable sort on time alone, so posts without reposts keep their usual order.
	return [p for _, p in sorted(items.values(), key=lambda x: x[0], reverse=True)]


def _attach_comment_counts(posts):
	"""Evaluates `posts` and attaches `.comments_count` (every comment
	AND every reply on the post, not just top-level ones) to each one.
	One extra query total, same pattern as _attach_like_data above."""
	posts = list(posts)
	post_ids = [p.id for p in posts]

	counts_by_post = {}
	for row in Comment.objects.filter(post_id__in=post_ids).values('post_id').annotate(n=Count('id')):
		counts_by_post[row['post_id']] = row['n']

	for post in posts:
		post.comments_count = counts_by_post.get(post.id, 0)

	return posts


def _attach_comment_like_data(comments, user):
	"""Same pattern as _attach_like_data, but for comments: attaches
	`.likes_count`, `.user_has_liked` and `.recent_likers` to each
	comment in the flat `comments` list, in one extra query total
	regardless of how many comments there are."""
	comment_ids = [c.id for c in comments]

	likes = CommentLike.objects.filter(comment_id__in=comment_ids).select_related(
		'user', 'user__student_profile'
	).order_by('-created_at')

	counts_by_comment = {}
	likers_by_comment = {}
	liked_comment_ids = set()
	for like in likes:
		counts_by_comment[like.comment_id] = counts_by_comment.get(like.comment_id, 0) + 1
		bucket = likers_by_comment.setdefault(like.comment_id, [])
		if len(bucket) < 3:
			bucket.append(like.user)
		if like.user_id == user.id:
			liked_comment_ids.add(like.comment_id)

	for c in comments:
		c.likes_count = counts_by_comment.get(c.id, 0)
		c.user_has_liked = c.id in liked_comment_ids
		c.recent_likers = likers_by_comment.get(c.id, [])

	return comments


def _build_comment_tree(post, user):
	"""Fetches every comment on `post` in one query and assembles them
	into a tree in Python: each comment gets a `.reply_list` (named to
	avoid colliding with Comment.replies, the model's own related-name
	for this same relationship — assigning straight to `.replies` is
	refused by Django since that name is a live reverse-relation
	manager, not a plain attribute), and only the top-level
	(parent-less) comments are returned — the template walks
	`.reply_list` recursively to render a reply's own replies, and so
	on to whatever depth the thread actually has. Each comment also
	gets its own like data attached (see _attach_comment_like_data)."""
	comments = list(
		Comment.objects.filter(post=post).select_related('author', 'author__student_profile').order_by('created_at')
	)
	by_id = {c.id: c for c in comments}
	for c in comments:
		c.reply_list = []

	if comments:
		_attach_comment_like_data(comments, user)

	roots = []
	for c in comments:
		if c.parent_id and c.parent_id in by_id:
			by_id[c.parent_id].reply_list.append(c)
		else:
			roots.append(c)

	return roots, len(comments)


def _image_size(f):
	"""(width, height) of an uploaded photo, or (None, None)."""
	from PIL import Image, ImageOps
	try:
		f.seek(0)
		with Image.open(f) as im:
			im = ImageOps.exif_transpose(im) or im   # phone photos taken sideways
			size = im.size
		f.seek(0)
		return size
	except Exception:
		return (None, None)


def _create_post_media(post, files, start_order=0, thumbnail=None):
	"""Turns cleaned_data['media'] (a list of uploaded files) into
	ordered PostMedia rows — one per file, saved as an image or a video
	depending on its content type. `thumbnail` (an uploaded image) is
	the video's chosen thumbnail, for a video stored on this server."""
	files = list(files)
	# Photos go to ImageKit when it's configured, so it can serve each
	# screen a sharp copy at the right size. Any it can't take stay here.
	photos = [f for f in files if not (f.content_type or '').startswith('video/')]
	on_imagekit = dict(zip(map(id, photos), imagekit.upload_images(photos, imagekit.PHOTO_FOLDER))) if photos and imagekit.enabled() else {}
	for offset, f in enumerate(files):
		is_video = (f.content_type or '').startswith('video/')
		ik = on_imagekit.get(id(f))
		width, height = (ik.get('width'), ik.get('height')) if ik else (_image_size(f) if not is_video else (None, None))
		PostMedia.objects.create(
			post=post,
			image=None if (is_video or ik) else f,
			ik_image_file_id=ik['fileId'] if ik else '',
			ik_image_url=ik['url'] if ik else '',
			width=width or None, height=height or None,
			video=f if is_video else None,
			thumbnail=thumbnail if is_video else None,
			order=start_order + offset,
		)


def _save_new_media(post, cleaned, start_order=0):
	"""Everything newly attached in the composer / edit form: files sent
	to this server, plus a video already uploaded to ImageKit (with its
	optional thumbnail) — see PostForm.clean() and feed/imagekit.py."""
	files = cleaned.get('media') or []
	_create_post_media(post, files, start_order, thumbnail=cleaned.get('video_thumbnail'))
	video = cleaned.get('ik_video')
	if video:
		thumb = cleaned.get('ik_thumbnail') or {}
		PostMedia.objects.create(
			post=post, order=start_order + len(files),
			ik_file_id=video['fileId'], ik_url=video['url'],
			ik_thumbnail_file_id=thumb.get('fileId', ''), ik_thumbnail_url=thumb.get('url', ''),
		)


def _create_listing_images(listing, files, start_order=0):
	"""Turns cleaned_data['images'] (a list of uploaded files) into
	ordered ListingImage rows — same pattern as _create_post_media(),
	minus the image-vs-video branch since a listing's photos are always
	images."""
	for offset, f in enumerate(files):
		ListingImage.objects.create(listing=listing, image=f, order=start_order + offset)


def _build_stories_carousel(user, university=None):
	"""Groups active (non-expired, is_active) stories by author for the
	Home feed carousel: the logged-in user's own group always comes
	first — even with an empty 'stories' list, since the card still
	needs to render so they have somewhere to tap to start one — then
	everyone else who currently has at least one active story, most
	recently posted author first. Each group's own stories list stays
	oldest-first, since that's the order the viewer plays them back in.

	Scoped to `university` — same "each university is its own space"
	principle the home feed and the rest of the app already follow.
	Without one (no student profile), only the user's own group is
	returned, since there's no university to scope anyone else to.

	Returns a list of dicts: {'user': User, 'stories': [Story, ...],
	'is_self': bool, 'latest_story': Story or None}."""
	own_stories = list(Story.objects.active().filter(user=user).select_related('user').order_by('created_at'))
	own_group = {'user': user, 'stories': own_stories, 'is_self': True, 'latest_story': own_stories[-1] if own_stories else None}

	if university is None:
		return [own_group]

	active_stories = (
		Story.objects.active()
		.filter(user__student_profile__university=university)
		.exclude(user_id=user.id)
		.select_related('user', 'user__student_profile')
		.order_by('created_at')
	)

	groups_by_user_id = {}
	user_id_order = []
	for story in active_stories:
		if story.user_id not in groups_by_user_id:
			groups_by_user_id[story.user_id] = {'user': story.user, 'stories': [], 'is_self': False}
			user_id_order.append(story.user_id)
		groups_by_user_id[story.user_id]['stories'].append(story)

	# Most-recently-posted author first. Each group's own list is
	# oldest-first (see above), so its last entry is that author's
	# newest story.
	user_id_order.sort(key=lambda uid: groups_by_user_id[uid]['stories'][-1].created_at, reverse=True)

	others = []
	for uid in user_id_order:
		group = groups_by_user_id[uid]
		group['latest_story'] = group['stories'][-1]
		others.append(group)

	return [own_group] + others


def _serialize_stories_for_js(groups, request):
	"""The same carousel groups _build_stories_carousel() returns,
	flattened into plain strings/numbers so they can go straight into
	a `{{ ...|json_script:"..." }}` tag — the Stories viewer (app.js)
	reads this instead of making a separate request just to open."""
	data = []
	for group in groups:
		story_user = group['user']
		student = getattr(story_user, 'student_profile', None)
		avatar_url = student.profile_photo.url if student and student.profile_photo else ''
		data.append({
			'userId': story_user.id,
			'username': story_user.username,
			'displayName': story_user.get_full_name() or story_user.username,
			'avatarUrl': avatar_url,
			'isSelf': group['is_self'],
			'stories': [
				{
					'id': story.id,
					'imageUrl': story.image_url,
					'caption': story.caption,
					'createdDisplay': timesince(story.created_at) + ' ago',
					'viewsCount': story.views.count() if group['is_self'] else None,
					'deleteUrl': reverse('delete_story', args=[story.id]) if group['is_self'] else None,
				}
				for story in group['stories']
			],
		})
	return data


@login_required
def home(request):
	student = getattr(request.user, 'student_profile', None)
	posts = Post.objects.none()

	# Computed once per request and reused both for the Following tab's
	# filter and for each post card's own "Follow @author" menu item —
	# one query instead of one per post on the page. Only ACCEPTED
	# follows count as "following" here; a pending request doesn't put
	# someone's posts in the Following tab yet. pending_ids is the
	# separate set of requests still awaiting approval, so post cards
	# can show "Requested" instead of "Follow".
	following_ids = set(Follow.objects.filter(follower=request.user, status=Follow.STATUS_ACCEPTED).values_list('following_id', flat=True))
	pending_ids = set(Follow.objects.filter(follower=request.user, status=Follow.STATUS_PENDING).values_list('following_id', flat=True))

	tab = request.GET.get('tab', 'foryou')
	if tab not in ('following', 'foryou', 'media', 'trending'):
		tab = 'foryou'


	if student:
		# Scoped to the student's own university — the same "each
		# university is its own space" principle used everywhere else.
		# A thread shows once, as its first post ("Show this thread").
		university_posts = _post_qs(_visible_on_home(Post.objects.filter(
			author__student_profile__university=student.university, thread_root__isnull=True,
		), request.user)).order_by('-created_at')
		# Reposts of this university's posts, by this university's students.
		university_reposts = Repost.objects.filter(
			post__author__student_profile__university=student.university,
			user__student_profile__university=student.university,
		).exclude(user_id__in=blocked_ids(request.user)).exclude(user__muted_by__muter=request.user)

		if tab == 'following':
			# People you follow: their posts and quotes, plus what they reposted.
			posts = _with_reposts(university_posts.filter(author_id__in=following_ids),
				university_reposts.filter(user_id__in=following_ids), university_posts, request.user)
		elif tab == 'media':
			posts = _has_video(university_posts)
		elif tab == 'trending':
			# Most engaged-with right now, with time decay (recommendations/trending.py).
			from recommendations.trending import trending_posts
			posts = trending_posts(request.user, limit=40)
		else:
			posts = _with_reposts(university_posts, university_reposts, university_posts, request.user)

	posts = _attach_like_data(posts, request.user)
	posts = _attach_comment_counts(posts)
	posts = _attach_bookmark_data(posts, request.user)

	# Upcoming (deadline countdowns, events, sessions...) and today's classes (courses/today.py).
	from courses.today import strip
	from courses.timetable import today_agenda
	# Campus Pulse at the top (it replaced Quick access): feed/pulse.py.
	from .pulse import bar_for
	return render(request, 'feed/home.html', {
		'pulse': bar_for(request.user) if student and tab != 'media' else None,
		'today': strip(request.user) if student and tab != 'media' else {'items': [], 'deadlines': [], 'upcoming': [], 'courses': [], 'kinds': []},
		'today_agenda': today_agenda(request.user) if student and tab != 'media' else [],
		'posts': posts, 'tab': tab, 'following_ids': following_ids, 'pending_ids': pending_ids,
	})


@login_required
def create_story(request):
	if request.method == 'POST':
		form = StoryForm(request.POST, request.FILES)
		if form.is_valid():
			story = form.save(commit=False)
			story.user = request.user
			if imagekit.enabled():
				# Sharp, right-sized story photos from ImageKit (kept here if it can't be reached).
				ik = imagekit.upload_images([form.cleaned_data['image']], imagekit.STORY_FOLDER)[0]
				if ik:
					story.ik_image_file_id, story.ik_image_url = ik['fileId'], ik['url']
					story.image = None
			story.save()
			messages.success(request, "Your story was posted.")
			try:  # Messages -> Updates shows new statuses live
				from chat.services import announce_status
				announce_status(story)
			except Exception:
				pass
			next_url = request.POST.get('next')
			if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
				return redirect(next_url)
			return redirect('home')
		# Invalid upload (not an image, too large, ...) — tell the user
		# why instead of silently redirecting back to a feed that looks
		# unchanged.
		for error in form.errors.get('image', []):
			messages.error(request, error)
		for error in form.non_field_errors():
			messages.error(request, error)
	return redirect('home')


@login_required
def delete_story(request, story_id):
	story = get_object_or_404(Story, pk=story_id)
	# A user can only delete their own story — never trust a story ID
	# alone; ownership is checked server-side regardless of what the
	# frontend shows.
	if story.user_id != request.user.id:
		raise PermissionDenied("You can only delete your own story.")

	if request.method == 'POST':
		story.delete()
		if _is_ajax(request):
			return JsonResponse({'deleted': True})
		messages.success(request, "Story deleted.")

	return redirect('home')


@login_required
def record_story_view(request, story_id):
	"""Called by the story viewer (app.js) each time a story becomes
	the one on screen. get_or_create() is what actually keeps this
	race-safe — a quick double-fire from auto-advance can't create two
	StoryView rows for the same (story, viewer) pair; the
	UniqueConstraint on the model is the database-level backstop."""
	if request.method != 'POST':
		return JsonResponse({'error': 'POST required'}, status=405)

	story = get_object_or_404(Story.objects.active(), pk=story_id)
	# Watching your own story back doesn't count as a "view" — only
	# other people's visits should show up in your view count.
	if story.user_id != request.user.id:
		StoryView.objects.get_or_create(story=story, viewer=request.user)

	return JsonResponse({'views_count': story.views.count()})


@login_required
def compose_post(request):
	# Posting into a community (communities app): the composer carries
	# the community's id; only its members may post there.
	from .drafts import draft_for, draft_payload
	from . import threads
	draft = draft_for(request.user, request.POST.get('draft_id') or request.GET.get('draft'))
	# "Add another post" on a thread (feed/threads.py): it goes on the end of it.
	thread = threads.root_for(request.user, request.POST.get('thread') or request.GET.get('thread')
		or (draft.thread_root_id if draft else None))
	community = thread.community if thread else _posting_community(request, request.POST.get('community') or request.GET.get('community')
		or (draft.community_id if draft and request.method == 'GET' else None))
	parts = []
	if request.method == 'POST':
		form = PostForm(request.POST, request.FILES)
		part_texts = request.POST.getlist('thread_part')
		parts, parts_error = threads.clean_parts(part_texts, already=threads.parts_count(thread) + 1 if thread else 0,
			files={i: request.FILES.getlist(f'thread_media_{i}') for i in range(len(part_texts))})
		if parts_error:
			form.add_error(None, parts_error)
		if form.is_valid():
			post = form.save(commit=False)
			post.author = request.user
			post.community = community
			post.location = form.cleaned_data.get('location') or ''
			if thread:
				post.thread_root, post.thread_index = thread, threads.next_index(thread)
			post.save()
			from .link_previews import attach as attach_link_preview
			attach_link_preview(post)          # a card for its first link (feed/link_previews.py)
			_save_new_media(post, form.cleaned_data)
			if form.cleaned_data.get('poll_options'):
				from .polls import create_poll
				create_poll(post, form.cleaned_data['poll_options'], form.cleaned_data.get('poll_days') or 1)
			if draft:
				draft.delete()          # posted (or scheduled): the draft has done its job
			when = form.cleaned_data.get('schedule_at')
			if when:
				# Posted later (feed/scheduling.py): mentions are told when it goes out.
				from .scheduling import schedule
				schedule(post, when)
				if parts:
					threads.add_parts(thread or post, parts, when=when)
				messages.success(request, f'Scheduled for {timezone.localtime(when):%a %d %b at %I:%M %p}.'.replace(' 0', ' ') + ' See it in Scheduled posts.')
				return redirect('scheduled_posts')
			notify_mentions(post.content, request.user, post)
			if parts:
				threads.add_parts(thread or post, parts, after=post)
			if thread or parts:
				messages.success(request, 'Added to your thread.' if thread else f'Thread posted — {len(parts) + 1} posts.')
				return redirect('post_detail', post_id=(thread or post).pk)
			messages.success(request, "Poll posted." if form.cleaned_data.get('poll_options') else "Post uploaded successfully.")
			if community:
				return redirect(reverse('community_detail', args=[community.pk]) + '?tab=latest')
			return redirect('home')
	else:
		# ?text=#tag — "Post" on a hashtag page starts the post with the tag.
		form = PostForm(initial={'content': draft.content if draft else (request.GET.get('text') or '')[:60] + (' ' if request.GET.get('text') else '')})
	draft_data = draft_payload(draft) if draft else None
	if request.method == 'POST':
		# Sent back with an error: the form keeps the text; keep the + boxes too.
		# (The photos in the + boxes have to be picked again — browsers can't be given files back.)
		draft_data = {'thread': [p['text'] for p in parts]} if parts else None
	return render(request, 'feed/compose_post.html', {'form': form, 'community': community, 'draft': draft,
		'draft_data': draft_data, 'adding_to_thread': thread})


@login_required
def imagekit_auth(request):
	"""A one-time signature that lets this student's browser upload one
	file (a video or its thumbnail) straight to ImageKit. The private
	key stays on the server; see feed/imagekit.py."""
	if not imagekit.enabled():
		return JsonResponse({'error': 'ImageKit is not configured.'}, status=404)
	response = JsonResponse(imagekit.auth_params())
	response['Cache-Control'] = 'no-store'
	return response


@login_required
def record_video_view(request, post_id):
	"""Counts a view once a post's video has played for a few seconds
	(static/js/video-player.js) — once per person per post, like story
	views. Returns the new total for the "N views" label."""
	if request.method != 'POST':
		return JsonResponse({'error': 'POST required'}, status=405)
	post = get_object_or_404(Post, pk=post_id)
	has_video = bool(post.video) or post.media_items.filter(Q(video__gt='') | Q(ik_url__gt='')).exists()
	if not has_video:
		return JsonResponse({'error': 'This post has no video.'}, status=400)
	VideoView.objects.get_or_create(post=post, user=request.user)
	count = post.video_views.count()
	return JsonResponse({'views': count, 'label': f"{count:,} view{'' if count == 1 else 's'}"})


@login_required
def edit_post(request, post_id):
	post = get_object_or_404(Post, pk=post_id)
	# Same rule as delete: only the author can edit, ever — checked
	# server-side regardless of what the frontend shows or hides.
	if post.author_id != request.user.id:
		raise PermissionDenied("You can only edit your own posts.")

	# A post made before multi-photo/video support only has the old
	# single image/video fields — move that one file onto a PostMedia
	# row the first time the post is edited, so the rest of this view
	# (and the edit template) only ever has to deal with media_items.
	if not post.media_items.exists() and (post.image or post.video):
		PostMedia.objects.create(post=post, image=post.image or None, video=post.video or None, order=0)
		post.image = None
		post.video = None
		post.save(update_fields=['image', 'video'])

	next_url = request.GET.get('next', '')

	if request.method == 'POST':
		form = PostEditForm(request.POST, request.FILES, instance=post)
		if form.is_valid():
			edited_post = form.save(commit=False)
			edited_post.is_edited = True
			edited_post.save()
			from .link_previews import attach as attach_link_preview
			attach_link_preview(edited_post)          # the link may have changed

			removed_ids = form.removed_media_ids(form.cleaned_data)
			if removed_ids:
				post.media_items.filter(id__in=removed_ids).delete()

			_save_new_media(post, form.cleaned_data, start_order=post.media_items.count())

			messages.success(request, "Post edited successfully.")
			redirect_to = request.POST.get('next') or request.META.get('HTTP_REFERER')
			if redirect_to:
				return redirect(redirect_to)
			return redirect('post_detail', post_id=post.id)
	else:
		form = PostEditForm(instance=post)

	from .threads import position
	return render(request, 'feed/edit_post.html', {
		'form': form, 'post': post, 'next_url': next_url, 'thread_position': position(post),
		'existing_media': post.media_items.all(),
	})


@login_required
def delete_post(request, post_id):
	post = get_object_or_404(Post, pk=post_id)
	# A user can only delete their own post — never trust a post ID
	# alone; ownership is checked server-side regardless of what the
	# frontend shows.
	if post.author_id != request.user.id:
		raise PermissionDenied("You can only delete your own posts.")

	if request.method == 'POST':
		# In a thread (feed/threads.py): the rest of the thread stays, unless
		# you chose to delete the whole thread from its first post.
		from . import threads
		size = Post.all_objects.filter(thread_root=post).count() if not post.thread_root_id else 0
		was_in_thread = bool(post.thread_root_id or size)
		whole = request.POST.get('scope', 'thread' if size else 'one') == 'thread'
		left = threads.remove(post, whole=whole)
		if was_in_thread and left is not None:
			messages.success(request, 'Post deleted. The rest of your thread is still up.')
			# Deleted from the thread's own page: stay on the thread.
			if request.POST.get('on_detail'):
				return redirect('post_detail', post_id=left.pk)
		elif size and whole:
			messages.success(request, f'Thread deleted ({size + 1} posts).')
		else:
			messages.success(request, "Post deleted successfully.")

	next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
	if next_url:
		return redirect(next_url)
	return redirect('profile')


@login_required
def post_detail(request, post_id):
	"""A single post's permalink page — what a post's timestamp and
	"Share" link point to. select_related pulls the author and their
	profile in the same query, since _post_card.html needs both to
	render the header (avatar, name, handle)."""
	post = get_object_or_404(_post_qs(Post.objects.all()), pk=post_id)
	if post.author_id in blocked_ids(request.user):
		raise Http404('Post not found.')
	from .analytics import record_detail
	record_detail(request.user, post)          # "Opened the post" in the author's analytics
	# A thread (feed/threads.py): the posts before this one above it, the rest under it.
	from .threads import MAX_PARTS, thread_of
	root, thread_ids = thread_of(post)
	thread_ids = [p.pk for p in thread_ids]
	others = _post_qs(Post.objects.filter(pk__in=thread_ids).exclude(pk=post.pk)).in_bulk() if thread_ids else {}
	cards = [post] + list(others.values())
	cards = _attach_bookmark_data(_attach_comment_counts(_attach_like_data(cards, request.user)), request.user)
	by_id = {p.pk: p for p in cards}
	post = by_id[post.pk]
	where = thread_ids.index(post.pk) if post.pk in thread_ids else 0
	before = [by_id[i] for i in thread_ids[:where]]
	after = [by_id[i] for i in thread_ids[where + 1:]]
	following_ids = set(Follow.objects.filter(follower=request.user, status=Follow.STATUS_ACCEPTED).values_list('following_id', flat=True))
	pending_ids = set(Follow.objects.filter(follower=request.user, status=Follow.STATUS_PENDING).values_list('following_id', flat=True))
	return render(request, 'feed/post_detail.html', {
		'post': post, 'following_ids': following_ids, 'pending_ids': pending_ids,
		'thread_before': before, 'thread_after': after, 'thread_root': root, 'in_thread': bool(thread_ids),
		# Your own post (not a scheduled one): "Add another post" under the thread.
		'can_add_to_thread': root.author_id == request.user.pk and not root.is_scheduled
			and max(len(thread_ids) - 1, 0) < MAX_PARTS,
	})


@login_required
def top_stories_page(request):
	"""The Top Stories page (the "Top stories" box's full list, and the
	fire icon in the phone bottom bar): the 20 posts people at your
	university are engaging with most right now (see feed/top_stories.py)."""
	from .top_stories import top_stories, trending_topics
	return render(request, 'feed/top_stories.html', {'stories': top_stories(request.user, limit=20),
		'trending': trending_topics(request.user)})


@login_required
def who_to_follow_page(request):
	"""The Who to follow page (the sidebar box's title and "Show More"):
	people in groups, closest first — coursemates, department, faculty,
	university, other universities — as cards (feed/people.py sections_for).
	?section=<key> shows everyone in one group; ?q= searches your university."""
	from django.core.paginator import Paginator
	from .people import PREVIEW, SECTION_PAGE, people_to_follow, ranked, sections_for, with_mutual_faces
	query = request.GET.get('q', '').strip()
	if query:
		page = Paginator(ranked(request.user, people_to_follow(request.user, query)), SECTION_PAGE).get_page(request.GET.get('page'))
		return render(request, 'feed/who_to_follow.html', {
			'query': query, 'page': page, 'people': with_mutual_faces(request.user, page), 'total': page.paginator.count})
	sections = sections_for(request.user)
	key = request.GET.get('section')
	one = next((s for s in sections if s[0] == key), None)
	if one:
		page = Paginator(ranked(request.user, one[3]), SECTION_PAGE).get_page(request.GET.get('page'))
		return render(request, 'feed/who_to_follow.html', {
			'section': {'key': one[0], 'title': one[1], 'sub': one[2]}, 'page': page,
			'people': with_mutual_faces(request.user, page), 'total': page.paginator.count})
	groups = []
	# People You May Know first (recommendations/people.py): the eligibility rule and ranking.
	from recommendations.people import people_you_may_know
	pymk = people_you_may_know(request.user, limit=6)
	if pymk:
		groups.append({'key': 'pymk', 'title': 'People you may know', 'sub': 'Students in your faculty and department',
			'total': len(pymk), 'people': with_mutual_faces(request.user, pymk)})
	for k, title, sub, qs in sections:
		total = qs.count()
		if total:
			groups.append({'key': k, 'title': title, 'sub': sub, 'total': total,
				'people': with_mutual_faces(request.user, ranked(request.user, qs)[:PREVIEW])})
	return render(request, 'feed/who_to_follow.html', {'groups': groups})


@login_required
def bookmarks_page(request):
	"""The Bookmarks page (the sidebar's "Bookmarks" link), two tabs:
	Posts — every post the logged-in user has saved, most recently saved
	first, drawn with the same post card as the feed; and Opportunities —
	the opportunities they saved with the bookmark on the Opportunities
	board (?tab=opportunities).

	Private by construction: it only ever reads request.user's own
	Bookmark rows, and there is no username in the URL to change.
	A deleted post can't leave a broken bookmark behind, because
	Bookmark.post is on_delete=CASCADE (the bookmark goes with it)."""
	# Folders (feed/bookmark_folders.py): chips above the posts; ?folder=<id> shows one.
	from .bookmark_folders import folders_for
	folders = folders_for(request.user)
	folder = None
	if str(request.GET.get('folder') or '').isdigit():
		folder = next((f for f in folders if f.pk == int(request.GET['folder'])), None)
		if folder is None:
			return redirect('bookmarks')
	all_count = Bookmark.objects.filter(user=request.user).count()
	bookmarks = (
		Bookmark.objects.filter(user=request.user, **({'folder': folder} if folder else {}))
		.select_related('post', 'post__author', 'post__author__student_profile',
			'post__quote_of', 'post__quote_of__author', 'post__quote_of__author__student_profile')
		.prefetch_related('post__media_items', 'post__quote_of__media_items')
		.order_by('-created_at')
	)
	posts = [b.post for b in bookmarks]
	for b, p in zip(bookmarks, posts):
		p.bookmark_folder_id = b.folder_id
	posts = _attach_like_data(posts, request.user)
	posts = _attach_comment_counts(posts)
	posts = _attach_bookmark_data(posts, request.user)

	# The post card's Follow button needs to know who you already follow.
	following_ids = set(Follow.objects.filter(follower=request.user, status=Follow.STATUS_ACCEPTED).values_list('following_id', flat=True))
	pending_ids = set(Follow.objects.filter(follower=request.user, status=Follow.STATUS_PENDING).values_list('following_id', flat=True))

	# Second tab: opportunities saved with their bookmark (opportunities app).
	from opportunities.models import Opportunity
	saved_opps = list(Opportunity.objects.filter(saves__user=request.user).order_by('-saves__created_at'))
	# Third tab: events saved with "Save Event" (feed/details.py).
	saved_events = [s.event for s in EventSave.objects.filter(user=request.user).select_related('event').order_by('event__date')]
	# Fourth tab: posts saved in groups (studygroups, the bookmark on a group post).
	from studygroups.models import GroupPostBookmark
	saved_group_posts = [b.post for b in GroupPostBookmark.objects.filter(user=request.user, post__group__members__user=request.user,
		post__group__members__status='active').select_related('post', 'post__group', 'post__author').distinct()]
	tab = request.GET.get('tab') if request.GET.get('tab') in ('opportunities', 'events', 'groups') else 'posts'

	return render(request, 'feed/bookmarks.html', {
		'posts': posts, 'following_ids': following_ids, 'pending_ids': pending_ids,
		'tab': tab, 'saved_opps': saved_opps, 'saved_ids': {o.pk for o in saved_opps}, 'saved_events': saved_events,
		'folders': folders, 'folder': folder, 'all_count': all_count, 'saved_group_posts': saved_group_posts,
	})


@login_required
def events_list(request):
	"""The Events page — four tabs sharing one URL (?tab=...), same
	pattern as the profile page's tabs:

	  events     — the stat row, the "Add Event" form, and the card grid
	  attendees  — register yourself for an event, and see who's going
	  venues     — a simple venue directory (name/address/type/capacity)
	  analytics  — two small charts: events by category, and
	               registrations per event

	Only the 'events' tab's data (needed for the attendance button's
	state on every card, visible or not) is built unconditionally; the
	other three tabs' data is only built when that tab is open."""
	today = timezone.now().date()

	tab = request.GET.get('tab', 'events')
	if tab not in ('events', 'attendees', 'venues', 'analytics'):
		tab = 'events'

	upcoming_events = list(
		Event.objects.filter(date__gte=today).select_related('organizer').prefetch_related('attendees')
	)

	# Category filter pills on the Events tab: one per real category type
	# (Event.CATEGORY_ICONS' keys, which exclude the three legacy
	# color-named values). A pill also matches any legacy code that
	# renders with the same display label, so old 'primary'/'danger'/
	# 'success' rows still show up under the matching pill.
	label_to_codes = {}
	for code, label in Event.CATEGORY_CHOICES:
		label_to_codes.setdefault(label, []).append(code)
	category_codes = dict(Event.CATEGORY_CHOICES)
	category_pills = [
		{'code': code, 'label': category_codes[code], 'icon': icon}
		for code, icon in Event.CATEGORY_ICONS.items()
	]

	selected_category = request.GET.get('category', 'all')
	if selected_category != 'all' and selected_category in Event.CATEGORY_ICONS:
		allowed_codes = set(label_to_codes[category_codes[selected_category]])
		filtered_events = [e for e in upcoming_events if e.category in allowed_codes]
	else:
		selected_category = 'all'
		filtered_events = upcoming_events

	context = {
		'tab': tab,
		'all_events': upcoming_events,
		'filtered_events': filtered_events,
		'category_pills': category_pills,
		'selected_category': selected_category,
		'events_count': len(upcoming_events),
		'this_week_count': len([e for e in upcoming_events if e.date <= today + timedelta(days=7)]),
		'categories_count': len({e.category for e in upcoming_events}),
		'event_form': EventForm(),
		'attending_event_ids': set(
			Attendee.objects.filter(user=request.user, event__in=upcoming_events).values_list('event_id', flat=True)
		),
	}

	if tab == 'events':
		# "Recommended for you" (recommendations/engine.py): upcoming, not full, not yet registered.
		from recommendations.engine import recommend
		context['recs'] = recommend(request.user, 'event', limit=8)
	if tab == 'attendees':
		context['attendees'] = list(
			Attendee.objects.select_related('event', 'user', 'user__student_profile').order_by('-registered_at')
		)
	elif tab == 'venues':
		context['venues'] = list(Venue.objects.select_related('created_by'))
		context['venue_form'] = VenueForm()
	elif tab == 'analytics':
		category_counts = {}
		for event in Event.objects.all():
			label = event.get_category_display()
			category_counts[label] = category_counts.get(label, 0) + 1

		top_registered = Event.objects.annotate(reg_count=Count('attendees')).filter(reg_count__gt=0).order_by('-reg_count')[:8]

		context['category_chart_data'] = {
			'labels': list(category_counts.keys()),
			'data': list(category_counts.values()),
		}
		context['registrations_chart_data'] = {
			'labels': [e.title for e in top_registered],
			'data': [e.reg_count for e in top_registered],
		}

	return render(request, 'feed/events_list.html', context)


@login_required
def create_event(request):
	# From a community's Events tab (communities/detail.html): its members
	# can add events to it, and they go back to that tab afterwards.
	community = None
	if str(request.POST.get('community') or '').isdigit():
		community = Community.objects.filter(pk=int(request.POST['community']), memberships__user=request.user,
			memberships__status=CommunityMember.ACTIVE).first()
	back = (reverse('community_detail', args=[community.pk]) + '?tab=events') if community else reverse('events') + '?tab=events'
	if request.method == 'POST':
		form = EventForm(request.POST, request.FILES)
		if form.is_valid():
			event = form.save(commit=False)
			event.organizer = request.user
			event.community = community
			event.save()
			# The organizer is automatically an attendee of their own
			# event — no need to separately register for it.
			Attendee.objects.get_or_create(
				event=event, user=request.user, defaults={'attendee_type': 'organizer'},
			)
			messages.success(request, "Event created successfully.")
		else:
			messages.error(request, "Please check the event details and try again.")
	return redirect(back)


@login_required
def edit_event(request, event_id):
	event = get_object_or_404(Event, pk=event_id)
	# Only the organizer who created an event can edit it — same
	# server-side rule as delete_event, enforced regardless of what the
	# frontend shows or hides.
	if event.organizer_id != request.user.id:
		raise PermissionDenied("You can only edit events you created.")

	if request.method == 'POST':
		form = EventForm(request.POST, request.FILES, instance=event)
		if form.is_valid():
			form.save()
			messages.success(request, "Event updated.")
		else:
			messages.error(request, "Please check the event details and try again.")

	return redirect(reverse('events') + '?tab=events')


@login_required
def delete_event(request, event_id):
	event = get_object_or_404(Event, pk=event_id)
	# Only the organizer who created an event can delete it — checked
	# server-side regardless of what the frontend shows or hides, same
	# rule as delete_post.
	if event.organizer_id != request.user.id:
		raise PermissionDenied("You can only delete events you created.")

	if request.method == 'POST':
		event.delete()
		messages.success(request, "Event deleted.")

	return redirect(reverse('events') + '?tab=events')


@login_required
def toggle_attendance(request):
	"""Register/un-register the logged-in user for an event — the same
	get_or_create()+UniqueConstraint toggle pattern as toggle_like and
	toggle_bookmark, just against Attendee. The event comes from the
	POST body (not the URL) so one endpoint serves both the per-card
	"Register" button and the Attendees tab's event-picker form."""
	if request.method != 'POST':
		return redirect('events')

	event = get_object_or_404(Event, pk=request.POST.get('event_id'))
	attendee_type = request.POST.get('attendee_type') or 'attendee'
	if attendee_type not in dict(Attendee.TYPE_CHOICES):
		attendee_type = 'attendee'

	existing = Attendee.objects.filter(event=event, user=request.user).first()
	if existing:
		existing.delete()
		registered = False
		unnotify(event.organizer, request.user, Notification.EVENT_REGISTER, event=event)
	else:
		if event.capacity is not None and event.attendees.count() >= event.capacity:
			if _is_ajax(request):
				return JsonResponse({'error': "This event is full."}, status=400)
			messages.error(request, "Sorry, this event is full.")
			return redirect(reverse('events') + '?tab=events')
		Attendee.objects.get_or_create(event=event, user=request.user, defaults={'attendee_type': attendee_type})
		registered = True
		log_interaction(request.user, Interaction.ITEM_EVENT, event.id, Interaction.ACTION_REGISTER)
		notify(event.organizer, request.user, Notification.EVENT_REGISTER, event=event, replace=True)

	if _is_ajax(request):
		return JsonResponse({
			'registered': registered,
			'attendees_count': event.attendees.count(),
			'spots_left': event.spots_left,
		})

	next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
	if next_url:
		return redirect(next_url)
	return redirect('events')


@login_required
def remove_attendee(request, attendee_id):
	attendee = get_object_or_404(Attendee, pk=attendee_id)
	# Either the attendee themself, or the event's organizer, can remove
	# a registration — not just anyone with the row's id.
	if attendee.user_id != request.user.id and attendee.event.organizer_id != request.user.id:
		raise PermissionDenied("You can't remove someone else's registration.")

	if request.method == 'POST':
		attendee.delete()
		messages.success(request, "Attendee removed.")

	return redirect(reverse('events') + '?tab=attendees')


@login_required
def create_venue(request):
	if request.method == 'POST':
		form = VenueForm(request.POST)
		if form.is_valid():
			venue = form.save(commit=False)
			venue.created_by = request.user
			venue.save()
			messages.success(request, "Venue added.")
		else:
			messages.error(request, "Please check the venue details and try again.")
	return redirect(reverse('events') + '?tab=venues')


@login_required
def delete_venue(request, venue_id):
	venue = get_object_or_404(Venue, pk=venue_id)
	if venue.created_by_id != request.user.id:
		raise PermissionDenied("You can only delete venues you added.")

	if request.method == 'POST':
		venue.delete()
		messages.success(request, "Venue deleted.")

	return redirect(reverse('events') + '?tab=venues')


@login_required
def marketplace_list(request):
	"""The Marketplace page — three tabs sharing one URL (?tab=...),
	same pattern as the Events page's tabs:

	  browse  — the category pills, search, and the grid of everyone's
	            available listings (the default)
	  mine    — the "Sell an item" form plus the listings *this* user is
	            selling (available and sold)
	  cart    — the items this user has added to their cart

	Only the 'browse' tab's data is built unconditionally (a cart badge
	needs the cart count on every tab); the other two tabs' data is only
	built when that tab is open."""
	tab = request.GET.get('tab', 'browse')
	if tab not in ('browse', 'mine', 'cart'):
		tab = 'browse'

	available_listings = list(
		Listing.objects.filter(status=Listing.STATUS_AVAILABLE)
		.exclude(seller=request.user)
		.select_related('seller')
		.prefetch_related('images')
	)

	category_codes = dict(Listing.CATEGORY_CHOICES)
	category_pills = [
		{'code': code, 'label': category_codes[code], 'icon': icon}
		for code, icon in Listing.CATEGORY_ICONS.items()
	]

	selected_category = request.GET.get('category', 'all')
	if selected_category != 'all' and selected_category in Listing.CATEGORY_ICONS:
		filtered_listings = [l for l in available_listings if l.category == selected_category]
	else:
		selected_category = 'all'
		filtered_listings = available_listings

	cart_items = list(
		CartItem.objects.filter(user=request.user).select_related('listing', 'listing__seller').prefetch_related('listing__images')
	)

	context = {
		'tab': tab,
		'filtered_listings': filtered_listings,
		'category_pills': category_pills,
		'selected_category': selected_category,
		'listings_count': len(available_listings),
		'cart_items': cart_items,
		'cart_count': sum(item.quantity for item in cart_items),
		'cart_total': sum(item.subtotal for item in cart_items),
		'listing_form': ListingForm(),
	}

	if tab == 'browse' and selected_category == 'all':
		# "Recommended for you" (recommendations/engine.py): available listings not in your
		# cart, ranked by your university, people you know, your Interested / Not
		# interested choices and, when it has been run, the batch model from
		# `manage.py train_recommender` (feed/recommender.py) as one more signal.
		from recommendations.engine import recommend
		context['recommendations'] = recommend(request.user, 'listing', limit=8)

	if tab == 'mine':
		context['my_listings'] = list(
			Listing.objects.filter(seller=request.user).prefetch_related('images')
		)

	return render(request, 'feed/marketplace_list.html', context)


@login_required
def listing_detail(request, listing_id):
	listing = get_object_or_404(Listing.objects.select_related('seller').prefetch_related('images'), pk=listing_id)
	in_cart_quantity = 0
	cart_item = CartItem.objects.filter(user=request.user, listing=listing).first()
	if cart_item:
		in_cart_quantity = cart_item.quantity

	# Opening a listing's page is the weakest interest signal the
	# recommender gets — but the most plentiful one. Viewing your own
	# listing says nothing about your taste, so it isn't logged.
	if listing.seller_id != request.user.id:
		log_interaction(request.user, Interaction.ITEM_LISTING, listing.id, Interaction.ACTION_VIEW)

	from .details import seller_rating
	return render(request, 'feed/listing_detail.html', {
		'seller_rating': seller_rating(listing.seller),
		'listing': listing,
		'in_cart_quantity': in_cart_quantity,
		'is_own_listing': listing.seller_id == request.user.id,
	})


@login_required
def create_listing(request):
	if request.method == 'POST':
		form = ListingForm(request.POST, request.FILES)
		if form.is_valid():
			images = form.cleaned_data.pop('images')
			listing = form.save(commit=False)
			listing.seller = request.user
			listing.save()
			_create_listing_images(listing, images)
			messages.success(request, "Listing created.")
		else:
			messages.error(request, "Please check the listing details and try again.")
	return redirect(reverse('marketplace') + '?tab=mine')


@login_required
def edit_listing(request, listing_id):
	listing = get_object_or_404(Listing, pk=listing_id)
	# Only the seller who created a listing can edit it — same
	# server-side rule as delete_listing, enforced regardless of what
	# the frontend shows or hides.
	if listing.seller_id != request.user.id:
		raise PermissionDenied("You can only edit listings you created.")

	if request.method == 'POST':
		form = ListingForm(request.POST, request.FILES, instance=listing)
		if form.is_valid():
			images = form.cleaned_data.pop('images')
			form.save()
			if images:
				start_order = listing.images.count()
				_create_listing_images(listing, images, start_order=start_order)
			messages.success(request, "Listing updated.")
		else:
			messages.error(request, "Please check the listing details and try again.")

	return redirect(reverse('marketplace') + '?tab=mine')


@login_required
def toggle_listing_sold(request, listing_id):
	"""A one-click way for a seller to mark their own listing sold/
	available again, separate from the full edit form."""
	listing = get_object_or_404(Listing, pk=listing_id)
	if listing.seller_id != request.user.id:
		raise PermissionDenied("You can only update listings you created.")

	if request.method == 'POST':
		listing.status = Listing.STATUS_AVAILABLE if listing.is_sold else Listing.STATUS_SOLD
		listing.save(update_fields=['status'])
		messages.success(request, f"Listing marked as {listing.get_status_display().lower()}.")

	return redirect(reverse('marketplace') + '?tab=mine')


@login_required
def delete_listing(request, listing_id):
	listing = get_object_or_404(Listing, pk=listing_id)
	# Only the seller who created a listing can delete it — checked
	# server-side regardless of what the frontend shows or hides, same
	# rule as delete_event.
	if listing.seller_id != request.user.id:
		raise PermissionDenied("You can only delete listings you created.")

	if request.method == 'POST':
		listing.delete()
		messages.success(request, "Listing deleted.")

	return redirect(reverse('marketplace') + '?tab=mine')


@login_required
def add_to_cart(request):
	"""Adds a listing to the logged-in user's cart, or bumps the
	quantity if it's already in there. A seller can't add their own
	listing to their own cart; a sold listing can't be added either."""
	if request.method == 'POST':
		listing = get_object_or_404(Listing, pk=request.POST.get('listing_id'))
		quantity = max(1, int(request.POST.get('quantity', 1) or 1))

		if listing.seller_id == request.user.id:
			messages.error(request, "You can't buy your own listing.")
		elif listing.is_sold:
			messages.error(request, "That item has already been sold.")
		else:
			cart_item, created = CartItem.objects.get_or_create(
				user=request.user, listing=listing, defaults={'quantity': quantity},
			)
			if not created:
				cart_item.quantity += quantity
				cart_item.save(update_fields=['quantity'])
			log_interaction(request.user, Interaction.ITEM_LISTING, listing.id, Interaction.ACTION_CART)
			if created:
				notify(listing.seller, request.user, Notification.LISTING_CART, listing=listing, replace=True)
			messages.success(request, "Added to cart.")

	next_url = request.POST.get('next') or (reverse('marketplace') + '?tab=browse')
	return redirect(next_url)


@login_required
def update_cart_item(request, cart_item_id):
	cart_item = get_object_or_404(CartItem, pk=cart_item_id)
	if cart_item.user_id != request.user.id:
		raise PermissionDenied("You can only update your own cart.")

	if request.method == 'POST':
		quantity = int(request.POST.get('quantity', 1) or 1)
		if quantity < 1:
			cart_item.delete()
		else:
			cart_item.quantity = quantity
			cart_item.save(update_fields=['quantity'])

	return redirect(reverse('marketplace') + '?tab=cart')


@login_required
def remove_from_cart(request, cart_item_id):
	cart_item = get_object_or_404(CartItem, pk=cart_item_id)
	if cart_item.user_id != request.user.id:
		raise PermissionDenied("You can only update your own cart.")

	if request.method == 'POST':
		cart_item.delete()
		messages.success(request, "Removed from cart.")

	return redirect(reverse('marketplace') + '?tab=cart')


@login_required
def follow_toggle(request, user_id):
	"""Every follow on UniConnect needs the target's approval, so this
	never creates an immediate follow. It's a 3-way toggle, keyed off
	whatever Follow row (if any) already exists for this pair:

	  no row       -> create one as PENDING (a follow request)
	  pending row  -> delete it (cancelling your own outstanding request)
	  accepted row -> delete it (unfollowing)

	Accepting/declining a pending request someone else sent you is a
	separate action — see follow_request_accept/decline — this view is
	only ever called by the follower's own side of the relationship."""
	if request.method != 'POST':
		return redirect('home')

	target = get_object_or_404(User, pk=user_id)
	status = 'none'

	if is_blocked(request.user, target):
		if _is_ajax(request):
			return JsonResponse({'status': 'none', 'error': "You can't follow this account."}, status=403)
		messages.error(request, "You can't follow this account.")
		return redirect('home')
	if target.id != request.user.id:
		follow, created = Follow.objects.get_or_create(
			follower=request.user, following=target,
			defaults={'status': Follow.STATUS_PENDING},
		)
		if not created:
			follow.delete()
			status = 'none'
			# Cancelling a request (or unfollowing) takes back the
			# notification it caused.
			unnotify(target, request.user, Notification.FOLLOW_REQUEST)
			unnotify(target, request.user, Notification.FOLLOW)
		else:
			status = Follow.STATUS_PENDING
			# Logged at request time, not on acceptance: asking to follow
			# someone is the user's own signal of interest, whatever the
			# other person decides.
			log_interaction(request.user, Interaction.ITEM_USER, target.id, Interaction.ACTION_FOLLOW)
			notify(target, request.user, Notification.FOLLOW_REQUEST, replace=True)

	if _is_ajax(request):
		return JsonResponse({'status': status})

	return redirect('home')


@login_required
def follow_requests_list(request):
	"""Pending follow requests waiting on the current user's approval —
	the minimal surface for the Instagram-style approve/decline flow,
	since the shared Notifications page is only a placeholder."""
	requests_qs = Follow.objects.filter(
		following=request.user, status=Follow.STATUS_PENDING,
	).select_related('follower', 'follower__student_profile').order_by('-created_at')
	return render(request, 'feed/follow_requests.html', {'requests': requests_qs})


@login_required
def follow_request_accept(request, follow_id):
	if request.method != 'POST':
		return redirect('follow_requests')

	follow = get_object_or_404(Follow, pk=follow_id, following=request.user, status=Follow.STATUS_PENDING)
	follow.status = Follow.STATUS_ACCEPTED
	follow.save(update_fields=['status'])
	# "X requested to follow you" becomes "X started following you" (kept
	# read/unread as it was), and the follower hears it was accepted.
	Notification.objects.filter(
		recipient=request.user, actor=follow.follower, type=Notification.FOLLOW_REQUEST,
	).update(type=Notification.FOLLOW)
	notify(follow.follower, request.user, Notification.FOLLOW_ACCEPTED, replace=True)

	if _is_ajax(request):
		return JsonResponse({
			'accepted': True,
			'followers_count': Follow.objects.filter(following=request.user, status=Follow.STATUS_ACCEPTED).count(),
		})

	return redirect('follow_requests')


@login_required
def follow_request_decline(request, follow_id):
	if request.method != 'POST':
		return redirect('follow_requests')

	follow = get_object_or_404(Follow, pk=follow_id, following=request.user, status=Follow.STATUS_PENDING)
	follow.delete()
	unnotify(request.user, follow.follower, Notification.FOLLOW_REQUEST)

	if _is_ajax(request):
		return JsonResponse({'declined': True})

	return redirect('follow_requests')


@login_required
def toggle_like(request, post_id):
	if request.method != 'POST':
		return redirect('home')

	post = get_object_or_404(Post, pk=post_id)

	# get_or_create() is what actually keeps this race-safe: if two
	# requests for the same user+post land at once (a double-click, two
	# open tabs), Django catches the UniqueConstraint violation from the
	# losing INSERT internally and re-fetches the winner's row instead
	# of raising — so this never creates a duplicate Like.
	like, created = Like.objects.get_or_create(user=request.user, post=post)
	if not created:
		like.delete()
		liked = False
		unnotify(post.author, request.user, Notification.LIKE_POST, post=post)
	else:
		liked = True
		log_interaction(request.user, Interaction.ITEM_POST, post.id, Interaction.ACTION_LIKE)
		notify(post.author, request.user, Notification.LIKE_POST, post=post, replace=True)

	post = _attach_like_data([post], request.user)[0]

	if _is_ajax(request):
		liked_by_html = render_to_string('feed/_post_liked_by.html', {'post': post}, request=request)
		return JsonResponse({'liked': liked, 'likes_count': post.likes_count, 'liked_by_html': liked_by_html})

	next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
	if next_url:
		return redirect(next_url)
	return redirect('home')


@login_required
def toggle_bookmark(request, post_id):
	"""Save/un-save a post for the logged-in user — same get_or_create()
	+ UniqueConstraint toggle pattern as toggle_like above, just against
	the Bookmark model instead of Like. Bookmarks are always scoped to
	request.user: there's no way to bookmark on someone else's behalf."""
	if request.method != 'POST':
		return redirect('home')

	post = get_object_or_404(Post, pk=post_id)

	bookmark, created = Bookmark.objects.get_or_create(user=request.user, post=post)
	if not created:
		bookmark.delete()
		bookmarked = False
	else:
		bookmarked = True
		log_interaction(request.user, Interaction.ITEM_POST, post.id, Interaction.ACTION_BOOKMARK)

	if _is_ajax(request):
		return JsonResponse({'bookmarked': bookmarked})

	next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
	if next_url:
		return redirect(next_url)
	return redirect('home')


def _json_error(message, status=400):
	return JsonResponse({'ok': False, 'error': message}, status=status)


@login_required
def toggle_repost(request, post_id):
	"""Repost a post, or undo your repost of it (POST, CSRF-protected).

	action=repost / action=undo say exactly what to do (so a double-click
	can't flip it back); with neither, it toggles. Only your own Repost
	row is ever touched — nobody can undo someone else's repost. The
	answer is the new state and count, straight from the database."""
	if request.method != 'POST':
		return _json_error('Use POST to repost.', 405) if _is_ajax(request) else redirect('home')
	try:
		post = _shareable_post_or_404(request.user, post_id)
	except Http404:
		if _is_ajax(request):
			return _json_error("That post isn't available any more.", 404)
		raise

	action = request.POST.get('action', '')
	existing = Repost.objects.filter(user=request.user, post=post)
	if action == 'undo' or (action != 'repost' and existing.exists()):
		existing.delete()
		reposted = False
		unnotify(post.author, request.user, Notification.REPOST, post=post)
		message = 'Repost removed.'
	else:
		# get_or_create + the UniqueConstraint: never a second row, even on a double-click.
		_, created = Repost.objects.get_or_create(user=request.user, post=post)
		reposted = True
		if created:
			notify(post.author, request.user, Notification.REPOST, post=post, replace=True)
		message = 'Reposted.'

	count = _repost_total(post)
	if _is_ajax(request):
		return JsonResponse({'ok': True, 'reposted': reposted, 'reposts_count': count, 'message': message})
	messages.success(request, message)
	next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
	if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
		return redirect(next_url)
	return redirect('home')


@login_required
def quote_preview(request, post_id):
	"""The embedded copy of a post shown in the quote composer."""
	post = _shareable_post_or_404(request.user, post_id)
	post = _post_qs(Post.objects.filter(pk=post.pk)).get()
	return render(request, 'feed/_quoted_post.html', {'q': post, 'in_composer': True})


@login_required
def create_quote(request, post_id):
	"""Quote a post (POST, CSRF-protected): a NEW post with your own words
	and/or photos or a video, embedding the original. The original is never
	changed. Something of your own is required — otherwise it'd be a repost."""
	if request.method != 'POST':
		return _json_error('Use POST to quote.', 405) if _is_ajax(request) else redirect('home')
	try:
		original = _shareable_post_or_404(request.user, post_id)
	except Http404:
		if _is_ajax(request):
			return _json_error("That post isn't available any more.", 404)
		raise

	# Same rules as any post (feed/forms.py PostForm): your words and/or
	# up to 4 photos or one video (sent here, or already on ImageKit).
	form = PostForm(request.POST, request.FILES)
	if not form.is_valid():
		errors = form.non_field_errors() or [e for errs in form.errors.values() for e in errs]
		error = str(errors[0]) if errors else 'Please check your quote and try again.'
		if error.startswith('Say something'):
			error = 'Add a comment, a photo or a video to quote this post.'
		if _is_ajax(request):
			return _json_error(error)
		messages.error(request, error)
		return redirect('post_detail', post_id=original.pk)

	quote = form.save(commit=False)
	quote.author = request.user
	quote.content = (quote.content or '').strip()
	quote.quote_of = original
	quote.is_quote = True
	quote.save()
	from .link_previews import attach as attach_link_preview
	attach_link_preview(quote)
	_save_new_media(quote, form.cleaned_data)
	notify(original.author, request.user, Notification.QUOTE, post=quote)
	notify_mentions(quote.content, request.user, quote, skip={original.author_id})

	if _is_ajax(request):
		quote = _post_qs(Post.objects.filter(pk=quote.pk)).get()
		quote = _attach_like_data([quote], request.user)[0]
		quote = _attach_comment_counts([quote])[0]
		quote = _attach_bookmark_data([quote], request.user)[0]
		html = render_to_string('feed/_post_card.html', {'post': quote, 'following_ids': set(), 'pending_ids': set()}, request=request)
		return JsonResponse({
			'ok': True, 'post_id': quote.pk, 'html': html, 'message': 'Your quote was posted.',
			'original_id': original.pk, 'reposts_count': _repost_total(original),
		})
	messages.success(request, 'Your quote was posted.')
	return redirect('home')


@login_required
def post_comments(request, post_id):
	"""AJAX: the data behind the comments modal — the post's own content
	(so it can be read alongside the thread) plus every comment on it,
	already assembled into a reply tree. Opened by clicking a post's
	comment icon, on both desktop (side-by-side panes) and mobile
	(stacked), same modal either way."""
	post = get_object_or_404(_post_qs(Post.objects.all()), pk=post_id)
	roots, total = _build_comment_tree(post, request.user)

	post_html = render_to_string('feed/_comment_post_pane.html', {'post': post}, request=request)
	comments_html = render_to_string('feed/_comment_thread.html', {'comments': roots}, request=request)

	from .post_settings import can_reply
	allowed, note = can_reply(post, request.user)
	return JsonResponse({
		'post_id': post.id,
		'can_reply': allowed, 'reply_note': note,
		'post_html': post_html,
		'comments_html': comments_html,
		'comments_count': total,
	})


@login_required
def add_comment(request, post_id):
	"""Adds a top-level comment on a post, or — when parent_id is given
	— a reply to another comment on the same post (which can itself
	already be a reply, so threads can go arbitrarily deep). A comment
	can carry text, a photo/video, or both — never neither."""
	if request.method != 'POST':
		return redirect('home')

	post = get_object_or_404(Post, pk=post_id)
	content = (request.POST.get('content') or '').strip()
	parent_id = request.POST.get('parent_id') or None
	media_file = request.FILES.get('media')

	if not content and not media_file:
		return JsonResponse({'error': "Comment can't be empty."}, status=400)
	if len(content) > Comment.MAX_CONTENT_LENGTH:
		return JsonResponse({'error': f"Comment is too long (max {Comment.MAX_CONTENT_LENGTH} characters)."}, status=400)

	parent = None
	if parent_id:
		# The parent must belong to the same post — a reply can't jump
		# to a comment thread on a different post.
		parent = Comment.objects.filter(pk=parent_id, post=post).first()
		if not parent:
			return JsonResponse({'error': "Can't find the comment you're replying to."}, status=404)

	from .post_settings import can_reply
	allowed, note = can_reply(post, request.user)
	if not allowed:
		return JsonResponse({'error': note}, status=403)

	comment = Comment(post=post, author=request.user, parent=parent, content=content)

	if media_file:
		ext = media_file.name.rsplit('.', 1)[-1].lower() if '.' in media_file.name else ''
		if ext in Comment.ALLOWED_IMAGE_EXTENSIONS:
			comment.image = media_file
		elif ext in Comment.ALLOWED_VIDEO_EXTENSIONS:
			comment.video = media_file
		else:
			return JsonResponse({'error': "Unsupported file type — use a photo (jpg, png, gif, webp) or a video (mp4, mov, webm)."}, status=400)

	try:
		comment.full_clean()
	except ValidationError as exc:
		errors = [msg for msgs in exc.message_dict.values() for msg in msgs]
		return JsonResponse({'error': ' '.join(errors) or "Could not post your comment."}, status=400)

	comment.save()
	log_interaction(request.user, Interaction.ITEM_POST, post.id, Interaction.ACTION_COMMENT)

	# Notifications: a reply tells the person replied to; the post's
	# author hears about any comment (unless they're the one replied to,
	# who already got the reply notification); anyone @mentioned is told
	# too, unless they've already been notified about this comment.
	notified = {request.user.pk}
	if parent and parent.author_id not in notified:
		notify(parent.author, request.user, Notification.REPLY, post=post, comment=comment)
		notified.add(parent.author_id)
	if post.author_id not in notified and not post.replies_muted:
		notify(post.author, request.user, Notification.COMMENT, post=post, comment=comment)
		notified.add(post.author_id)
	notify_mentions(content, request.user, post, comment, skip=notified)
	comment.reply_list = []  # fresh comment, never has replies yet — _comment_item.html expects this attribute
	comment.likes_count = 0  # fresh comment, never has likes yet — same reason
	comment.user_has_liked = False
	comment.recent_likers = []

	comment_html = render_to_string('feed/_comment_item.html', {'comment': comment}, request=request)
	total = Comment.objects.filter(post=post).count()

	return JsonResponse({
		'comment_html': comment_html,
		'comment_id': comment.id,
		'parent_id': parent.id if parent else None,
		'comments_count': total,
	})


@login_required
def edit_comment(request, comment_id):
	comment = get_object_or_404(Comment, pk=comment_id)
	# Only the comment's own author can ever edit it — checked
	# server-side regardless of what the frontend shows or hides.
	if comment.author_id != request.user.id:
		raise PermissionDenied("You can only edit your own comments.")

	if request.method != 'POST':
		return redirect('home')

	content = (request.POST.get('content') or '').strip()
	if not content:
		return JsonResponse({'error': "Comment can't be empty."}, status=400)
	if len(content) > Comment.MAX_CONTENT_LENGTH:
		return JsonResponse({'error': f"Comment is too long (max {Comment.MAX_CONTENT_LENGTH} characters)."}, status=400)

	comment.content = content
	comment.is_edited = True
	comment.save(update_fields=['content', 'is_edited', 'updated_at'])

	return JsonResponse({'content': comment.content, 'is_edited': True})


@login_required
def delete_comment(request, comment_id):
	comment = get_object_or_404(Comment, pk=comment_id)
	# Same rule as edit: only the author can ever delete it, ever.
	if comment.author_id != request.user.id:
		raise PermissionDenied("You can only delete your own comments.")

	if request.method != 'POST':
		return redirect('home')

	post_id = comment.post_id
	# Deleting a comment that has replies deletes them too (the
	# Comment.parent FK is on_delete=CASCADE) — same as deleting a post
	# deletes its comments.
	comment.delete()
	total = Comment.objects.filter(post_id=post_id).count()

	return JsonResponse({'deleted': True, 'comments_count': total})


@login_required
def toggle_comment_like(request, comment_id):
	"""Like/unlike a comment (or a reply — a reply is itself a Comment).
	Same get_or_create()-based race-safety as toggle_like for posts."""
	if request.method != 'POST':
		return redirect('home')

	comment = get_object_or_404(Comment, pk=comment_id)

	like, created = CommentLike.objects.get_or_create(user=request.user, comment=comment)
	if not created:
		like.delete()
		liked = False
		unnotify(comment.author, request.user, Notification.LIKE_COMMENT, comment=comment)
	else:
		liked = True
		notify(comment.author, request.user, Notification.LIKE_COMMENT, post=comment.post, comment=comment, replace=True)

	comment = _attach_comment_like_data([comment], request.user)[0]

	if _is_ajax(request):
		# Comments show a plain count next to the heart (TikTok-style),
		# not the avatars-and-names "Liked by ..." row posts get — so
		# there's no partial to render here, just the number itself.
		return JsonResponse({'liked': liked, 'likes_count': comment.likes_count})

	return redirect('home')


# Tabs with no backing feature yet — shown as
# honest "coming soon" empty states rather than fake or silently-dead
# buttons, same pattern as coming_soon(). 'replies' isn't here — it's
# backed by the Comment model (see profile_view). Bookmarks have their
# own page now (bookmarks_page), not a profile tab.
PROFILE_TAB_COMING_SOON = {}


@login_required
def profile_view(request, username=None):
	if username is None:
		profile_user = request.user
	else:
		profile_user = User.objects.filter(username__iexact=username).first()
		if profile_user is None:
			# An old username (Settings > Username): go to whoever had it.
			from .usernames import redirect_target
			new = redirect_target(username)
			if new:
				return redirect('user_profile', username=new)
			raise Http404('No such account.')
		if profile_user.username != username:
			return redirect('user_profile', username=profile_user.username)
	student = get_object_or_404(StudentProfile.objects.select_related(
		'user', 'university', 'faculty', 'department', 'level',
	), user=profile_user)

	is_own = profile_user.id == request.user.id
	if not is_own and profile_user.id in blocked_ids(request.user):
		# Blocked either way: no posts, follow button or details — just
		# who it is and (if you did the blocking) an Unblock button.
		return render(request, 'feed/profile_blocked.html', {'profile_user': profile_user, 'student': student,
			'i_blocked': Block.objects.filter(blocker=request.user, blocked=profile_user).exists()})
	# Three states the Follow button can be in: 'none' (show "Follow"),
	# 'pending' (show "Requested" — a request this viewer sent is
	# awaiting profile_user's approval), or 'accepted' (show
	# "Following"). is_following stays a plain bool for anything that
	# only cares whether the viewer is an approved follower.
	follow_status = 'none'
	if not is_own:
		existing = Follow.objects.filter(follower=request.user, following=profile_user).first()
		if existing:
			follow_status = existing.status
	is_following = follow_status == Follow.STATUS_ACCEPTED

	all_posts = _post_qs(Post.objects.filter(author=profile_user))

	tab = request.GET.get('tab', 'posts')
	if tab == 'bookmark':
		# Bookmarks moved from a profile tab to their own page. An old
		# "?tab=bookmark" link takes you there if it's your own profile;
		# on anyone else's it just shows their posts (bookmarks are private).
		if is_own:
			return redirect('bookmarks')
		tab = 'posts'
	if tab not in ('posts', 'media', 'likes', 'replies', 'repost') and tab not in PROFILE_TAB_COMING_SOON:
		tab = 'posts'
	# Likes are private: only the profile's owner sees what they've liked.
	# Anyone else asking for ?tab=likes just gets the Posts tab.
	if tab == 'likes' and not is_own:
		tab = 'posts'

	tab_coming_soon_message = PROFILE_TAB_COMING_SOON.get(tab)
	replies = []
	if tab == 'media':
		posts = _has_video(all_posts)
	elif tab == 'likes':
		# The posts profile_user has liked, most-recently-liked first —
		# not post creation order, liking order. Fetched as a plain list
		# (ordered to match the Like rows) rather than a queryset, since
		# "order by when THIS user liked it" isn't something a single
		# ORM query over Post expresses cleanly.
		liked_post_ids = list(
			Like.objects.filter(user=profile_user).order_by('-created_at').values_list('post_id', flat=True)
		)
		liked_posts_by_id = _post_qs(Post.objects.filter(id__in=liked_post_ids)).in_bulk()
		posts = [liked_posts_by_id[pid] for pid in liked_post_ids if pid in liked_posts_by_id]
	elif tab == 'replies':
		# Every comment profile_user has left on anyone's post — a
		# top-level comment on a post and a reply to another comment are
		# the same Comment model here, so both show up, newest first,
		# same as X/Twitter's own Replies tab. Rendered via its own
		# partial (_profile_reply_item.html), not the post card loop
		# below, so `posts` stays empty for this tab.
		replies = list(
			Comment.objects.filter(author=profile_user).select_related(
				'post', 'post__author', 'post__author__student_profile',
				'parent', 'parent__author',
			).order_by('-created_at')
		)
		if replies:
			# Each reply's own action row (like it's a mini post card) needs
			# the same like data a post gets, plus how many direct replies
			# IT has — same direct-children count the "View N replies"
			# toggle shows in the full thread, not every nested descendant.
			_attach_comment_like_data(replies, request.user)
			reply_ids = [r.id for r in replies]
			direct_reply_counts = {}
			for row in Comment.objects.filter(parent_id__in=reply_ids).values('parent_id').annotate(n=Count('id')):
				direct_reply_counts[row['parent_id']] = row['n']
			for r in replies:
				r.replies_count = direct_reply_counts.get(r.id, 0)
		posts = Post.objects.none()
	elif tab == 'repost':
		# Just what profile_user shared: their reposts and their quotes.
		posts = _profile_timeline(profile_user, all_posts.filter(is_quote=True))
	elif tab_coming_soon_message:
		posts = Post.objects.none()
	else:
		# Posts tab, like X's: everything profile_user posted (quotes
		# included) plus what they reposted, so followers see it all —
		# with their pinned post (if any) first, marked "Pinned".
		posts = _profile_timeline(profile_user, all_posts.filter(thread_root__isnull=True))
		pin = PinnedPost.objects.filter(user=profile_user, post__author=profile_user).first()
		if pin:
			pinned = _post_qs(Post.objects.filter(pk=pin.post_id)).first()
			if pinned is not None:
				pinned.is_pinned = True
				posts = [pinned] + [p for p in posts if not (p.pk == pinned.pk and not getattr(p, 'repost_by', None))]

	posts = _attach_like_data(posts, request.user)
	posts = _attach_comment_counts(posts)
	posts = _attach_bookmark_data(posts, request.user)

	from .skills import skills_for, suggestions as skill_suggestions
	context = {
		'skills': skills_for(profile_user, request.user),
		'skill_suggestions': skill_suggestions(request.user) if is_own else [],
		'skills_max': ProfileSkill.MAX,
		'profile_user': profile_user,
		'student': student,
		'is_own': is_own,
		'is_following': is_following,
		'follow_status': follow_status,
		'followers_count': Follow.objects.filter(following=profile_user, status=Follow.STATUS_ACCEPTED).count(),
		'following_count': Follow.objects.filter(follower=profile_user, status=Follow.STATUS_ACCEPTED).count(),
		'pending_follow_requests_count': Follow.objects.filter(following=request.user, status=Follow.STATUS_PENDING).count() if is_own else 0,
		'posts': posts,
		'replies': replies,
		'posts_count': all_posts.count(),
		'tab': tab,
		'tab_coming_soon_message': tab_coming_soon_message,
		# Likes and Repost show other people's posts too, so each card's
		# "Follow @author" item needs the viewer's real follow lists.
		'following_ids': set(Follow.objects.filter(follower=request.user, status=Follow.STATUS_ACCEPTED).values_list('following_id', flat=True)),
		'pending_ids': set(Follow.objects.filter(follower=request.user, status=Follow.STATUS_PENDING).values_list('following_id', flat=True)),
	}

	if is_own:
		# The desktop Edit Profile modal is rendered inline on this page
		# (unlike the mobile full-page version, which has its own
		# view/form) — so it needs a bound form here too, pre-filled from
		# the student's current data, or every field in the modal renders
		# blank.
		context['form'] = ProfileEditForm(instance=student, user=request.user)

	from .usernames import is_matric_style
	context['username_is_default'] = is_own and is_matric_style(profile_user.username)
	return render(request, 'feed/profile.html', context)


@login_required
def edit_profile(request):
	student = get_object_or_404(StudentProfile.objects.select_related('user'), user=request.user)

	if request.method == 'POST':
		form = ProfileEditForm(request.POST, request.FILES, instance=student, user=request.user)
		if form.is_valid():
			form.save()
			messages.success(request, "Profile updated successfully.")
			return redirect('profile')
	else:
		form = ProfileEditForm(instance=student, user=request.user)

	return render(request, 'feed/edit_profile.html', {'form': form, 'student': student})


# ---------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------

def _notifications_json(user, **extra):
	"""What every notifications endpoint sends back: the new unread
	count, so the bell's badge can be updated from any response."""
	count = unread_count(user)
	return JsonResponse({'unread': count, 'badge': badge_text(count), **extra})


@login_required
def notifications_page(request):
	"""The notifications list — the full page, or (?preview=1, AJAX) the
	latest few for the hover popup beside the left sidebar's bell.

	Viewing the list is what clears the bell: every entry shown here as
	unread is marked read in the database right after the list is
	built, so the highlight still shows for this one view (like
	Facebook) but the badge is gone, and stays gone after a refresh."""
	# Tabs (All / Mentions / Activity / Groups & Courses / Events & Market).
	tab = request.GET.get('tab', 'all')
	if tab not in NOTIFICATION_TAB_TYPES:
		tab = 'all'
	tab_unread = notification_unread_by_tab(request.user)   # before this view marks anything read
	entries = build_entries(recent_for(request.user, types=NOTIFICATION_TAB_TYPES[tab]))

	# Hover popup on the sidebar bell: the latest few, as a preview.
	# Nothing is marked read here; opening the page does that.
	if request.GET.get('preview') and _is_ajax(request):
		html = render_to_string('feed/_notification_preview.html', {'entries': entries[:5]}, request=request)
		return _notifications_json(request.user, html=html)

	# Follow requests still waiting on an answer get Confirm/Delete buttons.
	pending = dict(
		Follow.objects.filter(following=request.user, status=Follow.STATUS_PENDING)
		.values_list('follower_id', 'id')
	)
	for entry in entries:
		if entry['is_follow_request']:
			entry['follow_id'] = pending.get(entry['actor_id'])

	new_entries = [e for e in entries if not e['is_read']]
	earlier_entries = [e for e in entries if e['is_read']]
	mark_read(request.user, [pk for e in new_entries for pk in parse_ids(e['ids'])])
	# From here on everything shown is read in the database. The "New"
	# entries stay highlighted for this one view (like Facebook), but
	# their three-dot menu offers "Mark as unread", which is the truth.
	for entry in entries:
		entry['read_in_db'] = True

	tabs = [{'key': k, 'label': label, 'icon': icon, 'unread': 0 if k == tab else tab_unread.get(k, 0)}
		for k, label, icon, _ in NOTIFICATION_TABS]
	if tab != 'all':
		# Everything in this tab is read now; "All" keeps counting the other tabs.
		tabs[0]['unread'] = max(0, tab_unread['all'] - tab_unread.get(tab, 0))
	context = {'new_entries': new_entries, 'earlier_entries': earlier_entries, 'tab': tab, 'tabs': tabs,
		'any_unread': any(t['unread'] for t in tabs)}
	if request.GET.get('panel') and _is_ajax(request):
		html = render_to_string('feed/_notification_list.html', context, request=request)
		return _notifications_json(request.user, html=html)
	return render(request, 'feed/notifications.html', context)


@login_required
def notifications_count(request):
	"""Polled by the page every ~30s (and when the tab regains focus)
	to keep the bell's badge current without a refresh. Also where class
	reminders are made while the app is open (courses/reminders.py); a new
	one comes back as `reminders` so the page can pop it up."""
	from courses.reminders import due_reminders, pop_up
	from .scheduling import publish_due
	publish_due()
	from studygroups import sessions as group_sessions
	extra = {'reminders': [pop_up(n) for n in due_reminders(request.user)]
		+ [group_sessions.pop_up(n) for n in group_sessions.due_reminders(request.user)]}
	# New chat messages since the page last asked (?chat_since=<time from the last answer>).
	# The first ask only gets the time, so opening a page doesn't pop up old messages.
	from django.utils.dateparse import parse_datetime
	since = parse_datetime(request.GET.get('chat_since') or '')
	now = timezone.now()
	if since is not None and timezone.is_aware(since) and now - since < timedelta(minutes=10):
		from chat.services import new_message_popups
		extra['chats'] = new_message_popups(request.user, since)
	extra['chat_since'] = now.isoformat()
	return _notifications_json(request.user, **extra)


@login_required
def notification_open(request, notification_id):
	"""Clicking a notification: mark it (and the rows grouped with it)
	read, then go to what it's about — the post, the comment, the
	profile... (see notifications.target_url)."""
	notification = get_object_or_404(
		Notification.objects.select_related('actor', 'comment'), pk=notification_id, recipient=request.user,
	)
	group_members(notification).update(is_read=True)
	return redirect(target_url(notification))


@login_required
def notifications_mark(request):
	"""Three-dot menu: "Mark as read" / "Mark as unread" for one entry
	(all the rows grouped into it, sent as ids="1,2,3")."""
	if request.method != 'POST':
		return redirect('notifications')
	ids = parse_ids(request.POST.get('ids'))
	is_read = request.POST.get('state') != 'unread'
	Notification.objects.filter(recipient=request.user, pk__in=ids).update(is_read=is_read)
	if _is_ajax(request):
		return _notifications_json(request.user, is_read=is_read)
	return redirect('notifications')


@login_required
def toggle_pin(request, post_id):
	"""The "Pin to your profile" / "Unpin from profile" item in your own
	post's ... menu. One pinned post per person; pinning another replaces it."""
	post = get_object_or_404(Post, pk=post_id)
	if post.author_id != request.user.id:
		raise PermissionDenied("You can only pin your own posts.")
	if request.method == 'POST':
		current = PinnedPost.objects.filter(user=request.user).first()
		if current and current.post_id == post.pk:
			current.delete()
			pinned = False
			msg = 'Unpinned from your profile.'
		else:
			PinnedPost.objects.update_or_create(user=request.user, defaults={'post': post})
			pinned = True
			msg = 'Pinned to your profile.' + (' It replaces your earlier pinned post.' if current else '')
		if _is_ajax(request):
			return JsonResponse({'pinned': pinned, 'message': msg})
		messages.success(request, msg)
	nxt = request.POST.get('next') or ''
	if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
		return redirect(nxt)
	return redirect('profile')


@login_required
def notifications_mark_all(request):
	""""Mark all as read" on the Notifications page (every tab)."""
	if request.method == 'POST':
		Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
		if _is_ajax(request):
			return _notifications_json(request.user, is_read=True)
		messages.success(request, 'All caught up — everything is marked as read.')
	tab = request.POST.get('tab', '')
	return redirect(reverse('notifications') + (f'?tab={tab}' if tab in NOTIFICATION_TAB_TYPES and tab != 'all' else ''))


@login_required
def notifications_delete(request):
	"""Three-dot menu: "Remove this notification" (the whole entry)."""
	if request.method != 'POST':
		return redirect('notifications')
	ids = parse_ids(request.POST.get('ids'))
	Notification.objects.filter(recipient=request.user, pk__in=ids).delete()
	if _is_ajax(request):
		return _notifications_json(request.user, deleted=True)
	return redirect('notifications')


@login_required
def coming_soon(request, title, icon, description=''):
	"""A shared, honest placeholder for nav items whose real feature
	hasn't been built yet — keeps navigation whole (no dead links or
	404s) without pretending functionality exists."""
	return render(request, 'feed/coming_soon.html', {
		'title': title, 'icon': icon, 'description': description,
	})
