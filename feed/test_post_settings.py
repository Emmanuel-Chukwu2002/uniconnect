"""The rest of a post's "..." menu (feed/post_settings.py)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import Comment, Follow, HiddenPost, Mute, Notification, Post

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class PostMenuTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.ada, self.ben, self.cy = [self.student(n, uni, fac, dep, lvl) for n in ('ada', 'ben', 'cy')]
		self.ben_post = Post.objects.create(author=self.ben, content='Ben selling a fan, @cy see this')
		self.cy_post = Post.objects.create(author=self.cy, content='Cy says lecture moved')
		self.client.force_login(self.ada)

	def student(self, name, uni, fac, dep, lvl):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	def home(self):
		return self.client.get('/home/').content.decode()

	def test_not_interested_and_undo(self):
		self.assertEqual(self.client.post(f'/post/{self.ben_post.pk}/hide/', **AJAX).json(), {'hidden': True})
		self.assertNotIn('Ben selling a fan', self.home())
		self.assertIn('Cy says lecture moved', self.home())
		self.client.post(f'/post/{self.ben_post.pk}/hide/', **AJAX)              # Undo
		self.assertFalse(HiddenPost.objects.exists())
		self.assertIn('Ben selling a fan', self.home())

	def test_mute_hides_from_home_only(self):
		self.client.post('/u/ben/mute/')
		self.assertTrue(Mute.objects.filter(muter=self.ada, muted=self.ben).exists())
		self.assertNotIn('Ben selling a fan', self.home())
		self.assertIn('Ben selling a fan', self.client.get('/u/ben/').content.decode())   # still on his profile
		self.assertIn('Muted accounts', self.client.get('/settings/?s=security').content.decode())
		self.client.post('/u/ben/mute/')
		self.assertIn('Ben selling a fan', self.home())

	def test_menu_has_no_disabled_items(self):
		html = self.home()
		self.assertNotIn('coming soon', html.split('post-card-dropdown')[1][:4000])
		self.assertIn('Not interested in this post', html)
		self.assertIn('Mute @ben', html)

	def test_who_can_reply_following(self):
		self.client.force_login(self.ben)
		r = self.client.get(f'/post/{self.ben_post.pk}/settings/?s=reply')
		self.assertContains(r, 'People you follow')
		self.client.post(f'/post/{self.ben_post.pk}/settings/?s=reply', {'reply_policy': 'following'})
		self.ben_post.refresh_from_db()
		self.assertEqual(self.ben_post.reply_policy, 'following')
		self.client.force_login(self.ada)
		data = self.client.get(f'/post/{self.ben_post.pk}/comments/', **AJAX).json()
		self.assertFalse(data['can_reply'])
		self.assertIn('Ben follows', data['reply_note'])
		self.assertEqual(self.client.post(f'/post/{self.ben_post.pk}/comments/add/', {'content': 'hi'}).status_code, 403)
		Follow.objects.create(follower=self.ben, following=self.ada, status=Follow.STATUS_ACCEPTED)
		self.assertEqual(self.client.post(f'/post/{self.ben_post.pk}/comments/add/', {'content': 'hi'}).status_code, 200)
		self.assertIn('follows can reply', self.home())

	def test_who_can_reply_mentioned(self):
		Post.objects.filter(pk=self.ben_post.pk).update(reply_policy='mentioned')
		self.assertEqual(self.client.post(f'/post/{self.ben_post.pk}/comments/add/', {'content': 'hi'}).status_code, 403)
		self.client.force_login(self.cy)                                          # @cy is mentioned
		self.assertEqual(self.client.post(f'/post/{self.ben_post.pk}/comments/add/', {'content': 'hi'}).status_code, 200)

	def test_only_author_changes_settings(self):
		self.assertEqual(self.client.get(f'/post/{self.ben_post.pk}/settings/').status_code, 403)
		self.assertEqual(self.client.post(f'/post/{self.ben_post.pk}/mute-replies/').status_code, 403)

	def test_mute_replies(self):
		self.client.force_login(self.ben)
		self.client.post(f'/post/{self.ben_post.pk}/mute-replies/')
		self.client.force_login(self.ada)
		self.client.post(f'/post/{self.ben_post.pk}/comments/add/', {'content': 'how much?'})
		self.assertTrue(Comment.objects.exists())
		self.assertFalse(Notification.objects.filter(recipient=self.ben, type=Notification.COMMENT).exists())
		self.client.force_login(self.ben)
		self.assertIn('Unmute replies', self.client.get(f'/post/{self.ben_post.pk}/').content.decode())

	def test_disclosure_label(self):
		self.client.force_login(self.ben)
		self.client.post(f'/post/{self.ben_post.pk}/settings/?s=disclosure', {'disclosure': 'promo'})
		self.client.force_login(self.ada)
		self.assertIn('Paid promotion', self.home())
