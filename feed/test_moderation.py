"""Blocking and reporting (feed/moderation.py)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import Block, Follow, Notification, Post, Report
from feed.notifications import notify

User = get_user_model()


class ModerationTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.ada, self.ben, self.cy = [self.student(n, uni, fac, dep, lvl) for n in ('ada', 'ben', 'cy')]
		self.ben_post = Post.objects.create(author=self.ben, content='Buy my exam expo, 100% sure')
		self.cy_post = Post.objects.create(author=self.cy, content='Lecture moved to LT 2')
		self.client.force_login(self.ada)

	def student(self, name, uni, fac, dep, lvl):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	def test_block_hides_both_ways_and_unblock(self):
		Follow.objects.create(follower=self.ada, following=self.ben, status=Follow.STATUS_ACCEPTED)
		Follow.objects.create(follower=self.ben, following=self.ada, status=Follow.STATUS_ACCEPTED)
		self.client.post('/u/ben/block/')
		self.assertTrue(Block.objects.filter(blocker=self.ada, blocked=self.ben).exists())
		self.assertFalse(Follow.objects.exists())                     # follows removed both ways
		home = self.client.get('/home/').content.decode()
		self.assertNotIn('exam expo', home)
		self.assertIn('Lecture moved', home)
		self.assertIn('You blocked @ben', self.client.get('/u/ben/').content.decode())
		self.assertEqual(self.client.get(f'/post/{self.ben_post.pk}/').status_code, 404)
		self.assertEqual(self.client.post(f'/follow/{self.ben.pk}/', HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 403)
		from feed.search import search_people
		self.assertEqual(list(search_people(self.ada, self.ada.student_profile, ['ben'])), [])
		self.assertIn('ben', self.client.get('/settings/?s=security').content.decode())
		# Ben sees nothing of Ada either, and no Unblock button.
		self.client.force_login(self.ben)
		page = self.client.get('/u/ada/').content.decode()
		self.assertIn("This profile isn", page)
		self.assertNotIn('Unblock', page)
		self.assertIsNone(notify(self.ada, self.ben, Notification.LIKE_POST, post=Post.objects.create(author=self.ada, content='hi')))
		# Unblock
		self.client.force_login(self.ada)
		self.client.post('/u/ben/block/')
		self.assertFalse(Block.objects.exists())
		self.assertIn('exam expo', self.client.get('/home/').content.decode())

	def test_cannot_block_self(self):
		self.assertEqual(self.client.post('/u/ada/block/').status_code, 403)

	def test_people_lists_skip_blocked(self):
		from feed.people import people_to_follow
		Block.objects.create(blocker=self.ben, blocked=self.ada)
		self.assertEqual([p.user.username for p in people_to_follow(self.ada)], ['cy'])

	def test_chat_refused(self):
		Block.objects.create(blocker=self.ben, blocked=self.ada)
		r = self.client.post(f'/messages/start/{self.ben.pk}/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		self.assertEqual(r.status_code, 403)

	def test_report_post_hides_it_and_staff_remove(self):
		r = self.client.get(f'/post/{self.ben_post.pk}/report/')
		self.assertContains(r, 'Scam or fraud')
		self.client.post(f'/post/{self.ben_post.pk}/report/', {'reason': 'scam', 'details': 'Selling fake expo'})
		self.client.post(f'/post/{self.ben_post.pk}/report/', {'reason': 'spam'})      # again: updates, not a second report
		self.assertEqual(Report.objects.count(), 1)
		self.assertEqual(Report.objects.get().reason, 'spam')
		self.assertNotIn('exam expo', self.client.get('/home/').content.decode())
		self.client.force_login(self.cy)
		self.client.post(f'/post/{self.ben_post.pk}/report/', {'reason': 'scam', 'also_block': '1'})
		self.assertTrue(Block.objects.filter(blocker=self.cy, blocked=self.ben).exists())
		self.assertEqual(self.client.get('/moderation/').status_code, 403)            # not staff
		self.cy.is_staff = True
		self.cy.save()
		page = self.client.get('/moderation/').content.decode()
		self.assertIn('2 reports', page)
		self.assertIn('Selling fake expo', page)
		self.client.post(f'/moderation/{Report.objects.first().pk}/remove/')
		self.assertFalse(Post.objects.filter(pk=self.ben_post.pk).exists())
		self.assertEqual(set(Report.objects.values_list('status', flat=True)), {Report.REMOVED})
		self.assertIn('exam expo', self.client.get('/moderation/?status=removed').content.decode())

	def test_report_needs_reason_and_not_own_post(self):
		self.client.post(f'/post/{self.ben_post.pk}/report/', {'reason': 'nonsense'})
		self.assertFalse(Report.objects.exists())
		mine = Post.objects.create(author=self.ada, content='mine')
		self.assertEqual(self.client.get(f'/post/{mine.pk}/report/').status_code, 302)

	def test_report_account_and_dismiss(self):
		self.client.post('/u/cy/report/', {'reason': 'impersonation'})
		staff = User.objects.create_user('mod', password='x', is_staff=True)
		self.client.force_login(staff)
		self.assertContains(self.client.get('/moderation/'), 'Pretending to be someone else')
		self.client.post(f'/moderation/{Report.objects.get().pk}/dismiss/')
		self.assertEqual(Report.objects.get().status, Report.DISMISSED)
		self.assertTrue(Post.objects.filter(pk=self.cy_post.pk).exists())
