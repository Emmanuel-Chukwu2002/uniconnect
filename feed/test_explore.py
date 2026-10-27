"""The Explore page (feed/explore.py)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from communities.models import Community, CommunityMember
from courses.models import Course, CourseEnrollment
from feed.models import Attendee, Event
from studygroups.models import StudyGroup, StudyGroupMember

User = get_user_model()


class ExploreTests(TestCase):
	def setUp(self):
		self.uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		lag = University.objects.create(name='University of Lagos', short_name='UNILAG', email_domain='unilag.edu.ng')
		self.ada = self.student('ada', self.uni)
		self.dee = self.student('dee', lag)
		self.client.force_login(self.ada)

	def student(self, name, uni):
		fac = Faculty.objects.get_or_create(university=uni, name='Sciences')[0]
		dep = Department.objects.get_or_create(faculty=fac, name='Computer Science')[0]
		lvl = Level.objects.get_or_create(department=dep, name='400 Level')[0]
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@{uni.email_domain}')
		return user

	def test_communities_tab_and_join_in_place(self):
		c = Community.objects.create(university=self.dee.student_profile.university, name='Programming', description='Code', topic='tech', created_by=self.dee)
		CommunityMember.objects.create(community=c, user=self.dee, role='admin')
		g = StudyGroup.objects.create(university=self.uni, created_by=self.dee, course_code='COS 401', name='400 Level')
		StudyGroup.objects.create(university=self.uni, created_by=self.dee, name='Secret Room', privacy='invite')
		r = self.client.get('/explore/')
		self.assertContains(r, 'Popular Communities')
		self.assertContains(r, 'Programming')                      # other university's community is shown
		self.assertContains(r, 'COS 401 – 400 Level')
		self.assertNotContains(r, 'Secret Room')
		ajax = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
		self.assertEqual(self.client.post(f'/communities/{c.pk}/join/', **ajax).json()['state'], 'joined')
		self.assertEqual(self.client.post(f'/groups/{g.pk}/join/', **ajax).json()['state'], 'joined')
		self.assertTrue(StudyGroupMember.objects.filter(group=g, user=self.ada).exists())
		self.assertNotContains(self.client.get('/explore/'), 'COS 401 – 400 Level')   # joined groups aren't suggested
		self.assertContains(self.client.get('/explore/'), '>Joined<')

	def test_search_and_other_tabs(self):
		Community.objects.create(university=self.uni, name='Football', description='Sports', topic='sports')
		Community.objects.create(university=self.uni, name='Music', description='Songs', topic='arts')
		r = self.client.get('/explore/?q=foot')
		self.assertContains(r, 'Football')
		self.assertNotContains(r, '>Music<')
		e = Event.objects.create(title='Career Fair', location='Hall', date=timezone.localdate() + timedelta(days=2))
		self.assertContains(self.client.get('/explore/?tab=events'), 'Career Fair')
		r = self.client.post('/events/attend/toggle/', {'event_id': e.pk}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		self.assertTrue(r.json()['registered'])
		self.assertContains(self.client.get('/explore/?tab=events'), '>Going<')
		course = Course.objects.create(university=self.uni, code='COS 401', title='Data Structures')
		self.assertContains(self.client.get('/explore/?tab=courses'), 'COS 401 – Data Structures')
		self.assertEqual(self.client.post(f'/courses/{course.pk}/add/', HTTP_X_REQUESTED_WITH='XMLHttpRequest').json(), {'state': 'added'})
		self.assertTrue(CourseEnrollment.objects.filter(user=self.ada, course=course).exists())
		self.assertNotContains(self.client.get('/explore/?tab=courses'), 'COS 401 – Data Structures')
		self.assertEqual(self.client.get('/explore/?tab=opportunities').status_code, 200)
		self.assertEqual(self.client.get('/explore/?tab=nonsense').status_code, 200)
