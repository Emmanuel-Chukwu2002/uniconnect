"""Communities (run: python manage.py test communities)."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import Notification, Post
from .models import Community, CommunityMember, CommunityRule

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class CommunityTestCase(TestCase):
	def setUp(self):
		self.unn = self.make_university('University of Nigeria', 'UNN', 'unn.edu.ng')
		self.lag = self.make_university('University of Lagos', 'UNILAG', 'unilag.edu.ng')
		self.ada = self.student('ada', self.unn)
		self.ben = self.student('ben', self.unn)
		self.cy = self.student('cy', self.unn)
		self.dee = self.student('dee', self.lag)   # another university

	def make_university(self, name, short, domain):
		uni = University.objects.create(name=name, short_name=short, email_domain=domain)
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		Level.objects.create(department=dep, name='400 Level')
		return uni

	def student(self, username, uni):
		dep = Department.objects.get(faculty__university=uni)
		user = User.objects.create_user(username, password='x', first_name=username.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=dep.faculty, department=dep,
			level=Level.objects.get(department=dep), matric_number=username, university_email=f'{username}@{uni.email_domain}')
		return user

	def community(self, owner, name='Python Club', policy=Community.OPEN):
		c = Community.objects.create(university=owner.student_profile.university, name=name, description=f'All about {name}',
									 topic='tech', join_policy=policy, created_by=owner)
		CommunityMember.objects.create(community=c, user=owner, role=CommunityMember.ADMIN)
		return c

	def as_(self, user):
		self.client.force_login(user)
		return self.client


class CreateAndEditTests(CommunityTestCase):
	def test_create_makes_you_admin_and_saves_rules(self):
		r = self.as_(self.ada).post('/communities/new/', {
			'name': '  CSC   400 Level ', 'description': 'Final year', 'topic': 'courses', 'join_policy': 'restricted',
			'rules': 'Be kind\n\nStay on topic\n',
		})
		c = Community.objects.get()
		self.assertRedirects(r, f'/communities/{c.pk}/')
		self.assertEqual(c.name, 'CSC 400 Level')
		self.assertEqual(c.university, self.unn)
		self.assertTrue(c.is_restricted)
		self.assertEqual([r.text for r in c.rules.all()], ['Be kind', 'Stay on topic'])
		m = CommunityMember.objects.get(community=c, user=self.ada)
		self.assertEqual((m.role, m.status), (CommunityMember.ADMIN, CommunityMember.ACTIVE))

	def test_names_are_unique_across_universities(self):
		self.community(self.ada, 'Python Club')
		r = self.as_(self.ben).post('/communities/new/', {'name': 'python club', 'description': 'x', 'topic': 'tech', 'join_policy': 'open'})
		self.assertContains(r, 'already a community with this name')
		r = self.as_(self.dee).post('/communities/new/', {'name': 'Python Club', 'description': 'x', 'topic': 'tech', 'join_policy': 'open'})
		self.assertContains(r, 'already a community with this name')   # shared by every university: join it instead
		self.assertEqual(Community.objects.filter(name__iexact='python club').count(), 1)

	def test_too_many_rules_rejected(self):
		r = self.as_(self.ada).post('/communities/new/', {'name': 'Rules', 'description': 'x', 'topic': 'tech', 'join_policy': 'open',
														  'rules': '\n'.join(f'Rule {i}' for i in range(11))})
		self.assertContains(r, 'Up to 10 rules')
		self.assertFalse(Community.objects.exists())

	def test_only_admins_edit_and_delete(self):
		c = self.community(self.ada)
		CommunityMember.objects.create(community=c, user=self.ben, role=CommunityMember.MODERATOR)
		self.assertEqual(self.as_(self.ben).get(f'/communities/{c.pk}/edit/').status_code, 403)
		self.assertEqual(self.as_(self.ben).post(f'/communities/{c.pk}/delete/', {'confirm_name': c.name}).status_code, 403)
		r = self.as_(self.ada).post(f'/communities/{c.pk}/edit/', {'name': 'Python Club', 'description': 'New words', 'topic': 'clubs',
																   'join_policy': 'open', 'rules': 'One'})
		self.assertRedirects(r, f'/communities/{c.pk}/')
		c.refresh_from_db()
		self.assertEqual((c.description, c.topic), ('New words', 'clubs'))

	def test_delete_needs_the_name_and_removes_posts(self):
		c = self.community(self.ada)
		Post.objects.create(author=self.ada, content='in it', community=c)
		self.as_(self.ada).post(f'/communities/{c.pk}/delete/', {'confirm_name': 'wrong'})
		self.assertTrue(Community.objects.filter(pk=c.pk).exists())
		self.as_(self.ada).post(f'/communities/{c.pk}/delete/', {'confirm_name': 'python CLUB'})
		self.assertFalse(Community.objects.filter(pk=c.pk).exists())
		self.assertFalse(Post.objects.filter(content='in it').exists())


class VisibilityTests(CommunityTestCase):
	def test_students_from_other_universities_can_find_join_and_post(self):
		c = self.community(self.ada)
		dee = self.as_(self.dee)
		self.assertContains(dee.get('/communities/?tab=explore'), 'Python Club')
		self.assertNotContains(dee.get('/communities/?tab=explore&uni=1'), 'Python Club</a>')   # "only my university"
		self.assertEqual(dee.get(f'/communities/{c.pk}/').status_code, 200)
		dee.post(f'/communities/{c.pk}/join/')
		self.assertTrue(CommunityMember.objects.filter(community=c, user=self.dee, status=CommunityMember.ACTIVE).exists())
		dee.post('/post/new/', {'content': 'Hello from UNILAG', 'community': c.pk})
		self.assertTrue(Post.objects.filter(content='Hello from UNILAG', community=c).exists())
		self.assertContains(self.as_(self.ada).get(f'/communities/{c.pk}/?tab=latest'), 'Hello from UNILAG')
		self.assertContains(self.as_(self.ada).get(f'/communities/{c.pk}/?tab=about'), 'Members from <strong>2</strong> universities')

	def test_explore_topic_and_search(self):
		self.community(self.ada, 'Python Club')
		c2 = self.community(self.ada, 'Football Fans')
		c2.topic = 'sports'; c2.save()
		page = self.as_(self.ben).get('/communities/?tab=explore&topic=sports')
		self.assertContains(page, 'Football Fans')
		self.assertNotContains(page, 'Python Club</a>')
		page = self.as_(self.ben).get('/communities/?tab=explore&q=pyth')
		self.assertContains(page, 'Python Club')
		self.assertNotContains(page, 'Football Fans</a>')

	def test_restricted_communities_are_readable(self):
		c = self.community(self.ada, policy=Community.RESTRICTED)
		Post.objects.create(author=self.ada, content='visible to all at UNN', community=c)
		page = self.as_(self.ben).get(f'/communities/{c.pk}/?tab=latest')
		self.assertContains(page, 'visible to all at UNN')
		self.assertContains(page, 'Ask to join')
		self.assertNotContains(page, 'id="composePromptCard"')


class JoinTests(CommunityTestCase):
	def test_open_join_and_leave(self):
		c = self.community(self.ada)
		r = self.as_(self.ben).post(f'/communities/{c.pk}/join/', **AJAX)
		self.assertEqual(json.loads(r.content)['state'], 'joined')
		self.assertEqual(json.loads(r.content)['members'], 2)
		self.assertTrue(Notification.objects.filter(recipient=self.ada, actor=self.ben, type=Notification.COMMUNITY_JOIN).exists())
		r = self.client.post(f'/communities/{c.pk}/leave/', **AJAX)
		self.assertEqual(json.loads(r.content), {'state': 'none', 'members': 1, 'message': 'You left Python Club.'})
		self.assertFalse(Notification.objects.filter(type=Notification.COMMUNITY_JOIN).exists())

	def test_join_twice_is_harmless(self):
		c = self.community(self.ada)
		self.as_(self.ben).post(f'/communities/{c.pk}/join/', **AJAX)
		self.client.post(f'/communities/{c.pk}/join/', **AJAX)
		self.assertEqual(CommunityMember.objects.filter(community=c, user=self.ben).count(), 1)

	def test_join_needs_post(self):
		c = self.community(self.ada)
		self.assertEqual(self.as_(self.ben).get(f'/communities/{c.pk}/join/').status_code, 405)

	def test_restricted_request_approve(self):
		c = self.community(self.ada, policy=Community.RESTRICTED)
		CommunityMember.objects.create(community=c, user=self.cy, role=CommunityMember.MODERATOR)
		r = self.as_(self.ben).post(f'/communities/{c.pk}/join/', **AJAX)
		self.assertEqual(json.loads(r.content)['state'], 'requested')
		self.assertEqual(json.loads(r.content)['members'], 2)   # not a member yet
		# Admins and moderators hear about it.
		self.assertEqual(Notification.objects.filter(type=Notification.COMMUNITY_REQUEST).count(), 2)
		req = CommunityMember.objects.get(community=c, user=self.ben)
		# A plain member can't approve.
		self.assertEqual(self.as_(self.ben).post(f'/communities/{c.pk}/members/{req.pk}/approve/').status_code, 403)
		r = self.as_(self.cy).post(f'/communities/{c.pk}/members/{req.pk}/approve/')
		self.assertRedirects(r, f'/communities/{c.pk}/?tab=members')
		req.refresh_from_db()
		self.assertEqual(req.status, CommunityMember.ACTIVE)
		self.assertFalse(Notification.objects.filter(type=Notification.COMMUNITY_REQUEST).exists())
		self.assertTrue(Notification.objects.filter(recipient=self.ben, type=Notification.COMMUNITY_ACCEPTED).exists())

	def test_restricted_request_decline_and_cancel(self):
		c = self.community(self.ada, policy=Community.RESTRICTED)
		self.as_(self.ben).post(f'/communities/{c.pk}/join/', **AJAX)
		r = self.client.post(f'/communities/{c.pk}/leave/', **AJAX)   # cancel
		self.assertEqual(json.loads(r.content)['state'], 'none')
		self.assertFalse(Notification.objects.filter(type=Notification.COMMUNITY_REQUEST).exists())
		self.as_(self.ben).post(f'/communities/{c.pk}/join/', **AJAX)
		req = CommunityMember.objects.get(community=c, user=self.ben)
		self.as_(self.ada).post(f'/communities/{c.pk}/members/{req.pk}/decline/')
		self.assertFalse(CommunityMember.objects.filter(pk=req.pk).exists())

	def test_only_admin_cannot_leave(self):
		c = self.community(self.ada)
		r = self.as_(self.ada).post(f'/communities/{c.pk}/leave/', **AJAX)
		self.assertEqual(r.status_code, 400)
		self.assertIn('only admin', json.loads(r.content)['error'])
		self.assertTrue(CommunityMember.objects.filter(community=c, user=self.ada).exists())


class RoleTests(CommunityTestCase):
	def setUp(self):
		super().setUp()
		self.c = self.community(self.ada)
		self.mod = CommunityMember.objects.create(community=self.c, user=self.ben, role=CommunityMember.MODERATOR)
		self.mem = CommunityMember.objects.create(community=self.c, user=self.cy)

	def url(self, m, action):
		return f'/communities/{self.c.pk}/members/{m.pk}/{action}/'

	def test_moderator_removes_members_not_moderators(self):
		admin = CommunityMember.objects.get(community=self.c, user=self.ada)
		self.assertEqual(self.as_(self.ben).post(self.url(admin, 'remove')).status_code, 403)
		self.as_(self.ben).post(self.url(self.mem, 'remove'))
		self.assertFalse(CommunityMember.objects.filter(pk=self.mem.pk).exists())

	def test_only_admins_change_roles(self):
		self.assertEqual(self.as_(self.ben).post(self.url(self.mem, 'role'), {'role': 'moderator'}).status_code, 403)
		self.as_(self.ada).post(self.url(self.mem, 'role'), {'role': 'admin'})
		self.mem.refresh_from_db()
		self.assertEqual(self.mem.role, 'admin')
		self.assertEqual(self.as_(self.ada).post(self.url(self.mem, 'role'), {'role': 'boss'}).status_code, 403)

	def test_cannot_act_on_yourself(self):
		admin = CommunityMember.objects.get(community=self.c, user=self.ada)
		self.assertEqual(self.as_(self.ada).post(self.url(admin, 'remove')).status_code, 403)

	def test_second_admin_lets_first_leave(self):
		self.as_(self.ada).post(self.url(self.mod, 'role'), {'role': 'admin'})
		r = self.as_(self.ada).post(f'/communities/{self.c.pk}/leave/', **AJAX)
		self.assertEqual(json.loads(r.content)['state'], 'none')

	def test_members_tab_shows_requests_only_to_moderators(self):
		dan = self.student('dan', self.unn)
		CommunityMember.objects.create(community=self.c, user=dan, status=CommunityMember.PENDING)
		self.assertContains(self.as_(self.ben).get(f'/communities/{self.c.pk}/?tab=members'), 'Requests to join')
		self.assertNotContains(self.as_(self.cy).get(f'/communities/{self.c.pk}/?tab=members'), 'Requests to join')


class PostingTests(CommunityTestCase):
	def setUp(self):
		super().setUp()
		self.c = self.community(self.ada)
		CommunityMember.objects.create(community=self.c, user=self.ben)

	def test_member_posts_into_community(self):
		r = self.as_(self.ben).post('/post/new/', {'content': 'Hello club', 'community': self.c.pk})
		self.assertRedirects(r, f'/communities/{self.c.pk}/?tab=latest')
		self.assertEqual(Post.objects.get(content='Hello club').community, self.c)

	def test_non_member_cannot_post_into_community(self):
		r = self.as_(self.cy).post('/post/new/', {'content': 'Sneaky', 'community': self.c.pk})
		self.assertEqual(r.status_code, 403)
		self.assertFalse(Post.objects.filter(content='Sneaky').exists())

	def test_pending_member_cannot_post(self):
		CommunityMember.objects.create(community=self.c, user=self.cy, status=CommunityMember.PENDING)
		self.assertEqual(self.as_(self.cy).post('/post/new/', {'content': 'Early', 'community': self.c.pk}).status_code, 403)

	def test_ordinary_posts_still_work(self):
		self.assertRedirects(self.as_(self.cy).post('/post/new/', {'content': 'Just me'}), '/home/')
		self.assertIsNone(Post.objects.get(content='Just me').community)

	def test_home_shows_community_posts_to_members_only(self):
		Post.objects.create(author=self.ben, content='Club news', community=self.c)
		Post.objects.create(author=self.ben, content='Normal news')
		member_home = self.as_(self.ada).get('/home/?tab=foryou')
		self.assertContains(member_home, 'Club news')
		self.assertContains(member_home, 'post-card-community-label')
		outsider_home = self.as_(self.cy).get('/home/?tab=foryou')
		self.assertNotContains(outsider_home, 'Club news')
		self.assertContains(outsider_home, 'Normal news')

	def test_community_page_tabs(self):
		quiet = Post.objects.create(author=self.ben, content='Quiet one', community=self.c)
		busy = Post.objects.create(author=self.ada, content='Busy one', community=self.c)
		from feed.models import Like
		Like.objects.create(user=self.ben, post=quiet)
		Like.objects.create(user=self.cy, post=quiet)
		top = self.as_(self.ben).get(f'/communities/{self.c.pk}/?tab=top').content.decode()
		self.assertLess(top.index('Quiet one'), top.index('Busy one'))       # most liked first
		latest = self.client.get(f'/communities/{self.c.pk}/?tab=latest').content.decode()
		self.assertLess(latest.index('Busy one'), latest.index('Quiet one'))  # newest first
		self.assertNotIn('post-card-community-label', latest)               # no label inside the community itself
		about = self.client.get(f'/communities/{self.c.pk}/?tab=about')
		self.assertContains(about, 'Moderators')
		self.assertEqual(self.client.get(f'/communities/{self.c.pk}/?tab=nonsense').context['tab'], 'posts')

	def test_communities_home_tab_shows_your_communities_posts(self):
		Post.objects.create(author=self.ben, content='From the club', community=self.c)
		other = self.community(self.cy, 'Chess')
		Post.objects.create(author=self.cy, content='From chess', community=other)
		page = self.as_(self.ben).get('/communities/?tab=home')
		self.assertContains(page, 'From the club')
		self.assertNotContains(page, 'From chess')

	def test_notification_links_and_wording(self):
		self.as_(self.cy).post(f'/communities/{self.c.pk}/join/', **AJAX)
		page = self.as_(self.ada).get('/notifications/')
		self.assertContains(page, 'joined <strong>Python Club</strong>')
		n = Notification.objects.get(type=Notification.COMMUNITY_JOIN)
		self.assertRedirects(self.client.get(f'/notifications/{n.pk}/open/'), f'/communities/{self.c.pk}/?tab=members')
