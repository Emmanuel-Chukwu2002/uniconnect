"""Hashtag pages and linked #tags / @mentions (feed/hashtags.py, post_text filter)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import Block, Like, Post
from feed.templatetags.post_extras import post_text

User = get_user_model()


class HashtagTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		other = University.objects.create(name='University of Lagos', short_name='UNILAG', email_domain='unilag.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.ada, self.ben, self.cy = [self.student(n, uni, fac, dep, lvl) for n in ('ada', 'ben', 'cy')]
		self.far = self.student('far', other, fac, dep, lvl)
		self.p1 = Post.objects.create(author=self.ben, content='Exams start Monday #ExamSeason #UNN')
		self.p2 = Post.objects.create(author=self.cy, content='Library open till 10 #examseason')
		Post.objects.create(author=self.cy, content='#examseasonal is a different tag')
		Post.objects.create(author=self.far, content='Other school #examseason')
		Like.objects.create(user=self.ada, post=self.p1)
		self.client.force_login(self.ada)

	def student(self, name, uni, fac, dep, lvl):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@{uni.email_domain}')
		return user

	def test_page_matches_whole_tag_at_your_university(self):
		r = self.client.get('/hashtag/examseason/')
		html = r.content.decode()
		self.assertIn('Exams start Monday', html)
		self.assertIn('Library open till 10', html)
		self.assertNotIn('different tag', html)          # #examseasonal isn't #examseason
		self.assertNotIn('Other school', html)           # another university
		self.assertEqual(r.context['total'], 2)
		self.assertEqual(r.context['people'], 2)
		self.assertEqual(r.context['related'], ['unn'])
		self.assertEqual([p.pk for p in r.context['posts']], [self.p1.pk, self.p2.pk])          # Top: most liked first
		latest = self.client.get('/hashtag/examseason/?sort=latest').context['posts']
		self.assertEqual([p.pk for p in latest], [self.p2.pk, self.p1.pk])

	def test_case_and_hash_redirect(self):
		self.assertRedirects(self.client.get('/hashtag/ExamSeason/'), '/hashtag/examseason/')
		self.assertEqual(self.client.get('/hashtag/a/').status_code, 404)

	def test_blocked_left_out(self):
		Block.objects.create(blocker=self.ada, blocked=self.ben)
		self.assertNotIn('Exams start Monday', self.client.get('/hashtag/examseason/').content.decode())

	def test_post_text_links(self):
		html = post_text('Hi @ben and @nobody #Python <b>x</b>\nnext')
		self.assertIn('<a href="/u/ben/" class="post-mention">@ben</a>', html)
		self.assertNotIn('@nobody</a>', html)
		self.assertIn('<a href="/hashtag/python/" class="post-tag">#Python</a>', html)
		self.assertIn('&lt;b&gt;', html)
		self.assertIn('<br>', html)
		self.assertNotIn('post-tag', post_text("it's &#39; a#b"))

	def test_feed_shows_links_and_trending(self):
		self.assertIn('href="/hashtag/examseason/"', self.client.get('/home/').content.decode())
		self.assertIn('href="/hashtag/examseason/"', self.client.get('/explore/').content.decode())
		self.assertIn('href="/hashtag/examseason/"', self.client.get('/search/').content.decode())

	def test_compose_prefill(self):
		self.assertContains(self.client.get('/post/new/?text=%23examseason'), '#examseason </textarea>')
