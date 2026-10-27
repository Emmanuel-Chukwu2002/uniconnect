"""Groups (/groups/): WhatsApp-style groups for a specific purpose — a class
(COS 401 · 400 Level), a final-year project team, a hostel room, a club
committee. Communities are for shared interests; groups are for people who
work or talk together.

Each group has:
    a type          Academic, Project, Departmental, Hostel, Social, Professional
    a privacy       Public (anyone at the university joins at once),
                    Private (admins approve join requests),
                    Invite only (hidden; joined only through the invite link)
    roles           owner (started it), admins, members
    tabs            Posts (with pinned announcements and polls), Files, Members,
                    About, and its own group chat in Messages (studygroups/chat.py)

Groups belong to one university and are discovered there; anyone with the
invite link can join, including students from other universities.

(The app is still called "studygroups" because groups began as study groups;
an old study group is simply an Academic group.)
"""
import os
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import reverse


def new_invite_code():
	return secrets.token_urlsafe(12)


def validate_group_photo(value):
	if value and value.size > 8 * 1024 * 1024:
		raise ValidationError('The photo is too big — the limit is 8 MB.')


def pexels(pid, w=320, h=320):
	return f'https://images.pexels.com/photos/{pid}/pexels-photo-{pid}.jpeg?auto=compress&cs=tinysrgb&w={w}&h={h}&fit=crop'


# A free Pexels photo per subject, for study groups without their own photo (chosen by course code
# prefix, or a word in the group's name). Nothing is stored; the browser loads it from Pexels.
SUBJECT_PHOTOS = [
	(('hawking', 'space', 'astro', 'cosmo', 'galaxy'), (), 7480),             # Milky Way
	((), ('MTH', 'MAT', 'MATH'), 6256061),                                     # equation on a blackboard
	((), ('STA', 'STAT'), 590045),                                             # charts on paper
	((), ('CHM', 'CHE', 'CHEM', 'PCH'), 248152),                              # lab glassware
	((), ('MCB',), 10448365),                                                  # microorganisms under a microscope
	((), ('BIO', 'BCH', 'ZOO', 'BOT', 'ANA', 'PHS'), 4031321),               # woman using a microscope
	((), ('PHY',), 577514),                                                    # light bulb
	((), ('MEE', 'MEC', 'EEE', 'ECE', 'CVE', 'ENG', 'AGE'), 159298),          # gears
	((), ('HIS', 'HST', 'GST', 'ENG', 'LIT'), 18670323),                       # old books in a library
	((), ('CSC', 'COS', 'CIT', 'SEN', 'CMP', 'CPE'), 574077),                 # code on a laptop
	((), ('ECO', 'ACC', 'BUS', 'FIN', 'BAM', 'MKT'), 5849577),                # wallet and coins
]
STUDY_PHOTO = 5676678   # two students studying together


class StudyGroup(models.Model):
	ACADEMIC, PROJECT, DEPARTMENTAL, HOSTEL, SOCIAL, PROFESSIONAL = 'academic', 'project', 'departmental', 'hostel', 'social', 'professional'
	# (value, label, icon, colour, what it's for)
	TYPES = [
		(ACADEMIC, 'Academic', 'bi-mortarboard', 'blue', 'Course discussions, assignments and exam prep'),
		(PROJECT, 'Project', 'bi-kanban', 'violet', 'A team working on a project together'),
		(DEPARTMENTAL, 'Departmental', 'bi-building', 'teal', 'Everyone in a department or level'),
		(HOSTEL, 'Hostel', 'bi-house-door', 'orange', 'Roommates, floors and hostel blocks'),
		(SOCIAL, 'Social', 'bi-cup-hot', 'pink', 'Hangouts, trips and social plans'),
		(PROFESSIONAL, 'Professional', 'bi-briefcase', 'green', 'Learning a skill or working together'),
	]
	TYPE_CHOICES = [(v, label) for v, label, *_ in TYPES]
	TYPE_INFO = {v: {'label': label, 'icon': icon, 'colour': colour, 'help': help_text} for v, label, icon, colour, help_text in TYPES}

	PUBLIC, PRIVATE, INVITE = 'public', 'private', 'invite'
	PRIVACY_CHOICES = [(PUBLIC, 'Public'), (PRIVATE, 'Private'), (INVITE, 'Invite only')]
	PRIVACY_INFO = {
		PUBLIC: ('bi-globe2', 'Anyone at your university can find and join it.'),
		PRIVATE: ('bi-lock', 'Anyone can find it; admins approve who joins.'),
		INVITE: ('bi-link-45deg', "Hidden from search; people join with the invite link."),
	}

	IN_PERSON, ONLINE, BOTH = 'in_person', 'online', 'both'
	MODE_CHOICES = [(IN_PERSON, 'In person'), (ONLINE, 'Online'), (BOTH, 'In person & online')]
	MODE_ICONS = {IN_PERSON: 'bi-geo-alt', ONLINE: 'bi-camera-video', BOTH: 'bi-people'}

	MAX_LIMIT = 1024

	university = models.ForeignKey('accounts.University', on_delete=models.CASCADE, related_name='study_groups')
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='study_groups_created')
	group_type = models.CharField('Group type', max_length=14, choices=TYPE_CHOICES, default=ACADEMIC)
	privacy = models.CharField(max_length=8, choices=PRIVACY_CHOICES, default=PUBLIC)
	course_code = models.CharField(max_length=20, blank=True, help_text='For academic groups, e.g. COS 401')
	name = models.CharField(max_length=80, help_text='e.g. 400 Level, Final-year project team, Block C Room 12')
	description = models.TextField(max_length=1000, blank=True, help_text='What the group is for and who should join.')
	department = models.ForeignKey('accounts.Department', on_delete=models.SET_NULL, null=True, blank=True, related_name='study_groups')
	level = models.ForeignKey('accounts.Level', on_delete=models.SET_NULL, null=True, blank=True, related_name='study_groups')
	mode = models.CharField(max_length=10, choices=MODE_CHOICES, blank=True, default='')
	schedule = models.CharField(max_length=120, blank=True, help_text='When you meet, e.g. Mondays & Thursdays, 4–6pm')
	place = models.CharField(max_length=120, blank=True, help_text='e.g. Faculty library, 2nd floor')
	meeting_link = models.URLField(blank=True, help_text='Google Meet / Zoom link for online meetings.')
	max_members = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Leave empty for no limit.')
	is_open = models.BooleanField(default=True, help_text='Accepting new members.')
	# One rule per line, shown in About.
	rules = models.TextField(max_length=2000, blank=True, help_text='One rule per line, e.g. Be respectful.')
	# The Posts tab. A small group (a hostel room, a hangout) may only want Chat and Files.
	show_posts = models.BooleanField('Posts tab', default=True, help_text='Longer discussions, questions and announcements.')
	photo = models.ImageField('Group photo', upload_to='group_photos/%Y/%m/', blank=True, null=True, validators=[validate_group_photo],
		help_text="Shown as the group's icon. Study groups without one get a photo for their subject.")
	cover = models.ImageField('Cover photo', upload_to='group_covers/%Y/%m/', blank=True, null=True, validators=[validate_group_photo],
		help_text="The wide background photo at the top of the group's page.")
	invite_code = models.CharField(max_length=24, unique=True, default=new_invite_code, editable=False)
	conversation = models.OneToOneField('chat.Conversation', on_delete=models.SET_NULL, null=True, blank=True, related_name='study_group')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']
		verbose_name = 'group'

	def __str__(self):
		return self.title

	def get_absolute_url(self):
		return reverse('group_detail', args=[self.pk])

	@property
	def title(self):
		return f'{self.course_code} · {self.name}' if self.course_code else self.name

	# A free Pexels photo per group type for the banner on the group's page
	# (loaded from Pexels; nothing is stored here).
	TYPE_PHOTOS = {
		'academic': 574077,       # code on a laptop by books
		'project': 3184292,       # a team working around a table
		'departmental': 2305098,  # red-brick university building
		'hostel': 5965612,        # student by a university building
		'social': 6147001,        # students together outdoors
		'professional': 30688592, # business meeting in a Lagos office
	}

	@property
	def rule_list(self):
		return [r for r in (' '.join(line.split()) for line in (self.rules or '').splitlines()) if r]

	@property
	def banner_url(self):
		pid = self.TYPE_PHOTOS.get(self.group_type, self.TYPE_PHOTOS['academic'])
		return f'https://images.pexels.com/photos/{pid}/pexels-photo-{pid}.jpeg?auto=compress&cs=tinysrgb&w=1260&h=420&fit=crop'

	def _photo_id(self):
		"""The Pexels photo for this group: by subject for study groups, by type for others."""
		if self.group_type != self.ACADEMIC:
			return self.TYPE_PHOTOS.get(self.group_type, self.TYPE_PHOTOS['academic'])
		prefix = ''.join(ch for ch in (self.course_code or '').upper() if ch.isalpha())
		name = (self.name or '').lower()
		for words, prefixes, pid in SUBJECT_PHOTOS:
			if any(w in name for w in words) or (prefix and any(prefix.startswith(p) for p in prefixes)):
				return pid
		return STUDY_PHOTO

	@property
	def icon_url(self):
		"""The group's photo (its round picture), or a Pexels photo for the subject/type."""
		return self.photo.url if self.photo else pexels(self._photo_id())

	@property
	def icon_full_url(self):
		"""A bigger copy of the round picture, for viewing it full screen."""
		return self.photo.url if self.photo else pexels(self._photo_id(), w=1000, h=1000)

	@property
	def cover_full_url(self):
		"""The cover photo at full width, for viewing it full screen."""
		return self.cover.url if self.cover else pexels(self._photo_id(), w=1920, h=640)

	@property
	def cover_url(self):
		"""The group's cover (background) photo, or a wide Pexels photo for the subject/type."""
		return self.cover.url if self.cover else pexels(self._photo_id(), w=1260, h=420)

	@property
	def gradient(self):
		"""(from, to) colours for this group's tiles and page (studygroups/dashboard.py GRADIENTS)."""
		from .dashboard import GRADIENTS
		return GRADIENTS[self.pk % len(GRADIENTS)] if self.pk else GRADIENTS[0]

	@property
	def type_info(self):
		return self.TYPE_INFO.get(self.group_type, self.TYPE_INFO[self.ACADEMIC])

	@property
	def privacy_icon(self):
		return self.PRIVACY_INFO[self.privacy][0]

	@property
	def privacy_help(self):
		return self.PRIVACY_INFO[self.privacy][1]

	@property
	def mode_icon(self):
		return self.MODE_ICONS.get(self.mode, 'bi-people')

	@property
	def member_count(self):
		n = getattr(self, 'n_members', None)
		return n if n is not None else self.members.filter(status=StudyGroupMember.ACTIVE).count()

	@property
	def is_full(self):
		return bool(self.max_members) and self.member_count >= self.max_members

	@property
	def spots_left(self):
		return max(0, self.max_members - self.member_count) if self.max_members else None


class StudyGroupMember(models.Model):
	OWNER, ADMIN, MEMBER = 'owner', 'admin', 'member'
	ROLE_CHOICES = [(OWNER, 'Owner'), (ADMIN, 'Admin'), (MEMBER, 'Member')]
	ACTIVE, PENDING = 'active', 'pending'
	STATUS_CHOICES = [(ACTIVE, 'Member'), (PENDING, 'Requested to join')]

	group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name='members')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='study_group_memberships')
	role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=MEMBER)
	status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
	joined_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		unique_together = ('group', 'user')
		ordering = ['joined_at']

	@property
	def is_active(self):
		return self.status == self.ACTIVE

	@property
	def is_admin(self):
		"""Owner or admin (and actually in the group)."""
		return self.is_active and self.role in (self.OWNER, self.ADMIN)


def validate_upload_size(value, limit_mb=25):
	if value.size > limit_mb * 1024 * 1024:
		raise ValidationError(f'Files must be smaller than {limit_mb}MB.')


def validate_photo_size(value):
	validate_upload_size(value, limit_mb=8)


class GroupPost(models.Model):
	"""A post in a group's Posts tab. Announcements (admins only) are pinned
	to the top and notify every member. A post with options is a poll; its
	text is the question."""
	group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name='posts')
	author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='group_posts')
	title = models.CharField(max_length=150, blank=True, help_text='e.g. COS 401 Assignment 2: Instructions and Questions')
	body = models.TextField(max_length=5000, blank=True)
	image = models.ImageField(upload_to='group_posts/%Y/%m/', blank=True, null=True,
		validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'gif', 'webp']), validate_photo_size])
	is_announcement = models.BooleanField(default=False)
	pinned = models.BooleanField(default=False)
	poll_multiple = models.BooleanField(default=False)
	poll_closed = models.BooleanField(default=False)
	is_edited = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-pinned', '-created_at']

	@property
	def heading(self):
		"""The title, or the first line of the text (for cards and chat links)."""
		return self.title or ' '.join((self.body or '').split('\n')[0].split())[:90] or 'Post'

	def __str__(self):
		return f'{self.author} in {self.group}: {self.body[:40]}'


class GroupPostBookmark(models.Model):
	"""A member saving a post to find it again (Posts tab > Saved, and Bookmarks > Groups)."""
	post = models.ForeignKey(GroupPost, on_delete=models.CASCADE, related_name='bookmarks')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='group_post_bookmarks')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		unique_together = ('post', 'user')
		ordering = ['-created_at']


class GroupPostLike(models.Model):
	post = models.ForeignKey(GroupPost, on_delete=models.CASCADE, related_name='likes')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')

	class Meta:
		unique_together = ('post', 'user')


class GroupComment(models.Model):
	"""A comment on a group post, shown in the same comments sheet as Home posts:
	replies (one level: a reply to a reply joins the same thread), likes, edit."""
	post = models.ForeignKey(GroupPost, on_delete=models.CASCADE, related_name='comments')
	author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='group_comments')
	parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')
	body = models.TextField(max_length=1000)
	is_edited = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['created_at']


class GroupCommentLike(models.Model):
	comment = models.ForeignKey(GroupComment, on_delete=models.CASCADE, related_name='likes')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')

	class Meta:
		constraints = [models.UniqueConstraint(fields=['comment', 'user'], name='unique_group_comment_like')]


class GroupPollOption(models.Model):
	post = models.ForeignKey(GroupPost, on_delete=models.CASCADE, related_name='options')
	text = models.CharField(max_length=100)
	position = models.PositiveSmallIntegerField(default=0)

	class Meta:
		ordering = ['position', 'pk']


class GroupPollVote(models.Model):
	option = models.ForeignKey(GroupPollOption, on_delete=models.CASCADE, related_name='votes')
	post = models.ForeignKey(GroupPost, on_delete=models.CASCADE, related_name='votes')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')

	class Meta:
		unique_together = ('option', 'user')


VIDEO_EXTENSIONS = ['mp4', 'webm', 'mov']
FILE_EXTENSIONS = ['pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'csv', 'txt', 'md', 'rtf', 'odt', 'odp', 'ods',
	'zip', 'rar', '7z', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'py', 'java', 'c', 'cpp', 'js', 'html', 'css', 'sql', 'ipynb'] + VIDEO_EXTENSIONS


class GroupFile(models.Model):
	"""Lecture notes, slides, past questions... Only members can download
	them (studygroups/views.py file_download checks before sending)."""
	ICONS = {'pdf': 'bi-file-earmark-pdf', 'doc': 'bi-file-earmark-word', 'docx': 'bi-file-earmark-word', 'odt': 'bi-file-earmark-word',
		'rtf': 'bi-file-earmark-word', 'ppt': 'bi-file-earmark-ppt', 'pptx': 'bi-file-earmark-ppt', 'odp': 'bi-file-earmark-ppt',
		'xls': 'bi-file-earmark-excel', 'xlsx': 'bi-file-earmark-excel', 'ods': 'bi-file-earmark-excel', 'csv': 'bi-file-earmark-spreadsheet',
		'zip': 'bi-file-earmark-zip', 'rar': 'bi-file-earmark-zip', '7z': 'bi-file-earmark-zip', 'png': 'bi-file-earmark-image',
		'jpg': 'bi-file-earmark-image', 'jpeg': 'bi-file-earmark-image', 'gif': 'bi-file-earmark-image', 'webp': 'bi-file-earmark-image',
		'txt': 'bi-file-earmark-text', 'md': 'bi-file-earmark-text',
		'mp4': 'bi-file-earmark-play', 'webm': 'bi-file-earmark-play', 'mov': 'bi-file-earmark-play'}

	group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name='files')
	# Attached to a post (it also shows in the Files tab, as the same file).
	post = models.ForeignKey(GroupPost, on_delete=models.CASCADE, null=True, blank=True, related_name='attachments')
	# Shared in a study session's notes (it also shows in the Files tab).
	session_note = models.ForeignKey('SessionNote', on_delete=models.CASCADE, null=True, blank=True, related_name='files')
	uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='group_files')
	file = models.FileField(upload_to='group_files/%Y/%m/', validators=[FileExtensionValidator(FILE_EXTENSIONS), validate_upload_size])
	name = models.CharField(max_length=150)
	size = models.PositiveIntegerField(default=0)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']

	def __str__(self):
		return self.name

	@property
	def extension(self):
		return os.path.splitext(self.name)[1].lstrip('.').lower()

	@property
	def icon(self):
		return self.ICONS.get(self.extension, 'bi-file-earmark' if self.extension not in ('py', 'java', 'c', 'cpp', 'js', 'html', 'css', 'sql', 'ipynb') else 'bi-file-earmark-code')

	@property
	def is_video(self):
		return self.extension in VIDEO_EXTENSIONS

	@property
	def is_image(self):
		return self.extension in ('png', 'jpg', 'jpeg', 'gif', 'webp')

	@property
	def kind(self):
		e = self.extension
		if e in VIDEO_EXTENSIONS:
			return 'video'
		return 'pdf' if e == 'pdf' else 'word' if 'word' in self.icon else 'ppt' if 'ppt' in self.icon else 'excel' if ('excel' in self.icon or 'spread' in self.icon) else 'image' if 'image' in self.icon else 'other'


class GroupSession(models.Model):
	"""A study session / meetup scheduled in a group (studygroups/sessions.py):
	when, where (a place, an online link, or both), and who's coming."""
	DURATIONS = [(30, '30 minutes'), (60, '1 hour'), (90, '1½ hours'), (120, '2 hours'), (180, '3 hours')]

	group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name='sessions')
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='group_sessions_created')
	title = models.CharField(max_length=100)
	starts_at = models.DateTimeField(db_index=True)
	duration = models.PositiveSmallIntegerField(choices=DURATIONS, default=60, help_text='Minutes')
	place = models.CharField(max_length=120, blank=True, help_text='e.g. Faculty library, 2nd floor')
	link = models.URLField(blank=True, help_text='Google Meet / Zoom link')
	notes = models.TextField(max_length=1000, blank=True)
	is_cancelled = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['starts_at']

	def __str__(self):
		return self.title

	@property
	def ends_at(self):
		from datetime import timedelta
		return self.starts_at + timedelta(minutes=self.duration)


class GroupSessionRSVP(models.Model):
	GOING, MAYBE, NO = 'going', 'maybe', 'no'
	CHOICES = [(GOING, 'Going'), (MAYBE, 'Maybe'), (NO, "Can't go")]
	session = models.ForeignKey(GroupSession, on_delete=models.CASCADE, related_name='rsvps')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='group_session_rsvps')
	status = models.CharField(max_length=6, choices=CHOICES, default=GOING)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['session', 'user'], name='one_rsvp_per_person')]


class SessionAttendance(models.Model):
	"""Who came to a study session (studygroups/sessions.py): people tick
	"I was there" themselves, and the organiser or an admin can mark anyone."""
	session = models.ForeignKey(GroupSession, on_delete=models.CASCADE, related_name='attendance')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sessions_attended')
	marked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['session', 'user'], name='attended_once')]


class SessionNote(models.Model):
	"""Notes shared after (or during) a session: what was covered, answers,
	photos of the board, slides. Files go in GroupFile.session_note."""
	session = models.ForeignKey(GroupSession, on_delete=models.CASCADE, related_name='notes_shared')
	author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='session_notes')
	body = models.TextField(max_length=3000, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['created_at']
