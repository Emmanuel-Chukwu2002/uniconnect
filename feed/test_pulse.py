"""Campus Pulse (feed/pulse.py) — run: python manage.py test feed.test_pulse"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from chat.models import Conversation, Message
from communities.models import Community, CommunityMember
from courses.models import Course, CourseEnrollment

from .models import Block, Follow, Mute, Notification, PulseInterest, PulseReply, PulseStatus as P, PulseView
from . import pulse

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class CampusPulseTests(TestCase):
	def setUp(self):
		self.unn = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		self.ui = University.objects.create(name='University of Ibadan', short_name='UI', email_domain='ui.edu.ng')
		self.ada, self.ben, self.cy = self.student('ada'), self.student('ben'), self.student('cy')
		self.dee = self.student('dee', self.ui)                     # another university
		self.sta = Course.objects.create(university=self.unn, code='STA 422', title='Design of Experiments')
		CourseEnrollment.objects.create(user=self.ada, course=self.sta)
		self.client.force_login(self.ada)

	def student(self, name, uni=None):
		uni = uni or self.unn
		fac = Faculty.objects.get_or_create(university=uni, name='Sciences')[0]
		dep = Department.objects.get_or_create(faculty=fac, name='Statistics')[0]
		lvl = Level.objects.get_or_create(department=dep, name='400 Level')[0]
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@{uni.email_domain}')
		return user

	def make(self, user, kind=P.CAMPUS, text='Hello campus', audience=P.UNIVERSITY, **kw):
		now = timezone.now()
		return P.objects.create(user=user, kind=kind, text=text, audience=audience,
			university=user.student_profile.university, expires_at=kw.pop('expires_at', now + timedelta(hours=24)), **kw)

	def ids(self, user):
		return {c['status'].pk for c in pulse.bar_for(User.objects.get(pk=user.pk))['circles']}   # fresh: blocks are cached per user object

	# --- Home ---------------------------------------------------------------
	def test_home_shows_pulse_instead_of_quick_access(self):
		self.make(self.ben, P.STUDY, 'Reading STA 422 tonight')
		html = self.client.get('/home/').content.decode()
		self.assertIn('Campus Pulse', html)
		self.assertIn("What's happening around your university?", html)
		self.assertIn('Your Update', html)
		self.assertIn('data-kind="study"', html)
		self.assertNotIn('aria-label="Quick access"', html)
		self.assertNotIn('Campus Pulse', self.client.get('/home/?tab=media').content.decode())

	# --- Posting ------------------------------------------------------------
	def test_post_each_type(self):
		day = (timezone.localdate() + timedelta(days=2)).isoformat()
		self.client.post('/pulse/new/', {'kind': 'study', 'text': 'Anyone free to explain BIBD?', 'course': self.sta.pk,
			'topic': 'Design of Experiments', 'audience': 'university'})
		self.client.post('/pulse/new/', {'kind': 'question', 'text': 'Has COS 401 moved?', 'audience': 'university'})
		self.client.post('/pulse/new/', {'kind': 'event', 'event_title': 'Django Workshop', 'event_place': 'CS Dept',
			'event_date': day, 'event_time': '16:00', 'audience': 'everyone'})
		self.client.post('/pulse/new/', {'kind': 'available', 'activity': 'study', 'hours': '3', 'course': self.sta.pk, 'audience': 'university'})
		self.client.post('/pulse/new/', {'kind': 'opportunity', 'text': 'Coding challenge', 'link': 'example.com/c', 'audience': 'everyone'})
		self.client.post('/pulse/new/', {'kind': 'people', 'text': 'Two people for a Django project', 'audience': 'university'})
		self.client.post('/pulse/new/', {'kind': 'campus', 'text': 'Great day on campus', 'audience': 'university'})
		by = {s.kind: s for s in P.objects.all()}
		self.assertEqual(set(by), {k for k, _ in P.KIND_CHOICES})
		now = timezone.now()
		self.assertEqual((by['study'].course, by['study'].topic), (self.sta, 'Design of Experiments'))
		self.assertAlmostEqual((by['study'].expires_at - now).total_seconds(), 24 * 3600, delta=60)
		self.assertAlmostEqual((by['question'].expires_at - now).total_seconds(), 48 * 3600, delta=60)
		self.assertAlmostEqual((by['available'].expires_at - now).total_seconds(), 3 * 3600, delta=60)
		self.assertEqual(by['event'].expires_at, by['event'].event_at + pulse.EVENT_AFTER)
		self.assertEqual(by['opportunity'].link, 'https://example.com/c')
		self.assertEqual(by['study'].university, self.unn)

	def test_bad_posts_are_refused(self):
		yesterday = (timezone.localdate() - timedelta(days=2)).isoformat()
		other = Course.objects.create(university=self.unn, code='COS 401', title='Data Structures')   # not taking it
		comm = Community.objects.create(university=self.unn, name='Coders', description='x')            # not a member
		for data in [
			{'kind': 'question', 'text': '', 'audience': 'university'},
			{'kind': 'event', 'event_title': 'Old', 'event_date': yesterday, 'audience': 'university'},
			{'kind': 'available', 'audience': 'university'},
			{'kind': 'study', 'text': 'x', 'course': other.pk, 'audience': 'university'},
			{'kind': 'campus', 'text': 'x', 'audience': 'communities', 'community': comm.pk},
		]:
			self.client.post('/pulse/new/', data)
		self.assertFalse(P.objects.exists())

	# --- Who sees what ------------------------------------------------------
	def test_audiences_blocks_mutes_and_expiry(self):
		uni = self.make(self.ben, text='UNN only')
		everyone = self.make(self.dee, audience=P.EVERYONE, text='National coding competition')
		ui_only = self.make(self.dee, text='UI only')
		comm = Community.objects.create(university=self.unn, name='Coders', description='x')
		CommunityMember.objects.create(community=comm, user=self.ben)
		in_comm = self.make(self.ben, audience=P.COMMUNITIES, community=comm, text='Coders only')
		old = self.make(self.ben, expires_at=timezone.now() - timedelta(minutes=1))
		off = self.make(self.ben, is_active=False)

		self.assertEqual(self.ids(self.ada), {uni.pk, everyone.pk})
		self.assertEqual(self.ids(self.dee), {everyone.pk, ui_only.pk})
		CommunityMember.objects.create(community=comm, user=self.ada)
		self.assertIn(in_comm.pk, self.ids(self.ada))
		for s in (ui_only, old, off):
			self.assertEqual(self.client.get(f'/pulse/{s.pk}/', **AJAX).status_code, 404)
		self.assertEqual(self.client.get(f'/pulse/{everyone.pk}/', **AJAX).status_code, 200)

		Block.objects.create(blocker=self.ben, blocked=self.ada)
		self.assertNotIn(uni.pk, self.ids(self.ada))
		Mute.objects.create(muter=self.ada, muted=self.dee)
		self.assertNotIn(everyone.pk, self.ids(self.ada))

	def test_bar_order_and_scopes(self):
		cy = self.make(self.cy, text='from my uni')
		dee = self.make(self.dee, audience=P.EVERYONE)
		ben = self.make(self.ben, text='someone I follow')
		mine = self.make(self.ada)
		Follow.objects.create(follower=self.ada, following=self.ben, status=Follow.STATUS_ACCEPTED)
		PulseView.objects.create(status=cy, viewer=self.ada)
		circles = pulse.bar_for(self.ada)['circles']
		self.assertEqual([c['status'].pk for c in circles], [mine.pk, ben.pk, cy.pk, dee.pk])
		self.assertTrue(circles[2]['seen'])
		self.assertEqual(circles[3]['scopes'], 'all')               # other university: only under Everyone
		self.assertIn('uni', circles[1]['scopes'])

	# --- Actions ------------------------------------------------------------
	def test_question_quick_answers_replies_and_answered(self):
		q = self.make(self.ben, P.QUESTION, 'Has COS 401 moved?', expires_at=timezone.now() + timedelta(hours=48))
		self.client.post(f'/pulse/{q.pk}/answer/', {'answer': 'yes'}, **AJAX)
		self.client.post(f'/pulse/{q.pk}/answer/', {'answer': 'no'}, **AJAX)          # changes, not adds
		self.assertEqual(list(PulseReply.objects.values_list('answer', flat=True)), ['no'])
		# A written reply goes privately to the author's Messages, not onto the update.
		r = self.client.post(f'/pulse/{q.pk}/reply/', {'text': 'Yes, to LT2'}, **AJAX)
		self.assertTrue(r.json()['sent'])
		from chat.models import Message
		msg = Message.objects.get(sender=self.ada)
		self.assertIn('Yes, to LT2', msg.content)
		self.assertIn('Has COS 401 moved?', msg.content)
		self.assertTrue(msg.conversation.participants.filter(user=self.ben).exists())
		self.assertFalse(PulseReply.objects.filter(text='Yes, to LT2').exists())
		self.assertNotIn('Yes, to LT2', self.client.get(f'/pulse/{q.pk}/', **AJAX).content.decode())
		self.assertEqual(Notification.objects.filter(recipient=self.ben, type=Notification.PULSE_REPLY).count(), 1)   # the quick answer
		self.client.post(f'/pulse/{q.pk}/answer/', {'answer': 'no'}, **AJAX)          # tapping again removes it
		self.assertFalse(PulseReply.objects.exclude(answer='').exists())

		self.assertEqual(self.client.post(f'/pulse/{q.pk}/answered/', **AJAX).status_code, 403)   # only the author
		self.client.force_login(self.ben)
		self.client.post(f'/pulse/{q.pk}/answered/', **AJAX)
		q.refresh_from_db()
		self.assertTrue(q.is_answered)
		self.assertLessEqual(q.expires_at, timezone.now() + pulse.ANSWERED_LINGER)

	def test_interest_and_connect_open_a_chat(self):
		ev = self.make(self.ben, P.EVENT, '', event_title='Django Workshop', event_at=timezone.now() + timedelta(hours=5))
		self.client.post(f'/pulse/{ev.pk}/interest/', **AJAX)
		self.assertTrue(PulseInterest.objects.filter(status=ev, user=self.ada).exists())
		self.assertTrue(Notification.objects.filter(recipient=self.ben, type=Notification.PULSE_INTEREST).exists())
		self.client.post(f'/pulse/{ev.pk}/interest/', **AJAX)
		self.assertFalse(PulseInterest.objects.exists())

		study = self.make(self.ben, P.STUDY, 'BIBD help?', course=self.sta, topic='Design of Experiments')
		r = self.client.post(f'/pulse/{study.pk}/connect/', {'action': 'together'}, **AJAX)
		conv = Conversation.objects.get(kind=Conversation.DIRECT)
		self.assertEqual(r.json()['url'], f'/messages/c/{conv.pk}/')
		msg = Message.objects.get(conversation=conv)
		self.assertIn('STA 422', msg.content)
		self.assertIn('study together', msg.content)
		self.client.post(f'/pulse/{study.pk}/connect/', {'action': 'message'}, **AJAX)   # just opens the chat
		self.assertEqual(Message.objects.filter(conversation=conv).count(), 1)

		avail = self.make(self.ben, P.AVAILABLE, '', activity='coding')
		self.client.post(f'/pulse/{avail.pk}/connect/', {'action': 'join'}, **AJAX)
		self.assertIn('a coding session', Message.objects.latest('pk').content)

	def test_author_tools(self):
		mine = self.make(self.ada, P.AVAILABLE, '', activity='study')
		self.client.force_login(self.ben)
		self.client.post(f'/pulse/{mine.pk}/seen/', **AJAX)
		self.assertEqual(self.client.post(f'/pulse/{mine.pk}/remove/', **AJAX).status_code, 404)   # not theirs
		self.client.force_login(self.ada)
		html = self.client.get(f'/pulse/{mine.pk}/', **AJAX).json()['html']
		self.assertIn('Seen by 1', html)
		self.assertIn('Turn off', html)
		self.client.post(f'/pulse/{mine.pk}/remove/', **AJAX)
		self.assertNotIn(mine.pk, self.ids(self.ada))

	def test_notification_opens_the_update_page(self):
		s = self.make(self.ada, P.QUESTION, 'Lecture moved?')
		self.client.force_login(self.ben)
		self.client.post(f'/pulse/{s.pk}/answer/', {'answer': 'not_sure'}, **AJAX)        # a quick answer still notifies
		self.client.force_login(self.ada)
		n = Notification.objects.get(recipient=self.ada)
		self.assertRedirects(self.client.get(f'/notifications/{n.pk}/open/'), f'/pulse/{s.pk}/', fetch_redirect_response=False)
		page = self.client.get(f'/pulse/{s.pk}/').content.decode()
		self.assertIn('Lecture moved?', page)
		self.assertIn('replied to your Campus Pulse', self.client.get('/notifications/').content.decode())
