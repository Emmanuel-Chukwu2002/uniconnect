"""
Models for UniConnect Messages (the WhatsApp-style chat section).

Users are UniConnect's own accounts (django.contrib.auth User +
accounts.StudentProfile for photo/name). Status updates reuse the
existing feed.Story model, so there is no second "status" table.

    Conversation ──< ConversationParticipant >── User
         │
         └──< Message ──< MessageReaction >── User

    Community ──< CommunityMember >── User
         └──< Conversation (its announcements channel + its groups)

    Call (call history), UserPresence (online / last seen),
    ChatSettings (per-user Messages settings from the "You" tab)
"""
from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

User = settings.AUTH_USER_MODEL


class Community(models.Model):
	"""A WhatsApp-style community: an announcements channel plus groups."""
	name = models.CharField(max_length=80)
	description = models.CharField(max_length=300, blank=True)
	avatar = models.ImageField(upload_to='chat/community_avatars', blank=True, null=True)
	created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='communities_created')
	created_at = models.DateTimeField(default=timezone.now)

	class Meta:
		verbose_name_plural = 'communities'
		ordering = ['name']

	def __str__(self):
		return self.name


class CommunityMember(models.Model):
	ADMIN, MEMBER = 'admin', 'member'
	community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name='members')
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='community_memberships')
	role = models.CharField(max_length=10, choices=[(ADMIN, 'Admin'), (MEMBER, 'Member')], default=MEMBER)
	joined_at = models.DateTimeField(default=timezone.now)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['community', 'user'], name='unique_community_member')]

	def __str__(self):
		return f'{self.user} in {self.community}'


class Conversation(models.Model):
	"""A chat: either between two people (direct) or a group.
	A community's announcements channel is a group with
	is_announcement=True (only community admins can post in it)."""
	DIRECT, GROUP = 'direct', 'group'
	kind = models.CharField(max_length=10, choices=[(DIRECT, 'Direct'), (GROUP, 'Group')], default=DIRECT)
	name = models.CharField(max_length=80, blank=True)  # groups only
	description = models.CharField(max_length=300, blank=True)
	avatar = models.ImageField(upload_to='chat/group_avatars', blank=True, null=True)
	created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
	community = models.ForeignKey(Community, on_delete=models.CASCADE, null=True, blank=True, related_name='conversations')
	is_announcement = models.BooleanField(default=False)
	# "min_id:max_id" for direct chats, so the same two people can only
	# ever have one direct conversation (the unique constraint enforces it).
	direct_key = models.CharField(max_length=40, null=True, blank=True, unique=True)
	created_at = models.DateTimeField(default=timezone.now)
	# Updated whenever a message is sent: the chat list is sorted by it.
	last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)

	class Meta:
		ordering = ['-last_message_at']

	def __str__(self):
		return self.name or f'Direct chat {self.direct_key}'

	@property
	def is_group(self):
		return self.kind == self.GROUP

	@staticmethod
	def make_direct_key(user_a_id, user_b_id):
		low, high = sorted([user_a_id, user_b_id])
		return f'{low}:{high}'


class ConversationParticipant(models.Model):
	"""One person's membership of one conversation, plus their own
	per-chat settings (pinned, archived, favourite, muted) and how far
	they have received/read (for unread counts and ticks)."""
	ADMIN, MEMBER = 'admin', 'member'
	conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='participants')
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_participations')
	role = models.CharField(max_length=10, choices=[(ADMIN, 'Admin'), (MEMBER, 'Member')], default=MEMBER)
	joined_at = models.DateTimeField(default=timezone.now)
	is_pinned = models.BooleanField(default=False)
	is_archived = models.BooleanField(default=False)
	is_favourite = models.BooleanField(default=False)
	is_muted = models.BooleanField(default=False)
	# Muted for a while (8 hours, a week): unmutes by itself after this.
	# Empty while muted = muted until you unmute ("Always").
	muted_until = models.DateTimeField(null=True, blank=True)
	marked_unread = models.BooleanField(default=False)
	# Message requests (chat/requests.py), like Messenger: a private chat from
	# someone you don't follow waits under "Message requests" until you accept
	# it (or reply); "declined" hides it until they write again.
	REQUEST_PENDING, REQUEST_ACCEPTED, REQUEST_DECLINED = 'pending', 'accepted', 'declined'
	request_state = models.CharField(max_length=10, blank=True, default='', choices=[
		('', 'Normal'), (REQUEST_PENDING, 'Message request'), (REQUEST_ACCEPTED, 'Accepted'), (REQUEST_DECLINED, 'Deleted request')])
	# Everything up to these times has reached / been read by this person.
	last_delivered_at = models.DateTimeField(null=True, blank=True)
	last_read_at = models.DateTimeField(null=True, blank=True)
	# Like last_read_at, but only moves while this person has read
	# receipts switched on — it's what decides the blue ticks others see.
	last_read_receipt_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['conversation', 'user'], name='unique_participant')]
		indexes = [models.Index(fields=['user', 'is_archived'])]

	def __str__(self):
		return f'{self.user} in {self.conversation_id}'


def validate_attachment_size(f):
	from django.core.exceptions import ValidationError
	if f.size > 25 * 1024 * 1024:
		raise ValidationError('Files must be 25 MB or smaller.')


class Message(models.Model):
	TEXT, IMAGE, VIDEO, FILE, AUDIO, SYSTEM, POLL = 'text', 'image', 'video', 'file', 'audio', 'system', 'poll'
	KIND_CHOICES = [(TEXT, 'Text'), (IMAGE, 'Photo'), (VIDEO, 'Video'), (FILE, 'Document'), (AUDIO, 'Voice message'),
		(SYSTEM, 'System'), (POLL, 'Poll')]
	VIDEO_EXTENSIONS = ['mp4', 'webm', 'mov', 'm4v']
	MAX_LENGTH = 4000
	IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp']
	AUDIO_EXTENSIONS = ['webm', 'ogg', 'mp3', 'm4a', 'wav', 'aac']

	conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
	sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='chat_messages')
	kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=TEXT)
	content = models.TextField(blank=True, max_length=MAX_LENGTH)
	attachment = models.FileField(upload_to='chat/attachments/%Y/%m', blank=True, validators=[validate_attachment_size])
	attachment_name = models.CharField(max_length=200, blank=True)
	attachment_size = models.PositiveIntegerField(default=0)
	duration = models.PositiveIntegerField(default=0)  # voice messages, in seconds
	# Replying to an earlier message in the same chat (shown as a quote above it).
	reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
	created_at = models.DateTimeField(default=timezone.now, db_index=True)
	updated_at = models.DateTimeField(auto_now=True)
	is_deleted = models.BooleanField(default=False)
	# Edited by its sender (chat/editing.py); shows "edited" to everyone.
	edited_at = models.DateTimeField(null=True, blank=True)
	# Forwarded from another chat (chat/forwarding.py); shows "Forwarded".
	forwarded = models.BooleanField(default=False)
	# Pinned to the bar at the top of the chat (chat/pins.py).
	pinned_at = models.DateTimeField(null=True, blank=True)
	pinned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
	# Ticks: set once EVERY other participant has received / read it.
	delivered_at = models.DateTimeField(null=True, blank=True)
	read_at = models.DateTimeField(null=True, blank=True)
	is_read = models.BooleanField(default=False)

	class Meta:
		ordering = ['created_at']
		indexes = [models.Index(fields=['conversation', 'created_at'])]

	def __str__(self):
		return f'{self.sender} → {self.conversation_id}: {self.content[:30]}'


class StarredMessage(models.Model):
	"""A message someone starred to find again (Messages > Starred). Private:
	nobody else sees what you starred."""
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='starred_messages')
	message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='stars')
	created_at = models.DateTimeField(default=timezone.now)

	class Meta:
		ordering = ['-created_at']
		constraints = [models.UniqueConstraint(fields=['user', 'message'], name='star_once')]


class MessageMention(models.Model):
	"""Someone @mentioned in a group chat message (chat/mentions.py)."""
	message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='mentions')
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_mentions')

	class Meta:
		constraints = [models.UniqueConstraint(fields=['message', 'user'], name='one_mention_per_person')]


class ChatPoll(models.Model):
	"""A poll sent in a group chat (chat/polls.py). The message's content is
	the question too, so chat search and the chat list find and show it."""
	MAX_OPTIONS = 12
	message = models.OneToOneField(Message, on_delete=models.CASCADE, related_name='poll')
	question = models.CharField(max_length=200)
	allow_multiple = models.BooleanField(default=False)
	closed_at = models.DateTimeField(null=True, blank=True)

	def __str__(self):
		return self.question


class ChatPollOption(models.Model):
	poll = models.ForeignKey(ChatPoll, on_delete=models.CASCADE, related_name='options')
	text = models.CharField(max_length=100)
	order = models.PositiveSmallIntegerField(default=0)

	class Meta:
		ordering = ['order', 'id']


class ChatPollVote(models.Model):
	option = models.ForeignKey(ChatPollOption, on_delete=models.CASCADE, related_name='votes')
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_poll_votes')
	created_at = models.DateTimeField(default=timezone.now)

	class Meta:
		ordering = ['created_at']
		constraints = [models.UniqueConstraint(fields=['option', 'user'], name='one_vote_per_option')]


class MessageReaction(models.Model):
	"""One emoji reaction per person per message (choosing another replaces it)."""
	message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='reactions')
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_reactions')
	emoji = models.CharField(max_length=16)
	created_at = models.DateTimeField(default=timezone.now)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['message', 'user'], name='unique_reaction_per_user')]


class Call(models.Model):
	"""Call history. Ringing/accept/decline/end are signalled live over
	the WebSocket; there is no audio/video stream in this version."""
	AUDIO, VIDEO = 'audio', 'video'
	RINGING, ANSWERED, DECLINED, MISSED, CANCELLED = 'ringing', 'answered', 'declined', 'missed', 'cancelled'
	caller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='calls_made')
	callee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='calls_received')
	kind = models.CharField(max_length=10, choices=[(AUDIO, 'Voice'), (VIDEO, 'Video')], default=AUDIO)
	status = models.CharField(max_length=10, default=RINGING, choices=[
		(RINGING, 'Ringing'), (ANSWERED, 'Answered'), (DECLINED, 'Declined'), (MISSED, 'Missed'), (CANCELLED, 'Cancelled'),
	])
	started_at = models.DateTimeField(default=timezone.now, db_index=True)
	answered_at = models.DateTimeField(null=True, blank=True)
	ended_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		ordering = ['-started_at']

	@property
	def duration_seconds(self):
		if self.answered_at and self.ended_at:
			return max(0, int((self.ended_at - self.answered_at).total_seconds()))
		return 0


class UserPresence(models.Model):
	"""Online = at least one open WebSocket (any tab). last_seen is
	updated when the last one closes."""
	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='chat_presence')
	connections = models.PositiveIntegerField(default=0)
	last_seen = models.DateTimeField(null=True, blank=True)

	@property
	def is_online(self):
		return self.connections > 0


class ChatSettings(models.Model):
	"""The settings on the "You" tab that actually change behaviour."""
	EVERYONE, NOBODY = 'everyone', 'nobody'
	WALLPAPERS = [('doodle', 'Doodle'), ('plain', 'Plain')]
	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='chat_settings')
	about = models.CharField(max_length=140, default='Hey there! I am using UniConnect.')
	read_receipts = models.BooleanField(default=True)
	last_seen_visibility = models.CharField(
		max_length=10, choices=[(EVERYONE, 'Everyone'), (NOBODY, 'Nobody')], default=EVERYONE,
	)
	enter_to_send = models.BooleanField(default=True)
	sounds = models.BooleanField(default=True)
	wallpaper = models.CharField(max_length=10, choices=WALLPAPERS, default='doodle')

	@classmethod
	def for_user(cls, user):
		obj, _ = cls.objects.get_or_create(user=user)
		return obj
