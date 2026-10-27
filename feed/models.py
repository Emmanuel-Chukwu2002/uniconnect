from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone


def validate_image_size(value):
	limit_mb = 8
	if value.size > limit_mb * 1024 * 1024:
		raise ValidationError(f"Image must be smaller than {limit_mb}MB.")


def validate_video_size(value):
	limit_mb = 50
	if value.size > limit_mb * 1024 * 1024:
		raise ValidationError(f"Video must be smaller than {limit_mb}MB.")


class Event(models.Model):
	"""A campus event — shown both in the 'Events' sidebar widget (a
	short preview) and in full on the Events page, with registration
	(Attendee), a Venue directory, and simple analytics alongside it.

	`category` used to just BE a color name ('primary'/'danger'/
	'success') — a leftover from when the only thing it drove was the
	sidebar widget's badge color. It's a real event type now (the
	sidebar/card color comes from CATEGORY_COLORS below instead), but
	the three old values are kept as valid choices so events created
	before this change still load and still get a sensible color."""
	ALLOWED_IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp']

	CATEGORY_CHOICES = [
		('conference', 'Conference'),
		('workshop', 'Workshop'),
		('concert', 'Concert'),
		('sports', 'Sports'),
		('exhibition', 'Exhibition'),
		('networking', 'Networking'),
		('festival', 'Festival'),
		('other', 'Other'),
		# Legacy values from before categories had real names — kept so
		# old rows still display (see class docstring above).
		('primary', 'Conference'),
		('danger', 'Sports'),
		('success', 'Workshop'),
	]
	# Which of the app's three accent colors (var(--accent)/var(--danger)/
	# var(--success)) each category renders with, everywhere a category
	# needs a color: the sidebar widget's date badge, the Events page's
	# card banner, and the category pill. Unmapped/legacy values fall
	# back to 'primary' in category_color() below.
	CATEGORY_COLORS = {
		'conference': 'primary', 'workshop': 'success', 'concert': 'danger',
		'sports': 'danger', 'exhibition': 'primary', 'networking': 'success',
		'festival': 'danger', 'other': 'primary',
		'primary': 'primary', 'danger': 'danger', 'success': 'success',
	}
	CATEGORY_ICONS = {
		'conference': 'bi-mic', 'workshop': 'bi-tools', 'concert': 'bi-music-note-beamed',
		'sports': 'bi-trophy', 'exhibition': 'bi-easel', 'networking': 'bi-people',
		'festival': 'bi-stars', 'other': 'bi-calendar-event',
	}

	title = models.CharField(max_length=200)
	location = models.CharField(max_length=200)
	date = models.DateField()
	time = models.TimeField(null=True, blank=True)
	category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default='conference')
	description = models.TextField(blank=True)
	capacity = models.PositiveIntegerField(null=True, blank=True, help_text="Maximum attendees — leave blank for no limit.")
	price = models.DecimalField(max_digits=8, decimal_places=2, default=0, help_text="Entry fee — 0 for a free event.")
	image = models.ImageField(
		upload_to='event_images', null=True, blank=True,
		validators=[FileExtensionValidator(allowed_extensions=ALLOWED_IMAGE_EXTENSIONS), validate_image_size],
	)
	organizer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
	# Added from a community's Events tab (communities app): shown there too.
	community = models.ForeignKey('communities.Community', on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['date']

	def __str__(self):
		return self.title

	@classmethod
	def delete_expired(cls):
		"""Deletes every event whose date (and time, if one was set) is
		already in the past — called from sidebar_widgets so it runs on
		every page load, not just the Events page, so an event is gone
		site-wide shortly after it's happened rather than lingering until
		someone next opens the Events tab. An event with no time set is
		kept for the whole of its date, same as the 'upcoming' queries
		elsewhere (date__gte=today) already treat it."""
		now = timezone.now()
		cls.objects.filter(
			models.Q(date__lt=now.date())
			| models.Q(date=now.date(), time__isnull=False, time__lt=now.time())
		).delete()

	@property
	def category_color(self):
		return self.CATEGORY_COLORS.get(self.category, 'primary')

	@property
	def category_icon(self):
		return self.CATEGORY_ICONS.get(self.category, 'bi-calendar-event')

	@property
	def is_free(self):
		return self.price == 0

	@property
	def spots_left(self):
		"""None means no capacity limit was set (unlimited)."""
		if self.capacity is None:
			return None
		return max(0, self.capacity - self.attendees.count())


class Attendee(models.Model):
	"""A user registered for an Event. Tied to request.user — like
	every other per-user action in the app (Like, Bookmark, Follow) —
	rather than a free-typed name/email, so the attendee list is always
	real accounts, never fake data. The UniqueConstraint is the actual
	guard against double-registering (get_or_create() in the view
	already avoids it in the common case; the constraint makes it
	impossible even under a race)."""
	TYPE_CHOICES = [
		('attendee', 'Attendee'),
		('speaker', 'Speaker'),
		('organizer', 'Organizer'),
		('vip', 'VIP'),
	]
	TYPE_COLORS = {
		'attendee': 'primary', 'speaker': 'success', 'organizer': 'danger', 'vip': 'warning',
	}

	event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='attendees')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='event_registrations')
	attendee_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='attendee')
	registered_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-registered_at']
		constraints = [
			models.UniqueConstraint(fields=['event', 'user'], name='unique_attendee_per_user_per_event'),
		]

	def __str__(self):
		return f'{self.user} registered for {self.event}'

	@property
	def type_color(self):
		return self.TYPE_COLORS.get(self.attendee_type, 'primary')


class Venue(models.Model):
	"""A standalone directory of places events can be held — not
	linked to Event by a foreign key (an event's `location` stays the
	free-text field it always was), just a reference list organizers
	can check capacity/type against, same as the tutorial's independent
	Venues tab."""
	TYPE_CHOICES = [
		('indoor', 'Indoor'),
		('outdoor', 'Outdoor'),
		('virtual', 'Virtual'),
		('hybrid', 'Hybrid'),
	]

	name = models.CharField(max_length=200)
	address = models.CharField(max_length=255)
	venue_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='indoor')
	capacity = models.PositiveIntegerField(null=True, blank=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']

	def __str__(self):
		return self.name


class PublishedPostManager(models.Manager):
	"""Post.objects: every post except scheduled ones whose time hasn't
	come yet (the composer's Schedule button, feed/scheduling.py). A
	scheduled post's created_at is set to when it goes out, so it simply
	appears in feeds at that moment, in the right place. Post.all_objects
	sees everything (the author's Scheduled list)."""
	def get_queryset(self):
		from django.db.models.functions import Now
		return super().get_queryset().exclude(is_scheduled=True, created_at__gt=Now())


class Post(models.Model):
	"""A single feed post — text and, optionally, media (see PostMedia:
	up to 4 photos, or a single video, never a mix — enforced in
	PostForm.clean()). Deliberately minimal: no likes/comments/reposts
	yet, those are a later pass. Visible to other students at the same
	university as the author (see the home feed view), and on the
	author's own profile."""
	MAX_CONTENT_LENGTH = 500
	ALLOWED_IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp']
	ALLOWED_VIDEO_EXTENSIONS = ['mp4', 'mov', 'webm']

	author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='posts')
	content = models.TextField(blank=True, max_length=MAX_CONTENT_LENGTH)
	# Legacy single-attachment fields — kept only so posts created
	# before multi-photo/video support still render. New posts, and any
	# post that gets edited, use PostMedia (media_items) instead; see
	# edit_post()'s one-time migration of these onto a PostMedia row.
	image = models.ImageField(
		upload_to='post_images', blank=True, null=True,
		validators=[FileExtensionValidator(allowed_extensions=ALLOWED_IMAGE_EXTENSIONS), validate_image_size],
	)
	video = models.FileField(
		upload_to='post_videos', blank=True, null=True,
		validators=[FileExtensionValidator(allowed_extensions=ALLOWED_VIDEO_EXTENSIONS), validate_video_size],
	)
	created_at = models.DateTimeField(auto_now_add=True)
	is_edited = models.BooleanField(default=False, help_text="Set once this post's text or media has been edited; shows an 'Edited' marker on the post.")
	# Quote posts (X-style): an ordinary Post with the quoter's own words,
	# pointing at the post it quotes. is_quote stays True even if the
	# original is later deleted (quote_of then becomes NULL), so the card
	# can say "This post is unavailable" instead of turning into a plain
	# post. A simple repost is NOT a Post — see the Repost model below.
	quote_of = models.ForeignKey(
		'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='quotes',
		help_text="The post this one quotes (set only on quote posts).",
	)
	is_quote = models.BooleanField(default=False)
	# Post settings from the author's "..." menu (feed/post_settings.py).
	REPLY_EVERYONE, REPLY_FOLLOWING, REPLY_MENTIONED = 'everyone', 'following', 'mentioned'
	REPLY_CHOICES = [(REPLY_EVERYONE, 'Everyone'), (REPLY_FOLLOWING, 'People you follow'), (REPLY_MENTIONED, 'Only people you mention')]
	reply_policy = models.CharField(max_length=10, choices=REPLY_CHOICES, default=REPLY_EVERYONE)
	replies_muted = models.BooleanField(default=False, help_text='The author gets no notifications for comments on this post.')
	# Composer extras (feed/scheduling.py): a place ("Main Library, UNN"),
	# and posts scheduled for later (created_at = when they go out).
	location = models.CharField(max_length=80, blank=True)
	is_scheduled = models.BooleanField(default=False, help_text='Set by the Schedule button; hidden until created_at.')
	DISCLOSE_PROMO, DISCLOSE_AI = 'promo', 'ai'
	DISCLOSURE_CHOICES = [('', 'None'), (DISCLOSE_PROMO, 'Paid promotion'), (DISCLOSE_AI, 'Made with AI')]
	disclosure = models.CharField(max_length=5, choices=DISCLOSURE_CHOICES, blank=True, default='')
	# Posted into a community (communities app). Shown in that community,
	# on the author's profile, and in the Home feed of the community's
	# members only. Deleting the community deletes its posts.
	community = models.ForeignKey(
		'communities.Community', on_delete=models.CASCADE, null=True, blank=True, related_name='posts',
		help_text="The community this was posted in, if any.",
	)
	# Threads (feed/threads.py): connected posts written together with the
	# composer's + button, or added later with "Add another post". The
	# first post is an ordinary post; each later one points at it and has
	# its place (1, 2, 3...). Only the first shows in Home and on profiles,
	# with "Show this thread"; the post page shows them all. Deleting the
	# first post deletes the thread.
	thread_root = models.ForeignKey(
		'self', on_delete=models.CASCADE, null=True, blank=True, related_name='thread_replies',
		help_text='The first post of the thread this post continues.',
	)
	thread_index = models.PositiveSmallIntegerField(default=0)
	# The card for the first link in the post (feed/link_previews.py).
	link_preview = models.ForeignKey('LinkPreview', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

	objects = PublishedPostManager()
	all_objects = models.Manager()

	class Meta:
		ordering = ['-created_at']
		base_manager_name = 'all_objects'
		constraints = [
			# A post can't quote itself.
			models.CheckConstraint(condition=~models.Q(quote_of=models.F('pk')), name='post_cannot_quote_itself'),
		]

	def __str__(self):
		return f'Post by {self.author} at {self.created_at:%Y-%m-%d %H:%M}'


class LinkPreview(models.Model):
	"""What a web page says about itself (its title, summary and picture, from
	its Open Graph / meta tags), fetched once per address when a post with a
	link is made (feed/link_previews.py) and shown as a card under the post."""
	url = models.URLField(max_length=500, unique=True)
	title = models.CharField(max_length=200, blank=True)
	description = models.CharField(max_length=300, blank=True)
	image_url = models.URLField(max_length=500, blank=True)
	site_name = models.CharField(max_length=80, blank=True)
	ok = models.BooleanField(default=False, help_text='False if the page could not be read.')
	fetched_at = models.DateTimeField(auto_now=True)

	def __str__(self):
		return self.title or self.url

	@property
	def domain(self):
		from urllib.parse import urlsplit
		host = urlsplit(self.url).hostname or ''
		return host[4:] if host.startswith('www.') else host


class PostMedia(models.Model):
	"""One attachment on a post. A post can have 1-4 photos, or a single
	video (never a mix) — enforced in PostForm.clean(), not here. Kept
	as its own model (rather than image_2/image_3/... columns on Post)
	so a post can carry anywhere from zero to four attachments without
	wasted columns, and so they render in the order they were added."""
	post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='media_items')
	image = models.ImageField(
		upload_to='post_images', blank=True, null=True,
		validators=[FileExtensionValidator(allowed_extensions=Post.ALLOWED_IMAGE_EXTENSIONS), validate_image_size],
	)
	video = models.FileField(
		upload_to='post_videos', blank=True, null=True,
		validators=[FileExtensionValidator(allowed_extensions=Post.ALLOWED_VIDEO_EXTENSIONS), validate_video_size],
	)
	order = models.PositiveSmallIntegerField(default=0)

	# A video stored on ImageKit (see feed/imagekit.py) instead of in
	# `video` above: its ImageKit file ID (needed to delete it) and URL.
	ik_file_id = models.CharField(max_length=64, blank=True)
	ik_url = models.URLField(max_length=500, blank=True)
	# The video's thumbnail ("poster"), if the student picked one —
	# on ImageKit, or in `thumbnail` when ImageKit isn't configured.
	# Without one, ImageKit generates a thumbnail from the video itself.
	ik_thumbnail_file_id = models.CharField(max_length=64, blank=True)
	ik_thumbnail_url = models.URLField(max_length=500, blank=True)
	thumbnail = models.ImageField(
		upload_to='post_thumbnails', blank=True, null=True,
		validators=[FileExtensionValidator(allowed_extensions=Post.ALLOWED_IMAGE_EXTENSIONS), validate_image_size],
	)
	# A photo stored on ImageKit (feed/imagekit.py: upload_image) instead of
	# in `image` above, so ImageKit can serve every screen a sharp copy at
	# the right size (photo_srcset). Photos from before this, or saved while
	# ImageKit was unreachable, stay in `image`.
	ik_image_file_id = models.CharField(max_length=64, blank=True)
	ik_image_url = models.URLField(max_length=500, blank=True)
	# The photo's real size in pixels (None if unknown). A small photo is
	# shown at its true size instead of being stretched to fill the post
	# (is_small / is_small_tile below), and ImageKit is never asked for a
	# size bigger than this.
	width = models.PositiveIntegerField(null=True, blank=True)
	height = models.PositiveIntegerField(null=True, blank=True)

	# A photo "is small" when filling its frame would stretch it too far:
	# a post with one photo shows it about 620x300, a grid tile about 310x150.
	SMALL = (560, 280)
	SMALL_TILE = (320, 160)

	class Meta:
		ordering = ['order', 'id']

	def _smaller_than(self, size):
		return bool(self.width and self.height) and (self.width < size[0] or self.height < size[1])

	@property
	def is_small(self):
		return self._smaller_than(self.SMALL)

	@property
	def is_small_tile(self):
		return self._smaller_than(self.SMALL_TILE)

	# ---- photos: what the templates use ----
	@property
	def is_photo(self):
		return not self.is_video and bool(self.ik_image_url or self.image)

	@property
	def photo_url(self):
		"""The photo at feed size (the `src`; browsers that understand
		srcset pick a better size from photo_srcset)."""
		if self.ik_image_url:
			from .imagekit import sized_image_url
			return sized_image_url(self.ik_image_url, 1080)
		return self.image.url if self.image else ''

	@property
	def photo_srcset(self):
		"""Sizes up to the photo's own width — never bigger, so the browser
		never thinks a small photo is bigger than it is and stretches it."""
		if self.ik_image_url:
			from .imagekit import PHOTO_WIDTHS, srcset
			if self.width and self.width < PHOTO_WIDTHS[-1]:
				return srcset(self.ik_image_url, [w for w in PHOTO_WIDTHS if w < self.width] + [self.width])
			return srcset(self.ik_image_url)
		return ''

	@property
	def photo_full(self):
		"""The sharpest version, for the full-screen photo viewer."""
		if self.ik_image_url:
			from .imagekit import FULL_WIDTH, sized_image_url
			return sized_image_url(self.ik_image_url, FULL_WIDTH)
		return self.image.url if self.image else ''

	@property
	def photo_thumb(self):
		"""A small version for previews (quote composer, edit form)."""
		if self.ik_image_url:
			from .imagekit import sized_image_url
			return sized_image_url(self.ik_image_url, 480)
		return self.image.url if self.image else ''

	@property
	def is_video(self):
		return bool(self.video) or bool(self.ik_url)

	@property
	def on_imagekit(self):
		return bool(self.ik_url)

	@property
	def video_url(self):
		"""The video file itself (ImageKit's original, or the local media file)."""
		if self.ik_url:
			from .imagekit import original_url
			return original_url(self.ik_url)
		return self.video.url if self.video else ''

	@property
	def stream_url(self):
		"""Adaptive (HLS) stream — ImageKit videos only."""
		from .imagekit import stream_url
		return stream_url(self.ik_url)

	@property
	def poster_url(self):
		"""The thumbnail shown before the video plays."""
		from .imagekit import auto_thumbnail_url, sized_image_url
		if self.ik_thumbnail_url:
			return sized_image_url(self.ik_thumbnail_url, 1920)
		if self.thumbnail:
			return self.thumbnail.url
		return auto_thumbnail_url(self.ik_url)

	def __str__(self):
		return f'Media #{self.order} for post {self.post_id}'


class Like(models.Model):
	"""A single user's like on a post. The UniqueConstraint below is
	the real guard against duplicate likes — get_or_create() in the
	view already avoids creating a second row in the common case, but
	the constraint is what makes a duplicate impossible at the database
	level even under a race (a double-click, two open tabs, ...)."""
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='likes')
	post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='likes')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']
		constraints = [
			models.UniqueConstraint(fields=['user', 'post'], name='unique_like_per_user_per_post'),
		]

	def __str__(self):
		return f'{self.user} likes post {self.post_id}'


class Repost(models.Model):
	"""A simple repost (X-style): `user` shares someone's existing `post`
	with their followers, with no words of their own. It points at the
	original — nothing is copied — so the original's text, media, likes
	and comments all stay the original's. Shown in the Home feed as
	"David reposted" above the original card, and on David's profile
	under the Repost tab. (A quote — the user's own words plus the
	original — is a Post with quote_of set, not a Repost.)

	Same race-safety story as Like: get_or_create() in the view avoids a
	second row in the common case, and the UniqueConstraint makes a
	duplicate impossible at the database level. Deleting the original
	post (or the user) removes their reposts of it."""
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reposts')
	post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='reposts')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']
		constraints = [
			models.UniqueConstraint(fields=['user', 'post'], name='unique_repost_per_user_per_post'),
		]

	def __str__(self):
		return f'{self.user} reposted post {self.post_id}'


class BookmarkFolder(models.Model):
	"""A folder of bookmarks ("Exam prep", "Events"), like X's. Private to its
	owner (feed/bookmark_folders.py). A bookmark is in one folder at most;
	deleting a folder keeps its bookmarks (they go back to "All")."""
	MAX = 30
	NAME_LENGTH = 30
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookmark_folders')
	name = models.CharField(max_length=NAME_LENGTH)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['name']

	def __str__(self):
		return f'{self.user}: {self.name}'


class Bookmark(models.Model):
	"""A user saving a post to their private Bookmarks tab. Same shape
	and same race-safety story as Like above: get_or_create() in the
	view avoids creating a duplicate in the common case, and the
	UniqueConstraint below makes a duplicate impossible at the database
	level even under a race (a double-click, two open tabs, ...).
	on_delete=models.CASCADE on `post` means a bookmark is cleaned up
	automatically if its post is ever deleted — no extra code needed to
	avoid a dangling/broken bookmark."""
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookmarks')
	post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='bookmarks')
	created_at = models.DateTimeField(auto_now_add=True)
	folder = models.ForeignKey(BookmarkFolder, on_delete=models.SET_NULL, null=True, blank=True, related_name='bookmarks')

	class Meta:
		ordering = ['-created_at']
		constraints = [
			models.UniqueConstraint(fields=['user', 'post'], name='unique_bookmark_per_user_per_post'),
		]

	def __str__(self):
		return f'{self.user} bookmarked post {self.post_id}'


class Comment(models.Model):
	"""A comment on a post, or a reply to another comment (self-referencing
	`parent`) — arbitrary depth, so a reply can itself be replied to,
	rendered as an indented thread. Deleting a comment cascades to its
	replies (on_delete=CASCADE on `parent`), same as deleting a post
	cascades to its comments.

	A comment can optionally carry a single photo or video (never
	both — add_comment() picks one based on the uploaded file's
	extension), the same single-attachment pattern Post itself used
	before PostMedia. content is blank=True so a comment can be
	media-only, same as a Post can be."""
	MAX_CONTENT_LENGTH = 1000
	ALLOWED_IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp']
	ALLOWED_VIDEO_EXTENSIONS = ['mp4', 'mov', 'webm']

	post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
	author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='comments')
	parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')
	content = models.TextField(max_length=MAX_CONTENT_LENGTH, blank=True)
	image = models.ImageField(
		upload_to='comment_images', blank=True, null=True,
		validators=[FileExtensionValidator(allowed_extensions=ALLOWED_IMAGE_EXTENSIONS), validate_image_size],
	)
	video = models.FileField(
		upload_to='comment_videos', blank=True, null=True,
		validators=[FileExtensionValidator(allowed_extensions=ALLOWED_VIDEO_EXTENSIONS), validate_video_size],
	)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)
	is_edited = models.BooleanField(default=False, help_text="Set once this comment's text has been edited; shows an 'Edited' marker.")

	class Meta:
		ordering = ['created_at']

	def __str__(self):
		return f'Comment by {self.author} on post {self.post_id}'


class CommentLike(models.Model):
	"""A single user's like on a comment (or reply — a reply is itself
	a Comment). Same shape and same race-safety guarantee as Like on
	Post: get_or_create() avoids a duplicate in the common case, and
	the UniqueConstraint below makes one impossible at the database
	level even under a race."""
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='comment_likes')
	comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name='likes')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']
		constraints = [
			models.UniqueConstraint(fields=['user', 'comment'], name='unique_like_per_user_per_comment'),
		]

	def __str__(self):
		return f'{self.user} likes comment {self.comment_id}'


class Follow(models.Model):
	"""A follow *request* between two students — every follow on
	UniConnect needs the target's approval, Instagram-style, with no
	per-account opt-out. A row starts out PENDING when one user asks to
	follow another; it only becomes ACCEPTED once the target approves
	it, and a decline (or an unfollow of an already-accepted row) just
	deletes the row rather than storing a third state.

	follower.following (the Follow rows a user owns) and
	follower.followers (the Follow rows pointing at a user) are the two
	sides of the relationship. Followers/Following counts and the
	home-feed 'following' filter only ever consider ACCEPTED rows —
	a pending request is not a follow yet.

	Two database-level constraints — not just application checks —
	keep the relationship valid no matter what code path writes to it:
	unique_together stops the same pair requesting/following twice
	(so a declined request must be deleted before it can be re-sent),
	and the check constraint stops a user from being their own
	follower."""
	STATUS_PENDING = 'pending'
	STATUS_ACCEPTED = 'accepted'
	STATUS_CHOICES = [
		(STATUS_PENDING, 'Pending'),
		(STATUS_ACCEPTED, 'Accepted'),
	]

	follower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='following')
	following = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='followers')
	status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		unique_together = ('follower', 'following')
		constraints = [
			models.CheckConstraint(
				condition=~models.Q(follower=models.F('following')),
				name='follow_cannot_follow_self',
			),
		]

	def __str__(self):
		verb = 'follows' if self.status == self.STATUS_ACCEPTED else 'requested to follow'
		return f'{self.follower} {verb} {self.following}'


class Listing(models.Model):
	"""A single item a student is selling — the Marketplace's equivalent
	of Event: one model backing both the browse grid and the detail
	page, with its own category/condition choices and a `seller` instead
	of an `organizer`. Unlike Event, a listing can carry several photos
	(see ListingImage) since a buyer judging a used item wants to see it
	from more than one angle — modeled on the reference add-to-cart
	tutorial's per-color image sets, but a listing has no variants, so
	plain multi-photo covers the same need without the extra complexity.

	seller uses CASCADE (not Event.organizer's SET_NULL) — a listing is
	"stuff I'm selling", closer to a Post than a standing calendar
	entry, so it doesn't need to outlive its owner's account."""
	ALLOWED_IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp']

	CATEGORY_CHOICES = [
		('textbooks', 'Textbooks'),
		('electronics', 'Electronics'),
		('furniture', 'Furniture'),
		('clothing', 'Clothing'),
		('appliances', 'Appliances'),
		('sports', 'Sports & Fitness'),
		('tickets', 'Tickets & Vouchers'),
		('other', 'Other'),
	]
	CATEGORY_ICONS = {
		'textbooks': 'bi-book', 'electronics': 'bi-laptop', 'furniture': 'bi-house-door',
		'clothing': 'bi-bag', 'appliances': 'bi-plug', 'sports': 'bi-dribbble',
		'tickets': 'bi-ticket-perforated', 'other': 'bi-shop',
	}
	# A distinct banner color per category (unlike Event, where color is a
	# separate user-chosen field) — so the browse grid reads as varied at
	# a glance instead of every card sharing one blue banner.
	CATEGORY_COLORS = {
		'textbooks': 'primary', 'electronics': 'indigo', 'furniture': 'orange',
		'clothing': 'purple', 'appliances': 'teal', 'sports': 'success',
		'tickets': 'danger', 'other': 'primary',
	}
	CONDITION_CHOICES = [
		('new', 'New'),
		('like_new', 'Like New'),
		('good', 'Good'),
		('fair', 'Fair'),
	]
	CONDITION_COLORS = {
		'new': 'success', 'like_new': 'primary', 'good': 'primary', 'fair': 'danger',
	}
	STATUS_AVAILABLE = 'available'
	STATUS_SOLD = 'sold'
	STATUS_CHOICES = [
		(STATUS_AVAILABLE, 'Available'),
		(STATUS_SOLD, 'Sold'),
	]

	seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='listings')
	title = models.CharField(max_length=200)
	description = models.TextField(blank=True)
	category = models.CharField(max_length=15, choices=CATEGORY_CHOICES, default='other')
	condition = models.CharField(max_length=10, choices=CONDITION_CHOICES, default='good')
	price = models.DecimalField(max_digits=10, decimal_places=2)
	quantity_available = models.PositiveIntegerField(default=1, help_text="How many of this item you have to sell.")
	status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_AVAILABLE)
	location = models.CharField(max_length=200, blank=True, help_text="Meetup spot, e.g. a hostel block or campus gate.")
	# True only for listings written by the generate_simulated_data
	# command (recommender training data), so they can be told apart
	# from real listings and removed with --clear.
	is_simulated = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']

	def __str__(self):
		return self.title

	@property
	def category_icon(self):
		return self.CATEGORY_ICONS.get(self.category, 'bi-shop')

	@property
	def category_color(self):
		return self.CATEGORY_COLORS.get(self.category, 'primary')

	@property
	def condition_color(self):
		return self.CONDITION_COLORS.get(self.condition, 'primary')

	@property
	def is_sold(self):
		return self.status == self.STATUS_SOLD

	@property
	def cover_image(self):
		first = self.images.first()
		return first.image if first else None


class ListingImage(models.Model):
	"""One photo of a listing, ordered — the first (order=0) is the
	cover shown on the browse grid; the detail page's gallery shows all
	of them, same main-image-plus-thumbnails pattern as the reference
	tutorial's per-color image sets, just without the color dimension."""
	listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name='images')
	image = models.ImageField(
		upload_to='listing_images',
		validators=[FileExtensionValidator(allowed_extensions=Listing.ALLOWED_IMAGE_EXTENSIONS), validate_image_size],
	)
	order = models.PositiveSmallIntegerField(default=0)

	class Meta:
		ordering = ['order', 'id']

	def __str__(self):
		return f'Image #{self.order} for listing {self.listing_id}'


class PostPoll(models.Model):
	"""A poll in a feed post, like X: the post's text is the question, 2-4
	options, open for 1 day to 1 week. One vote per person, final once cast;
	results show after you vote, to the post's author, and once it closes.
	Voting is feed/polls.py."""
	LENGTHS = [(1, '1 day'), (3, '3 days'), (7, '1 week')]
	post = models.OneToOneField('Post', on_delete=models.CASCADE, related_name='poll')
	closes_at = models.DateTimeField()
	created_at = models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return f'Poll on post {self.post_id}'

	@property
	def is_closed(self):
		return timezone.now() >= self.closes_at


class PostPollOption(models.Model):
	poll = models.ForeignKey(PostPoll, on_delete=models.CASCADE, related_name='options')
	text = models.CharField(max_length=25)
	position = models.PositiveSmallIntegerField(default=0)

	class Meta:
		ordering = ['position']


class PostPollVote(models.Model):
	poll = models.ForeignKey(PostPoll, on_delete=models.CASCADE, related_name='votes')
	option = models.ForeignKey(PostPollOption, on_delete=models.CASCADE, related_name='votes')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='poll_votes')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['poll', 'user'], name='one_vote_per_poll')]


class Block(models.Model):
	"""`blocker` blocked `blocked`. Works both ways from then on: neither
	sees the other's posts, profile, follow button or chats, and existing
	follows between them are removed (feed/moderation.py)."""
	blocker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='blocks_made')
	blocked = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='blocked_by')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']
		constraints = [
			models.UniqueConstraint(fields=['blocker', 'blocked'], name='one_block_per_pair'),
			models.CheckConstraint(condition=~models.Q(blocker=models.F('blocked')), name='cannot_block_self'),
		]


class Report(models.Model):
	"""A student reported a post (or an account) for breaking the rules.
	Staff review open reports at /moderation/ and either remove the post or
	dismiss the report. The reporter stops seeing a post they reported."""
	SPAM, HARASSMENT, HATE, NUDITY, VIOLENCE, FALSE_INFO, SCAM, IMPERSONATION, OTHER = (
		'spam', 'harassment', 'hate', 'nudity', 'violence', 'false_info', 'scam', 'impersonation', 'other')
	REASONS = [
		(SPAM, 'Spam', "Repeated, misleading or unwanted promotion"),
		(HARASSMENT, 'Harassment or bullying', 'Insulting, threatening or targeting someone'),
		(HATE, 'Hate speech', 'Attacks people for who they are'),
		(NUDITY, 'Nudity or sexual content', ''),
		(VIOLENCE, 'Violence or dangerous acts', 'Threats, self-harm or dangerous behaviour'),
		(FALSE_INFO, 'False information', 'Fake news, e.g. made-up school announcements'),
		(SCAM, 'Scam or fraud', 'Fake sales, payment tricks, exam "expo"'),
		(IMPERSONATION, 'Pretending to be someone else', ''),
		(OTHER, 'Something else', ''),
	]
	REASON_CHOICES = [(v, label) for v, label, _ in REASONS]
	# Review workflow (the admin dashboard, adminpanel/): Pending -> Under review ->
	# Content removed / Action taken (warning, suspension) / Dismissed.
	OPEN, REVIEWING, REMOVED, ACTIONED, DISMISSED = 'open', 'reviewing', 'removed', 'actioned', 'dismissed'
	STATUS_CHOICES = [(OPEN, 'Waiting for review'), (REVIEWING, 'Under review'), (REMOVED, 'Post removed'),
		(ACTIONED, 'Action taken'), (DISMISSED, 'No action needed')]
	CLOSED = (REMOVED, ACTIONED, DISMISSED)

	# What was reported. `post` stays for posts (the original reporting flow);
	# target_type / target_id name anything else that can be reported.
	T_POST, T_COMMENT, T_USER, T_LISTING, T_BOOK, T_EVENT, T_GROUP, T_COMMUNITY = (
		'post', 'comment', 'user', 'listing', 'book', 'event', 'group', 'community')
	TARGET_CHOICES = [(T_POST, 'Post'), (T_COMMENT, 'Comment'), (T_USER, 'Account'), (T_LISTING, 'Listing'),
		(T_BOOK, 'Book'), (T_EVENT, 'Event'), (T_GROUP, 'Group'), (T_COMMUNITY, 'Community')]

	reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reports_made')
	post = models.ForeignKey('Post', on_delete=models.SET_NULL, null=True, blank=True, related_name='reports')
	reported_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reports_received')
	reason = models.CharField(max_length=15, choices=REASON_CHOICES)
	details = models.TextField(max_length=1000, blank=True)
	post_snapshot = models.TextField(blank=True, help_text='The post text when it was reported (kept if the post is removed).')
	status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=OPEN)
	reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
	reviewed_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	target_type = models.CharField(max_length=10, choices=TARGET_CHOICES, default=T_POST)
	target_id = models.PositiveIntegerField(null=True, blank=True)
	target_label = models.CharField(max_length=200, blank=True, help_text='The title / name when it was reported.')
	# The university the reported content belongs to, so University Admins see their own.
	university = models.ForeignKey('accounts.University', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
	assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
	decision_reason = models.TextField(blank=True, help_text="The moderator's reason for the decision.")

	class Meta:
		ordering = ['-created_at']
		indexes = [models.Index(fields=['status', 'created_at']), models.Index(fields=['target_type', 'target_id'])]

	def __str__(self):
		return f'{self.reporter} reported {self.post_id or self.reported_user}: {self.reason}'


class HiddenPost(models.Model):
	"""A post `user` chose "Not interested in this post" on: gone from their Home and Search."""
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='hidden_posts')
	post = models.ForeignKey('Post', on_delete=models.CASCADE, related_name='hidden_by')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['user', 'post'], name='hide_post_once')]


class Mute(models.Model):
	"""`muter` muted `muted`: their posts and reposts leave muter's Home
	(still on their profile, and nothing changes for them — they aren't told)."""
	muter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mutes_made')
	muted = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='muted_by')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']
		constraints = [
			models.UniqueConstraint(fields=['muter', 'muted'], name='one_mute_per_pair'),
			models.CheckConstraint(condition=~models.Q(muter=models.F('muted')), name='cannot_mute_self'),
		]


class PreviousUsername(models.Model):
	"""A username someone used before changing it (Settings > Account >
	Username). Old /u/<old name>/ links redirect to the new profile — until
	someone else takes the name, which (like X) anyone can once it's free."""
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='previous_usernames')
	username = models.CharField(max_length=150, db_index=True)
	changed_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-changed_at']


class PostView(models.Model):
	"""Someone saw a post (feed/analytics.py) — at most one row per person,
	post, day and kind, so scrolling past it again the same day doesn't
	inflate it. FEED: the card was on screen (half of it, for a second) in
	any list — Home, a profile, search, a hashtag. DETAIL: they opened the
	post itself. The author's own views never count."""
	FEED, DETAIL = 'feed', 'detail'
	KIND_CHOICES = [(FEED, 'Seen in a feed'), (DETAIL, 'Opened the post')]
	post = models.ForeignKey('Post', on_delete=models.CASCADE, related_name='views')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='post_views')
	kind = models.CharField(max_length=6, choices=KIND_CHOICES, default=FEED)
	day = models.DateField()
	created_at = models.DateTimeField(auto_now_add=True)
	# Made by `manage.py seed_post_views` for the demo, so it can be reported
	# honestly and removed (--reset), like Interaction.is_simulated.
	is_simulated = models.BooleanField(default=False)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['post', 'user', 'day', 'kind'], name='one_post_view_per_day')]
		indexes = [models.Index(fields=['post', 'day'])]


class PostDraft(models.Model):
	"""An unfinished post saved from the composer (feed/drafts.py): its text,
	poll choices, location, community, the time it was set to go out (if
	scheduled) and its photos/video (PostDraftMedia). Posting it — or
	scheduling it — deletes the draft."""
	MAX = 50
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='post_drafts')
	content = models.TextField(blank=True, max_length=500)
	poll_options = models.JSONField(default=list, blank=True)
	poll_days = models.PositiveSmallIntegerField(default=1)
	location = models.CharField(max_length=80, blank=True)
	community = models.ForeignKey('communities.Community', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
	schedule_at = models.DateTimeField(null=True, blank=True)
	# The rest of a thread (the composer's + button): the texts after the first.
	thread_parts = models.JSONField(default=list, blank=True)
	# Started with "Add another post" on a thread: the thread it goes on.
	thread_root = models.ForeignKey('Post', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['-updated_at']

	def __str__(self):
		return f'Draft by {self.user}: {self.content[:30]}'


class PostDraftMedia(models.Model):
	"""A photo or video attached to a draft — up to 4 photos or 1 video, like a
	post. Re-saving the draft replaces them; the files are deleted with the row."""
	draft = models.ForeignKey(PostDraft, on_delete=models.CASCADE, related_name='media')
	file = models.FileField(upload_to='draft_media')
	name = models.CharField(max_length=120, blank=True)
	content_type = models.CharField(max_length=60, blank=True)
	order = models.PositiveSmallIntegerField(default=0)
	# 0: the first post; 1, 2…: the posts after it in a thread (the + boxes).
	part = models.PositiveSmallIntegerField(default=0)

	class Meta:
		ordering = ['part', 'order']

	@property
	def is_video(self):
		return self.content_type.startswith('video/')


class PinnedPost(models.Model):
	"""The one post a student pinned to the top of their profile (like X).
	Pinning another post replaces it; deleting the post unpins it."""
	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pinned')
	post = models.ForeignKey('Post', on_delete=models.CASCADE, related_name='pins')
	pinned_at = models.DateTimeField(auto_now=True)

	def __str__(self):
		return f'{self.user} pinned post {self.post_id}'


class ProfileSkill(models.Model):
	"""A skill on a student's profile ("Python", "Figma", "Public speaking").
	Up to MAX per student; other students can endorse it (SkillEndorsement).
	Search and Explore > People find students by skill (feed/skills.py)."""
	MAX = 15
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='skills')
	name = models.CharField(max_length=40)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['created_at']
		constraints = [models.UniqueConstraint(models.functions.Lower('name'), 'user', name='one_skill_name_per_user')]

	def __str__(self):
		return self.name


class SkillEndorsement(models.Model):
	skill = models.ForeignKey(ProfileSkill, on_delete=models.CASCADE, related_name='endorsements')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='skill_endorsements')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['skill', 'user'], name='one_endorsement_per_skill')]


class EventSave(models.Model):
	"""An event someone saved for later with "Save Event" (separate from
	registering for it). Listed under Bookmarks > Events."""
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_events')
	event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name='saves')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']
		constraints = [models.UniqueConstraint(fields=['user', 'event'], name='one_save_per_user_per_event')]


class SellerReview(models.Model):
	"""A buyer's star rating (1-5) and comment about a marketplace seller.
	One review per buyer per seller (writing again updates it). Only
	people who have actually chatted with the seller — both sides sent a
	message in their direct chat — can review (feed/details.py can_review)."""
	seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='seller_reviews')
	reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews_written')
	listing = models.ForeignKey('Listing', on_delete=models.SET_NULL, null=True, blank=True, related_name='reviews')
	rating = models.PositiveSmallIntegerField()
	comment = models.TextField(max_length=600, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['-updated_at']
		constraints = [
			models.UniqueConstraint(fields=['seller', 'reviewer'], name='one_review_per_buyer_per_seller'),
			models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name='rating_1_to_5'),
		]

	def __str__(self):
		return f'{self.reviewer} → {self.seller}: {self.rating}★'


class CartItem(models.Model):
	"""One listing in a user's cart, with a quantity — a real database
	row per (user, listing) rather than the reference tutorial's
	browser sessionStorage, since every user here already has an
	account: the cart should survive across devices and sessions the
	same way bookmarks/likes do. The UniqueConstraint is the real guard
	against a duplicate row (adding the same listing twice bumps
	quantity instead — see the view); get_or_create() in the view
	already avoids it in the common case."""
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cart_items')
	listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name='cart_items')
	quantity = models.PositiveIntegerField(default=1)
	added_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-added_at']
		constraints = [
			models.UniqueConstraint(fields=['user', 'listing'], name='unique_cart_item_per_user_per_listing'),
		]

	def __str__(self):
		return f"{self.quantity} x {self.listing} in {self.user}'s cart"

	@property
	def subtotal(self):
		return self.listing.price * self.quantity


class Interaction(models.Model):
	"""One thing a user did with one item — the raw training data for the
	recommender. Every signal lands in this single table (a listing view,
	an add-to-cart, a like, a follow ...) so the recommender reads one
	clean log instead of joining six different tables.

	item_id is a plain integer, not a ForeignKey, because the item can be
	a Listing, an Event, a Post or a User depending on item_type. Deleting
	the item doesn't delete its interactions; the recommender simply skips
	ids that no longer exist.

	ACTION_WEIGHTS turns actions into an "implicit rating": a view is weak
	evidence of interest, adding to cart is strong evidence. These weights
	are a modelling choice to justify in the report, not a fact.

	is_simulated marks rows written by the generate_simulated_data command,
	so simulated data can be reported honestly, filtered out, or deleted."""
	ITEM_LISTING = 'listing'
	ITEM_EVENT = 'event'
	ITEM_POST = 'post'
	ITEM_USER = 'user'
	ITEM_TYPE_CHOICES = [
		(ITEM_LISTING, 'Listing'),
		(ITEM_EVENT, 'Event'),
		(ITEM_POST, 'Post'),
		(ITEM_USER, 'User'),
	]

	ACTION_VIEW = 'view'
	ACTION_LIKE = 'like'
	ACTION_COMMENT = 'comment'
	ACTION_BOOKMARK = 'bookmark'
	ACTION_CART = 'cart'
	ACTION_REGISTER = 'register'
	ACTION_FOLLOW = 'follow'
	ACTION_CHOICES = [
		(ACTION_VIEW, 'Viewed'),
		(ACTION_LIKE, 'Liked'),
		(ACTION_COMMENT, 'Commented'),
		(ACTION_BOOKMARK, 'Bookmarked'),
		(ACTION_CART, 'Added to cart'),
		(ACTION_REGISTER, 'Registered'),
		(ACTION_FOLLOW, 'Followed'),
	]
	ACTION_WEIGHTS = {
		ACTION_VIEW: 1.0,
		ACTION_LIKE: 3.0,
		ACTION_COMMENT: 3.0,
		ACTION_BOOKMARK: 4.0,
		ACTION_CART: 5.0,
		ACTION_REGISTER: 5.0,
		ACTION_FOLLOW: 5.0,
	}

	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='interactions')
	item_type = models.CharField(max_length=10, choices=ITEM_TYPE_CHOICES)
	item_id = models.PositiveIntegerField()
	action = models.CharField(max_length=10, choices=ACTION_CHOICES)
	is_simulated = models.BooleanField(default=False)
	created_at = models.DateTimeField(default=timezone.now)

	class Meta:
		ordering = ['-created_at']
		indexes = [
			models.Index(fields=['user', 'item_type']),
			models.Index(fields=['item_type', 'item_id']),
		]

	def __str__(self):
		return f'{self.user} {self.action} {self.item_type} #{self.item_id}'

	@property
	def weight(self):
		return self.ACTION_WEIGHTS.get(self.action, 1.0)


class Recommendation(models.Model):
	"""One listing recommended to one student, precomputed by
	`python manage.py train_recommender` (see feed/recommender.py).

	Recommendations are computed in a batch and stored, rather than
	computed on every page load: the Marketplace page just reads a few
	rows, stays fast, and never needs the machine-learning libraries.
	The trade-off is freshness — re-run the command (e.g. nightly) to pick
	up new activity and new listings."""
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='recommendations')
	listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name='+')
	rank = models.PositiveSmallIntegerField(help_text="1 = best match.")
	score = models.FloatField()
	reason = models.CharField(max_length=200, help_text='Shown under the card, e.g. "Because you viewed ..."')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['user', 'rank']
		constraints = [
			models.UniqueConstraint(fields=['user', 'listing'], name='unique_recommendation_per_user_per_listing'),
		]

	def __str__(self):
		return f'#{self.rank} for {self.user}: {self.listing}'


class Notification(models.Model):
	"""One thing that happened to a student, caused by someone else:
	"Amaka liked your photo", "Tunde replied to your comment", ...

	Each row is a single event by a single person. Facebook-style
	grouping ("Amaka, Tunde and 2 other people liked your photo") is
	done when the list is shown (feed/notifications.py), using
	group_key: rows with the same non-empty group_key and the same
	read state are shown as one entry. An empty group_key means the
	notification always stands alone (a follow request, a mention).

	The wording is never stored: it's built from `type` and the related
	objects each time the list is shown, so it stays correct if, say,
	someone changes their name. The related objects use CASCADE, so
	deleting a post or comment also removes the notifications about it.

	is_read is what the unread badge counts. Opening the notifications
	list marks what it shows as read (see feed/notifications.py)."""
	LIKE_POST = 'like_post'
	LIKE_COMMENT = 'like_comment'
	COMMENT = 'comment'
	REPLY = 'reply'
	MENTION = 'mention'
	FOLLOW_REQUEST = 'follow_request'
	FOLLOW = 'follow'
	FOLLOW_ACCEPTED = 'follow_accepted'
	EVENT_REGISTER = 'event_register'
	LISTING_CART = 'listing_cart'
	REPOST = 'repost'
	QUOTE = 'quote'
	COMMUNITY_JOIN = 'community_join'
	COMMUNITY_REQUEST = 'community_request'
	COMMUNITY_ACCEPTED = 'community_accepted'
	GROUP_REQUEST = 'group_request'
	GROUP_ACCEPTED = 'group_accepted'
	GROUP_ANNOUNCEMENT = 'group_announcement'
	COURSE_ANSWER = 'course_answer'
	CLASS_REMINDER = 'class_reminder'
	CLASS_CHANGED = 'class_changed'
	CHAT_MENTION = 'chat_mention'
	GROUP_SESSION = 'group_session'
	SESSION_REMINDER = 'session_reminder'
	SESSION_CHANGED = 'session_changed'
	PULSE_REPLY = 'pulse_reply'
	PULSE_INTEREST = 'pulse_interest'
	TYPE_CHOICES = [
		(LIKE_POST, 'Liked your post'),
		(LIKE_COMMENT, 'Liked your comment'),
		(COMMENT, 'Commented on your post'),
		(REPLY, 'Replied to your comment'),
		(MENTION, 'Mentioned you'),
		(FOLLOW_REQUEST, 'Requested to follow you'),
		(FOLLOW, 'Started following you'),
		(FOLLOW_ACCEPTED, 'Accepted your follow request'),
		(EVENT_REGISTER, 'Registered for your event'),
		(LISTING_CART, 'Added your listing to their cart'),
		(REPOST, 'Reposted your post'),
		(QUOTE, 'Quoted your post'),
		(COMMUNITY_JOIN, 'Joined your community'),
		(COMMUNITY_REQUEST, 'Asked to join your community'),
		(COMMUNITY_ACCEPTED, 'Approved your request to join a community'),
		(GROUP_REQUEST, 'Asked to join your group'),
		(GROUP_ACCEPTED, 'Approved your request to join a group'),
		(GROUP_ANNOUNCEMENT, 'Posted an announcement in your group'),
		(COURSE_ANSWER, 'Answered your course question'),
		(CLASS_REMINDER, 'Class starting soon'),
		(CLASS_CHANGED, 'Department cancelled or moved a class'),
		(CHAT_MENTION, 'Mentioned you in a group chat'),
		(GROUP_SESSION, 'Scheduled a study session in your group'),
		(SESSION_REMINDER, 'Study session starting soon'),
		(SESSION_CHANGED, 'Changed a study session you are going to'),
		(PULSE_REPLY, 'Replied to your Campus Pulse update'),
		(PULSE_INTEREST, 'Is interested in your Campus Pulse update'),
	]

	recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
	actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications_caused')
	type = models.CharField(max_length=20, choices=TYPE_CHOICES)
	post = models.ForeignKey(Post, on_delete=models.CASCADE, null=True, blank=True, related_name='+')
	comment = models.ForeignKey('Comment', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
	event = models.ForeignKey(Event, on_delete=models.CASCADE, null=True, blank=True, related_name='+')
	listing = models.ForeignKey(Listing, on_delete=models.CASCADE, null=True, blank=True, related_name='+')
	community = models.ForeignKey('communities.Community', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
	study_group = models.ForeignKey('studygroups.StudyGroup', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
	group_post = models.ForeignKey('studygroups.GroupPost', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
	course_question = models.ForeignKey('courses.CourseQuestion', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
	# Class reminders (courses/reminders.py): the timetable class starting soon.
	# The "actor" of a reminder is the student themselves — nobody else caused it.
	class_slot = models.ForeignKey('courses.ClassSlot', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
	# @mentions in group chats (chat/mentions.py): the message you were mentioned in.
	chat_message = models.ForeignKey('chat.Message', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
	# Group study sessions (studygroups/sessions.py).
	group_session = models.ForeignKey('studygroups.GroupSession', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
	# Campus Pulse (feed/pulse.py): the update that was replied to / marked interesting.
	pulse_status = models.ForeignKey('PulseStatus', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
	group_key = models.CharField(max_length=60, blank=True, db_index=True)
	is_read = models.BooleanField(default=False)
	created_at = models.DateTimeField(default=timezone.now)

	class Meta:
		ordering = ['-created_at']
		indexes = [models.Index(fields=['recipient', 'is_read'])]

	def __str__(self):
		return f'{self.actor} -> {self.recipient}: {self.type}'


class StoryQuerySet(models.QuerySet):
	def active(self):
		"""Only stories that haven't been taken down (is_active) and
		haven't aged past their 24-hour window (expires_at) — the only
		stories that should ever show up in the carousel or the viewer.
		There's no background job expiring stories; "expired" simply
		means this filter excludes them from here on."""
		return self.filter(is_active=True, expires_at__gt=timezone.now())


class Story(models.Model):
	"""A single 24-hour photo status, shown in the Stories carousel
	above the Home feed composer (see feed/views.py's
	_build_stories_carousel() and templates/feed/home.html). Each story
	disappears from the carousel on its own once expires_at has passed
	— see StoryQuerySet.active() — nothing has to run in the background
	to "expire" it.

	is_active is separate from expiry: it's what lets a user take a
	story down early (see delete_story()) without caring whether that
	means an actual row deletion or a soft "hide this" flag."""
	ALLOWED_IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp']
	LIFETIME = timedelta(hours=24)

	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='stories')
	# Stored on ImageKit (ik_image_url) when it's configured — see
	# PostMedia — otherwise (or if ImageKit can't be reached) in `image`.
	image = models.ImageField(
		upload_to='story_images', blank=True,
		validators=[FileExtensionValidator(allowed_extensions=ALLOWED_IMAGE_EXTENSIONS), validate_image_size],
	)
	ik_image_file_id = models.CharField(max_length=64, blank=True)
	ik_image_url = models.URLField(max_length=500, blank=True)
	caption = models.CharField(max_length=200, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	# Not auto_now_add — set once, in save() below, to created_at + 24h.
	# editable=False keeps it out of ModelForms (StoryForm never asks
	# for it; it's computed, not entered).
	expires_at = models.DateTimeField(editable=False)
	is_active = models.BooleanField(default=True)

	objects = StoryQuerySet.as_manager()

	class Meta:
		ordering = ['created_at']

	def save(self, *args, **kwargs):
		if not self.expires_at:
			self.expires_at = timezone.now() + self.LIFETIME
		super().save(*args, **kwargs)

	@property
	def is_expired(self):
		return timezone.now() >= self.expires_at

	@property
	def image_url(self):
		"""The story photo, full-screen size (the story viewer)."""
		if self.ik_image_url:
			from .imagekit import sized_image_url
			return sized_image_url(self.ik_image_url, 1440)
		return self.image.url if self.image else ''

	@property
	def card_url(self):
		"""The story photo, small (the story cards above the feed)."""
		if self.ik_image_url:
			from .imagekit import sized_image_url
			return sized_image_url(self.ik_image_url, 480)
		return self.image.url if self.image else ''

	def __str__(self):
		return f'Story by {self.user} at {self.created_at:%Y-%m-%d %H:%M}'


class StoryView(models.Model):
	"""Records that a user has watched a particular story — at most
	once per (story, viewer) pair. Same race-safety pattern as Like and
	CommentLike: record_story_view() uses get_or_create() so a
	double-fire from the viewer's auto-advance never creates a second
	row, and the UniqueConstraint below makes a duplicate impossible at
	the database level even under a race. Only used to show a story's
	own author how many people have viewed it — nothing currently shows
	*who* viewed it."""
	story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='views')
	viewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='story_views')
	viewed_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['story', 'viewer'], name='unique_view_per_user_per_story'),
		]

	def __str__(self):
		return f'{self.viewer} viewed story {self.story_id}'


class VideoView(models.Model):
	"""One person watching a post's video — counted once per person per
	post (watching it again doesn't add another view). Recorded by
	views.record_video_view once the video has played for a few
	seconds; shown as "N views" on video posts."""
	post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='video_views')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='video_views')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['post', 'user'], name='unique_video_view_per_user_per_post'),
		]

	def __str__(self):
		return f'{self.user} watched post {self.post_id}'


from django.db.models.signals import post_delete  # noqa: E402
from django.dispatch import receiver  # noqa: E402


@receiver(post_delete, sender=PostMedia)
def _delete_from_imagekit(sender, instance, **kwargs):
	"""When a video (or its post) is deleted, delete its files from
	ImageKit too, so they don't keep using storage. Best effort: a
	failure here never stops the delete in UniConnect."""
	_delete_imagekit_files(instance.ik_file_id, instance.ik_thumbnail_file_id, instance.ik_image_file_id)


@receiver(post_delete, sender=Story)
def _delete_story_from_imagekit(sender, instance, **kwargs):
	_delete_imagekit_files(instance.ik_image_file_id)


def _delete_imagekit_files(*file_ids):
	file_ids = [f for f in file_ids if f]
	if not file_ids:
		return
	import logging
	from . import imagekit
	for file_id in file_ids:
		try:
			imagekit.delete_file(file_id)
		except imagekit.ImageKitError as e:
			logging.getLogger(__name__).warning("Couldn't delete %s from ImageKit: %s", file_id, e)


@receiver(post_delete, sender=PostDraftMedia)
def _delete_draft_media_file(sender, instance, **kwargs):
	"""Deleting a draft (or re-saving it) removes its stored photos/videos too."""
	if instance.file:
		instance.file.delete(save=False)


# ---------------------------------------------------------------------
# Campus Pulse (feed/pulse.py, templates/feed/_pulse_bar.html)
# ---------------------------------------------------------------------

class PulseStatusQuerySet(models.QuerySet):
	def live(self):
		"""Not turned off / deleted and not past expires_at. Like Story, nothing runs
		in the background: an expired update simply stops matching this."""
		return self.filter(is_active=True, expires_at__gt=timezone.now())


def validate_pulse_video(value):
	validate_video_size(value)


class PulseStatus(models.Model):
	"""A Campus Pulse update: a short-lived student update shown as a circle at the
	top of Home. Each one has a type (kind), which decides what it shows and which
	buttons the viewer gets, and an audience, which decides who may see it:

	  university   students at the author's university (the default)
	  communities  members of one community the author belongs to
	  everyone     every UniConnect student, at any university

	Who may see what is decided on the server (feed/pulse.py visible_to), never
	only in the page. How long an update stays depends on its type
	(feed/pulse.py expiry_for): 24 hours for most, 48 for questions, until the
	event is over for events, and the length the student picked for "Available"."""
	STUDY = 'study'
	CAMPUS = 'campus'
	EVENT = 'event'
	QUESTION = 'question'
	AVAILABLE = 'available'
	PEOPLE = 'people'
	OPPORTUNITY = 'opportunity'
	KIND_CHOICES = [
		(STUDY, 'Study'),
		(CAMPUS, 'Campus Life'),
		(EVENT, 'Event'),
		(QUESTION, 'Question'),
		(AVAILABLE, 'Available'),
		(PEOPLE, 'Find People'),
		(OPPORTUNITY, 'Opportunity'),
	]

	UNIVERSITY = 'university'
	COMMUNITIES = 'communities'
	EVERYONE = 'everyone'
	AUDIENCE_CHOICES = [
		(UNIVERSITY, 'My University'),
		(COMMUNITIES, 'A community'),
		(EVERYONE, 'Everyone'),
	]

	# "Available Now": what the student is free for.
	ACTIVITY_CHOICES = [
		('study', 'Group study'),
		('coding', 'A coding session'),
		('project', 'Project partners'),
		('sports', 'Football / sports'),
		('other', 'Hanging out'),
	]

	ALLOWED_IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp']
	ALLOWED_VIDEO_EXTENSIONS = ['mp4', 'webm', 'mov', 'm4v']

	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pulse_statuses')
	kind = models.CharField(max_length=12, choices=KIND_CHOICES, default=CAMPUS)
	text = models.CharField(max_length=280, blank=True)
	image = models.ImageField(
		upload_to='pulse_images', blank=True,
		validators=[FileExtensionValidator(allowed_extensions=ALLOWED_IMAGE_EXTENSIONS), validate_image_size],
	)
	ik_image_file_id = models.CharField(max_length=64, blank=True)
	ik_image_url = models.URLField(max_length=500, blank=True)
	video = models.FileField(
		upload_to='pulse_videos', blank=True,
		validators=[FileExtensionValidator(allowed_extensions=ALLOWED_VIDEO_EXTENSIONS), validate_pulse_video],
	)
	# The author's university when it was posted (who "My University" means).
	university = models.ForeignKey('accounts.University', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
	audience = models.CharField(max_length=12, choices=AUDIENCE_CHOICES, default=UNIVERSITY)
	community = models.ForeignKey('communities.Community', on_delete=models.CASCADE, null=True, blank=True, related_name='pulse_statuses')
	# Study / Available: the course (optional) and topic.
	course = models.ForeignKey('courses.Course', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
	topic = models.CharField(max_length=120, blank=True)
	# Events: an event from the Events page, or the details typed in.
	event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True, related_name='pulse_statuses')
	event_title = models.CharField(max_length=120, blank=True)
	event_place = models.CharField(max_length=120, blank=True)
	event_at = models.DateTimeField(null=True, blank=True)
	# Events / Opportunities: where to read more.
	link = models.URLField(max_length=300, blank=True)
	activity = models.CharField(max_length=12, choices=ACTIVITY_CHOICES, blank=True)
	is_answered = models.BooleanField(default=False)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(default=timezone.now)
	expires_at = models.DateTimeField()

	objects = PulseStatusQuerySet.as_manager()

	class Meta:
		ordering = ['-created_at']
		indexes = [models.Index(fields=['is_active', 'expires_at'])]

	def __str__(self):
		return f'{self.get_kind_display()} by {self.user} at {self.created_at:%Y-%m-%d %H:%M}'

	@property
	def image_url(self):
		if self.ik_image_url:
			from .imagekit import sized_image_url
			return sized_image_url(self.ik_image_url, 1080)
		return self.image.url if self.image else ''


class PulseReply(models.Model):
	"""A reply to a Campus Pulse update: written text, or for questions a quick
	answer (Yes / No / Not sure — one per person, changing it replaces it)."""
	YES, NO, NOT_SURE = 'yes', 'no', 'not_sure'
	ANSWER_CHOICES = [(YES, 'Yes'), (NO, 'No'), (NOT_SURE, 'Not sure')]

	status = models.ForeignKey(PulseStatus, on_delete=models.CASCADE, related_name='replies')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pulse_replies')
	text = models.CharField(max_length=500, blank=True)
	answer = models.CharField(max_length=10, choices=ANSWER_CHOICES, blank=True)
	created_at = models.DateTimeField(default=timezone.now)

	class Meta:
		ordering = ['created_at']
		constraints = [
			models.UniqueConstraint(fields=['status', 'user'], condition=~models.Q(answer=''), name='one_quick_answer_per_person'),
		]

	def __str__(self):
		return f'{self.user} on pulse {self.status_id}: {self.answer or self.text[:30]}'


class PulseView(models.Model):
	"""Someone opened an update (its circle turns grey for them; the author sees the count)."""
	status = models.ForeignKey(PulseStatus, on_delete=models.CASCADE, related_name='views')
	viewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pulse_views')
	viewed_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['status', 'viewer'], name='one_pulse_view_per_person')]


class PulseInterest(models.Model):
	"""'I'm interested' on an Event or Opportunity update."""
	status = models.ForeignKey(PulseStatus, on_delete=models.CASCADE, related_name='interests')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pulse_interests')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['status', 'user'], name='one_pulse_interest_per_person')]
