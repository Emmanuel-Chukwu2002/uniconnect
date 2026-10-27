"""Groups, Opportunities and Course Companion in sections of cards, closest
first, like Who to follow (feed/closeness.py).
Run: python manage.py test feed.test_card_pages"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from courses.models import Course, CourseEnrollment
from opportunities.models import Opportunity, OpportunitySave
from studygroups.models import StudyGroup, StudyGroupMember
from .models import Follow

User = get_user_model()


class CardPageTests(TestCase):
	def setUp(self):
		self.uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		self.sci = Faculty.objects.create(university=self.uni, name='Sciences')
		self.arts = Faculty.objects.create(university=self.uni, name='Arts')
		self.cs = Department.objects.create(faculty=self.sci, name='Computer Science')
		self.phy = Department.objects.create(faculty=self.sci, name='Physics')
		self.eng = Department.objects.create(faculty=self.arts, name='English')
		self.l4 = Level.objects.create(department=self.cs, name='400 Level')
		self.l2 = Level.objects.create(department=self.cs, name='200 Level')
		self.me = self.student('ada', self.cs, self.l4)
		self.mate = self.student('bo', self.cs, self.l4)
		self.junior = self.student('cy', self.cs, self.l2)
		self.physicist = self.student('di', self.phy, Level.objects.create(department=self.phy, name='300 Level'))
		self.writer = self.student('ed', self.eng, Level.objects.create(department=self.eng, name='100 Level'))
		self.client.force_login(self.me)

	def student(self, name, dept, level):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=self.uni, faculty=dept.faculty, department=dept, level=level,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	# --- Groups ----------------------------------------------------------
	def group(self, name, by, **kw):
		g = StudyGroup.objects.create(university=self.uni, created_by=by, name=name, **kw)
		StudyGroupMember.objects.create(group=g, user=by, role='owner')
		return g

	def test_groups_closest_first(self):
		cls = self.group('Our class', self.mate, department=self.cs, level=self.l4)
		dept = self.group('CS everyone', self.junior, department=self.cs)
		fac = self.group('Physics lab', self.physicist, department=self.phy)
		hall = self.group('Eni Njoku Hall', self.writer, group_type='hostel')
		mine = self.group('Mine', self.me, department=self.cs, level=self.l4)
		hidden = self.group('Secret', self.mate, department=self.cs, level=self.l4, privacy='invite')
		Follow.objects.create(follower=self.me, following=self.mate, status=Follow.STATUS_ACCEPTED)
		r = self.client.get('/groups/')
		got = {g['key']: [x.pk for x in g['items']] for g in r.context['groups']}
		self.assertEqual(got, {'mine': [mine.pk], 'class': [cls.pk], 'department': [dept.pk], 'faculty': [fac.pk], 'campus': [hall.pk]})
		html = r.content.decode()
		sections = html[html.index('class="pc-section"'):]                         # below "Recommended for you"
		self.assertLess(sections.index('Your groups'), sections.index('For your class'))   # a group you made shows first, with Open
		self.assertEqual(html.count(f'href="/groups/{mine.pk}/"'), 4)
		self.assertNotIn('Secret', html)
		secret_mine = self.group('My secret', self.me, privacy='invite')
		self.assertIn('My secret', self.client.get('/groups/').content.decode())   # your invite-only groups too
		self.assertIn('1 you follow', html)                          # Bo is in "Our class"
		self.assertIn(f'data-url="/groups/{cls.pk}/join/"', html)
		self.assertLess(html.index('For your class'), html.index('Around UNN'))
		# Join from the card
		r = self.client.post(f'/groups/{cls.pk}/join/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		self.assertEqual(r.json()['state'], 'joined')

	def test_groups_see_all_and_search(self):
		for n in range(5):
			self.group(f'Hall group {n}', self.writer, group_type='hostel')
		r = self.client.get('/groups/')
		self.assertIn('href="?section=campus"', r.content.decode())
		r = self.client.get('/groups/?section=campus')
		self.assertEqual(r.context['total'], 5)
		self.assertEqual(r.content.decode().count('class="pc-card'), 5)
		self.assertEqual(self.client.get('/groups/?q=hall').content.decode().count('class="pc-card'), 5)
		r = self.client.get('/groups/?type=hostel')
		self.assertIn('href="?type=hostel&amp;section=campus"', r.content.decode())

	# --- Opportunities ---------------------------------------------------
	def opp(self, title, by, **kw):
		return Opportunity.objects.create(university=self.uni, posted_by=by, title=title, organization='Acme Ltd',
			description=kw.pop('description', 'Apply now.'), apply_email='jobs@acme.ng', **kw)

	def test_opportunities_closest_first(self):
		course = self.opp('Graduate trainee', self.writer, eligibility='Computer Science students')
		mate = self.opp('Mate shared', self.mate)
		dept = self.opp('Dept shared', self.junior)
		fac = self.opp('Faculty shared', self.physicist)
		far = self.opp('Arts shared', self.writer)
		own = self.opp('My own', self.me)
		Follow.objects.create(follower=self.me, following=self.junior, status=Follow.STATUS_ACCEPTED)
		OpportunitySave.objects.create(user=self.junior, opportunity=far)
		r = self.client.get('/opportunities/')
		got = {g['key']: [x.pk for x in g['items']] for g in r.context['groups']}
		self.assertEqual(got, {'course': [course.pk], 'coursemates': [mate.pk], 'department': [dept.pk],
			'faculty': [fac.pk], 'university': [far.pk]})
		html = r.content.decode()
		self.assertNotIn('My own', html)
		self.assertIn('1 you follow saved this', html)
		self.assertIn('Shared by Bo', html)
		self.assertIn(f'data-url="/opportunities/{mate.pk}/save/"', html)
		r = self.client.post(f'/opportunities/{mate.pk}/save/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		self.assertTrue(r.json()['saved'])
		html = self.client.get('/opportunities/?tab=saved').content.decode()
		self.assertIn('Mate shared', html)
		self.assertIn('> Saved</button>', html)
		self.assertIn('My own', self.client.get('/opportunities/?tab=mine').content.decode())

	# --- Course Companion ------------------------------------------------
	def test_courses_closest_first(self):
		taken = Course.objects.create(university=self.uni, code='STA 341', title='Probability', department=self.cs)
		CourseEnrollment.objects.create(user=self.mate, course=taken)
		dept = Course.objects.create(university=self.uni, code='COS 201', title='Programming', department=self.cs)
		fac = Course.objects.create(university=self.uni, code='PHY 101', title='Mechanics', department=self.phy)
		far = Course.objects.create(university=self.uni, code='ENG 101', title='Use of English', department=self.eng)
		mine = Course.objects.create(university=self.uni, code='COS 401', title='Data Structures', department=self.cs)
		CourseEnrollment.objects.create(user=self.me, course=mine)
		r = self.client.get('/courses/')
		got = {g['key']: [x.pk for x in g['items']] for g in r.context['groups']}
		self.assertEqual(got, {'coursemates': [taken.pk], 'department': [dept.pk], 'faculty': [fac.pk], 'university': [far.pk]})
		self.assertEqual([c.pk for c in r.context['mine']], [mine.pk])
		html = r.content.decode()
		self.assertIn('1 coursemate takes this', html)
		self.assertIn(f'data-url="/courses/{dept.pk}/add/"', html)
		self.assertLess(html.index('My Courses'), html.index('Your coursemates take these'))
