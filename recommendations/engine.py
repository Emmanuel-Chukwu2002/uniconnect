"""One recommendation service for Bookshop, Marketplace, Events, Groups and
Communities. People You May Know is in people.py and Trending in trending.py;
all three share Viewer (eligibility.py) and the feedback store (feedback.py).

    recommend(user, 'book' | 'listing' | 'event' | 'group' | 'community', limit=8) -> [Rec]

How an item is chosen — the same pipeline for every feature; only the small
Feature classes below differ:

  1. ACCESS. Each feature's candidates() returns only items the student can
     already open in the app (Bookshop: books from their own university; events:
     upcoming and not full; groups: their university, not invite-only, open,
     not full; ...), and never anything by someone blocked either way or muted,
     their own items, things they've already joined / registered for / put in
     their cart, or anything they marked Not Interested. Ranking only ever
     reorders this list, so nothing can rank its way past these rules.

  2. SCORE, from signals that all exist from day one (cold start):
       relevance   academic fit: your course, department, faculty, university
       social      the creator's closeness *if eligible* (follow / same faculty /
                   same department, eligibility.py), or genuine activity by
                   eligible students (saves, registrations, members, carts).
                   Activity by anyone else never counts here.
       popularity  genuine activity by everyone (log-scaled, so a few busy items
                   can't drown the rest)
       freshness   newly added; for events, how soon it is
       taste       overlap with what the student said they're Interested in or
                   engaged with, minus overlap with what they said they're Not
                   Interested in (same category / course / topic — never "same
                   creator", so one rejected post doesn't hide a person)
       model       Marketplace only: the precomputed score from
                   `manage.py train_recommender` (feed/recommender.py), when present
     Simulated rows (feed.Interaction.is_simulated) are never counted.

  3. DIVERSITY: at most 2 items from one creator.
  4. REASON: one short line from the strongest signal. It never names another
     student ("From someone you follow", "Popular in your faculty").
"""
import math
from dataclasses import dataclass, field

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from .eligibility import Viewer, norm_code, profiles_of
from .models import Feedback as F

POOL = 300                # newest candidates considered per feature
PER_CREATOR = 2
WEIGHTS = {'relevance': 0.30, 'social': 0.25, 'popularity': 0.15, 'freshness': 0.12, 'taste': 0.25, 'model': 0.20}
DISLIKE_FACTOR = 1.5      # a Not Interested category weighs more than an Interested one
REASON_PRIORITY = {'relevance': 2.0, 'social': 2.0, 'taste': 2.0, 'model': 1.5, 'popularity': 1.0, 'freshness': 0.8}


@dataclass
class Rec:
	item: object
	item_type: str
	title: str
	sub: str
	url: str
	image: str = ''
	icon: str = 'bi-stars'
	reason: str = ''
	score: float = 0.0
	feedback: str = ''
	parts: dict = field(default_factory=dict)

	@property
	def item_id(self):
		return self.item.pk


def _decay(days, half_life):
	return 0.5 ** (max(days, 0) / half_life)


def _age_days(dt, now):
	return (now - dt).total_seconds() / 86400 if dt else 999


class Feature:
	item_type = ''
	fresh_half_life = 14
	fresh_reason = 'Just added'

	def accessible(self, v):
		"""Everything this student may open (access rules only). Used for candidates and to validate feedback."""
		raise NotImplementedError

	def candidates(self, v):
		raise NotImplementedError

	def creator_id(self, item):
		return None

	def tokens(self, item):
		return set()

	def relevance(self, v, item):
		return 0.0, ''

	def engaged(self, v, ids):
		"""{item_id: set(user ids)} — genuine activity on these items."""
		return {}

	def positive_ids(self, v):
		"""Items the student engaged with positively (their taste), besides Interested."""
		return set()

	def freshness(self, item, now):
		return _decay(_age_days(getattr(item, 'created_at', None), now), self.fresh_half_life)

	def model_scores(self, v, ids):
		return {}

	def card(self, item):
		raise NotImplementedError

	def by_ids(self, ids):
		return self.model.objects.filter(pk__in=ids)


# ---------------------------------------------------------------------
# Bookshop
# ---------------------------------------------------------------------

class BookFeature(Feature):
	item_type = F.BOOK

	@property
	def model(self):
		from bookshop.models import Book
		return Book

	def accessible(self, v):
		# bookshop/views.py: students see books listed by students of their own university.
		return (self.model.objects.filter(seller__student_profile__university_id=v.profile.university_id, seller__is_active=True)
			.exclude(seller_id__in=v.hidden_people))

	def candidates(self, v):
		return (self.accessible(v).filter(status=self.model.STATUS_AVAILABLE).exclude(seller=v.user)
			.exclude(pk__in=[i for i, val in v.feedback(F.BOOK).items() if val == F.NOT_INTERESTED])
			.select_related('department', 'seller').order_by('-created_at'))

	def creator_id(self, item):
		return item.seller_id

	def tokens(self, item):
		t = {f'cat:{item.category}'}
		if item.course_code:
			t.add(f'course:{norm_code(item.course_code)}')
		if item.department_id:
			t.add(f'dept:{item.department_id}')
		return t

	def relevance(self, v, item):
		code = norm_code(item.course_code)
		if code and code in v.course_codes:
			return 1.0, f'For your course {item.course_code}'
		if item.department_id == v.profile.department_id:
			return 0.8, 'For your department'
		if item.department_id and item.department.faculty_id == v.profile.faculty_id:
			return 0.5, 'For your faculty'
		return 0.0, ''

	def engaged(self, v, ids):
		from bookshop.models import BookSave, BookView
		out = {}
		for model in (BookSave, BookView):
			for b, u in model.objects.filter(book_id__in=ids).values_list('book_id', 'user_id'):
				out.setdefault(b, set()).add(u)
		return out

	def positive_ids(self, v):
		from bookshop.models import BookSave
		return set(BookSave.objects.filter(user=v.user).values_list('book_id', flat=True))

	def card(self, b):
		return {'title': b.title, 'sub': f'{b.author} · {b.price_display}', 'url': b.get_absolute_url(),
			'image': b.cover.url if b.cover else '', 'icon': b.category_icon}


# ---------------------------------------------------------------------
# Marketplace
# ---------------------------------------------------------------------

class ListingFeature(Feature):
	item_type = F.LISTING

	@property
	def model(self):
		from feed.models import Listing
		return Listing

	def accessible(self, v):
		# feed/views.py marketplace_list: every university's listings are browsable.
		return self.model.objects.filter(seller__is_active=True).exclude(seller_id__in=v.hidden_people)

	def candidates(self, v):
		from feed.models import CartItem
		return (self.accessible(v).filter(status=self.model.STATUS_AVAILABLE, quantity_available__gt=0)
			.exclude(seller=v.user)
			.exclude(pk__in=CartItem.objects.filter(user=v.user).values('listing_id'))
			.exclude(pk__in=[i for i, val in v.feedback(F.LISTING).items() if val == F.NOT_INTERESTED])
			.select_related('seller__student_profile').prefetch_related('images').order_by('-created_at'))

	def creator_id(self, item):
		return item.seller_id

	def tokens(self, item):
		return {f'cat:{item.category}'}

	def relevance(self, v, item):
		prof = getattr(item.seller, 'student_profile', None)
		if prof is not None and prof.university_id == v.profile.university_id:
			return 0.7, 'Sold at your university'
		return 0.0, ''

	def engaged(self, v, ids):
		from feed.models import CartItem, Interaction
		out = {}
		for l, u in CartItem.objects.filter(listing_id__in=ids).values_list('listing_id', 'user_id'):
			out.setdefault(l, set()).add(u)
		for l, u in (Interaction.objects.filter(item_type=Interaction.ITEM_LISTING, item_id__in=ids, is_simulated=False)
				.values_list('item_id', 'user_id')):
			out.setdefault(l, set()).add(u)
		return out

	def positive_ids(self, v):
		from feed.models import CartItem, Interaction
		ids = set(CartItem.objects.filter(user=v.user).values_list('listing_id', flat=True))
		ids |= set(Interaction.objects.filter(user=v.user, item_type=Interaction.ITEM_LISTING, is_simulated=False,
			action=Interaction.ACTION_CART).values_list('item_id', flat=True))
		return ids

	def model_scores(self, v, ids):
		"""The batch model's picks (feed.Recommendation), rank 1 = 1.0."""
		from feed.models import Recommendation
		rows = list(Recommendation.objects.filter(user=v.user, listing_id__in=ids).values_list('listing_id', 'rank'))
		if not rows:
			return {}
		worst = max(r for _, r in rows)
		return {l: 1 - (r - 1) / max(worst, 1) for l, r in rows}

	def card(self, l):
		cover = l.cover_image
		return {'title': l.title, 'sub': f'₦{l.price:,.0f} · {l.get_condition_display()}', 'url': reverse('listing_detail', args=[l.pk]),
			'image': cover.url if cover else '', 'icon': l.category_icon}


# ---------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------

class EventFeature(Feature):
	item_type = F.EVENT
	fresh_reason = 'Coming up soon'

	@property
	def model(self):
		from feed.models import Event
		return Event

	def accessible(self, v):
		# Upcoming events are open to everyone (Events page); past ones are deleted.
		return self.model.objects.filter(date__gte=timezone.localdate()).exclude(organizer_id__in=v.hidden_people)

	def candidates(self, v):
		from feed.models import Attendee
		now = timezone.localtime()
		qs = (self.accessible(v)
			.exclude(date=now.date(), time__isnull=False, time__lt=now.time())          # already started today
			.exclude(pk__in=Attendee.objects.filter(user=v.user).values('event_id'))   # already registered
			.exclude(organizer=v.user)
			.exclude(pk__in=[i for i, val in v.feedback(F.EVENT).items() if val == F.NOT_INTERESTED])
			.annotate(n_attending=Count('attendees', distinct=True))
			.filter(Q(capacity__isnull=True) | Q(capacity__gt=0) & Q(n_attending__lt=models_F('capacity')))
			.select_related('organizer__student_profile', 'community').order_by('date', 'time'))
		return qs

	def creator_id(self, item):
		return item.organizer_id

	def tokens(self, item):
		t = {f'cat:{item.category}'}
		if item.community_id:
			t.add(f'community:{item.community_id}')
		return t

	def relevance(self, v, item):
		if item.community_id and item.community_id in v.community_ids:
			return 1.0, "From a community you're in"
		prof = getattr(item.organizer, 'student_profile', None) if item.organizer_id else None
		uni = prof.university_id if prof else (item.community.university_id if item.community_id else None)
		if uni == v.profile.university_id:
			return 0.7, 'At your university'
		return 0.0, ''

	def engaged(self, v, ids):
		from feed.models import Attendee, EventSave
		out = {}
		for model in (Attendee, EventSave):
			for e, u in model.objects.filter(event_id__in=ids).values_list('event_id', 'user_id'):
				out.setdefault(e, set()).add(u)
		return out

	def positive_ids(self, v):
		from feed.models import Attendee, EventSave
		return (set(Attendee.objects.filter(user=v.user).values_list('event_id', flat=True))
			| set(EventSave.objects.filter(user=v.user).values_list('event_id', flat=True)))

	def freshness(self, item, now):
		days = (item.date - timezone.localdate()).days
		return _decay(days, 7)          # the sooner, the higher

	def card(self, e):
		when = e.date.strftime('%a %d %b') + (f', {e.time.strftime("%I:%M %p").lstrip("0")}' if e.time else '')
		return {'title': e.title, 'sub': f'{when} · {e.location}', 'url': reverse('event_detail', args=[e.pk]),
			'image': e.image.url if e.image else '', 'icon': e.category_icon}


def models_F(name):
	from django.db.models import F as Field
	return Field(name)


# ---------------------------------------------------------------------
# Groups (study groups)
# ---------------------------------------------------------------------

class GroupFeature(Feature):
	item_type = F.GROUP
	fresh_half_life = 30

	@property
	def model(self):
		from studygroups.models import StudyGroup
		return StudyGroup

	def accessible(self, v):
		# studygroups: your university's groups; invite-only groups are reached by invite link only.
		G = self.model
		return (G.objects.filter(university_id=v.profile.university_id).exclude(privacy=G.INVITE)
			.exclude(created_by_id__in=v.hidden_people))

	def candidates(self, v):
		from studygroups.models import StudyGroupMember as M
		return (self.accessible(v).filter(is_open=True)
			.exclude(pk__in=M.objects.filter(user=v.user).values('group_id'))         # member or already asked
			.exclude(pk__in=[i for i, val in v.feedback(F.GROUP).items() if val == F.NOT_INTERESTED])
			.annotate(n_active=Count('members', filter=Q(members__status=M.ACTIVE), distinct=True))
			.filter(Q(max_members__isnull=True) | Q(n_active__lt=models_F('max_members')))
			.select_related('department', 'level').order_by('-created_at'))

	def creator_id(self, item):
		return item.created_by_id

	def tokens(self, item):
		t = {f'type:{item.group_type}'}
		if item.course_code:
			t.add(f'course:{norm_code(item.course_code)}')
		if item.department_id:
			t.add(f'dept:{item.department_id}')
		return t

	def relevance(self, v, g):
		code = norm_code(g.course_code)
		if code and code in v.course_codes:
			return 1.0, f'For your course {g.course_code}'
		if g.department_id == v.profile.department_id:
			if g.level_id == v.profile.level_id:
				return 0.9, 'For your class'
			return 0.8, 'For your department'
		if g.department_id and g.department.faculty_id == v.profile.faculty_id:
			return 0.5, 'For your faculty'
		if not g.department_id:
			return 0.3, 'Open to all students'
		return 0.0, ''

	def engaged(self, v, ids):
		from studygroups.models import StudyGroupMember as M
		out = {}
		for g, u in M.objects.filter(group_id__in=ids, status=M.ACTIVE).values_list('group_id', 'user_id'):
			out.setdefault(g, set()).add(u)
		return out

	def positive_ids(self, v):
		from studygroups.models import StudyGroupMember as M
		return set(M.objects.filter(user=v.user, status=M.ACTIVE).values_list('group_id', flat=True))

	def card(self, g):
		return {'title': g.title, 'sub': f'{g.get_group_type_display()} · {g.n_active} member{"s" if g.n_active != 1 else ""}',
			'url': g.get_absolute_url(), 'image': g.icon_url, 'icon': 'bi-collection'}


# ---------------------------------------------------------------------
# Communities
# ---------------------------------------------------------------------

class CommunityFeature(Feature):
	item_type = F.COMMUNITY
	fresh_half_life = 60

	@property
	def model(self):
		from communities.models import Community
		return Community

	def accessible(self, v):
		# communities/views.py: every community is visible to every student.
		return self.model.objects.exclude(created_by_id__in=v.hidden_people)

	def candidates(self, v):
		from communities.models import CommunityMember as M
		return (self.accessible(v)
			.exclude(pk__in=M.objects.filter(user=v.user).values('community_id'))
			.exclude(pk__in=[i for i, val in v.feedback(F.COMMUNITY).items() if val == F.NOT_INTERESTED])
			.annotate(n_active=Count('memberships', filter=Q(memberships__status=M.ACTIVE), distinct=True))
			.select_related('university').order_by('-created_at'))

	def creator_id(self, item):
		return item.created_by_id

	def tokens(self, c):
		return {f'topic:{c.topic}'} | {f'tag:{t.lower()}' for t in c.tag_list}

	def relevance(self, v, c):
		if c.university_id == v.profile.university_id:
			return 0.6, 'At your university'
		return 0.0, ''

	def engaged(self, v, ids):
		from communities.models import CommunityMember as M
		out = {}
		for c, u in M.objects.filter(community_id__in=ids, status=M.ACTIVE).values_list('community_id', 'user_id'):
			out.setdefault(c, set()).add(u)
		return out

	def positive_ids(self, v):
		return set(v.community_ids)

	def card(self, c):
		return {'title': c.name, 'sub': f'{c.get_topic_display()} · {c.n_active} member{"s" if c.n_active != 1 else ""}',
			'url': c.get_absolute_url(), 'image': c.icon.url if c.icon else c.topic_photo_url, 'icon': c.topic_icon}


FEATURES = {f.item_type: f for f in (BookFeature(), ListingFeature(), EventFeature(), GroupFeature(), CommunityFeature())}


# ---------------------------------------------------------------------
# The shared pipeline
# ---------------------------------------------------------------------

def _taste_tokens(feature, v):
	"""(liked tokens, disliked tokens) from Interested / Not Interested and positive activity."""
	fb = v.feedback(feature.item_type)
	liked_ids = {i for i, val in fb.items() if val == F.INTERESTED} | feature.positive_ids(v)
	disliked_ids = {i for i, val in fb.items() if val == F.NOT_INTERESTED}
	liked, disliked = set(), set()
	if liked_ids or disliked_ids:
		for item in feature.by_ids(liked_ids | disliked_ids):
			(disliked if item.pk in disliked_ids else liked).update(feature.tokens(item))
	return liked, disliked - liked


def recommend(user, item_type, limit=8, viewer=None):
	v = viewer or Viewer(user)
	if not v.is_student or item_type not in FEATURES:
		return []
	feature = FEATURES[item_type]
	items = list(feature.candidates(v)[:POOL])
	if not items:
		return []
	now = timezone.now()
	ids = [i.pk for i in items]
	engaged = feature.engaged(v, ids)
	creators = {feature.creator_id(i) for i in items} - {None}
	people = set().union(*engaged.values()) if engaged else set()
	profiles = profiles_of(people | creators)
	liked, disliked = _taste_tokens(feature, v)
	fb = v.feedback(item_type)
	model = feature.model_scores(v, ids)

	active = [len(engaged.get(i, set()) - {v.user.pk} - v.hidden_people) for i in ids]
	top_active = max(active) if active else 0
	recs = []
	for item, n_active in zip(items, active):
		parts, reasons = {}, {}
		parts['relevance'], reasons['relevance'] = feature.relevance(v, item)

		cid = feature.creator_id(item)
		creator_close = v.closeness(cid, profiles) if cid else 0.0
		eligible_people = [u for u in engaged.get(item.pk, ()) if u != v.user.pk and v.closeness(u, profiles) > 0]
		crowd = min(1.0, math.log1p(len(eligible_people)) / math.log(6))
		parts['social'] = max(creator_close, crowd)
		if creator_close >= crowd and creator_close > 0:
			reasons['social'] = ('From someone you follow' if cid in v.following else
				'From your department' if creator_close >= 0.8 else 'From your faculty')
		elif crowd > 0:
			same_dept = any(profiles.get(u, (None, None))[1] == v.profile.department_id for u in eligible_people)
			reasons['social'] = 'Popular in your department' if same_dept else 'Popular with people you know'

		parts['popularity'] = math.log1p(n_active) / math.log1p(top_active) if top_active else 0.0
		reasons['popularity'] = 'Popular right now'
		parts['freshness'] = feature.freshness(item, now)
		reasons['freshness'] = feature.fresh_reason

		toks = feature.tokens(item)
		taste = 0.0
		if toks:
			taste = len(toks & liked) / len(toks) - DISLIKE_FACTOR * len(toks & disliked) / len(toks)
		if fb.get(item.pk) == F.INTERESTED:
			taste += 0.5
		parts['taste'] = taste
		reasons['taste'] = "You're interested in this" if fb.get(item.pk) == F.INTERESTED else 'Similar to things you like'

		if model:
			parts['model'] = model.get(item.pk, 0.0)
			reasons['model'] = 'Matches your Marketplace activity'

		contrib = {k: WEIGHTS[k] * val for k, val in parts.items()}
		score = sum(contrib.values())
		# The reason line prefers the personal signals over "Just added" / "Popular right now".
		best = max((k for k in contrib if contrib[k] > 0 and reasons.get(k)),
			key=lambda k: contrib[k] * REASON_PRIORITY.get(k, 1.0), default=None)
		card = feature.card(item)
		recs.append(Rec(item=item, item_type=item_type, score=score, reason=reasons.get(best, '') if best else 'New on UniConnect',
			feedback=fb.get(item.pk, ''), parts={k: round(val, 3) for k, val in parts.items()}, **card))

	recs.sort(key=lambda r: (-r.score, -r.item.pk))
	out, per_creator = [], {}
	for r in recs:
		cid = feature.creator_id(r.item)
		if cid is not None:
			if per_creator.get(cid, 0) >= PER_CREATOR:
				continue
			per_creator[cid] = per_creator.get(cid, 0) + 1
		out.append(r)
		if len(out) == limit:
			break
	return out


def can_access(user, item_type, item_id, viewer=None):
	"""May this student give feedback on this item (i.e. can they open it)?"""
	v = viewer or Viewer(user)
	if not v.is_student:
		return False
	if item_type in FEATURES:
		return FEATURES[item_type].accessible(v).filter(pk=item_id).exists()
	if item_type == F.POST:
		# Same rules as Home (feed/views.py _visible_on_home), except that a post you
		# already hid stays reachable here so the choice can be undone.
		from feed.models import Post
		post = Post.objects.filter(pk=item_id).only('author_id', 'community_id').first()
		if post is None or post.author_id == v.user.pk or post.author_id in v.blocked:
			return False
		return post.community_id is None or post.community_id in v.community_ids
	if item_type == F.USER:
		from accounts.models import StudentProfile
		return (item_id != v.user.pk and item_id not in v.blocked
			and StudentProfile.objects.filter(user_id=item_id, user__is_active=True).exists())
	return False
