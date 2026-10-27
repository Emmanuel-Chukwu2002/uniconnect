"""
Communities (X/Twitter-style), each belonging to one university.

A community has a banner, a name, a topic, a short description, rules,
and members. Members post into it: those posts are ordinary feed Posts
with Post.community set (feed/models.py), so likes, comments, reposts,
quotes, bookmarks and media all work exactly as they do everywhere else.

Joining: an "open" community lets anyone at the university join at once;
a "restricted" one turns a join into a request that an admin or moderator
approves (CommunityMember.status = pending until then).

Roles: the creator is the first admin. Admins edit the community and
choose moderators; admins and moderators approve requests and remove
members. Everyone else is a member.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models.functions import Lower
from django.urls import reverse


def validate_banner_size(value):
	limit_mb = 8
	if value.size > limit_mb * 1024 * 1024:
		raise ValidationError(f'Banner must be smaller than {limit_mb}MB.')


class Community(models.Model):
	# The topics shown as "Browse topics" on the Communities page:
	# (value, label, Bootstrap icon).
	TOPICS = [
		('courses', 'Courses & Study', 'bi-journal-bookmark'),
		('departments', 'Departments', 'bi-building'),
		('clubs', 'Clubs & Societies', 'bi-people'),
		('tech', 'Tech & Coding', 'bi-cpu'),
		('careers', 'Careers & Business', 'bi-briefcase'),
		('sports', 'Sports & Fitness', 'bi-trophy'),
		('arts', 'Arts & Culture', 'bi-palette'),
		('campus', 'Hostels & Campus Life', 'bi-house-door'),
		('gaming', 'Gaming', 'bi-controller'),
		('faith', 'Faith', 'bi-stars'),
		('other', 'Other', 'bi-grid'),
	]
	TOPIC_CHOICES = [(v, label) for v, label, _ in TOPICS]
	TOPIC_ICONS = {v: icon for v, _, icon in TOPICS}

	OPEN = 'open'
	RESTRICTED = 'restricted'
	JOIN_POLICY_CHOICES = [
		(OPEN, 'Open — anyone at your university can join'),
		(RESTRICTED, 'Restricted — admins and moderators approve requests'),
	]

	# A free photo from Pexels (pexels.com) per topic, used as the banner on a
	# community's own page when it has no banner photo of its own. Loaded from
	# Pexels' servers; nothing is stored here.
	TOPIC_PHOTOS = {
		'courses': 5940711,      # students with laptops in a library
		'departments': 2305098,  # red-brick university building among trees
		'clubs': 6147001,        # students studying together outdoors
		'tech': 574077,          # code on a laptop screen
		'careers': 30688592,     # business meeting in a Lagos office
		'sports': 14658684,      # football pitch
		'arts': 29589096,        # art studio with brushes and paints
		'campus': 5965612,       # student with a laptop by a university building
		'gaming': 28774616,      # game controller
		'faith': 9831736,        # worship
		'other': 256374,         # books on library shelves
	}

	# Banner colours used when there's no banner photo (picked by the
	# community's id, so each one keeps its own colour).
	COLOURS = ['blue', 'violet', 'teal', 'orange', 'pink', 'green', 'indigo', 'red']

	ALLOWED_IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp']
	MAX_RULES = 10
	MAX_TAGS = 10
	TAG_LENGTH = 20

	university = models.ForeignKey('accounts.University', on_delete=models.CASCADE, related_name='communities')
	name = models.CharField(max_length=60)
	description = models.TextField(max_length=500, help_text='What is this community about?')
	topic = models.CharField(max_length=20, choices=TOPIC_CHOICES, default='other')
	join_policy = models.CharField(max_length=12, choices=JOIN_POLICY_CHOICES, default=OPEN)
	banner = models.ImageField(
		upload_to='community_banners', blank=True, null=True,
		validators=[FileExtensionValidator(allowed_extensions=ALLOWED_IMAGE_EXTENSIONS), validate_banner_size],
	)
	# The square picture by the name (a logo). Without one, the community's
	# colour with its topic's icon is shown instead.
	icon = models.ImageField(
		upload_to='community_icons', blank=True, null=True,
		validators=[FileExtensionValidator(allowed_extensions=ALLOWED_IMAGE_EXTENSIONS), validate_banner_size],
	)
	# Short labels under the description ("Python, Django, Web Dev"), comma-separated.
	tags = models.CharField(max_length=250, blank=True, default='')
	# The blue tick by the name: an official community, set by UniConnect's
	# staff in the Django admin (not by the community's own admins).
	is_verified = models.BooleanField(default=False, help_text='Official community: shows a blue tick by its name.')
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='feed_communities_created')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['name']
		verbose_name_plural = 'communities'
		constraints = [
			# One "Python Club" per university (whatever the capitals).
			models.UniqueConstraint(Lower('name'), 'university', name='community_name_unique_per_university'),
		]

	def __str__(self):
		return self.name

	def get_absolute_url(self):
		return reverse('community_detail', args=[self.pk])

	@property
	def is_restricted(self):
		return self.join_policy == self.RESTRICTED

	@property
	def topic_icon(self):
		return self.TOPIC_ICONS.get(self.topic, 'bi-grid')

	@property
	def topic_photo_url(self):
		"""The topic's Pexels photo (for a community without its own banner)."""
		pid = self.TOPIC_PHOTOS.get(self.topic, self.TOPIC_PHOTOS['other'])
		return f'https://images.pexels.com/photos/{pid}/pexels-photo-{pid}.jpeg?auto=compress&cs=tinysrgb&w=1260&h=520&fit=crop'

	@property
	def tag_list(self):
		return [t for t in (x.strip() for x in (self.tags or '').split(',')) if t]

	@property
	def colour(self):
		return self.COLOURS[(self.pk or 0) % len(self.COLOURS)]


class CommunityMember(models.Model):
	ADMIN = 'admin'
	MODERATOR = 'moderator'
	MEMBER = 'member'
	ROLE_CHOICES = [(ADMIN, 'Admin'), (MODERATOR, 'Moderator'), (MEMBER, 'Member')]

	ACTIVE = 'active'
	PENDING = 'pending'
	STATUS_CHOICES = [(ACTIVE, 'Member'), (PENDING, 'Requested to join')]

	community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name='memberships')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='feed_community_memberships')
	role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=MEMBER)
	status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
	created_at = models.DateTimeField(auto_now_add=True)  # joined (or asked to join)

	class Meta:
		ordering = ['created_at']
		constraints = [models.UniqueConstraint(fields=['community', 'user'], name='one_membership_per_user')]
		indexes = [models.Index(fields=['user', 'status'])]

	def __str__(self):
		return f'{self.user} in {self.community} ({self.role}, {self.status})'

	@property
	def is_active(self):
		return self.status == self.ACTIVE

	@property
	def can_moderate(self):
		"""Approve requests and remove members."""
		return self.is_active and self.role in (self.ADMIN, self.MODERATOR)

	@property
	def is_admin(self):
		return self.is_active and self.role == self.ADMIN


class CommunityRule(models.Model):
	community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name='rules')
	text = models.CharField(max_length=200)
	order = models.PositiveSmallIntegerField(default=0)

	class Meta:
		ordering = ['order', 'id']

	def __str__(self):
		return self.text
