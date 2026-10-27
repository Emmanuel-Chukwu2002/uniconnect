"""Course Companion (run: python manage.py test courses)."""
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import Notification as N
from studygroups.models import StudyGroup, StudyGroupMember
from .models import Course, CourseAnswer, CourseEnrollment, CourseMaterial, CourseQuestion, normalise_code

User = get_user_model()
MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class CourseTests(TestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(MEDIA, ignore_errors=True)

	def setUp(self):
		self.uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		other = University.objects.create(name='University of Lagos', short_name='UNILAG', email_domain='unilag.edu.ng')
		self.ada, self.ben = (self.student(n, self.uni) for n in ('ada', 'ben'))
		self.far = self.student('far', other)
		self.client.force_login(self.ada)

	def student(self, name, uni):
		fac = Faculty.objects.get_or_create(university=uni, name='Sciences')[0]
		dep = Department.objects.get_or_create(faculty=fac, name='Computer Science')[0]
		lvl = Level.objects.get_or_create(department=dep, name='400 Level')[0]
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@{uni.email_domain}')
		return user

	def test_codes_are_normalised(self):
		self.assertEqual([normalise_code(c) for c in ('cos401', 'COS  401', 'cos-401', 'csc 411l')], ['COS 401'] * 3 + ['CSC 411L'])

	def test_add_search_and_my_courses(self):
		self.client.post('/courses/new/', {'code': 'cos401', 'title': 'Data Structures'})
		c = Course.objects.get()
		self.assertEqual(c.code, 'COS 401')
		self.assertTrue(CourseEnrollment.objects.filter(user=self.ada, course=c).exists())
		r = self.client.get('/courses/')
		self.assertEqual([x.pk for x in r.context['mine']], [c.pk])                      # in My Courses, as a card
		self.assertContains(r, '<p class="pc-sub">Data Structures</p>', html=False)
		self.assertContains(r, '> Open</a>', html=False)
		self.client.post('/courses/new/', {'code': 'COS 401', 'title': 'Duplicate'})     # same code: no second course
		self.assertEqual(Course.objects.count(), 1)
		self.client.force_login(self.ben)
		r = self.client.get('/courses/?q=cos401')
		self.assertContains(r, 'Data Structures')
		self.assertContains(r, '> Add</button>', html=False)
		self.client.post(f'/courses/{c.pk}/add/')
		self.assertEqual(c.enrollments.count(), 2)
		self.assertContains(self.client.get('/courses/?q=MTH 999'), 'value="MTH 999"')     # offer to add it
		self.client.force_login(self.far)                                             # other university
		self.assertEqual(self.client.get(f'/courses/{c.pk}/').status_code, 404)

	def test_notes_and_past_questions(self):
		c = Course.objects.create(university=self.uni, code='COS 401', title='Data Structures')
		self.client.post(f'/courses/{c.pk}/upload/', {'kind': 'notes', 'title': 'Week 1', 'file': SimpleUploadedFile('w1.pdf', b'%PDF-1.4 x')})
		self.client.post(f'/courses/{c.pk}/upload/', {'kind': 'past_question', 'year': '2023', 'file': SimpleUploadedFile('pq.pdf', b'%PDF-1.4 y')})
		self.client.post(f'/courses/{c.pk}/upload/', {'kind': 'notes', 'file': SimpleUploadedFile('virus.exe', b'MZ')})
		self.assertEqual(CourseMaterial.objects.count(), 2)
		pq = CourseMaterial.objects.get(kind='past_question')
		self.assertEqual((pq.year, pq.title), (2023, 'pq'))
		self.assertContains(self.client.get(f'/courses/{c.pk}/?tab=past'), 'pq (2023)')
		self.assertNotContains(self.client.get(f'/courses/{c.pk}/?tab=notes'), 'pq (2023)')
		self.client.force_login(self.ben)
		r = self.client.get(f'/courses/{c.pk}/files/{pq.pk}/')
		self.assertEqual(b''.join(r.streaming_content), b'%PDF-1.4 y')
		pq.refresh_from_db()
		self.assertEqual(pq.downloads, 1)
		self.client.post(f'/courses/{c.pk}/files/{pq.pk}/delete/')                   # not his upload
		self.assertEqual(CourseMaterial.objects.count(), 2)
		self.client.force_login(self.far)
		self.assertEqual(self.client.get(f'/courses/{c.pk}/files/{pq.pk}/').status_code, 404)
		# Quick Access shows files from My Courses only.
		self.client.force_login(self.ada)
		self.assertContains(self.client.get('/courses/my/past/'), 'pq (2023)')
		self.client.force_login(self.ben)
		self.assertContains(self.client.get('/courses/my/past/'), 'Add your courses first')

	def test_questions_answers_and_notification(self):
		c = Course.objects.create(university=self.uni, code='COS 401', title='Data Structures')
		self.client.post(f'/courses/{c.pk}/ask/', {'title': 'How do AVL rotations work?', 'body': 'Stuck on case LR'})
		q = CourseQuestion.objects.get()
		self.client.force_login(self.ben)
		self.client.post(f'/courses/{c.pk}/q/{q.pk}/', {'body': 'Rotate left, then right.'})
		a = CourseAnswer.objects.get()
		n = N.objects.get(recipient=self.ada, type=N.COURSE_ANSWER)
		self.assertEqual(n.course_question, q)
		self.client.post(f'/courses/{c.pk}/q/{q.pk}/accept/{a.pk}/')                 # only the asker can accept
		a.refresh_from_db()
		self.assertFalse(a.is_accepted)
		self.client.force_login(self.ada)
		self.client.post(f'/courses/{c.pk}/q/{q.pk}/accept/{a.pk}/')
		a.refresh_from_db()
		self.assertTrue(a.is_accepted)
		self.assertContains(self.client.get(f'/courses/{c.pk}/?tab=questions'), 'Answered')
		self.assertContains(self.client.get('/notifications/'), 'answered your question')

	def test_study_groups_tab_uses_course_code(self):
		c = Course.objects.create(university=self.uni, code='COS 401', title='Data Structures')
		g = StudyGroup.objects.create(university=self.uni, created_by=self.ben, course_code='COS 401', name='Exam prep')
		StudyGroupMember.objects.create(group=g, user=self.ben, role='owner')
		StudyGroup.objects.create(university=self.uni, created_by=self.ben, course_code='COS 401', name='Secret', privacy='invite')
		r = self.client.get(f'/courses/{c.pk}/?tab=groups')
		self.assertContains(r, 'Exam prep')
		self.assertNotContains(r, 'Secret')
		self.assertContains(r, '/groups/new/?type=academic&amp;code=COS%20401')

	def test_study_groups_page(self):
		from studygroups.models import GroupPost
		cos = Course.objects.create(university=self.uni, code='COS 401', title='Data Structures')
		mth = Course.objects.create(university=self.uni, code='MTH 201', title='Linear Algebra')
		for c in (cos, mth):
			CourseEnrollment.objects.create(user=self.ada, course=c)
		mine = StudyGroup.objects.create(university=self.uni, created_by=self.ada, course_code='COS 401', name='Tree Climbers')
		StudyGroupMember.objects.create(group=mine, user=self.ada, role='owner')
		GroupPost.objects.create(group=mine, author=self.ada, title='AVL rotations', body='Who gets them?')
		pick = StudyGroup.objects.create(university=self.uni, created_by=self.ben, course_code='MTH 201', name='Matrix Crew')
		StudyGroupMember.objects.create(group=pick, user=self.ben, role='owner')
		StudyGroup.objects.create(university=self.uni, created_by=self.ben, group_type='hostel', name='Block C')   # not a study group
		html = self.client.get('/courses/my/groups/').content.decode()
		for text in ('My Study Groups', 'Tree Climbers', 'Recent Activity', 'AVL rotations', 'Leaderboard',
				'Picked For You', 'Matrix Crew', 'Create new study group', '10 points', 'MTH 201'):
			self.assertIn(text, html)
		self.assertNotIn('Block C', html)
		html = self.client.get(f'/courses/my/groups/?course={mth.pk}').content.decode()   # one course
		self.assertIn('Matrix Crew', html)
		self.assertNotIn('Tree Climbers', html)
		self.assertIn('code=MTH%20201', html)

	def test_seed(self):
		from io import StringIO
		from django.core.management import call_command
		call_command('seed_courses', stdout=StringIO())
		self.assertEqual(Course.objects.filter(university=self.uni).count(), 10)
		self.assertTrue(CourseMaterial.objects.exists())
		Course.objects.create(university=self.uni, code='ABC 101', title='Mine', created_by=self.ada)
		call_command('seed_courses', '--reset', stdout=StringIO())
		self.assertTrue(Course.objects.filter(code='ABC 101').exists())             # real courses are kept
