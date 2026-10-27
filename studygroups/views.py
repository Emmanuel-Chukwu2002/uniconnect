"""Group pages (templates/studygroups/). See models.py for what a group is.

    /groups/                              Discover / My groups, search, type chips, "Only my department"
    /groups/new/                          start a group (you become its owner)
    /groups/invite/<code>/                invite link: preview, then Join (POST)
    /groups/<id>/?tab=posts|sessions|files|members|about
    The group's chat lives in Messages (/messages/c/<conversation>/): the page's
    Chat button opens it there, and old ?tab=chat links are sent there too.
    /groups/<id>/chat/seen/  chat/search/  JSON for the Chat tab
    /groups/<id>/edit/  delete/           owner (edit: admins too)
    /groups/<id>/join/                    POST: join a public group, or ask to join a private one
    /groups/<id>/leave/                   POST: leave, or cancel your request
    /groups/<id>/open/                    POST, admins: stop / start accepting members
    /groups/<id>/invite/reset/            POST, admins: new invite link (the old one stops working)
    /groups/<id>/members/<m>/<action>/    POST, admins: approve, decline, remove, make_admin, remove_admin
    /groups/<id>/posts/new/               POST, members: post, poll, or (admins) announcement
    /groups/<id>/posts/<p>/like|comment|vote|pin|close|delete/
    /groups/<id>/comments/<c>/delete/
    /groups/<id>/files/upload/            POST, members
    /groups/<id>/files/<f>/  delete/      download (members only) / delete

Who sees what: public and private groups are listed for students of the
group's university; invite-only groups are only seen by their members.
Posts, files and the group chat are for members only.
"""
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from feed.models import Notification as N
from feed.notifications import notify, unnotify
from . import chat
from .forms import GroupFileForm, GroupPostForm, StudyGroupForm
from .models import (GroupComment, GroupCommentLike, GroupFile, GroupPollOption, GroupPollVote, GroupPost, GroupPostBookmark, GroupPostLike,
	StudyGroup, StudyGroupMember as M)

POST_FILTERS = [('', 'All'), ('announcements', 'Announcements'), ('files', 'With files'), ('polls', 'Polls'),
	('saved', 'Saved'), ('mine', 'Mine')]
MAX_POST_FILES = 6

TABS = [('discover', 'Discover'), ('mine', 'My groups')]
POST_LIMIT = 100
INLINE_FILES = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'txt'}


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _student(request):
	student = getattr(request.user, 'student_profile', None)
	if student is None:
		raise Http404('Only students can use groups.')
	return student


def _ajax(request):
	return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _load(request, pk):
	"""(group, my membership or None). 404 if the viewer may not see it."""
	student = _student(request)
	group = get_object_or_404(StudyGroup.objects.select_related('created_by', 'department', 'level', 'university'), pk=pk)
	me = M.objects.filter(group=group, user=request.user).first()
	if me is None and (group.university_id != student.university_id or group.privacy == StudyGroup.INVITE):
		raise Http404
	return group, me


def _member(request, pk):
	group, me = _load(request, pk)
	if not (me and me.is_active):
		raise Http404
	return group, me


def _admin(request, pk):
	group, me = _member(request, pk)
	if not me.is_admin:
		raise Http404
	return group, me


def _owner(request, pk):
	group, me = _member(request, pk)
	if me.role != M.OWNER:
		raise Http404
	return group, me


def _active_count(group):
	return group.members.filter(status=M.ACTIVE).count()


def _admins(group):
	return [m.user for m in group.members.filter(status=M.ACTIVE, role__in=[M.OWNER, M.ADMIN]).select_related('user')]


def _tab_url(group, tab, anchor=''):
	return f"{reverse('group_detail', args=[group.pk])}?tab={tab}{anchor}"


def _name(user):
	return user.get_full_name() or user.username


def _add_member(group, user, role=M.MEMBER):
	"""Adds `user` as an active member (and to the group chat)."""
	m, _ = M.objects.update_or_create(group=group, user=user, defaults={'status': M.ACTIVE, 'role': role})
	chat.add_member(group, user)
	return m


def _with_counts(qs):
	return qs.annotate(n_members=Count('members', filter=Q(members__status=M.ACTIVE), distinct=True))


# ---------------------------------------------------------------------
# List
# ---------------------------------------------------------------------
@login_required
def index(request):
	student = _student(request)
	tab = request.GET.get('tab', 'discover')
	if tab not in dict(TABS):
		tab = 'discover'
	kind = request.GET.get('type', '')
	if kind not in StudyGroup.TYPE_INFO:
		kind = ''
	q = ' '.join(request.GET.get('q', '').split())[:60]
	mine_only = request.GET.get('dept') == '1'

	states = dict(M.objects.filter(user=request.user).values_list('group_id', 'status'))
	my_ids = {gid for gid, s in states.items() if s == M.ACTIVE}
	if tab == 'mine':
		qs = StudyGroup.objects.filter(pk__in=my_ids)
	else:
		qs = StudyGroup.objects.filter(university=student.university).exclude(privacy=StudyGroup.INVITE)
	qs = _with_counts(qs.select_related('department', 'level'))
	if kind:
		qs = qs.filter(group_type=kind)
	if mine_only:
		qs = qs.filter(Q(department=student.department) | Q(department__isnull=True))
	for word in q.split():
		qs = qs.filter(Q(course_code__icontains=word) | Q(course_code__icontains=word.replace(' ', ''))
			| Q(name__icontains=word) | Q(description__icontains=word))
	ctx = {'tab': tab, 'tabs': TABS, 'q': q, 'mine_only': mine_only, 'kind': kind,
		'types': StudyGroup.TYPES, 'my_count': len(my_ids), 'student': student,
		'see_all': f'type={kind}&' if kind else ''}
	if tab == 'discover' and not q and not mine_only:
		# "Recommended for you" on top (recommendations/engine.py), then
		# closest first, in sections of cards (studygroups/discover.py).
		if not kind:
			from recommendations.engine import recommend
			ctx['recs'] = recommend(request.user, 'group', limit=8)
		from feed.closeness import SECTION_PAGE, overview
		from . import discover
		parts = discover.sections(student, request.user, kind)
		joined = _with_counts(StudyGroup.objects.filter(pk__in=my_ids).select_related('department', 'level')).order_by('-created_at')
		if kind:
			joined = joined.filter(group_type=kind)
		joined = discover.prepare(joined, request.user)
		if joined:   # your own groups first, so one you just made is easy to find
			parts.insert(0, ('mine', 'Your groups', "Groups you're in", joined))
		one = next((p for p in parts if p[0] == request.GET.get('section')), None)
		if one is None:
			return render(request, 'studygroups/index.html', dict(ctx, groups=overview(parts)))
		page = Paginator(one[3], SECTION_PAGE).get_page(request.GET.get('page'))
		return render(request, 'studygroups/index.html', dict(ctx, page=page, items=list(page),
			section={'key': one[0], 'title': one[1], 'sub': one[2]}, total=len(one[3])))
	if tab == 'discover':
		# Your department first, then groups with room, then newest.
		qs = sorted(qs.order_by('-is_open', '-created_at'),
			key=lambda g: (g.department_id != student.department_id, bool(g.max_members) and g.n_members >= g.max_members))
	else:
		qs = qs.order_by('-created_at')
	from feed.closeness import SECTION_PAGE
	from .discover import prepare
	page = Paginator(qs, SECTION_PAGE).get_page(request.GET.get('page'))
	return render(request, 'studygroups/index.html', dict(ctx, page=page, items=prepare(page, request.user)))


# ---------------------------------------------------------------------
# A group
# ---------------------------------------------------------------------
def _prepare_posts(posts, user, roles):
	"""Adds to each post: like count and mine, comments, poll results."""
	posts = list(posts)
	ids = [p.pk for p in posts]
	if not ids:
		return posts
	likes = dict(GroupPostLike.objects.filter(post_id__in=ids).values('post_id').annotate(n=Count('id')).values_list('post_id', 'n'))
	liked = set(GroupPostLike.objects.filter(post_id__in=ids, user=user).values_list('post_id', flat=True))
	# Comments as threads (top-level comments with .reply_list), with like counts — the Home comments sheet look.
	all_comments = list(GroupComment.objects.filter(post_id__in=ids).select_related('author', 'author__student_profile'))
	c_ids = [c.pk for c in all_comments]
	c_likes = dict(GroupCommentLike.objects.filter(comment_id__in=c_ids).values('comment_id').annotate(n=Count('id')).values_list('comment_id', 'n'))
	c_liked = set(GroupCommentLike.objects.filter(comment_id__in=c_ids, user=user).values_list('comment_id', flat=True))
	comments, n_comments, by_id = {}, {}, {c.pk: c for c in all_comments}
	for c in all_comments:
		c.likes_count = c_likes.get(c.pk, 0)
		c.user_has_liked = c.pk in c_liked
		c.reply_list = []
		n_comments[c.post_id] = n_comments.get(c.post_id, 0) + 1
	for c in all_comments:
		if c.parent_id and c.parent_id in by_id:
			by_id[c.parent_id].reply_list.append(c)
		else:
			comments.setdefault(c.post_id, []).append(c)
	options = {}
	for o in GroupPollOption.objects.filter(post_id__in=ids).annotate(n=Count('votes')):
		options.setdefault(o.post_id, []).append(o)
	my_votes = set(GroupPollVote.objects.filter(post_id__in=ids, user=user).values_list('option_id', flat=True))
	voters = dict(GroupPollVote.objects.filter(post_id__in=ids).values('post_id').annotate(n=Count('user', distinct=True)).values_list('post_id', 'n'))
	saved = set(GroupPostBookmark.objects.filter(post_id__in=ids, user=user).values_list('post_id', flat=True))
	files = {}
	for f in GroupFile.objects.filter(post_id__in=ids).order_by('pk'):
		files.setdefault(f.post_id, []).append(f)
	for p in posts:
		p.i_saved = p.pk in saved
		p.files = files.get(p.pk, [])
		p.videos = [f for f in p.files if f.is_video]
		p.photos = [f for f in p.files if f.is_image]
		p.docs = [f for f in p.files if not f.is_video and not f.is_image]
		p.like_count = likes.get(p.pk, 0)
		p.i_liked = p.pk in liked
		p.comment_list = comments.get(p.pk, [])
		p.comment_count = n_comments.get(p.pk, 0)
		p.author_role = roles.get(p.author_id, '')
		p.poll = options.get(p.pk, [])
		if p.poll:
			total = sum(o.n for o in p.poll)
			p.voters = voters.get(p.pk, 0)
			p.voted = False
			top = max(o.n for o in p.poll)
			for o in p.poll:
				o.mine = o.pk in my_votes
				p.voted = p.voted or o.mine
				o.percent = round(100 * o.n / total) if total else 0
				o.leading = bool(total) and o.n == top
	return posts


def _post_card_context(request, group, me, post):
	roles = dict(group.members.filter(status=M.ACTIVE).values_list('user_id', 'role'))
	post = _prepare_posts([post], request.user, roles)[0]
	return {'post': post, 'group': group, 'me': me}


def _files_count(group):
	n = group.files.count()
	if group.conversation_id:
		from chat.models import Message
		n += Message.objects.filter(conversation_id=group.conversation_id, is_deleted=False,
			kind__in=[Message.FILE, Message.IMAGE, Message.VIDEO]).exclude(attachment='').count()
	return n


class _LibraryItem:
	"""One entry in the Files tab: an uploaded file, a post's attachment, or a
	file sent in the chat (shown from where it is — never copied)."""
	def __init__(self, name, size, url, by, at, source, file=None, post_id=None):
		self.name, self.size, self.url, self.by, self.at, self.source = name, size, url, by, at, source
		self.file, self.post_id = file, post_id
		self.extension = os.path.splitext(name)[1].lstrip('.').lower()
		probe = GroupFile(name=name)
		self.icon, self.kind = probe.icon, probe.kind


def _library(request, group):
	src = request.GET.get('from') if request.GET.get('from') in ('uploads', 'posts', 'chat') else ''
	items = []
	for f in group.files.select_related('uploaded_by'):
		source = 'posts' if f.post_id else 'uploads'
		items.append(_LibraryItem(f.name, f.size, reverse('group_file', args=[group.pk, f.pk]), f.uploaded_by, f.created_at,
			source, file=f, post_id=f.post_id))
	if group.conversation_id:
		from chat.models import Message
		for m in (Message.objects.filter(conversation_id=group.conversation_id, is_deleted=False,
				kind__in=[Message.FILE, Message.IMAGE, Message.VIDEO]).exclude(attachment='').select_related('sender')):
			items.append(_LibraryItem(m.attachment_name or os.path.basename(m.attachment.name), m.attachment_size,
				m.attachment.url, m.sender, m.created_at, 'chat'))
	counts = {k: sum(1 for i in items if i.source == k) for k in ('uploads', 'posts', 'chat')}
	if src:
		items = [i for i in items if i.source == src]
	q = ' '.join((request.GET.get('q') or '').split())[:80].lower()
	if q:
		items = [i for i in items if all(w in i.name.lower() for w in q.split())]
	items.sort(key=lambda i: i.at, reverse=True)
	return {'files': items, 'file_source': src, 'file_q': q, 'file_counts': counts, 'library_total': sum(counts.values())}


@login_required
def detail(request, pk):
	group, me = _load(request, pk)
	member = bool(me and me.is_active)
	tabs = ([('posts', 'Posts')] if group.show_posts else []) + [('files', 'Files'), ('members', 'Members'), ('about', 'About')] if member else \
		[('about', 'About')] + ([('members', 'Members')] if group.privacy == StudyGroup.PUBLIC else [])
	if member and group.conversation_id and request.GET.get('tab') == 'chat':
		# The group chat is in Messages now; old links (?tab=chat, ?m=<message>) go there.
		url = reverse('chat_conversation', args=[group.conversation_id])
		m = request.GET.get('m', '')
		return redirect(url + (f'?m={m}' if m.isdigit() else ''))
	if member:
		tabs.insert(int(group.show_posts), ('sessions', 'Sessions'))   # study sessions (sessions.py)
	tab = request.GET.get('tab') or tabs[0][0]
	if tab not in dict(tabs):
		tab = tabs[0][0]

	all_members = list(group.members.select_related('user', 'user__student_profile', 'user__student_profile__department',
		'user__student_profile__level', 'user__student_profile__university'))
	active = [m for m in all_members if m.is_active]
	order = {M.OWNER: 0, M.ADMIN: 1, M.MEMBER: 2}
	active.sort(key=lambda m: (order[m.role], m.joined_at))
	context = {
		'group': group, 'me': me, 'member': member, 'tab': tab, 'tabs': tabs,
		'count': len(active), 'faces': active[:4], 'more_faces': max(0, len(active) - 4),
		'full': bool(group.max_members) and len(active) >= group.max_members,
		'is_admin': bool(me and me.is_admin),
		'pending_count': sum(1 for m in all_members if not m.is_active) if me and me.is_admin else 0,
		'files_count': _files_count(group) if member else 0,
	}
	if member:
		context['announcements_count'] = group.posts.filter(is_announcement=True).count()
		context['chips'] = [c for c in (group.type_info['label'], 'Course Group' if group.course_code else '',
			group.level.name if group.level else '') if c]
		if group.conversation_id:
			from chat import services as chat_services
			from chat.models import ConversationParticipant
			chat_services.unmute_expired(request.user)
			part = ConversationParticipant.objects.filter(conversation_id=group.conversation_id, user=request.user).first()
			context['chat_url'] = reverse('chat_conversation', args=[group.conversation_id])
			context['chat_unread'] = chat_services.unread_for(part) if part else 0
			context['chat_muted'] = bool(part and part.is_muted)
			context['chat_muted_until'] = part.muted_until if context['chat_muted'] else None
	if member:
		from . import sessions as SS
		context['next_session'] = SS.next_session(group)
	if tab == 'sessions':
		from . import sessions as SS
		context['upcoming'], context['past'] = SS.for_group(group, request.user)
		SS.prepare(context['upcoming'] + context['past'], request.user, me)
		context['durations'] = SS.S.DURATIONS
		from django.utils import timezone as tz
		context['today'] = tz.localdate().isoformat()
	if tab == 'posts':
		roles = {m.user_id: m.role for m in active}
		posts_qs = group.posts.select_related('author', 'author__student_profile')
		# Finding discussions: words, and a filter.
		show = request.GET.get('show') if request.GET.get('show') in dict(POST_FILTERS) else ''
		q = ' '.join((request.GET.get('q') or '').split())[:80]
		if show == 'announcements':
			posts_qs = posts_qs.filter(is_announcement=True)
		elif show == 'files':
			posts_qs = posts_qs.filter(Q(attachments__isnull=False) | Q(image__gt='')).distinct()
		elif show == 'polls':
			posts_qs = posts_qs.filter(options__isnull=False).distinct()
		elif show == 'saved':
			posts_qs = posts_qs.filter(bookmarks__user=request.user)
		elif show == 'mine':
			posts_qs = posts_qs.filter(author=request.user)
		for word in q.split():
			posts_qs = posts_qs.filter(Q(title__icontains=word) | Q(body__icontains=word) | Q(comments__body__icontains=word)
				| Q(attachments__name__icontains=word)).distinct()
		context.update(show=show, q=q, post_filters=POST_FILTERS, only_announcements=show == 'announcements')
		context['posts'] = _prepare_posts(posts_qs[:POST_LIMIT], request.user, roles)
		# "Make a post" from a chat message: its text starts the composer.
		from_msg = request.GET.get('from_msg')
		if str(from_msg or '').isdigit() and group.conversation_id:
			from chat.models import Message
			m = Message.objects.filter(pk=int(from_msg), conversation_id=group.conversation_id, is_deleted=False).first()
			if m:
				context['prefill'] = m.content
		context['post_form'] = GroupPostForm(can_announce=me.is_admin)
		context['option_slots'] = range(1, 7)
	elif tab == 'files':
		context.update(_library(request, group))
	elif tab == 'members':
		context['members'] = active
		if me and me.is_admin:
			context['requests'] = [m for m in all_members if not m.is_active]
	else:
		context['admins'] = [m for m in active if m.role in (M.OWNER, M.ADMIN)]
		context['type_info'] = group.type_info
	if me and me.is_admin:
		context['invite_url'] = request.build_absolute_uri(reverse('group_invite', args=[group.invite_code]))
	return render(request, 'studygroups/detail.html', context)


# ---------------------------------------------------------------------
# The Chat tab (static/js/group-chat.js). Sending, reactions, replies and
# live updates use Messages' own WebSocket and upload address; these two
# only read.
# ---------------------------------------------------------------------
@login_required
def chat_seen(request, pk):
	"""When each other member last read the chat (for "Seen by N" under your messages)."""
	group, _ = _member(request, pk)
	from chat.models import ConversationParticipant
	reads = {}
	if group.conversation_id:
		for uid, at in (ConversationParticipant.objects.filter(conversation_id=group.conversation_id)
				.exclude(user=request.user).values_list('user_id', 'last_read_receipt_at')):
			reads[str(uid)] = at.isoformat() if at else None
	return JsonResponse({'reads': reads})


@login_required
def chat_search(request, pk):
	"""Messages in the group chat containing these words (newest first)."""
	group, _ = _member(request, pk)
	from chat import services as S
	from chat.models import Message
	q = ' '.join((request.GET.get('q') or '').split())[:80]
	if not q or not group.conversation_id:
		return JsonResponse({'results': []})
	qs = Message.objects.filter(conversation_id=group.conversation_id, is_deleted=False).exclude(kind=Message.SYSTEM)
	for word in q.split():
		qs = qs.filter(Q(content__icontains=word) | Q(attachment_name__icontains=word))
	found = qs.select_related('sender', 'sender__student_profile', 'reply_to__sender').prefetch_related('reactions').order_by('-created_at')[:30]
	return JsonResponse({'results': [S.serialize_message(m) for m in found]})


# ---------------------------------------------------------------------
# Create / edit / delete
# ---------------------------------------------------------------------
@login_required
def create(request):
	student = _student(request)
	initial = {'group_type': request.GET.get('type') if request.GET.get('type') in StudyGroup.TYPE_INFO else StudyGroup.ACADEMIC}
	if request.GET.get('code'):   # "Start a study group for COS 401" in Course Companion
		initial.update(course_code=request.GET['code'][:20], group_type=StudyGroup.ACADEMIC, name='Study group')
	# Hostel and social groups start with just Chat and Files (Posts can be switched on).
	initial['show_posts'] = initial['group_type'] not in (StudyGroup.HOSTEL, StudyGroup.SOCIAL)
	form = StudyGroupForm(request.POST or None, request.FILES or None, student=student, initial=initial)
	if request.method == 'POST' and form.is_valid():
		with transaction.atomic():
			group = form.save(commit=False)
			group.university, group.created_by, group.department = student.university, request.user, student.department
			group.save()
			M.objects.create(group=group, user=request.user, role=M.OWNER)
		chat.create_chat(group)
		messages.success(request, 'Group created. Its group chat is in Messages.')
		return redirect(group)
	return render(request, 'studygroups/form.html', {'form': form, 'editing': False, 'types': StudyGroup.TYPES,
		'privacy_info': StudyGroup.PRIVACY_INFO})


@login_required
def edit(request, pk):
	group, me = _admin(request, pk)
	form = StudyGroupForm(request.POST or None, request.FILES or None, instance=group, student=_student(request))
	if request.method == 'POST' and form.is_valid():
		form.save()
		chat.rename(group)
		messages.success(request, 'Group updated.')
		return redirect(group)
	return render(request, 'studygroups/form.html', {'form': form, 'editing': True, 'group': group, 'types': StudyGroup.TYPES,
		'privacy_info': StudyGroup.PRIVACY_INFO, 'is_owner': me.role == M.OWNER})


@login_required
@require_POST
def delete(request, pk):
	group, _ = _owner(request, pk)
	conv = group.conversation
	if conv is not None:
		try:
			chat._say(conv, 'The group was deleted. This chat stays so you keep your messages.')
		except Exception:
			pass
	group.delete()
	messages.success(request, 'Group deleted.')
	return redirect('groups')


# ---------------------------------------------------------------------
# Joining and leaving
# ---------------------------------------------------------------------
def _join(request, group, by_invite=False):
	"""Joins (or asks to join) `group`; returns the message to show."""
	with transaction.atomic():
		locked = StudyGroup.objects.select_for_update().get(pk=group.pk)
		existing = M.objects.filter(group=locked, user=request.user).first()
		if existing and existing.is_active:
			return None
		if not by_invite and not locked.is_open:
			raise ValueError("This group isn't taking new members right now.")
		if locked.max_members and _active_count(locked) >= locked.max_members:
			raise ValueError('Sorry — this group is full.')
		if locked.privacy == StudyGroup.PRIVATE and not by_invite:
			if existing:
				return 'Your request is waiting for an admin.'
			M.objects.create(group=locked, user=request.user, status=M.PENDING)
			pending = True
		else:
			pending = False
			if existing:   # a pending request, now let in by the invite link
				existing.status = M.ACTIVE
				existing.save(update_fields=['status'])
			else:
				M.objects.create(group=locked, user=request.user)
	if pending:
		for admin in _admins(group):
			notify(admin, request.user, N.GROUP_REQUEST, study_group=group, replace=True)
		return 'Request sent — an admin will review it.'
	chat.add_member(group, request.user)
	for admin in _admins(group):
		unnotify(admin, request.user, N.GROUP_REQUEST, study_group=group)
	return f'You joined {group.title}. Say hello in the group chat!'


@login_required
@require_POST
def join(request, pk):
	group, me = _load(request, pk)
	if _ajax(request):   # Join buttons on the Explore page
		try:
			msg = _join(request, group)
		except ValueError as e:
			return JsonResponse({'error': str(e)}, status=400)
		state = M.objects.filter(group=group, user=request.user).values_list('status', flat=True).first()
		return JsonResponse({'state': 'joined' if state == M.ACTIVE else 'requested', 'message': msg or ''})
	try:
		msg = _join(request, group)
	except ValueError as e:
		messages.error(request, str(e))
	else:
		if msg:
			messages.success(request, msg)
	return redirect(group)


@login_required
def invite(request, code):
	"""The invite link. Works for any signed-in student, from any university."""
	_student(request)
	group = get_object_or_404(_with_counts(StudyGroup.objects.select_related('university', 'created_by')), invite_code=code)
	me = M.objects.filter(group=group, user=request.user).first()
	if me and me.is_active:
		return redirect(group)
	if request.method == 'POST':
		try:
			msg = _join(request, group, by_invite=True)
		except ValueError as e:
			messages.error(request, str(e))
			return redirect('group_invite', code=code)
		if msg:
			messages.success(request, msg)
		return redirect(group)
	return render(request, 'studygroups/invite.html', {
		'group': group, 'full': bool(group.max_members) and group.n_members >= group.max_members,
	})


@login_required
@require_POST
def leave(request, pk):
	group, me = _load(request, pk)
	if me is None:
		return redirect(group if group.privacy != StudyGroup.INVITE else 'groups')
	if me.role == M.OWNER:
		messages.error(request, "You started this group, so you can't leave it — delete it instead.")
		return redirect(group)
	was_active = me.is_active
	me.delete()
	if was_active:
		chat.remove_member(group, request.user)
		messages.success(request, f'You left {group.title}.')
	else:
		for admin in _admins(group):
			unnotify(admin, request.user, N.GROUP_REQUEST, study_group=group)
		messages.success(request, 'Request cancelled.')
	return redirect(group if group.privacy != StudyGroup.INVITE or not was_active else 'groups')


@login_required
@require_POST
def toggle_open(request, pk):
	group, _ = _admin(request, pk)
	group.is_open = not group.is_open
	group.save(update_fields=['is_open'])
	messages.success(request, 'Now accepting new members.' if group.is_open else 'No longer accepting new members.')
	return redirect(_tab_url(group, 'about'))


@login_required
@require_POST
def reset_invite(request, pk):
	group, _ = _admin(request, pk)
	from .models import new_invite_code
	group.invite_code = new_invite_code()
	group.save(update_fields=['invite_code'])
	messages.success(request, 'New invite link made. The old link no longer works.')
	return redirect(_tab_url(group, 'members'))


@login_required
@require_POST
def member_action(request, pk, member_id, action):
	group, me = _admin(request, pk)
	target = get_object_or_404(M.objects.select_related('user'), pk=member_id, group=group)
	back = _tab_url(group, 'members')
	name = _name(target.user)

	if action in ('approve', 'decline'):
		if target.is_active:
			raise Http404
		for admin in _admins(group):
			unnotify(admin, target.user, N.GROUP_REQUEST, study_group=group)
		if action == 'approve':
			if group.max_members and _active_count(group) >= group.max_members:
				messages.error(request, 'The group is full — raise the member limit first.')
				return redirect(back)
			target.status = M.ACTIVE
			target.save(update_fields=['status'])
			chat.add_member(group, target.user)
			notify(target.user, request.user, N.GROUP_ACCEPTED, study_group=group, replace=True)
			messages.success(request, f'{name} is now a member.')
		else:
			target.delete()
			messages.success(request, f"Declined {name}'s request.")
		return redirect(back)

	if target.user_id == request.user.pk or target.role == M.OWNER or not target.is_active:
		raise Http404
	if action == 'remove':
		if target.role == M.ADMIN and me.role != M.OWNER:
			messages.error(request, 'Only the owner can remove an admin.')
			return redirect(back)
		target.delete()
		chat.remove_member(group, target.user, removed=True)
		messages.success(request, f'Removed {name}.')
	elif action in ('make_admin', 'remove_admin'):
		if me.role != M.OWNER:
			raise Http404
		target.role = M.ADMIN if action == 'make_admin' else M.MEMBER
		target.save(update_fields=['role'])
		messages.success(request, f'{name} is now {"an admin" if target.role == M.ADMIN else "a member"}.')
	else:
		raise Http404
	return redirect(back)


# ---------------------------------------------------------------------
# Posts, announcements, polls
# ---------------------------------------------------------------------
@login_required
@require_POST
def post_create(request, pk):
	group, me = _member(request, pk)
	uploads = request.FILES.getlist('files')[:MAX_POST_FILES]
	form = GroupPostForm(request.POST, request.FILES, can_announce=me.is_admin, has_files=bool(uploads))
	checked = []
	for f in uploads:
		ff = GroupFileForm(files={'file': f})
		if not ff.is_valid():
			messages.error(request, f'{f.name}: {ff.errors["file"][0]}')
			return redirect(_tab_url(group, 'posts'))
		checked.append(ff)
	if not form.is_valid():
		errors = form.non_field_errors() or [e for errs in form.errors.values() for e in errs]
		messages.error(request, errors[0] if errors else 'Could not post that.')
		return redirect(_tab_url(group, 'posts'))
	with transaction.atomic():
		post = form.save(commit=False)
		post.group, post.author = group, request.user
		post.pinned = post.is_announcement
		post.save()
		for ff in checked:
			# Attached to the post, and listed in the Files tab too (the same file).
			obj = ff.save(commit=False)
			obj.group, obj.uploaded_by, obj.post = group, request.user, post
			obj.save()
		GroupPollOption.objects.bulk_create([GroupPollOption(post=post, text=t, position=i) for i, t in enumerate(form.options)])
	if post.is_announcement:
		for m in group.members.filter(status=M.ACTIVE).exclude(user=request.user).select_related('user', 'user__student_profile'):
			notify(m.user, request.user, N.GROUP_ANNOUNCEMENT, study_group=group, group_post=post)
		messages.success(request, 'Announcement posted and pinned. Members have been notified.')
	return redirect(_tab_url(group, 'posts', f'#p{post.pk}'))


def _post(group, post_id):
	return get_object_or_404(GroupPost.objects.select_related('author', 'author__student_profile'), pk=post_id, group=group)


def _card_response(request, group, me, post, anchor=True):
	if _ajax(request):
		from django.template.loader import render_to_string
		html = render_to_string('studygroups/_post.html', _post_card_context(request, group, me, post), request=request)
		return JsonResponse({'html': html})
	return redirect(_tab_url(group, 'posts', f'#p{post.pk}'))


@login_required
@require_POST
def post_like(request, pk, post_id):
	group, me = _member(request, pk)
	post = _post(group, post_id)
	like, created = GroupPostLike.objects.get_or_create(post=post, user=request.user)
	if not created:
		like.delete()
	if _ajax(request):
		return JsonResponse({'liked': created, 'count': post.likes.count()})
	return redirect(_tab_url(group, 'posts', f'#p{post.pk}'))


@login_required
@require_POST
def post_comment(request, pk, post_id):
	group, me = _member(request, pk)
	post = _post(group, post_id)
	body = (request.POST.get('body') or '').strip()[:1000]
	parent = None
	if request.POST.get('parent', '').isdigit():
		parent = GroupComment.objects.filter(pk=request.POST['parent'], post=post).first()
		if parent and parent.parent_id:   # one level of replies: a reply to a reply joins the same thread
			parent = parent.parent
	if body:
		GroupComment.objects.create(post=post, author=request.user, body=body, parent=parent)
	return _card_response(request, group, me, post)


@login_required
@require_POST
def comment_like(request, pk, comment_id):
	group, me = _member(request, pk)
	comment = get_object_or_404(GroupComment.objects.select_related('post'), pk=comment_id, post__group=group)
	like, created = GroupCommentLike.objects.get_or_create(comment=comment, user=request.user)
	if not created:
		like.delete()
	return _card_response(request, group, me, comment.post)


@login_required
@require_POST
def comment_edit(request, pk, comment_id):
	group, me = _member(request, pk)
	comment = get_object_or_404(GroupComment.objects.select_related('post'), pk=comment_id, post__group=group, author=request.user)
	body = (request.POST.get('body') or '').strip()[:1000]
	if body and body != comment.body:
		comment.body, comment.is_edited = body, True
		comment.save(update_fields=['body', 'is_edited'])
	return _card_response(request, group, me, comment.post)


@login_required
@require_POST
def comment_delete(request, pk, comment_id):
	group, me = _member(request, pk)
	comment = get_object_or_404(GroupComment.objects.select_related('post'), pk=comment_id, post__group=group)
	if comment.author_id != request.user.pk and not me.is_admin:
		raise Http404
	post = comment.post
	comment.delete()
	return _card_response(request, group, me, post)


@login_required
@require_POST
def post_vote(request, pk, post_id):
	group, me = _member(request, pk)
	post = _post(group, post_id)
	option = get_object_or_404(GroupPollOption, pk=request.POST.get('option') or 0, post=post)
	if post.poll_closed:
		if not _ajax(request):
			messages.error(request, 'This poll is closed.')
		return _card_response(request, group, me, post)
	with transaction.atomic():
		mine = GroupPollVote.objects.filter(option=option, user=request.user)
		if mine.exists():
			mine.delete()   # tapping your answer again takes the vote back
		else:
			if not post.poll_multiple:
				GroupPollVote.objects.filter(post=post, user=request.user).delete()
			GroupPollVote.objects.create(option=option, post=post, user=request.user)
	return _card_response(request, group, me, post)


@login_required
@require_POST
def post_close(request, pk, post_id):
	group, me = _member(request, pk)
	post = _post(group, post_id)
	if post.author_id != request.user.pk and not me.is_admin:
		raise Http404
	post.poll_closed = not post.poll_closed
	post.save(update_fields=['poll_closed'])
	return _card_response(request, group, me, post)


@login_required
@require_POST
def post_pin(request, pk, post_id):
	group, me = _admin(request, pk)
	post = _post(group, post_id)
	post.pinned = not post.pinned
	post.save(update_fields=['pinned'])
	messages.success(request, 'Pinned to the top.' if post.pinned else 'Unpinned.')
	return redirect(_tab_url(group, 'posts', f'#p{post.pk}'))


@login_required
@require_POST
def post_delete(request, pk, post_id):
	group, me = _member(request, pk)
	post = _post(group, post_id)
	if post.author_id != request.user.pk and not me.is_admin:
		raise Http404
	if post.image:
		post.image.delete(save=False)
	for f in post.attachments.all():
		f.file.delete(save=False)
	post.delete()
	messages.success(request, 'Post deleted.')
	return redirect(_tab_url(group, 'posts'))


@login_required
@require_POST
def post_edit(request, pk, post_id):
	"""Your own post: change its title and text (shows "Edited")."""
	group, me = _member(request, pk)
	post = _post(group, post_id)
	if post.author_id != request.user.pk:
		raise Http404
	title = ' '.join((request.POST.get('title') or '').split())[:150]
	body = (request.POST.get('body') or '').strip()[:5000]
	if not body and not title and not post.image and not post.attachments.exists():
		messages.error(request, "A post can't be empty.")
	elif (title, body) != (post.title, post.body):
		post.title, post.body, post.is_edited = title, body, True
		post.save(update_fields=['title', 'body', 'is_edited'])
		messages.success(request, 'Post updated.')
	return redirect(_tab_url(group, 'posts', f'#p{post.pk}'))


@login_required
@require_POST
def post_save(request, pk, post_id):
	"""Bookmark a post to find it again (Saved filter, and Bookmarks > Groups)."""
	group, me = _member(request, pk)
	post = _post(group, post_id)
	mark, created = GroupPostBookmark.objects.get_or_create(post=post, user=request.user)
	if not created:
		mark.delete()
	if _ajax(request):
		return JsonResponse({'saved': created})
	return redirect(_tab_url(group, 'posts', f'#p{post.pk}'))


@login_required
@require_POST
def post_share_chat(request, pk, post_id):
	"""Share a post into the group chat, so members can talk about it there."""
	group, me = _member(request, pk)
	post = _post(group, post_id)
	if not group.conversation_id:
		raise Http404
	from chat import services as S
	from chat.models import Message
	url = request.build_absolute_uri(_tab_url(group, 'posts', f'#p{post.pk}'))
	note = (request.POST.get('note') or '').strip()[:500]
	text = (note + '\n' if note else '') + f'📝 {post.heading}\n{url}'
	msg = S.create_message(group.conversation, request.user, Message.TEXT, text)
	S.broadcast_message(Message.objects.select_related('sender__student_profile').get(pk=msg.pk))
	S.push_unread_counts(group.conversation_id, exclude_user=request.user.pk)
	if _ajax(request):
		return JsonResponse({'ok': True, 'message': 'Shared in the group chat.'})
	messages.success(request, 'Shared in the group chat.')
	return redirect(_tab_url(group, 'chat'))


# ---------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------
@login_required
@require_POST
def file_upload(request, pk):
	group, me = _member(request, pk)
	uploads = request.FILES.getlist('file')[:10]
	if not uploads:
		messages.error(request, 'Choose a file to upload.')
		return redirect(_tab_url(group, 'files'))
	saved, errors = 0, []
	for f in uploads:
		form = GroupFileForm(files={'file': f})
		if form.is_valid():
			obj = form.save(commit=False)
			obj.group, obj.uploaded_by = group, request.user
			obj.save()
			saved += 1
		else:
			errors.append(f'{f.name}: {form.errors["file"][0]}')
	if saved:
		messages.success(request, f'Uploaded {saved} file{"" if saved == 1 else "s"}.')
	for e in errors[:3]:
		messages.error(request, e)
	return redirect(_tab_url(group, 'files'))


@login_required
def file_download(request, pk, file_id):
	group, me = _member(request, pk)
	f = get_object_or_404(GroupFile, pk=file_id, group=group)
	try:
		handle = f.file.open('rb')
	except (FileNotFoundError, OSError):
		raise Http404('That file is missing.')
	return FileResponse(handle, as_attachment=f.extension not in INLINE_FILES, filename=f.name)


@login_required
@require_POST
def file_delete(request, pk, file_id):
	group, me = _member(request, pk)
	f = get_object_or_404(GroupFile, pk=file_id, group=group)
	if f.uploaded_by_id != request.user.pk and not me.is_admin:
		raise Http404
	f.file.delete(save=False)
	f.delete()
	messages.success(request, f'Deleted {f.name}.')
	return redirect(_tab_url(group, 'files'))


# ---------------------------------------------------------------------
# Study sessions (studygroups/sessions.py)
# ---------------------------------------------------------------------

def _session(group, session_id):
	return get_object_or_404(group.sessions, pk=session_id)


@login_required
@require_POST
def session_create(request, pk):
	from django.core.exceptions import ValidationError
	from . import sessions as SS
	group, me = _member(request, pk)
	try:
		session = SS.create(group, request.user, request.POST)
	except ValidationError as e:
		messages.error(request, e.messages[0])
		return redirect(_tab_url(group, 'sessions') + '&new=1')
	messages.success(request, f'Session scheduled for {SS.when_text(session)}. The group has been told.')
	return redirect(_tab_url(group, 'sessions', f'#s{session.pk}'))


@login_required
@require_POST
def session_edit(request, pk, session_id):
	from django.core.exceptions import ValidationError
	from . import sessions as SS
	group, me = _member(request, pk)
	session = _session(group, session_id)
	if not SS.can_cancel(session, me):             # the same people who can cancel it
		raise Http404
	try:
		changed = SS.update(session, request.user, request.POST)
	except ValidationError as e:
		messages.error(request, e.messages[0])
		return redirect(_tab_url(group, 'sessions', f'&edit={session.pk}#s{session.pk}'))
	if not changed:
		messages.info(request, 'Nothing was changed.')
	elif changed == ['details']:
		messages.success(request, 'Session updated.')
	else:
		messages.success(request, 'Session updated. People coming have been told what changed.')
	return redirect(_tab_url(group, 'sessions', f'#s{session.pk}'))


@login_required
@require_POST
def session_rsvp(request, pk, session_id):
	from django.core.exceptions import ValidationError
	from . import sessions as SS
	group, me = _member(request, pk)
	session = _session(group, session_id)
	try:
		SS.rsvp(session, request.user, request.POST.get('status'))
	except ValidationError as e:
		messages.error(request, e.messages[0])
	return redirect(_tab_url(group, 'sessions', f'#s{session.pk}'))


@login_required
@require_POST
def session_cancel(request, pk, session_id):
	from . import sessions as SS
	group, me = _member(request, pk)
	session = _session(group, session_id)
	if not SS.can_cancel(session, me):
		raise Http404
	SS.cancel(session, request.user)
	messages.success(request, 'Session cancelled. The group chat says so.')
	return redirect(_tab_url(group, 'sessions'))


@login_required
def session_ics(request, pk, session_id):
	from django.http import HttpResponse
	from . import sessions as SS
	group, me = _member(request, pk)
	session = _session(group, session_id)
	resp = HttpResponse(SS.ics(session, request), content_type='text/calendar; charset=utf-8')
	resp['Content-Disposition'] = f'attachment; filename="study-session-{session.pk}.ics"'
	return resp


@login_required
@require_POST
def session_attended(request, pk, session_id):
	"""'I was there' / 'I wasn't there' (your own tick)."""
	from django.core.exceptions import ValidationError
	from . import sessions as SS
	group, me = _member(request, pk)
	session = _session(group, session_id)
	try:
		SS.set_attended(session, request.user, request.POST.get('came') == '1')
	except ValidationError as e:
		messages.error(request, e.messages[0])
	return redirect(_tab_url(group, 'sessions', f'#s{session.pk}'))


@login_required
@require_POST
def session_mark(request, pk, session_id):
	"""The organiser's (or an admin's) 'Mark who came' checklist."""
	from django.core.exceptions import ValidationError
	from . import sessions as SS
	group, me = _member(request, pk)
	session = _session(group, session_id)
	if not SS.can_cancel(session, me):
		raise Http404
	try:
		n = SS.mark_list(session, request.user, request.POST.getlist('came'))
		messages.success(request, f'Attendance saved — {n} came.')
	except ValidationError as e:
		messages.error(request, e.messages[0])
	return redirect(_tab_url(group, 'sessions', f'#s{session.pk}'))


@login_required
@require_POST
def session_note(request, pk, session_id):
	from django.core.exceptions import ValidationError
	from . import sessions as SS
	group, me = _member(request, pk)
	session = _session(group, session_id)
	try:
		note, errors = SS.add_note(session, request.user, request.POST.get('body'), request.FILES.getlist('files'))
		messages.success(request, 'Notes shared with the group.')
		for e in errors[:3]:
			messages.error(request, e)
	except ValidationError as e:
		messages.error(request, e.messages[0])
	return redirect(_tab_url(group, 'sessions', f'#s{session.pk}'))


@login_required
@require_POST
def session_note_delete(request, pk, session_id, note_id):
	from .models import SessionNote
	group, me = _member(request, pk)
	note = get_object_or_404(SessionNote, pk=note_id, session__group=group, session_id=session_id)
	if note.author_id != request.user.pk and not me.is_admin:
		raise Http404
	note.delete()
	messages.success(request, 'Notes deleted.')
	return redirect(_tab_url(group, 'sessions', f'#s{session_id}'))
