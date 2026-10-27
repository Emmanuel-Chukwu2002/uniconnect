"""Recommendations: eligibility, feedback, Trending, People You May Know and the
five content features. Run: python manage.py test recommendations"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from bookshop.models import Book, BookSave
from communities.models import Community, CommunityMember
from courses.models import Course, CourseEnrollment
from feed.models import (Attendee, Block, Bookmark, CartItem, Comment, Event, Follow, HiddenPost, Interaction, Like,
	Listing, Mute, Post, PostView, Repost)
from studygroups.models import StudyGroup, StudyGroupMember

from .eligibility import Viewer
from .engine import can_access, recommend
from .feedback import feedback_map, set_feedback
from .models import Feedback as F
from .people import people_you_may_know
from .trending import trending_posts

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class Base(TestCase):
	@classmethod
	def setUpTestData(cls):
		cls.unn = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		cls.ui = University.objects.create(name='University of Ibadan', short_name='UI', email_domain='ui.edu.ng')
		cls.sci = Faculty.objects.create(university=cls.unn, name='Physical Sciences')
		cls.arts = Faculty.objects.create(university=cls.unn, name='Arts')
		cls.ui_sci = Faculty.objects.create(university=cls.ui, name='Science')
		cls.cs = Department.objects.create(faculty=cls.sci, name='Computer Science')
		cls.stat = Department.objects.create(faculty=cls.sci, name='Statistics')
		cls.hist = Department.objects.create(faculty=cls.arts, name='History')
		cls.ui_cs = Department.objects.create(faculty=cls.ui_sci, name='Computer Science')

	def student(self, name, dept=None, level='400 Level', active=True):
		dept = dept or self.cs
		lvl = Level.objects.get_or_create(department=dept, name=level)[0]
		u = User.objects.create_user(name, password='x', first_name=name.title(), is_active=active)
		StudentProfile.objects.create(user=u, university=dept.faculty.university, faculty=dept.faculty, department=dept,
			level=lvl, matric_number=name, university_email=f'{name}@x.edu')
		return u

	def fresh(self, user):
		return User.objects.get(pk=user.pk)        # Viewer and blocked_ids cache per user object

	def ids(self, user, kind, **kw):
		return [r.item_id for r in recommend(self.fresh(user), kind, **kw)]


class EligibilityTests(Base):
	def setUp(self):
		self.ada = self.student('ada')                         # CS, Sciences
		self.ben = self.student('ben')                         # same department
		self.cy = self.student('cy', self.stat)                # same faculty, other department
		self.dee = self.student('dee', self.hist)              # other faculty
		self.eve = self.student('eve', self.ui_cs)             # other university

	def test_rule_follow_faculty_department(self):
		v = Viewer(self.ada)
		profiles = {u.pk: u.student_profile for u in (self.ben, self.cy, self.dee, self.eve)}
		self.assertTrue(v.is_eligible(profiles[self.ben.pk]))      # same department
		self.assertTrue(v.is_eligible(profiles[self.cy.pk]))       # same faculty
		self.assertFalse(v.is_eligible(profiles[self.dee.pk]))     # neither
		self.assertFalse(v.is_eligible(profiles[self.eve.pk]))
		self.assertFalse(v.is_eligible(self.ada.student_profile))  # never yourself
		Follow.objects.create(follower=self.ada, following=self.eve, status=Follow.STATUS_PENDING)
		self.assertFalse(Viewer(self.ada).is_eligible(profiles[self.eve.pk]))   # a request isn't a follow
		Follow.objects.filter(follower=self.ada, following=self.eve).update(status=Follow.STATUS_ACCEPTED)
		v = Viewer(self.ada)
		self.assertTrue(v.is_eligible(profiles[self.eve.pk]))      # followed: eligible anywhere
		self.assertEqual(v.eligible_ids, {self.ben.pk, self.cy.pk, self.eve.pk})

	def test_blocked_muted_and_inactive_are_never_eligible(self):
		zed = self.student('zed', active=False)
		Block.objects.create(blocker=self.ben, blocked=self.ada)
		Mute.objects.create(muter=self.ada, muted=self.cy)
		self.assertEqual(Viewer(self.fresh(self.ada)).eligible_ids, set())
		self.assertNotIn(zed.pk, Viewer(self.fresh(self.ada)).eligible_ids)


class FeedbackTests(Base):
	def setUp(self):
		self.ada, self.ben = self.student('ada'), self.student('ben')
		self.book = Book.objects.create(seller=self.ben, title='Algorithms', author='CLRS', price=5000)
		self.client.force_login(self.ada)

	def post_fb(self, item_type, item_id, value):
		return self.client.post('/recommendations/feedback/', {'item_type': item_type, 'item_id': item_id, 'value': value}, **AJAX)

	def test_set_change_undo_without_duplicates(self):
		self.assertEqual(self.post_fb('book', self.book.pk, 'interested').json()['value'], 'interested')
		self.post_fb('book', self.book.pk, 'interested')
		self.assertEqual(F.objects.count(), 1)                                   # no duplicate row
		self.post_fb('book', self.book.pk, 'not_interested')
		self.assertEqual(list(F.objects.values_list('value', flat=True)), ['not_interested'])   # changed, still one
		self.post_fb('book', self.book.pk, '')
		self.assertFalse(F.objects.exists())                                     # undone

	def test_post_feedback_uses_hiddenpost_and_never_both(self):
		post = Post.objects.create(author=self.ben, content='hello')
		self.post_fb('post', post.pk, 'interested')
		self.assertEqual(feedback_map(self.ada, F.POST), {post.pk: 'interested'})
		self.post_fb('post', post.pk, 'not_interested')
		self.assertTrue(HiddenPost.objects.filter(user=self.ada, post=post).exists())
		self.assertFalse(F.objects.filter(item_type=F.POST).exists())
		self.post_fb('post', post.pk, 'interested')                              # undo the hide by choosing Interested
		self.assertFalse(HiddenPost.objects.exists())
		self.client.post(f'/post/{post.pk}/hide/', **AJAX)                       # the menu's existing Not interested
		self.assertFalse(F.objects.filter(item_type=F.POST).exists())
		self.assertEqual(self.post_fb('post', post.pk, '').status_code, 200)    # still reachable to undo

	def test_validation_and_permissions(self):
		self.assertEqual(self.post_fb('book', self.book.pk, 'love').status_code, 400)
		self.assertEqual(self.post_fb('spaceship', 1, 'interested').status_code, 400)
		self.assertEqual(self.post_fb('user', self.ben.pk, 'interested').status_code, 400)   # follow instead
		self.assertEqual(self.post_fb('book', 99999, 'interested').status_code, 404)
		own = Post.objects.create(author=self.ada, content='mine')
		self.assertEqual(self.post_fb('post', own.pk, 'interested').status_code, 404)
		g = StudyGroup.objects.create(university=self.unn, created_by=self.ben, name='Secret', privacy=StudyGroup.INVITE)
		self.assertEqual(self.post_fb('group', g.pk, 'interested').status_code, 404)        # invite-only
		other = Book.objects.create(seller=self.student('eve', self.ui_cs), title='UI book', author='x', price=1)
		self.assertEqual(self.post_fb('book', other.pk, 'interested').status_code, 404)    # other university's shelf
		self.client.logout()
		self.assertEqual(self.post_fb('book', self.book.pk, 'interested').status_code, 302)  # sign in first
		self.assertEqual(self.client.get('/recommendations/feedback/').status_code, 302)

	def test_one_students_feedback_is_theirs_only(self):
		set_feedback(self.ben, F.BOOK, self.book.pk, F.INTERESTED)
		self.client.post('/recommendations/feedback/', {'item_type': 'book', 'item_id': self.book.pk, 'value': '', 'user': self.ben.pk}, **AJAX)
		self.assertTrue(F.objects.filter(user=self.ben).exists())       # ada's undo can't touch ben's row


class ContentRecommendationTests(Base):
	def setUp(self):
		self.ada = self.student('ada')
		self.ben = self.student('ben')                    # same department
		self.dee = self.student('dee', self.hist)         # other faculty
		self.eve = self.student('eve', self.ui_cs)        # other university
		self.cos = Course.objects.create(university=self.unn, code='COS 401', title='Data Structures')
		CourseEnrollment.objects.create(user=self.ada, course=self.cos)

	def test_cold_start_still_recommends(self):
		Book.objects.create(seller=self.dee, title='Any book', author='x', price=100)
		Listing.objects.create(seller=self.eve, title='Desk lamp', price=2000)
		Event.objects.create(title='Fair', location='Hall', date=timezone.localdate() + timedelta(days=2))
		StudyGroup.objects.create(university=self.unn, created_by=self.dee, name='Campus runners', group_type='social')
		Community.objects.create(university=self.ui, name='Coders', description='x', created_by=self.eve)
		for kind in ('book', 'listing', 'event', 'group', 'community'):
			self.assertEqual(len(recommend(self.fresh(self.ada), kind)), 1, kind)

	def test_books_relevance_access_and_unavailable(self):
		mine = Book.objects.create(seller=self.dee, title='DS notes', author='x', price=100, course_code='cos401')
		dept = Book.objects.create(seller=self.student('d2', self.hist), title='Dept book', author='x', price=100, department=self.cs)
		other = Book.objects.create(seller=self.student('d3', self.hist), title='Novel', author='x', price=100)
		Book.objects.create(seller=self.dee, title='Sold', author='x', price=100, status=Book.STATUS_SOLD)
		Book.objects.create(seller=self.eve, title='UI only', author='x', price=100)        # not on UNN's shelf
		Book.objects.create(seller=self.ada, title='My own', author='x', price=100)
		recs = recommend(self.fresh(self.ada), 'book')
		self.assertEqual([r.item_id for r in recs], [mine.pk, dept.pk, other.pk])
		self.assertEqual(recs[0].reason, 'For your course cos401')

	def test_eligible_social_proof_only(self):
		a = Book.objects.create(seller=self.dee, title='A', author='x', price=1)
		b = Book.objects.create(seller=self.dee, title='B', author='x', price=1)
		for name in ('h1', 'h2', 'h3'):                                     # three History students save B
			BookSave.objects.create(book=b, user=self.student(name, self.hist))
		BookSave.objects.create(book=a, user=self.ben)                      # one classmate saves A
		recs = {r.item_id: r for r in recommend(self.fresh(self.ada), 'book')}
		self.assertGreater(recs[a.pk].parts['social'], 0)
		self.assertEqual(recs[b.pk].parts['social'], 0)                     # non-eligible students don't count as social proof
		self.assertEqual(recs[a.pk].reason, 'Popular in your department')

	def test_creator_closeness_needs_eligibility(self):
		near = Listing.objects.create(seller=self.ben, title='Calculator', price=1)
		far = Listing.objects.create(seller=self.eve, title='Calculator 2', price=1)
		recs = {r.item_id: r for r in recommend(self.fresh(self.ada), 'listing')}
		self.assertEqual(recs[near.pk].parts['social'], 0.8)               # same department
		self.assertEqual(recs[far.pk].parts['social'], 0)
		Follow.objects.create(follower=self.ada, following=self.eve, status=Follow.STATUS_ACCEPTED)
		recs = {r.item_id: r for r in recommend(self.fresh(self.ada), 'listing')}
		self.assertEqual(recs[far.pk].parts['social'], 1.0)                 # followed: eligible

	def test_marketplace_respects_status_cart_block_and_ignores_simulated(self):
		ok = Listing.objects.create(seller=self.ben, title='Fan', price=1)
		Listing.objects.create(seller=self.ben, title='Gone', price=1, status=Listing.STATUS_SOLD)
		Listing.objects.create(seller=self.ben, title='None left', price=1, quantity_available=0)
		carted = Listing.objects.create(seller=self.dee, title='In cart', price=1)
		CartItem.objects.create(user=self.ada, listing=carted)
		blocked = Listing.objects.create(seller=self.eve, title='Blocked seller', price=1)
		Block.objects.create(blocker=self.eve, blocked=self.ada)
		self.assertEqual(self.ids(self.ada, 'listing'), [ok.pk])
		Interaction.objects.create(user=self.ben, item_type='listing', item_id=ok.pk, action='cart', is_simulated=True)
		self.assertEqual(recommend(self.fresh(self.ada), 'listing')[0].parts['popularity'], 0)
		self.assertFalse(can_access(self.fresh(self.ada), F.LISTING, blocked.pk))

	def test_events_dates_capacity_and_registration(self):
		today = timezone.localdate()
		soon = Event.objects.create(title='Soon', location='x', date=today + timedelta(days=1))
		later = Event.objects.create(title='Later', location='x', date=today + timedelta(days=20))
		full = Event.objects.create(title='Full', location='x', date=today + timedelta(days=1), capacity=1)
		Attendee.objects.create(event=full, user=self.ben)
		going = Event.objects.create(title='Going', location='x', date=today + timedelta(days=1))
		Attendee.objects.create(event=going, user=self.ada)
		Event.objects.create(title='Past', location='x', date=today - timedelta(days=1))
		self.assertEqual(self.ids(self.ada, 'event'), [soon.pk, later.pk])

	def test_groups_membership_privacy_and_room(self):
		G = StudyGroup
		mine = G.objects.create(university=self.unn, created_by=self.ben, name='COS 401 crew', course_code='COS 401')
		G.objects.create(university=self.unn, created_by=self.ben, name='Invite', privacy=G.INVITE)
		G.objects.create(university=self.unn, created_by=self.ben, name='Closed', is_open=False)
		full = G.objects.create(university=self.unn, created_by=self.ben, name='Full', max_members=1)
		StudyGroupMember.objects.create(group=full, user=self.ben)
		joined = G.objects.create(university=self.unn, created_by=self.ben, name='Joined')
		StudyGroupMember.objects.create(group=joined, user=self.ada)
		G.objects.create(university=self.ui, created_by=self.eve, name='Elsewhere')
		recs = recommend(self.fresh(self.ada), 'group')
		self.assertEqual([r.item_id for r in recs], [mine.pk])
		self.assertEqual(recs[0].reason, 'For your course COS 401')

	def test_communities_and_membership(self):
		a = Community.objects.create(university=self.unn, name='Coders', description='x', created_by=self.ben, topic='clubs')
		b = Community.objects.create(university=self.unn, name='Chess', description='x', created_by=self.dee)
		CommunityMember.objects.create(community=b, user=self.ada)
		self.assertEqual(self.ids(self.ada, 'community'), [a.pk])

	def test_not_interested_removes_and_lowers_similar_and_undo(self):
		x = Book.objects.create(seller=self.dee, title='X', author='a', price=1, category='novel')
		y = Book.objects.create(seller=self.dee, title='Y', author='a', price=1, category='novel')
		z = Book.objects.create(seller=self.ben, title='Z', author='a', price=1, category='textbook')
		before = {r.item_id: r.score for r in recommend(self.fresh(self.ada), 'book')}
		set_feedback(self.ada, F.BOOK, x.pk, F.NOT_INTERESTED)
		after = {r.item_id: r.score for r in recommend(self.fresh(self.ada), 'book')}
		self.assertNotIn(x.pk, after)                          # never shown again
		self.assertLess(after[y.pk], before[y.pk])             # similar (same category) ranks lower
		self.assertIn(z.pk, after)
		self.assertIn(y.pk, after)                             # same seller isn't hidden: only the item
		set_feedback(self.ada, F.BOOK, x.pk, None)
		self.assertIn(x.pk, self.ids(self.ada, 'book'))         # undo brings it back

	def test_interested_boosts_similar(self):
		x = Book.objects.create(seller=self.dee, title='X', author='a', price=1, category='novel')
		y = Book.objects.create(seller=self.dee, title='Y', author='a', price=1, category='novel')
		w = Book.objects.create(seller=self.ben, title='W', author='a', price=1, category='textbook')
		before = {r.item_id: r.score for r in recommend(self.fresh(self.ada), 'book')}
		set_feedback(self.ada, F.BOOK, x.pk, F.INTERESTED)
		after = {r.item_id: r for r in recommend(self.fresh(self.ada), 'book')}
		self.assertGreater(after[y.pk].score, before[y.pk])
		self.assertEqual(after[x.pk].feedback, 'interested')
		self.assertAlmostEqual(after[w.pk].score, before[w.pk], places=4)

	def test_at_most_two_per_creator(self):
		for i in range(5):
			Book.objects.create(seller=self.dee, title=f'B{i}', author='a', price=1)
		self.assertEqual(len(recommend(self.fresh(self.ada), 'book')), 2)

	def test_non_students_get_nothing(self):
		admin = User.objects.create_user('admin', password='x')
		Book.objects.create(seller=self.dee, title='X', author='a', price=1)
		self.assertEqual(recommend(admin, 'book'), [])
		self.assertEqual(people_you_may_know(admin), [])
		self.assertEqual(trending_posts(admin), [])


class PeopleYouMayKnowTests(Base):
	def setUp(self):
		self.ada = self.student('ada')

	def test_exclusions(self):
		ben = self.student('ben')                          # same dept
		cy = self.student('cy', self.stat)                 # same faculty
		dee = self.student('dee', self.hist)               # other faculty: not eligible
		eve = self.student('eve', self.ui_cs)              # other university
		fay = self.student('fay')                          # followed already
		gus = self.student('gus')                          # requested
		hal = self.student('hal')                          # blocked
		ivy = self.student('ivy')                          # muted
		jon = self.student('jon', active=False)            # deactivated
		kim = self.student('kim')                          # dismissed
		Follow.objects.create(follower=self.ada, following=fay, status=Follow.STATUS_ACCEPTED)
		Follow.objects.create(follower=self.ada, following=gus, status=Follow.STATUS_PENDING)
		Block.objects.create(blocker=hal, blocked=self.ada)
		Mute.objects.create(muter=self.ada, muted=ivy)
		set_feedback(self.ada, F.USER, kim.pk, F.NOT_INTERESTED)
		got = {p.user_id for p in people_you_may_know(self.fresh(self.ada), limit=50)}
		self.assertEqual(got, {ben.pk, cy.pk})
		self.assertNotIn(self.ada.pk, got)
		Follow.objects.create(follower=self.ada, following=eve, status=Follow.STATUS_ACCEPTED)
		self.assertNotIn(eve.pk, {p.user_id for p in people_you_may_know(self.fresh(self.ada), limit=50)})
		self.assertFalse(Follow.objects.filter(follower=self.ada, following=ben).exists())   # never auto-follows

	def test_ranking_mutuals_follows_you_and_courses(self):
		friend = self.student('friend', self.hist)
		Follow.objects.create(follower=self.ada, following=friend, status=Follow.STATUS_ACCEPTED)
		plain = self.student('plain', self.stat)
		mutual = self.student('mutual', self.stat)
		Follow.objects.create(follower=friend, following=mutual, status=Follow.STATUS_ACCEPTED)
		fan = self.student('fan', self.stat)
		Follow.objects.create(follower=fan, following=self.ada, status=Follow.STATUS_ACCEPTED)
		people = people_you_may_know(self.fresh(self.ada), limit=10)
		order = [p.user_id for p in people]
		self.assertLess(order.index(mutual.pk), order.index(plain.pk))
		self.assertLess(order.index(fan.pk), order.index(plain.pk))
		reasons = {p.user_id: p.pymk_reason for p in people}
		self.assertEqual(reasons[mutual.pk], '1 mutual connection')
		self.assertEqual(reasons[fan.pk], 'Follows you')
		self.assertEqual(reasons[plain.pk], 'In your faculty')

	def test_sidebar_and_page_show_pymk_with_follow_button(self):
		ben = self.student('ben')
		self.student('dee', self.hist)
		self.client.force_login(self.ada)
		html = self.client.get('/home/').content.decode()
		self.assertIn('People You May Know', html)
		self.assertIn(f'data-user-id="{ben.pk}"', html)
		from django.urls import reverse
		page = self.client.get(reverse('who_to_follow')).content.decode()
		self.assertIn('People you may know', page)
		self.assertIn(f'data-rec-id="{ben.pk}"', page)                     # with its dismiss button


class TrendingTests(Base):
	def setUp(self):
		self.ada = self.student('ada')
		self.people = [self.student(f'p{i}', self.hist) for i in range(6)]
		self.now = timezone.now()

	def post(self, author=None, hours_ago=1, **kw):
		p = Post.objects.create(author=author or self.people[0], content=kw.pop('content', 'hi'), **kw)
		Post.objects.filter(pk=p.pk).update(created_at=self.now - timedelta(hours=hours_ago))
		return p

	def at(self, model, hours_ago, **kw):
		obj = model.objects.create(**kw)
		model.objects.filter(pk=obj.pk).update(created_at=self.now - timedelta(hours=hours_ago))
		return obj

	def ranked(self):
		return [p.pk for p in trending_posts(self.fresh(self.ada), now=self.now)]

	def test_recent_engagement_beats_old_and_combined_signals_beat_one(self):
		new, old = self.post(hours_ago=2), self.post(hours_ago=100)
		for u in self.people[1:4]:
			self.at(Like, 1, post=new, user=u)
			self.at(Like, 100, post=old, user=u)
		self.assertEqual(self.ranked()[:2], [new.pk, old.pk])
		mixed = self.post(hours_ago=2)
		self.at(Like, 1, post=mixed, user=self.people[1])
		self.at(Comment, 1, post=mixed, author=self.people[2], content='nice')
		self.at(Repost, 1, post=mixed, user=self.people[3])
		self.assertEqual(self.ranked()[0], mixed.pk)

	def test_views_alone_cannot_dominate_and_simulated_views_ignored(self):
		viewed, liked = self.post(), self.post()
		day = timezone.localdate()
		for u in self.people[1:]:
			PostView.objects.create(post=viewed, user=u, day=day)
		for u in self.people[1:3]:
			self.at(Like, 1, post=liked, user=u)
		self.assertEqual(self.ranked()[0], liked.pk)
		fake = self.post()
		for u in self.people[1:]:
			PostView.objects.create(post=fake, user=u, day=day, is_simulated=True)
		self.assertNotIn(fake.pk, self.ranked())

	def test_visibility_moderation_and_no_duplicates(self):
		a, b, c = self.post(), self.post(author=self.people[1]), self.post()
		other_uni = self.post(author=self.student('eve', self.ui_cs))
		comm = Community.objects.create(university=self.unn, name='Private-ish', description='x')
		in_comm = self.post(community=comm)
		for p in (a, b, c, other_uni, in_comm):
			for u in self.people[2:5]:
				self.at(Like, 1, post=p, user=u)
			self.at(Bookmark, 1, post=p, user=self.people[5])
		self.at(Comment, 1, post=a, author=self.people[2], content='x')
		ranked = self.ranked()
		self.assertEqual(len(ranked), len(set(ranked)))
		self.assertNotIn(other_uni.pk, ranked)           # your university only
		self.assertNotIn(in_comm.pk, ranked)             # community posts: members only
		Block.objects.create(blocker=self.people[1], blocked=self.ada)
		HiddenPost.objects.create(user=self.ada, post=c)
		self.assertEqual(set(self.ranked()), {a.pk})

	def test_authors_own_engagement_does_not_count(self):
		p = self.post()
		self.at(Like, 1, post=p, user=self.people[0])
		self.assertEqual(self.ranked(), [])

	def test_not_interested_hashtags_lower_similar_posts(self):
		x = self.post(content='Big #football match')
		y = self.post(content='More #football tonight')
		z = self.post(content='Quiet #library day')
		for p in (x, y, z):
			for u in self.people[1:4]:
				self.at(Like, 1, post=p, user=u)
		set_feedback(self.ada, F.POST, x.pk, F.NOT_INTERESTED)
		ranked = self.ranked()
		self.assertNotIn(x.pk, ranked)
		self.assertLess(ranked.index(z.pk), ranked.index(y.pk))

	def test_home_trending_tab(self):
		p = self.post(content='Trending post here')
		for u in self.people[1:3]:
			self.at(Like, 1, post=p, user=u)
		self.client.force_login(self.ada)
		html = self.client.get('/home/?tab=trending').content.decode()
		self.assertIn('Trending post here', html)
		self.assertIn('Interested in this post', html)


class PagesTests(Base):
	def test_pages_render_recommendations(self):
		ada, ben = self.student('ada'), self.student('ben')
		Book.objects.create(seller=ben, title='Rec book', author='x', price=1)
		Listing.objects.create(seller=ben, title='Rec lamp', price=1)
		Event.objects.create(title='Rec event', location='x', date=timezone.localdate() + timedelta(days=3))
		StudyGroup.objects.create(university=self.unn, created_by=ben, name='Rec group')
		Community.objects.create(university=self.unn, name='Rec community', description='x', created_by=ben)
		self.client.force_login(ada)
		for url, text in [('/bookshop/', 'Rec book'), ('/marketplace/', 'Rec lamp'), ('/events/', 'Rec event'),
				('/groups/', 'Rec group'), ('/communities/?tab=explore', 'Rec community')]:
			r = self.client.get(url)
			self.assertEqual(r.status_code, 200, url)
			html = r.content.decode()
			self.assertIn(text, html, url)
			self.assertIn('/recommendations/feedback/', html, url)
