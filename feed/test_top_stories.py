"""Tests for the "Top stories" box and page (run: python manage.py test feed.test_top_stories)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from .models import Bookmark, Comment, Like, Post
from .top_stories import time_ago, top_stories

User = get_user_model()


class TopStoriesTests(TestCase):
	def setUp(self):
		self.unn = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		self.other_uni = University.objects.create(name='Other University', short_name='OU', email_domain='ou.edu.ng')
		self.me = self.student('ada', self.unn)
		self.people = [self.student(f'p{i}', self.unn) for i in range(6)]
		self.outsider = self.student('out', self.other_uni)
		self.client.force_login(self.me)

	def student(self, username, uni):
		user = User.objects.create_user(username, password='x', first_name=username.title())
		fac = Faculty.objects.get_or_create(university=uni, name='Physical Sciences')[0]
		dep = Department.objects.get_or_create(faculty=fac, name='Computer Science')[0]
		lvl = Level.objects.get_or_create(department=dep, name='400 Level')[0]
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=username, university_email=f'{username}@{uni.email_domain}')
		return user

	def post(self, text, author=None, days_old=0, likers=0, commenters=0):
		p = Post.objects.create(author=author or self.people[0], content=text)
		if days_old:
			Post.objects.filter(pk=p.pk).update(created_at=timezone.now() - timedelta(days=days_old))
		for u in self.people[:likers]:
			Like.objects.create(user=u, post=p)
		for u in self.people[:commenters]:
			Comment.objects.create(post=p, author=u, content='Nice')
		return p

	def titles(self):
		return [s['headline'] for s in top_stories(self.me)]

	def test_most_readers_first(self):
		self.post('Quiet post', likers=1)
		self.post('Busy post', likers=5)
		self.post('Middle post', likers=2, commenters=3)
		self.assertEqual(self.titles(), ['Busy post', 'Middle post', 'Quiet post'])

	def test_readers_are_distinct_people(self):
		p = self.post('Read twice', likers=2, commenters=2)
		Bookmark.objects.create(user=self.people[3], post=p)
		story = top_stories(self.me)[0]
		self.assertEqual(story['readers'], 3)
		self.assertEqual(story['readers_text'], '3 readers')

	def test_only_my_university_and_only_engaged_posts(self):
		self.post('Ours', likers=1)
		self.post('No one engaged')
		self.post('Theirs', author=self.outsider, likers=3)
		self.assertEqual(self.titles(), ['Ours'])

	def test_recent_week_wins_when_there_are_enough(self):
		for i in range(4):
			self.post(f'Fresh {i}', likers=1)
		self.post('Old but popular', days_old=20, likers=6)
		self.assertNotIn('Old but popular', self.titles())

	def test_widens_the_window_on_a_quiet_campus(self):
		self.post('Fresh', likers=1)
		self.post('Old but popular', days_old=20, likers=6)
		self.assertEqual(self.titles(), ['Old but popular', 'Fresh'])

	def test_headline_is_first_line_or_photo_label(self):
		self.post('\n  Exam   timetable is out \nsecond line', likers=1)
		self.post('', likers=2)
		self.assertEqual(self.titles(), ['Photo from P0', 'Exam timetable is out'])

	def test_time_ago(self):
		now = timezone.now()
		self.assertEqual(time_ago(now - timedelta(seconds=20), now), 'Just now')
		self.assertEqual(time_ago(now - timedelta(minutes=21), now), '21 min ago')
		self.assertEqual(time_ago(now - timedelta(hours=1, minutes=5), now), '1 hour ago')
		self.assertEqual(time_ago(now - timedelta(hours=5), now), '5 hours ago')
		self.assertEqual(time_ago(now - timedelta(days=2), now), '2 days ago')

	def test_sidebar_box_shows_four_and_show_more(self):
		for i in range(6):
			self.post(f'Story {i}', likers=1)
		page = self.client.get('/bookmarks/').content.decode()
		self.assertIn('<h6>Top stories</h6>', page)
		self.assertEqual(page.count('class="top-story"'), 4)                     # four shown in the box
		self.assertIn('href="/top-stories/" class="top-stories-more', page)        # "Show more" opens the full page
		self.assertLess(page.index('<h6>Events</h6>'), page.index('<h6>Top stories</h6>'))

	def test_no_show_more_without_stories(self):
		page = self.client.get('/bookmarks/').content.decode()
		self.assertNotIn('class="top-stories-more', page)
		self.post('Only one', likers=1)
		page = self.client.get('/bookmarks/').content.decode()
		self.assertIn('class="top-stories-more', page)

	def test_page_lists_stories(self):
		p = self.post('Departmental dinner on Friday', likers=2)
		page = self.client.get('/top-stories/')
		self.assertContains(page, 'Departmental dinner on Friday')
		self.assertContains(page, f'href="/post/{p.pk}/"')
		self.assertContains(page, '2 readers')

	def test_page_trending_cards(self):
		self.post('Revising tonight #ExamSeason #STA341')
		self.post('Who else? #examseason')
		self.post('Demo day #FinalYearProject')
		html = self.client.get('/top-stories/').content.decode()
		self.assertIn('Trending', html)
		self.assertIn('href="/hashtag/examseason/"', html)
		self.assertIn('Exam Season', html)          # CamelCase tags get spaces
		self.assertIn('02 posts', html)
		self.assertIn('bi-pencil-square', html)     # exam → pencil icon
