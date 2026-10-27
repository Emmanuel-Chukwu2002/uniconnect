"""Profile skills (feed/skills.py), search by skill, Explore > People."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import ProfileSkill, SkillEndorsement

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class SkillTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		other = Department.objects.create(faculty=fac, name='Physics')
		olvl = Level.objects.create(department=other, name='100 Level')
		self.ada = self.student('ada', uni, fac, dep, lvl)
		self.ben = self.student('ben', uni, fac, dep, lvl)
		self.cy = self.student('cy', uni, fac, other, olvl)
		self.client.force_login(self.ada)

	def student(self, name, uni, fac, dep, lvl):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	def test_add_remove_and_limits(self):
		r = self.client.post('/profile/skills/add/', {'name': '  Python  '}, **AJAX)
		self.assertIn('Python', r.json()['html'])
		r = self.client.post('/profile/skills/add/', {'name': 'python'}, **AJAX)
		self.assertEqual(r.status_code, 400)
		self.assertIn('already', r.json()['error'])
		for i in range(14):
			ProfileSkill.objects.create(user=self.ada, name=f'Skill {i}')
		self.assertIn('up to 15', self.client.post('/profile/skills/add/', {'name': 'Figma'}, **AJAX).json()['error'])
		skill = ProfileSkill.objects.get(user=self.ada, name='Python')
		self.client.force_login(self.ben)
		self.client.post(f'/profile/skills/{skill.pk}/remove/')       # not his
		self.assertTrue(ProfileSkill.objects.filter(pk=skill.pk).exists())
		self.client.force_login(self.ada)
		self.client.post(f'/profile/skills/{skill.pk}/remove/')
		self.assertFalse(ProfileSkill.objects.filter(pk=skill.pk).exists())

	def test_endorse_and_profile(self):
		skill = ProfileSkill.objects.create(user=self.ada, name='Figma')
		self.assertContains(self.client.get('/profile/'), 'Add a skill')
		self.client.post(f'/profile/skills/{skill.pk}/endorse/', **AJAX)  # can't endorse yourself
		self.assertFalse(SkillEndorsement.objects.exists())
		self.client.force_login(self.ben)
		self.assertEqual(self.client.post(f'/profile/skills/{skill.pk}/endorse/', **AJAX).json(), {'endorsed': True, 'count': 1})
		r = self.client.get('/u/ada/')
		self.assertContains(r, 'Tap a skill to endorse it')
		self.assertNotContains(r, 'Add a skill')
		self.assertEqual(self.client.post(f'/profile/skills/{skill.pk}/endorse/', **AJAX).json(), {'endorsed': False, 'count': 0})

	def test_search_and_explore_people(self):
		ProfileSkill.objects.create(user=self.cy, name='Public speaking')
		ProfileSkill.objects.create(user=self.ben, name='Python')
		r = self.client.get('/search/?q=python&type=people')
		self.assertContains(r, '@ben ·')
		self.assertNotContains(r, '@cy ·')
		r = self.client.get('/explore/?tab=people')
		self.assertContains(r, 'Your classmate')                    # Ben: same department and level, listed first
		html = r.content.decode()
		self.assertLess(html.index('aria-label="Ben"'), html.index('aria-label="Cy"'))
		r = self.client.get('/explore/?tab=people&skill=public speaking')
		self.assertContains(r, 'People who know public speaking')
		self.assertContains(r, 'aria-label="Cy"')
		self.assertNotContains(r, 'aria-label="Ben"')
