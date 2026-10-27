"""Search (run: python manage.py test feed.test_search)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from communities.models import Community, CommunityMember
from .models import Event, Follow, Listing, Post

User = get_user_model()


class SearchTests(TestCase):
	def setUp(self):
		self.uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		other_uni = University.objects.create(name='University of Lagos', short_name='UNILAG', email_domain='unilag.edu.ng')
		self.me = self.student('ada', 'Ada', 'Obi', self.uni)
		self.ben = self.student('ben', 'Benson', 'Eze', self.uni)
		self.far = self.student('fara', 'Benson', 'Far', other_uni)
		self.client.force_login(self.me)

	def student(self, username, first, last, uni):
		fac = Faculty.objects.get_or_create(university=uni, name='Sciences')[0]
		dep = Department.objects.get_or_create(faculty=fac, name='Computer Science')[0]
		lvl = Level.objects.get_or_create(department=dep, name='400 Level')[0]
		user = User.objects.create_user(username, password='x', first_name=first, last_name=last)
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=username, university_email=f'{username}@{uni.email_domain}')
		return user

	def get(self, **params):
		return self.client.get('/search/', params).content.decode()

	def test_empty_page_shows_trending(self):
		Post.objects.create(author=self.ben, content='Big game today #UCL #football')
		Post.objects.create(author=self.ben, content='Who is watching? #ucl')
		Post.objects.create(author=self.far, content='Other school #Secret')
		html = self.get()
		self.assertIn('Trending at your university', html)
		self.assertIn('#ucl', html)
		self.assertIn('2 posts in the last two weeks', html)
		self.assertNotIn('#secret', html)

	def test_people_only_from_my_university_with_follow_state(self):
		html = self.get(q='benson')
		self.assertIn('@ben', html)
		self.assertNotIn('@fara', html)
		self.assertIn('data-status="none">Follow', html)
		Follow.objects.create(follower=self.me, following=self.ben, status=Follow.STATUS_PENDING)
		self.assertIn('data-status="pending">Requested', self.get(q='benson', type='people'))

	def test_posts_words_hashtags_and_community_privacy(self):
		Post.objects.create(author=self.ben, content='Python club meets on Friday #code')
		Post.objects.create(author=self.ben, content='Python is fun')
		Post.objects.create(author=self.far, content='Python club elsewhere')
		club = Community.objects.create(university=self.uni, name='Secret Society', description='x', created_by=self.ben)
		hidden = Post.objects.create(author=self.ben, content='Python club members only', community=club)
		html = self.get(q='python club', type='posts')
		self.assertIn('meets on Friday', html)
		self.assertNotIn('Python is fun', html)          # every word must match
		self.assertNotIn('elsewhere', html)              # other university
		self.assertNotIn('members only', html)           # not a member
		CommunityMember.objects.create(community=club, user=self.me, status=CommunityMember.ACTIVE)
		self.assertIn('members only', self.get(q='python club', type='posts'))
		self.assertIn('meets on Friday', self.get(q='#code'))

	def test_top_mixes_kinds_and_nothing_found(self):
		Community.objects.create(university=self.uni, name='Chess Club', description='Weekly chess games', created_by=self.ben)
		Event.objects.create(title='Chess Tournament', location='Main Hall', date=timezone.localdate() + timedelta(days=3))
		Listing.objects.create(seller=self.ben, title='Chess board', price=5000)
		html = self.get(q='chess')
		for bit in ('Chess Club', 'Chess Tournament', 'Chess board', '>Communities<', '>Events<', '>Marketplace<'):
			self.assertIn(bit, html)
		self.assertIn('No results for', self.get(q='zzzzqqq'))

	def test_sidebar_box_is_a_search_form(self):
		html = self.client.get('/home/').content.decode()
		self.assertIn('action="/search/"', html)
		self.assertIn('name="q" placeholder="Search UniConnect..."', html)
