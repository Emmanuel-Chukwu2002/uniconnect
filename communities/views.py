"""
Communities pages (X/Twitter-style):
  /communities/                    Home: posts from your communities  (?tab=home)
                                   Explore: browse by topic and search (?tab=explore&topic=&q=)
  /communities/new/                Create a community
  /communities/<id>/               A community: Posts / Members / About / Events / Resources tabs
  /communities/<id>/edit/          Edit it (admins)
  /communities/<id>/delete/        Delete it (admins, POST)
  /communities/<id>/join/          Join, or ask to join a restricted one (POST)
  /communities/<id>/leave/         Leave, or cancel your request (POST)
  /communities/<id>/members/<membership id>/<action>/
                                   approve / decline / remove / role (POST, moderators)

Communities are open to students of every university: anyone on
UniConnect can find, join and post in one (a community still records the
university it was started at, shown on its card). Posts in a community are ordinary feed Posts with
Post.community set, so the feed's post card, likes, comments, reposts and
quotes all just work (feed/views.py does the rest: the composer posts into
a community, and Home shows community posts to members only).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import Lower
from django.utils import timezone
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from feed.models import Follow, Notification, Post
from feed.notifications import notify, unnotify
from feed.views import _attach_bookmark_data, _attach_comment_counts, _attach_like_data, _post_qs
from .forms import CommunityForm
from .models import Community, CommunityMember

ACTIVE, PENDING = CommunityMember.ACTIVE, CommunityMember.PENDING
DETAIL_TABS = ('posts', 'members', 'about', 'events', 'resources')
# Old tab names (links made before the redesign) -> the new ones.
OLD_TABS = {'top': 'posts', 'latest': 'posts', 'media': 'resources'}
SORTS = {'popular': 'Most Popular', 'active': 'Most Active', 'newest': 'Newest', 'name': 'A–Z'}
RECOMMENDED = 3
FEED_LIMIT = 200


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _is_ajax(request):
	return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _university(user):
	student = getattr(user, 'student_profile', None)
	return student.university if student else None


def _university_communities(user):
	"""Every community a student can see — all of them, whichever university
	they were started at. (Accounts without a student profile see none.)"""
	if _university(user) is None:
		return Community.objects.none()
	return Community.objects.all()


def _community_or_404(user, pk):
	return get_object_or_404(_university_communities(user).select_related('created_by', 'university'), pk=pk)


def _universities_count(community):
	return (CommunityMember.objects.filter(community=community, status=ACTIVE)
			.values('user__student_profile__university').distinct().count())


def _membership(community, user):
	return CommunityMember.objects.filter(community=community, user=user).first()


def _with_member_counts(qs):
	return qs.annotate(n_members=Count('memberships', filter=Q(memberships__status=ACTIVE), distinct=True))


def _decorate(communities, user, faces=3):
	"""Adds to each community: .my_state ('joined' / 'requested' / 'none'),
	.my_role, and .faces (a few members' photos for the avatar stack).
	A fixed number of queries for the whole list."""
	communities = list(communities)
	ids = [c.pk for c in communities]
	mine = {m.community_id: m for m in CommunityMember.objects.filter(user=user, community_id__in=ids)}
	by_c = {}
	for m in (CommunityMember.objects.filter(community_id__in=ids, status=ACTIVE)
			  .select_related('user', 'user__student_profile').order_by('community_id', 'created_at')):
		bucket = by_c.setdefault(m.community_id, [])
		if len(bucket) < faces:
			bucket.append(m.user)
	for c in communities:
		m = mine.get(c.pk)
		c.my_state = 'none' if m is None else ('joined' if m.status == ACTIVE else 'requested')
		c.my_role = m.role if m and m.status == ACTIVE else ''
		c.faces = by_c.get(c.pk, [])
	return communities


def _post_cards(posts, user):
	posts = _attach_like_data(posts, user)
	posts = _attach_comment_counts(posts)
	return _attach_bookmark_data(posts, user)


def _follow_sets(user):
	return {
		'following_ids': set(Follow.objects.filter(follower=user, status=Follow.STATUS_ACCEPTED).values_list('following_id', flat=True)),
		'pending_ids': set(Follow.objects.filter(follower=user, status=Follow.STATUS_PENDING).values_list('following_id', flat=True)),
	}


def _topics_with_counts(user):
	counts = dict(_university_communities(user).values('topic').annotate(n=Count('id')).values_list('topic', 'n'))
	return [{'value': v, 'label': label, 'icon': icon, 'count': counts.get(v, 0)} for v, label, icon in Community.TOPICS]


def _moderators(community):
	return [m.user for m in community.memberships.filter(status=ACTIVE, role__in=[CommunityMember.ADMIN, CommunityMember.MODERATOR])
			.select_related('user')]


def _admins(community):
	return [m.user for m in community.memberships.filter(status=ACTIVE, role=CommunityMember.ADMIN).select_related('user')]


def _members_count(community):
	return community.memberships.filter(status=ACTIVE).count()


def _back(request, fallback):
	nxt = request.POST.get('next') or request.GET.get('next')
	if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
		return redirect(nxt)
	return redirect(fallback)


# ---------------------------------------------------------------------
# Communities home: your communities' posts, and Explore
# ---------------------------------------------------------------------
@login_required
def index(request):
	user = request.user
	uni = _university(user)
	my_ids = list(CommunityMember.objects.filter(user=user, status=ACTIVE)
				  .values_list('community_id', flat=True)) if uni else []

	tab = request.GET.get('tab') or ('home' if my_ids else 'explore')
	if tab not in ('home', 'explore'):
		tab = 'home'
	topic = request.GET.get('topic', '')
	if topic not in Community.TOPIC_ICONS:
		topic = ''
	q = (request.GET.get('q') or '').strip()
	only_mine = request.GET.get('uni') == '1'

	mine = _decorate(_with_member_counts(Community.objects.filter(pk__in=my_ids)).order_by('name'), user)

	context = {'tab': tab, 'topic': topic, 'q': q, 'my_communities': mine, 'university': uni, 'only_mine': only_mine}
	if tab == 'home':
		posts = _post_qs(Post.objects.filter(community_id__in=my_ids, thread_root__isnull=True)).order_by('-created_at')[:FEED_LIMIT]
		context['posts'] = _post_cards(posts, user)
		context.update(_follow_sets(user))
	else:
		qs = _with_member_counts(_university_communities(user).select_related('university'))
		if only_mine:
			qs = qs.filter(university=uni)
		if topic:
			qs = qs.filter(topic=topic)
		for word in q.split():
			qs = qs.filter(Q(name__icontains=word) | Q(description__icontains=word) | Q(tags__icontains=word))
		# "All Communities": the sort menu.
		sort = request.GET.get('sort') if request.GET.get('sort') in SORTS else 'popular'
		if sort == 'active':
			since = timezone.now() - timedelta(days=30)
			qs = qs.annotate(n_recent=Count('posts', filter=Q(posts__created_at__gte=since), distinct=True)).order_by('-n_recent', '-n_members', 'name')
		elif sort == 'newest':
			qs = qs.order_by('-created_at')
		elif sort == 'name':
			qs = qs.order_by(Lower('name'))
		else:
			qs = qs.order_by('-n_members', 'name')
		context['results'] = _decorate(qs, user)
		context['sort'], context['sorts'] = sort, SORTS.items()
		# "Recommended for You" (only on the plain list, not while searching or filtering).
		if not q and not topic and not only_mine:
			context['recommended'] = _recommended(user, uni)
		context['topics'] = _topics_with_counts(user)
		context['topic_label'] = dict(Community.TOPIC_CHOICES).get(topic, '')
	return render(request, 'communities/index.html', context)


def _recommended(user, uni):
	"""Communities you aren't in yet, from the shared recommendation service
	(recommendations/engine.py): your university, topics and tags like the ones
	you joined or marked Interested, people you know who are members, and never
	one you marked Not interested."""
	from recommendations.engine import recommend
	recs = recommend(user, 'community', limit=RECOMMENDED)
	pool = []
	for r in recs:
		c = r.item
		c.n_members, c.rec_reason, c.rec_feedback = c.n_active, r.reason, r.feedback
		pool.append(c)
	return _decorate(pool, user)


# ---------------------------------------------------------------------
# A community
# ---------------------------------------------------------------------
def _engagement(post):
	return post.likes_count + 2 * post.comments_count + 2 * post.reposts_count


@login_required
def detail(request, pk):
	user = request.user
	community = _community_or_404(user, pk)
	community = _decorate(_with_member_counts(Community.objects.filter(pk=community.pk)), user, faces=5)[0]
	membership = _membership(community, user)
	is_member = bool(membership and membership.is_active)
	can_moderate = bool(membership and membership.can_moderate)
	is_admin = bool(membership and membership.is_admin)

	tab = request.GET.get('tab', 'posts')
	if tab in OLD_TABS:
		sort_from_old = 'top' if tab == 'top' else ''
		tab = OLD_TABS[tab]
	else:
		sort_from_old = ''
	if tab not in DETAIL_TABS:
		tab = 'posts'

	all_posts = _post_qs(Post.objects.filter(community=community))
	context = {
		'community': community, 'membership': membership, 'is_member': is_member,
		'can_moderate': can_moderate, 'is_admin': is_admin, 'tab': tab,
		'posts_count': all_posts.count(), 'in_community': True,
		'pending_count': community.memberships.filter(status=PENDING).count() if can_moderate else 0,
		'universities_count': _universities_count(community),
	}

	if tab in ('posts', 'resources'):
		posts = all_posts.order_by('-created_at')
		q = ' '.join((request.GET.get('q') or '').split())[:80]
		if tab == 'posts':
			if q:
				# The search button on the banner: posts in this community with these words.
				for word in q.split():
					posts = posts.filter(content__icontains=word)
			else:
				posts = posts.filter(thread_root__isnull=True)      # a thread shows once, as its first post
		else:
			# Resources: what people shared to use — links, photos, videos.
			posts = posts.filter(
				Q(image__gt='') | Q(video__gt='') | Q(media_items__isnull=False) | Q(link_preview__isnull=False)
				| Q(content__icontains='http://') | Q(content__icontains='https://')
			).distinct()
		posts = _post_cards(posts[:FEED_LIMIT], user)
		sort = request.GET.get('sort') or sort_from_old or 'latest'
		if tab == 'posts' and sort == 'top' and not q:
			# Most engaged first (likes, comments, reposts); newest breaks ties.
			posts.sort(key=_engagement, reverse=True)
		# Each author's role here, for "Admin · UNN" under their name.
		roles = dict(community.memberships.filter(status=ACTIVE, user_id__in={p.author_id for p in posts})
			.values_list('user_id', 'role'))
		label = {CommunityMember.ADMIN: 'Admin', CommunityMember.MODERATOR: 'Moderator'}
		for p in posts:
			p.cm_role = label.get(roles.get(p.author_id), 'Student')
		context.update(posts=posts, sort='top' if sort == 'top' else 'latest', q=q)
		context.update(_follow_sets(user))
	elif tab == 'events':
		from feed.forms import EventForm
		today = timezone.localdate()
		context['events'] = list(community.events.filter(date__gte=today).select_related('organizer').order_by('date', 'time'))
		context['past_events'] = list(community.events.filter(date__lt=today).order_by('-date')[:5])
		if is_member:
			context['event_form'] = EventForm()
	elif tab == 'about':
		context['rules'] = list(community.rules.all())
		context['moderators'] = (community.memberships.filter(status=ACTIVE, role__in=[CommunityMember.ADMIN, CommunityMember.MODERATOR])
								 .select_related('user', 'user__student_profile').order_by('role', 'created_at'))
	else:  # members
		members = list(community.memberships.filter(status=ACTIVE).select_related(
			'user', 'user__student_profile', 'user__student_profile__department', 'user__student_profile__level',
			'user__student_profile__university'))
		order = {CommunityMember.ADMIN: 0, CommunityMember.MODERATOR: 1, CommunityMember.MEMBER: 2}
		members.sort(key=lambda m: (order[m.role], m.created_at))
		context['members'] = members
		if can_moderate:
			context['requests'] = list(community.memberships.filter(status=PENDING).select_related(
				'user', 'user__student_profile', 'user__student_profile__department', 'user__student_profile__level'))
	return render(request, 'communities/detail.html', context)


# ---------------------------------------------------------------------
# Create / edit / delete
# ---------------------------------------------------------------------
@login_required
def create(request):
	uni = _university(request.user)
	if uni is None:
		raise PermissionDenied('Only students can create communities.')
	if request.method == 'POST':
		form = CommunityForm(request.POST, request.FILES, university=uni)
		if form.is_valid():
			community = form.save(commit=False)
			community.university = uni
			community.created_by = request.user
			community.save()
			form.save_rules(community)
			CommunityMember.objects.create(community=community, user=request.user, role=CommunityMember.ADMIN, status=ACTIVE)
			messages.success(request, f'{community.name} is ready. Invite people by sharing it, and post the first update.')
			return redirect('community_detail', pk=community.pk)
	else:
		form = CommunityForm(university=uni, initial={'topic': request.GET.get('topic') or 'other'})
	return render(request, 'communities/form.html', {'form': form, 'is_edit': False, 'topics': Community.TOPICS})


def _admin_membership(request, community):
	membership = _membership(community, request.user)
	if not (membership and membership.is_admin):
		raise PermissionDenied('Only admins can do that.')
	return membership


@login_required
def edit(request, pk):
	community = _community_or_404(request.user, pk)
	_admin_membership(request, community)
	if request.method == 'POST':
		form = CommunityForm(request.POST, request.FILES, instance=community, university=community.university)
		if form.is_valid():
			if form.cleaned_data.get('remove_banner') and not request.FILES.get('banner'):
				form.instance.banner = None
			if form.cleaned_data.get('remove_icon') and not request.FILES.get('icon'):
				form.instance.icon = None
			form.save()
			form.save_rules(community)
			messages.success(request, 'Community updated.')
			return redirect('community_detail', pk=community.pk)
	else:
		form = CommunityForm(instance=community, university=community.university)
	return render(request, 'communities/form.html', {'form': form, 'is_edit': True, 'community': community, 'topics': Community.TOPICS})


@login_required
@require_POST
def delete(request, pk):
	community = _community_or_404(request.user, pk)
	_admin_membership(request, community)
	if (request.POST.get('confirm_name') or '').strip().lower() != community.name.lower():
		messages.error(request, 'Type the community name exactly to delete it.')
		return redirect('community_edit', pk=community.pk)
	name = community.name
	community.delete()
	messages.success(request, f'{name} was deleted.')
	return redirect(reverse('communities') + '?tab=explore')


# ---------------------------------------------------------------------
# Joining and leaving
# ---------------------------------------------------------------------
def _state_response(request, community, state, message=''):
	if _is_ajax(request):
		return JsonResponse({'state': state, 'members': _members_count(community), 'message': message})
	if message:
		messages.success(request, message)
	return _back(request, reverse('community_detail', args=[community.pk]))


@login_required
@require_POST
def join(request, pk):
	community = _community_or_404(request.user, pk)
	membership = _membership(community, request.user)
	if membership:
		return _state_response(request, community, 'joined' if membership.is_active else 'requested')
	if community.is_restricted:
		CommunityMember.objects.create(community=community, user=request.user, status=PENDING)
		for mod in _moderators(community):
			notify(mod, request.user, Notification.COMMUNITY_REQUEST, community=community, replace=True)
		return _state_response(request, community, 'requested', 'Request sent — a moderator will review it.')
	CommunityMember.objects.create(community=community, user=request.user, status=ACTIVE)
	for admin in _admins(community):
		notify(admin, request.user, Notification.COMMUNITY_JOIN, community=community, replace=True)
	return _state_response(request, community, 'joined', f'You joined {community.name}.')


@login_required
@require_POST
def leave(request, pk):
	community = _community_or_404(request.user, pk)
	membership = _membership(community, request.user)
	if membership is None:
		return _state_response(request, community, 'none')
	if membership.is_admin and community.memberships.filter(status=ACTIVE, role=CommunityMember.ADMIN).count() == 1:
		message = "You're the only admin — make someone else an admin first, or delete the community."
		if _is_ajax(request):
			return JsonResponse({'error': message}, status=400)
		messages.error(request, message)
		return _back(request, reverse('community_detail', args=[community.pk]))
	was_pending = not membership.is_active
	membership.delete()
	if was_pending:
		for mod in _moderators(community):
			unnotify(mod, request.user, Notification.COMMUNITY_REQUEST, community=community)
		return _state_response(request, community, 'none', 'Request cancelled.')
	for admin in _admins(community):
		unnotify(admin, request.user, Notification.COMMUNITY_JOIN, community=community)
	return _state_response(request, community, 'none', f'You left {community.name}.')


# ---------------------------------------------------------------------
# Moderation: requests, removing members, roles
# ---------------------------------------------------------------------
@login_required
@require_POST
def member_action(request, pk, member_id, action):
	community = _community_or_404(request.user, pk)
	me = _membership(community, request.user)
	if not (me and me.can_moderate):
		raise PermissionDenied('Only admins and moderators can manage members.')
	target = get_object_or_404(CommunityMember.objects.select_related('user'), pk=member_id, community=community)
	back = reverse('community_detail', args=[community.pk]) + '?tab=members'
	name = target.user.get_full_name() or target.user.username

	if action in ('approve', 'decline'):
		if target.status != PENDING:
			raise Http404('No such request.')
		for mod in _moderators(community):
			unnotify(mod, target.user, Notification.COMMUNITY_REQUEST, community=community)
		if action == 'approve':
			target.status = ACTIVE
			target.save(update_fields=['status'])
			notify(target.user, request.user, Notification.COMMUNITY_ACCEPTED, community=community, replace=True)
			messages.success(request, f'{name} is now a member.')
		else:
			target.delete()
			messages.success(request, f"Declined {name}'s request.")
		return _back(request, back)

	if target.user_id == request.user.id:
		raise PermissionDenied("Use Leave to remove yourself.")

	if action == 'remove':
		# Moderators remove members; only admins remove moderators or admins.
		if target.role != CommunityMember.MEMBER and not me.is_admin:
			raise PermissionDenied('Only admins can remove moderators.')
		target.delete()
		messages.success(request, f'{name} was removed from {community.name}.')
		return _back(request, back)

	if action == 'role':
		if not me.is_admin:
			raise PermissionDenied('Only admins can change roles.')
		role = request.POST.get('role')
		if role not in dict(CommunityMember.ROLE_CHOICES) or target.status != ACTIVE:
			raise PermissionDenied('Unknown role.')
		target.role = role
		target.save(update_fields=['role'])
		messages.success(request, f'{name} is now {"an admin" if role == "admin" else "a " + role}.')
		return _back(request, back)

	raise Http404('Unknown action.')
