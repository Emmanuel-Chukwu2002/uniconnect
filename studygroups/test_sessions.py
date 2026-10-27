"""Study sessions in a group (studygroups/sessions.py)."""
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from chat.models import Message
from feed.models import Notification as N

from . import sessions as SS
from .models import GroupSession, GroupSessionRSVP as R
from .test_group_chat import Helpers
from .tests import MEDIA

LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


@override_settings(MEDIA_ROOT=MEDIA, CHANNEL_LAYERS=LAYERS)
class SessionTests(Helpers, TestCase):
	def setUp(self):
		Helpers.setUp(self)
		self.g = self.create()
		self.join(self.g, self.ben)
		self.as_user(self.ada)

	def form(self, hours=26, **extra):
		t = timezone.localtime(timezone.now() + timedelta(hours=hours))
		return {'title': 'STA 341 past questions', 'date': t.strftime('%Y-%m-%d'), 'time': t.strftime('%H:%M'),
			'duration': '90', 'place': 'Faculty library, 2nd floor', **extra}

	def test_schedule_tells_the_group(self):
		r = self.client.post(f'/groups/{self.g.pk}/sessions/new/', self.form())
		s = GroupSession.objects.get()
		self.assertRedirects(r, f'/groups/{self.g.pk}/?tab=sessions#s{s.pk}', fetch_redirect_response=False)
		self.assertEqual(s.duration, 90)
		self.assertEqual(R.objects.get(session=s, user=self.ada).status, R.GOING)        # the one who made it is going
		self.assertTrue(N.objects.filter(recipient=self.ben, type=N.GROUP_SESSION, group_session=s).exists())
		self.assertTrue(Message.objects.filter(conversation=self.g.conversation, kind=Message.SYSTEM,
			content__startswith='📅 New study session: STA 341 past questions').exists())
		page = self.client.get(f'/groups/{self.g.pk}/?tab=sessions').content.decode()
		for text in ('STA 341 past questions', 'Faculty library, 2nd floor', '1 going', 'Add to calendar', 'Cancel session'):
			self.assertIn(text, page)
		self.assertIn('Next:', self.client.get(f'/groups/{self.g.pk}/?tab=about').content.decode())

	def test_bad_forms(self):
		url = f'/groups/{self.g.pk}/sessions/new/'
		for bad in ({'title': ''}, {'time': ''}, {'link': 'not a link at all'}):
			self.client.post(url, self.form(**bad))
		self.client.post(url, self.form(hours=-2))                                       # in the past
		self.assertFalse(GroupSession.objects.exists())
		self.as_user(self.cy)                                                            # not a member
		self.assertEqual(self.client.post(url, self.form()).status_code, 404)

	def test_rsvp_and_cancel(self):
		s = SS.create(self.g, self.ada, self.form())
		self.as_user(self.ben)
		self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/rsvp/', {'status': 'maybe'})
		self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/rsvp/', {'status': 'going'})
		self.assertEqual(R.objects.get(session=s, user=self.ben).status, R.GOING)
		self.assertEqual(self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/cancel/').status_code, 404)   # not his
		self.as_user(self.ada)
		self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/cancel/')
		s.refresh_from_db()
		self.assertTrue(s.is_cancelled)
		self.as_user(self.ben)
		self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/rsvp/', {'status': 'no'})
		self.assertEqual(R.objects.get(session=s, user=self.ben).status, R.GOING)       # can't answer a cancelled one

	def test_reminder_30_minutes_before_for_people_coming(self):
		s = SS.create(self.g, self.ada, self.form(hours=0.4))       # in 24 minutes
		R.objects.create(session=s, user=self.ben, status=R.NO)
		made = SS.due_reminders(self.ada)
		self.assertEqual(len(made), 1)
		self.assertIn('Study session in', SS.pop_up(made[0])['title'])
		self.ada._session_reminders_checked = False
		self.assertEqual(SS.due_reminders(self.ada), [])            # only once
		self.assertEqual(SS.due_reminders(self.ben), [])            # said he can't go
		# and through the page's 30-second check
		self.assertTrue(N.objects.filter(recipient=self.ada, type=N.SESSION_REMINDER).exists())

	def test_calendar_file(self):
		s = SS.create(self.g, self.ada, self.form(link='meet.google.com/abc-defg-hij'))
		self.assertEqual(s.link, 'https://meet.google.com/abc-defg-hij')
		r = self.client.get(f'/groups/{self.g.pk}/sessions/{s.pk}/calendar.ics')
		self.assertEqual(r['Content-Type'], 'text/calendar; charset=utf-8')
		body = r.content.decode()
		self.assertIn('BEGIN:VEVENT', body)
		self.assertIn('SUMMARY:STA 341 past questions', body)
		self.assertIn('TRIGGER:-PT30M', body)

	def test_notification_wording_and_link(self):
		from feed.notifications import sentence, target_url
		s = SS.create(self.g, self.ada, self.form())
		n = N.objects.get(recipient=self.ben, type=N.GROUP_SESSION)
		self.assertIn('scheduled a study session in', str(sentence(n.type, [n], [self.ada])))
		self.assertEqual(target_url(n), f'/groups/{self.g.pk}/?tab=sessions#s{s.pk}')


@override_settings(MEDIA_ROOT=MEDIA, CHANNEL_LAYERS=LAYERS)
class SessionEditTests(Helpers, TestCase):
	setUp = SessionTests.setUp
	form = SessionTests.form

	def test_move_it_and_people_coming_are_told(self):
		s = SS.create(self.g, self.ada, self.form())
		R.objects.create(session=s, user=self.ben, status=R.MAYBE)
		N.objects.create(recipient=self.ben, actor=self.ben, type=N.SESSION_REMINDER, group_session=s)   # an old reminder
		r = self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/edit/', self.form(hours=50, place='LT 2'))
		self.assertRedirects(r, f'/groups/{self.g.pk}/?tab=sessions#s{s.pk}', fetch_redirect_response=False)
		s.refresh_from_db()
		self.assertEqual(s.place, 'LT 2')
		n = N.objects.get(recipient=self.ben, type=N.SESSION_CHANGED)
		from feed.notifications import sentence
		self.assertIn('changed the study session', str(sentence(n.type, [n], [self.ada])))
		self.assertFalse(N.objects.filter(group_session=s, type=N.SESSION_REMINDER).exists())     # reminder moves
		note = Message.objects.filter(conversation=self.g.conversation, kind=Message.SYSTEM).last().content
		self.assertTrue(note.startswith('✏️ Study session changed: STA 341 past questions — time:'))
		self.assertIn('place: Faculty library, 2nd floor → LT 2', note)

	def test_title_only_is_quiet(self):
		s = SS.create(self.g, self.ada, self.form())
		R.objects.create(session=s, user=self.ben, status=R.GOING)
		t = timezone.localtime(s.starts_at)
		self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/edit/', self.form(title='STA 341 — bring calculators',
			date=t.strftime('%Y-%m-%d'), time=t.strftime('%H:%M')))
		s.refresh_from_db()
		self.assertEqual(s.title, 'STA 341 — bring calculators')
		self.assertFalse(N.objects.filter(type=N.SESSION_CHANGED).exists())

	def test_only_maker_or_admin_and_not_cancelled(self):
		s = SS.create(self.g, self.ada, self.form())
		self.as_user(self.ben)
		self.assertEqual(self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/edit/', self.form(place='X')).status_code, 404)
		self.as_user(self.ada)
		SS.cancel(s, self.ada)
		self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/edit/', self.form(place='X'))
		s.refresh_from_db()
		self.assertEqual(s.place, 'Faculty library, 2nd floor')


@override_settings(MEDIA_ROOT=MEDIA, CHANNEL_LAYERS=LAYERS)
class SessionAfterTests(Helpers, TestCase):
	"""Attendance and notes once a session has started."""
	setUp = SessionTests.setUp
	form = SessionTests.form

	def started(self):
		s = SS.create(self.g, self.ada, self.form())
		GroupSession.objects.filter(pk=s.pk).update(starts_at=timezone.now() - timedelta(hours=2))
		s.refresh_from_db()
		return s

	def test_not_before_it_starts(self):
		s = SS.create(self.g, self.ada, self.form())
		self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/attended/', {'came': '1'})
		self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/notes/', {'body': 'early'})
		self.assertFalse(s.attendance.exists())
		self.assertFalse(s.notes_shared.exists())
		self.assertNotIn('I was there', self.client.get(f'/groups/{self.g.pk}/?tab=sessions').content.decode())

	def test_i_was_there_and_the_checklist(self):
		s = self.started()
		self.as_user(self.ben)
		self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/attended/', {'came': '1'})
		self.assertEqual(list(s.attendance.values_list('user__username', flat=True)), [self.ben.username])
		self.assertEqual(self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/mark/', {'came': [self.ben.pk]}).status_code, 404)
		self.as_user(self.ada)
		page = self.client.get(f'/groups/{self.g.pk}/?tab=sessions').content.decode()
		self.assertIn('1 came', page)
		self.assertIn('Mark who came', page)
		self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/mark/', {'came': [self.ada.pk, self.cy.pk]})   # Cy isn't a member
		self.assertEqual(list(s.attendance.values_list('user_id', flat=True)), [self.ada.pk])
		self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/attended/', {'came': '0'})
		self.assertFalse(s.attendance.exists())

	def test_share_notes_with_a_file(self):
		from django.core.files.uploadedfile import SimpleUploadedFile
		from .models import GroupFile
		s = self.started()
		self.as_user(self.ben)
		pdf = SimpleUploadedFile('answers.pdf', b'%PDF-1.4 answers', content_type='application/pdf')
		self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/notes/', {'body': 'We did Q1–5. Q3 answer is 0.25.', 'files': [pdf]})
		note = s.notes_shared.get()
		f = GroupFile.objects.get(session_note=note)
		self.assertEqual(f.name, 'answers.pdf')
		page = self.client.get(f'/groups/{self.g.pk}/?tab=sessions').content.decode()
		self.assertIn('Q3 answer is 0.25', page)
		self.assertIn('answers.pdf', page)
		self.assertIn('answers.pdf', self.client.get(f'/groups/{self.g.pk}/?tab=files').content.decode())   # in Files too
		self.assertTrue(Message.objects.filter(conversation=self.g.conversation, content__contains='shared notes (1 file) from the study session').exists())
		# empty notes are refused; only the author or an admin can delete
		self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/notes/', {'body': '  '})
		self.assertEqual(s.notes_shared.count(), 1)
		self.as_user(self.ada)                     # admin
		self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/notes/{note.pk}/delete/')
		self.assertFalse(s.notes_shared.exists())
		self.assertFalse(GroupFile.objects.filter(pk=f.pk).exists())

	def test_cancelled_sessions_have_no_follow_up(self):
		s = self.started()
		SS.cancel(s, self.ada)
		self.client.post(f'/groups/{self.g.pk}/sessions/{s.pk}/attended/', {'came': '1'})
		self.assertFalse(s.attendance.exists())
