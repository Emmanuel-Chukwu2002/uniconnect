"""Tests for "Who to follow" (run: python manage.py test feed.test_who_to_follow)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from .models import Follow

User = get_user_model()


class WhoToFollowTests(TestCase):
	def setUp(self):
		self.unn = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		other = University.objects.create(name='Other University', short_name='OU', email_domain='ou.edu.ng')
		self.me = self.student('ada', 'Ada', self.unn, 'Computer Science')
		self.others = [self.student(f'p{i:02}', f'Person{i:02}', self.unn, 'Physics') for i in range(25)]
		self.classmate = self.student('zed', 'Zed', self.unn, 'Computer Science')
		self.outsider = self.student('out', 'Outsider', other, 'Physics')
		self.client.force_login(self.me)

	def student(self, username, first, uni, dept):
		user = User.objects.create_user(username, password='x', first_name=first)
		fac = Faculty.objects.get_or_create(university=uni, name='Sciences')[0]
		dep = Department.objects.get_or_create(faculty=fac, name=dept)[0]
		lvl = Level.objects.get_or_create(department=dep, name='400 Level')[0]
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=username, university_email=f'{username}@{uni.email_domain}')
		return user

	def test_sidebar_shows_four_and_links_to_page(self):
		html = self.client.get('/bookmarks/').content.decode()
		# The box is People You May Know now (recommendations/people.py): same rule, same 4 + Show More.
		box = html[html.index('class="right-card-title-link">People You May Know</a>'):]
		self.assertEqual(box.count('class="wtf-row '), 4)
		self.assertIn('href="/people/" class="show-more-link"', box)
		self.assertIn('href="/people/" class="right-card-see-all"', box)
		# Own department first.
		self.assertLess(box.index('Zed'), box.index('Person00'))

	def test_no_show_more_when_four_or_fewer(self):
		for u in self.others[:23]:
			Follow.objects.create(follower=self.me, following=u, status=Follow.STATUS_ACCEPTED)
		html = self.client.get('/bookmarks/').content.decode()
		self.assertNotIn('show-more-link', html)

	def test_page_groups_closest_first(self):
		Follow.objects.create(follower=self.me, following=self.others[0], status=Follow.STATUS_PENDING)
		r = self.client.get('/people/')
		keys = [g['key'] for g in r.context['groups']]
		self.assertEqual(keys, ['pymk', 'coursemates', 'faculty', 'elsewhere'])   # People You May Know first
		g = {g['key']: g for g in r.context['groups']}
		self.assertEqual([p.user for p in g['coursemates']['people']], [self.classmate])
		self.assertEqual(g['faculty']['total'], 24)            # p00 already asked
		self.assertEqual(len(g['faculty']['people']), 3)
		self.assertEqual([p.user for p in g['elsewhere']['people']], [self.outsider])
		html = r.content.decode()
		self.assertEqual(html.count('class="pc-card"'), 5)
		self.assertIn('href="?section=faculty"', html)
		self.assertNotIn('href="?section=coursemates"', html)  # nothing more to see
		self.assertLess(html.index('Your coursemates'), html.index('From your faculty'))
		self.assertNotIn('>Person00<', html)

	def test_mutual_connections_rank_first(self):
		friend = self.others[10]
		Follow.objects.create(follower=self.me, following=friend, status=Follow.STATUS_ACCEPTED)
		Follow.objects.create(follower=friend, following=self.others[20], status=Follow.STATUS_ACCEPTED)
		r = self.client.get('/people/')
		fac = [g for g in r.context['groups'] if g['key'] == 'faculty'][0]
		first = fac['people'][0]
		self.assertEqual(first.user, self.others[20])
		self.assertEqual(first.mutual, 1)
		self.assertIn('1 mutual connection<', r.content.decode())

	def test_see_all_section_pages(self):
		r = self.client.get('/people/?section=faculty')
		self.assertEqual(r.context['section']['key'], 'faculty')
		html = r.content.decode()
		self.assertEqual(html.count('class="pc-card"'), 24)   # 25 in the faculty, 24 a page
		self.assertIn('Page 1 of 2', html)
		self.assertIn('href="?section=faculty&page=2"', html)
		self.assertEqual(self.client.get('/people/?section=faculty&page=2').content.decode().count('class="pc-card"'), 1)
		self.assertIn('groups', self.client.get('/people/?section=nonsense').context)  # unknown: the overview

	def test_search(self):
		html = self.client.get('/people/?q=person07').content.decode()
		self.assertIn('1 result for', html)
		self.assertIn('Person07', html)
		self.assertIn('No one found', self.client.get('/people/?q=nobody').content.decode())
