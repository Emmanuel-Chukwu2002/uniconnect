"""Opportunities (run: python manage.py test opportunities)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from .models import Opportunity, OpportunitySave

User = get_user_model()


class OpportunityTests(TestCase):
	def setUp(self):
		self.uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		self.other_uni = University.objects.create(name='University of Lagos', short_name='UNILAG', email_domain='unilag.edu.ng')
		self.me = self.student('ada', self.uni)
		self.ben = self.student('ben', self.uni)
		self.far = self.student('far', self.other_uni)
		self.client.force_login(self.me)
		self.today = timezone.localdate()

	def student(self, name, uni):
		fac = Faculty.objects.get_or_create(university=uni, name='Sciences')[0]
		dep = Department.objects.get_or_create(faculty=fac, name='Computer Science')[0]
		lvl = Level.objects.get_or_create(department=dep, name='400 Level')[0]
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@{uni.email_domain}')
		return user

	def opp(self, by=None, uni=None, **kw):
		data = dict(title='Software Intern', organization='Andela', description='Build things', apply_url='https://example.com/apply')
		data.update(kw)
		return Opportunity.objects.create(university=uni or self.uni, posted_by=by or self.ben, **data)

	def test_board_shows_open_ones_from_my_university(self):
		self.opp(title='Open internship')
		self.opp(title='Expired one', deadline=self.today - timedelta(days=1))
		self.opp(title='Closed one', is_closed=True)
		self.opp(title='Other school', uni=self.other_uni, by=self.far)
		html = self.client.get('/opportunities/').content.decode()
		self.assertIn('Open internship', html)
		for hidden in ('Expired one', 'Closed one', 'Other school'):
			self.assertNotIn(hidden, html)
		self.assertIn('Expired one', self.client.get('/opportunities/?closed=1').content.decode())

	def test_filters_search_and_sort(self):
		self.opp(title='Data Scholarship', kind=Opportunity.SCHOLARSHIP, organization='MTN Foundation', deadline=self.today + timedelta(days=30))
		self.opp(title='Remote Design Job', kind=Opportunity.JOB, is_remote=True, deadline=self.today + timedelta(days=2))
		html = self.client.get('/opportunities/?kind=scholarship').content.decode()
		self.assertIn('Data Scholarship', html)
		self.assertNotIn('Remote Design Job', html)
		self.assertIn('Remote Design Job', self.client.get('/opportunities/?remote=1').content.decode())
		self.assertNotIn('Data Scholarship', self.client.get('/opportunities/?remote=1').content.decode())
		self.assertIn('Data Scholarship', self.client.get('/opportunities/?q=mtn').content.decode())
		html = self.client.get('/opportunities/?sort=deadline').content.decode()
		self.assertLess(html.index('Remote Design Job'), html.index('Data Scholarship'))
		self.assertIn('Closes in 2 days', html)

	def test_post_needs_a_way_to_apply_then_edit_close_delete(self):
		data = {'kind': 'internship', 'title': 'ML Intern', 'organization': 'Google', 'description': 'Help with ML'}
		r = self.client.post('/opportunities/new/', data)
		self.assertContains(r, 'Add a link or an email address')
		data['apply_email'] = 'jobs@example.com'
		r = self.client.post('/opportunities/new/', data)
		opp = Opportunity.objects.get(title='ML Intern')
		self.assertRedirects(r, f'/opportunities/{opp.pk}/')
		self.assertEqual((opp.university, opp.posted_by), (self.uni, self.me))
		self.assertContains(self.client.get(r.url), 'Apply Now by email')
		self.client.post(f'/opportunities/{opp.pk}/edit/', {**data, 'title': 'ML Intern 2026'})
		opp.refresh_from_db()
		self.assertEqual(opp.title, 'ML Intern 2026')
		self.client.post(f'/opportunities/{opp.pk}/close/')
		opp.refresh_from_db()
		self.assertTrue(opp.is_closed)
		self.assertContains(self.client.get(f'/opportunities/{opp.pk}/'), 'Applications closed')
		self.client.post(f'/opportunities/{opp.pk}/delete/')
		self.assertFalse(Opportunity.objects.filter(pk=opp.pk).exists())

	def test_only_the_poster_can_change_it_and_other_schools_cant_see_it(self):
		theirs = self.opp(by=self.ben)
		self.assertEqual(self.client.get(f'/opportunities/{theirs.pk}/edit/').status_code, 404)
		self.assertEqual(self.client.post(f'/opportunities/{theirs.pk}/delete/').status_code, 404)
		elsewhere = self.opp(uni=self.other_uni, by=self.far)
		self.assertEqual(self.client.get(f'/opportunities/{elsewhere.pk}/').status_code, 404)

	def test_save_and_saved_tab(self):
		o = self.opp(title='Keep me')
		r = self.client.post(f'/opportunities/{o.pk}/save/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		self.assertEqual(r.json(), {'saved': True, 'count': 1})
		self.assertIn('Keep me', self.client.get('/opportunities/?tab=saved').content.decode())
		self.assertEqual(self.client.post(f'/opportunities/{o.pk}/save/', HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()['saved'], False)
		self.assertFalse(OpportunitySave.objects.exists())

	def test_found_by_site_search(self):
		self.opp(title='Cyber Security Fellowship', kind=Opportunity.FELLOWSHIP)
		html = self.client.get('/search/', {'q': 'cyber'}).content.decode()
		self.assertIn('Cyber Security Fellowship', html)
		self.assertIn('>Opportunities<', html)

	def test_saved_ones_show_on_the_bookmarks_page(self):
		o = self.opp(title='Bookmark me please')
		self.client.post(f'/opportunities/{o.pk}/save/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		html = self.client.get('/bookmarks/?tab=opportunities').content.decode()
		self.assertIn('Bookmark me please', html)
		self.assertIn('1 saved opportunity', html)
		self.assertIn('bi-bookmark-fill', html)
		self.assertIn('Opportunities <span class="bm-count">1</span>', self.client.get('/bookmarks/').content.decode())
