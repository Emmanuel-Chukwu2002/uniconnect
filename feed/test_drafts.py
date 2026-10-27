"""Drafts (feed/drafts.py)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import Post, PostDraft

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class DraftTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.ada, self.ben = [self.student(n, uni, fac, dep, lvl) for n in ('ada', 'ben')]
		self.client.force_login(self.ada)

	def student(self, name, uni, fac, dep, lvl):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	def test_save_update_open_and_post(self):
		r = self.client.post('/post/drafts/save/', {'content': 'Half-written thought', 'poll': '1', 'poll_option_1': 'Yes',
			'poll_option_2': 'No', 'poll_days': '3', 'location': 'Main  Library'}, **AJAX).json()
		d = PostDraft.objects.get()
		self.assertEqual(r['id'], d.pk)
		self.assertEqual((d.poll_options, d.poll_days, d.location), (['Yes', 'No'], 3, 'Main Library'))
		self.client.post('/post/drafts/save/', {'content': 'Half-written thought, finished', 'draft_id': d.pk}, **AJAX)
		self.assertEqual(PostDraft.objects.count(), 1)                         # updated, not duplicated
		self.assertContains(self.client.get('/post/drafts/'), 'Half-written thought, finished')
		page = self.client.get(f'/post/new/?draft={d.pk}').content.decode()
		self.assertIn('Half-written thought, finished</textarea>', page)
		self.assertIn(f'name="draft_id" value="{d.pk}"', page)
		self.client.post('/post/new/', {'content': 'Half-written thought, finished', 'draft_id': d.pk})
		self.assertTrue(Post.objects.filter(content='Half-written thought, finished').exists())
		self.assertFalse(PostDraft.objects.exists())                          # posted: draft gone

	def test_empty_not_saved_and_private(self):
		self.assertEqual(self.client.post('/post/drafts/save/', {'content': '  '}, **AJAX).status_code, 400)
		d = PostDraft.objects.create(user=self.ben, content='bens secret')
		self.client.post('/post/drafts/save/', {'content': 'hijack', 'draft_id': d.pk}, **AJAX)
		d.refresh_from_db()
		self.assertEqual(d.content, 'bens secret')                            # someone else's id: a new draft instead
		self.assertNotIn('bens secret', self.client.get('/post/drafts/').content.decode())
		self.assertEqual(self.client.post(f'/post/drafts/{d.pk}/delete/').status_code, 404)
		self.assertNotIn('bens secret', self.client.get(f'/post/new/?draft={d.pk}').content.decode())

	def test_tabs(self):
		html = self.client.get('/post/scheduled/').content.decode()
		self.assertIn('Unsent posts', html)
		self.assertIn('Nothing scheduled', html)
		self.assertIn('No drafts', self.client.get('/post/drafts/').content.decode())

	def test_photos_and_schedule_kept(self):
		import io, json, shutil, tempfile
		from datetime import timedelta
		from django.core.files.uploadedfile import SimpleUploadedFile
		from django.test import override_settings
		from django.utils import timezone
		from PIL import Image
		tmp = tempfile.mkdtemp()
		self.addCleanup(shutil.rmtree, tmp, True)

		def png(name):
			buf = io.BytesIO(); Image.new('RGB', (4, 4), 'red').save(buf, 'PNG')
			return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')
		when = timezone.localtime(timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')
		with override_settings(MEDIA_ROOT=tmp):
			r = self.client.post('/post/drafts/save/', {'content': 'With pictures', 'schedule_at': when,
				'media': [png('a.png'), png('b.png')]}, **AJAX)
			self.assertEqual(r.status_code, 200)
			d = PostDraft.objects.get()
			self.assertEqual([m.name for m in d.media.all()], ['a.png', 'b.png'])
			self.assertEqual(timezone.localtime(d.schedule_at).strftime('%Y-%m-%dT%H:%M'), when)
			html = self.client.get('/post/drafts/').content.decode()
			self.assertIn('2 photos', html)
			self.assertIn('To go out', html)
			data = json.loads(html.split(f'id="draft-data-{d.pk}" type="application/json">')[1].split('</script>')[0])
			self.assertEqual((data['schedule_at'], len(data['media']), data['media'][0]['type']), (when, 2, 'image/png'))
			# Saving again replaces the photos (the composer sends them all) and drops a time that was cleared.
			self.client.post('/post/drafts/save/', {'content': 'With pictures', 'draft_id': d.pk, 'media': [png('c.png')]}, **AJAX)
			d.refresh_from_db()
			self.assertEqual([m.name for m in d.media.all()], ['c.png'])
			self.assertIsNone(d.schedule_at)
			# Photos alone are enough to save; a video with photos isn't allowed.
			self.assertEqual(self.client.post('/post/drafts/save/', {'media': [png('d.png')]}, **AJAX).status_code, 200)
			bad = self.client.post('/post/drafts/save/', {'content': 'x', 'media': [png('e.png'),
				SimpleUploadedFile('v.mp4', b'0000', content_type='video/mp4')]}, **AJAX)
			self.assertEqual(bad.status_code, 400)
			d.delete()                                                         # files go with it
