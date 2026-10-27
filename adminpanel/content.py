"""Every kind of thing that can be reported or moderated, described once.

Used by student reporting (feed/moderation.py report_item), the report queue
(reports.py) and the moderation tables (Content Moderation, Marketplace,
Bookshop, Events, Groups & Communities).

Each Kind knows: its model, the university it belongs to (for scoping),
who owns it (the account a report is filed against), a short label, where it
lives in the app, and how to search it. Removing content deletes it after its
text has been kept on the report and in the audit log, so the decision can
still be explained later.
"""
from django.db.models import Count, Q
from django.urls import reverse


def _snip(text, n=90):
	text = ' '.join((text or '').split())
	return text if len(text) <= n else text[:n - 1] + '…'


class Kind:
	key = ''              # URL key on the dashboard
	report_type = ''      # feed.Report target_type
	label = ''            # 'Posts'
	noun = ''             # 'post'
	icon = 'bi-file-text'
	search = ()
	order = '-created_at'
	removable = True

	def model(self):
		raise NotImplementedError

	def queryset(self):
		return self.model().objects.all()

	def scope_q(self, university):
		raise NotImplementedError

	def owner(self, obj):
		raise NotImplementedError

	def university_id(self, obj):
		raise NotImplementedError

	def title(self, obj):
		return str(obj)

	def url(self, obj):
		return ''

	def details(self, obj):
		"""Extra columns for the moderation table: [(label, value)]."""
		return []

	def snapshot(self, obj):
		return self.title(obj)

	def for_admin(self, admin, q=''):
		qs = self.queryset()
		if admin.university is not None:
			qs = qs.filter(self.scope_q(admin.university))
		for word in (q or '').split()[:6]:
			cond = Q()
			for f in self.search:
				cond |= Q(**{f'{f}__icontains': word})
			qs = qs.filter(cond)
		return qs.order_by(self.order).distinct()

	def get(self, pk):
		return self.queryset().filter(pk=pk).first()


def _uni_of_user(user):
	prof = getattr(user, 'student_profile', None) if user else None
	return prof.university_id if prof else None


class PostKind(Kind):
	key, report_type, label, noun, icon = 'posts', 'post', 'Posts', 'post', 'bi-file-text'
	search = ('content', 'author__username', 'author__first_name', 'author__last_name')

	def model(self):
		from feed.models import Post
		return Post

	def queryset(self):
		return self.model().objects.select_related('author', 'author__student_profile__university', 'community')

	def scope_q(self, university):
		return Q(author__student_profile__university=university)

	def owner(self, obj):
		return obj.author

	def university_id(self, obj):
		return _uni_of_user(obj.author)

	def title(self, obj):
		return _snip(obj.content) or 'Photo or video post'

	def url(self, obj):
		return reverse('post_detail', args=[obj.pk])

	def details(self, obj):
		return [('Community', obj.community.name if obj.community_id else '—')]

	def snapshot(self, obj):
		return (obj.content or '')[:2000]


class MediaKind(PostKind):
	key, label, noun, icon = 'media', 'Images & videos', 'post', 'bi-image'

	def queryset(self):
		return super().queryset().filter(Q(media_items__isnull=False) | Q(video__gt=''))


class CommentKind(Kind):
	key, report_type, label, noun, icon = 'comments', 'comment', 'Comments', 'comment', 'bi-chat-left-text'
	search = ('content', 'author__username', 'author__first_name', 'author__last_name')

	def model(self):
		from feed.models import Comment
		return Comment

	def queryset(self):
		return self.model().objects.select_related('author', 'author__student_profile__university', 'post')

	def scope_q(self, university):
		return Q(author__student_profile__university=university)

	def owner(self, obj):
		return obj.author

	def university_id(self, obj):
		return _uni_of_user(obj.author)

	def title(self, obj):
		return _snip(obj.content) or 'Photo or video comment'

	def url(self, obj):
		return reverse('post_detail', args=[obj.post_id]) + f'?comment={obj.pk}'

	def snapshot(self, obj):
		return (obj.content or '')[:2000]


class ListingKind(Kind):
	key, report_type, label, noun, icon = 'listings', 'listing', 'Listings', 'listing', 'bi-shop'
	search = ('title', 'description', 'seller__username', 'seller__first_name', 'seller__last_name')

	def model(self):
		from feed.models import Listing
		return Listing

	def queryset(self):
		return self.model().objects.select_related('seller', 'seller__student_profile__university')

	def scope_q(self, university):
		return Q(seller__student_profile__university=university)

	def owner(self, obj):
		return obj.seller

	def university_id(self, obj):
		return _uni_of_user(obj.seller)

	def title(self, obj):
		return obj.title

	def url(self, obj):
		return reverse('listing_detail', args=[obj.pk])

	def details(self, obj):
		return [('Price', f'₦{obj.price:,.0f}'), ('Status', obj.get_status_display())]

	def snapshot(self, obj):
		return f'{obj.title}\n{obj.description}'[:2000]


class BookKind(Kind):
	key, report_type, label, noun, icon = 'books', 'book', 'Books', 'book', 'bi-book'
	search = ('title', 'author', 'course_code', 'seller__username', 'seller__first_name', 'seller__last_name')

	def model(self):
		from bookshop.models import Book
		return Book

	def queryset(self):
		return self.model().objects.select_related('seller', 'seller__student_profile__university')

	def scope_q(self, university):
		return Q(seller__student_profile__university=university)

	def owner(self, obj):
		return obj.seller

	def university_id(self, obj):
		return _uni_of_user(obj.seller)

	def title(self, obj):
		return obj.title

	def url(self, obj):
		return obj.get_absolute_url()

	def details(self, obj):
		return [('Price', obj.price_display), ('Status', obj.get_status_display())]

	def snapshot(self, obj):
		return f'{obj.title} — {obj.author}\n{obj.description}'[:2000]


class EventKind(Kind):
	key, report_type, label, noun, icon = 'events', 'event', 'Events', 'event', 'bi-calendar-event'
	search = ('title', 'location', 'description', 'organizer__username', 'organizer__first_name')
	order = 'date'

	def model(self):
		from feed.models import Event
		return Event

	def queryset(self):
		return self.model().objects.select_related('organizer', 'organizer__student_profile__university', 'community')

	def scope_q(self, university):
		return Q(organizer__student_profile__university=university) | Q(community__university=university)

	def owner(self, obj):
		return obj.organizer or (obj.community.created_by if obj.community_id else None)

	def university_id(self, obj):
		return _uni_of_user(obj.organizer) or (obj.community.university_id if obj.community_id else None)

	def title(self, obj):
		return obj.title

	def url(self, obj):
		return reverse('event_detail', args=[obj.pk])

	def details(self, obj):
		return [('Date', obj.date.strftime('%d %b %Y')), ('Where', obj.location)]

	def snapshot(self, obj):
		return f'{obj.title} — {obj.location}, {obj.date}\n{obj.description}'[:2000]


class GroupKind(Kind):
	key, report_type, label, noun, icon = 'groups', 'group', 'Groups', 'group', 'bi-collection'
	search = ('name', 'course_code', 'description', 'created_by__username')

	def model(self):
		from studygroups.models import StudyGroup
		return StudyGroup

	def queryset(self):
		return (self.model().objects.select_related('created_by', 'university')
			.annotate(n_members=Count('members', distinct=True)))

	def scope_q(self, university):
		return Q(university=university)

	def owner(self, obj):
		return obj.created_by

	def university_id(self, obj):
		return obj.university_id

	def title(self, obj):
		return obj.title

	def url(self, obj):
		return obj.get_absolute_url()

	def details(self, obj):
		return [('Members', getattr(obj, 'n_members', '')), ('Privacy', obj.get_privacy_display())]

	def snapshot(self, obj):
		return f'{obj.title}\n{obj.description}'[:2000]


class CommunityKind(Kind):
	key, report_type, label, noun, icon = 'communities', 'community', 'Communities', 'community', 'bi-people'
	search = ('name', 'description', 'tags', 'created_by__username')

	def model(self):
		from communities.models import Community
		return Community

	def queryset(self):
		return (self.model().objects.select_related('created_by', 'university')
			.annotate(n_members=Count('memberships', distinct=True)))

	def scope_q(self, university):
		return Q(university=university)

	def owner(self, obj):
		return obj.created_by

	def university_id(self, obj):
		return obj.university_id

	def title(self, obj):
		return obj.name

	def url(self, obj):
		return obj.get_absolute_url()

	def details(self, obj):
		return [('Members', getattr(obj, 'n_members', '')), ('Topic', obj.get_topic_display())]

	def snapshot(self, obj):
		return f'{obj.name}\n{obj.description}'[:2000]


class UserKind(Kind):
	key, report_type, label, noun, icon = 'users', 'user', 'Accounts', 'account', 'bi-person'
	removable = False

	def model(self):
		from django.contrib.auth import get_user_model
		return get_user_model()

	def queryset(self):
		return self.model().objects.select_related('student_profile__university')

	def scope_q(self, university):
		return Q(student_profile__university=university)

	def owner(self, obj):
		return obj

	def university_id(self, obj):
		return _uni_of_user(obj)

	def title(self, obj):
		return f'{obj.get_full_name() or obj.username} (@{obj.username})'

	def url(self, obj):
		return reverse('user_profile', args=[obj.username])


KINDS = {k.key: k for k in (PostKind(), MediaKind(), CommentKind(), ListingKind(), BookKind(), EventKind(),
	GroupKind(), CommunityKind(), UserKind())}
BY_REPORT_TYPE = {k.report_type: k for k in KINDS.values() if k.key != 'media'}


def open_report_counts(report_type, ids):
	from feed.models import Report
	return dict(Report.objects.filter(target_type=report_type, target_id__in=list(ids),
		status__in=[Report.OPEN, Report.REVIEWING]).values('target_id').annotate(n=Count('id')).values_list('target_id', 'n'))
