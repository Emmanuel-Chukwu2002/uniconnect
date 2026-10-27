"""Admin dashboard: access, university scoping, the report workflow, account actions,
universities, announcements, roles, audit log and statistics.
Run: python manage.py test adminpanel"""
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import Comment, Like, Listing, Post, Report

from . import services, stats
from .content import KINDS
from .models import AccountAction, AdminLog, AdminRole, Announcement
from .permissions import admin_for

User = get_user_model()


class Base(TestCase):
	def setUp(self):
		self.unn = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		self.ui = University.objects.create(name='University of Ibadan', short_name='UI', email_domain='ui.edu.ng')
		self.ada, self.ben = self.student('ada', self.unn), self.student('ben', self.unn)
		self.eve = self.student('eve', self.ui)
		self.root = User.objects.create_superuser('root', 'root@x.com', 'x')
		self.uniadmin = self.student('uadmin', self.unn)
		AdminRole.objects.create(user=self.uniadmin, role=AdminRole.UNIVERSITY_ADMIN, university=self.unn)
		self.mod = self.student('mod', self.unn)
		AdminRole.objects.create(user=self.mod, role=AdminRole.MODERATOR)
		self.support = self.student('help', self.unn)
		AdminRole.objects.create(user=self.support, role=AdminRole.SUPPORT, university=self.unn)

	def student(self, name, uni):
		fac = Faculty.objects.get_or_create(university=uni, name='Sciences')[0]
		dep = Department.objects.get_or_create(faculty=fac, name='Computer Science')[0]
		lvl = Level.objects.get_or_create(department=dep, name='400 Level')[0]
		u = User.objects.create_user(name, password='x', first_name=name.title(), email=f'{name}@x.com')
		StudentProfile.objects.create(user=u, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name.upper(), university_email=f'{name}@{uni.email_domain}')
		return u

	def as_(self, user):
		self.client.force_login(user)
		return self.client


class AccessTests(Base):
	def test_who_gets_in(self):
		self.assertEqual(self.as_(self.ada).get('/staff/').status_code, 403)          # students
		self.client.logout()
		self.assertEqual(self.client.get('/staff/').status_code, 302)                  # sign in first
		for u in (self.root, self.uniadmin, self.mod, self.support):
			self.assertEqual(self.as_(u).get('/staff/').status_code, 200, u)
		staff = User.objects.create_user('oldstaff', password='x', is_staff=True)
		self.assertEqual(admin_for(staff).role, AdminRole.MODERATOR)                  # staff before roles: moderator
		self.assertEqual(admin_for(self.root).role, AdminRole.SUPER_ADMIN)

	def test_role_permissions_are_enforced_server_side(self):
		self.assertEqual(self.as_(self.support).get('/staff/reports/').status_code, 403)
		self.assertEqual(self.as_(self.support).get('/staff/moderation/').status_code, 403)
		self.assertEqual(self.as_(self.mod).get('/staff/logs/').status_code, 403)
		self.assertEqual(self.as_(self.mod).post('/staff/universities/', {'name': 'X', 'short_name': 'X', 'email_domain': 'x.edu'}).status_code, 403)
		r = self.as_(self.mod).post(f'/staff/users/{self.ben.pk}/action/', {'action': 'suspend', 'reason': 'x'})
		self.assertEqual(r.status_code, 403)                                         # moderators can't suspend
		self.assertTrue(User.objects.get(pk=self.ben.pk).is_active)
		html = self.as_(self.mod).get('/staff/').content.decode()
		self.assertNotIn('Admin Logs', html)                                          # nor see what they can't use

	def test_private_details_only_for_roles_that_need_them(self):
		self.assertNotIn('ben@unn.edu.ng', self.as_(self.mod).get(f'/staff/users/{self.ben.pk}/').content.decode())
		self.assertIn('ben@unn.edu.ng', self.as_(self.support).get(f'/staff/users/{self.ben.pk}/').content.decode())


class ScopeTests(Base):
	def test_university_admin_sees_only_their_university(self):
		c = self.as_(self.uniadmin)
		self.assertEqual(c.get(f'/staff/users/{self.eve.pk}/').status_code, 404)
		self.assertEqual(c.get(f'/staff/universities/{self.ui.pk}/').status_code, 404)
		html = c.get('/staff/users/').content.decode()
		self.assertIn('@ben', html)
		self.assertNotIn('@eve', html)
		eve_post = Post.objects.create(author=self.eve, content='UI post')
		self.assertEqual(c.post(f'/staff/content/posts/{eve_post.pk}/remove/', {'reason': 'x'}).status_code, 404)
		self.assertTrue(Post.objects.filter(pk=eve_post.pk).exists())
		r = services.file_report(self.ada, KINDS['posts'], eve_post, 'spam')
		self.assertEqual(c.get(f'/staff/reports/{r.pk}/').status_code, 404)
		self.assertEqual(self.as_(self.root).get(f'/staff/reports/{r.pk}/').status_code, 200)


class ReportWorkflowTests(Base):
	def test_students_report_any_kind_into_one_queue(self):
		listing = Listing.objects.create(seller=self.ben, title='Phone', price=1)
		c = self.as_(self.ada)
		c.post(f'/report/listing/{listing.pk}/', {'reason': 'scam', 'details': 'Asked for payment first'})
		c.post(f'/report/listing/{listing.pk}/', {'reason': 'scam'})                 # again: same report, updated
		r = Report.objects.get()
		self.assertEqual((r.target_type, r.target_id, r.reported_user, r.university, r.target_label),
			('listing', listing.pk, self.ben, self.unn, 'Phone'))
		self.assertEqual(r.details, 'Asked for payment first')
		self.assertEqual(c.get(f'/report/listing/{listing.pk}/').status_code, 200)
		self.assertEqual(self.as_(self.ben).get(f'/report/listing/{listing.pk}/').status_code, 302)   # not your own
		comment = Comment.objects.create(post=Post.objects.create(author=self.ada, content='p'), author=self.ben, content='rude')
		self.as_(self.ada).post(f'/report/comment/{comment.pk}/', {'reason': 'harassment'})
		self.assertTrue(Report.objects.filter(target_type='comment', target_id=comment.pk).exists())
		self.assertEqual(self.client.get('/report/spaceship/1/').status_code, 404)

	def test_review_then_remove_closes_every_report_and_keeps_the_text(self):
		post = Post.objects.create(author=self.ben, content='Something nasty')
		r1 = services.file_report(self.ada, KINDS['posts'], post, 'harassment')
		r2 = services.file_report(self.eve, KINDS['posts'], post, 'hate')
		c = self.as_(self.mod)
		c.post(f'/staff/reports/{r1.pk}/action/', {'action': 'review'})
		r1.refresh_from_db()
		self.assertEqual((r1.status, r1.assigned_to), (Report.REVIEWING, self.mod))
		c.post(f'/staff/reports/{r1.pk}/action/', {'action': 'remove'})                # no reason: refused
		self.assertTrue(Post.objects.filter(pk=post.pk).exists())
		c.post(f'/staff/reports/{r1.pk}/action/', {'action': 'remove', 'reason': 'Harassment of a classmate'})
		self.assertFalse(Post.objects.filter(pk=post.pk).exists())
		for r in Report.objects.all():
			self.assertEqual((r.status, r.reviewed_by, r.decision_reason, r.post_snapshot),
				(Report.REMOVED, self.mod, 'Harassment of a classmate', 'Something nasty'))
		self.assertTrue(AdminLog.objects.filter(action='report.remove', actor=self.mod).exists())

	def test_dismiss_and_warn_owner(self):
		post = Post.objects.create(author=self.ben, content='fine')
		r = services.file_report(self.ada, KINDS['posts'], post, 'spam')
		self.as_(self.mod).post(f'/staff/reports/{r.pk}/action/', {'action': 'dismiss', 'reason': 'Not spam'})
		r.refresh_from_db()
		self.assertEqual(r.status, Report.DISMISSED)
		self.assertTrue(Post.objects.filter(pk=post.pk).exists())                     # a report alone deletes nothing
		r2 = services.file_report(self.ada, KINDS['users'], self.ben, 'impersonation')
		self.as_(self.mod).post(f'/staff/reports/{r2.pk}/action/', {'action': 'warn', 'reason': 'Pretending to be the course rep'})
		r2.refresh_from_db()
		self.assertEqual(r2.status, Report.ACTIONED)
		w = AccountAction.objects.get(user=self.ben, kind=AccountAction.WARNING)
		self.assertEqual(w.report, r2)


class AccountActionTests(Base):
	def test_suspend_signs_out_blocks_and_reactivates(self):
		c = self.as_(self.uniadmin)
		c.post(f'/staff/users/{self.ben.pk}/action/', {'action': 'suspend', 'reason': 'Repeated scams', 'days': '3'})
		ben = User.objects.get(pk=self.ben.pk)
		self.assertFalse(ben.is_active)
		self.assertFalse(self.client.login(username='ben', password='x'))
		self.assertEqual(stats.overview_cards(admin_for(self.root), 7)[4]['value'], 1)  # Suspended Accounts
		AccountAction.objects.filter(user=ben).update(ends_at=timezone.now() - timedelta(minutes=1))
		self.assertEqual(services.lift_expired(), 1)
		self.assertTrue(User.objects.get(pk=self.ben.pk).is_active)
		c = self.as_(self.uniadmin)
		c.post(f'/staff/users/{self.ben.pk}/action/', {'action': 'suspend', 'reason': 'Again'})
		c.post(f'/staff/users/{self.ben.pk}/action/', {'action': 'reactivate', 'reason': 'Appeal accepted'})
		self.assertTrue(User.objects.get(pk=self.ben.pk).is_active)
		self.assertEqual(list(AdminLog.objects.filter(target_id=self.ben.pk).values_list('action', flat=True)),
			['user.reactivate', 'user.suspend', 'user.suspend'])

	def test_protected_accounts_and_reasons(self):
		c = self.as_(self.uniadmin)
		c.post(f'/staff/users/{self.mod.pk}/action/', {'action': 'suspend', 'reason': 'x'})          # another admin
		c.post(f'/staff/users/{self.uniadmin.pk}/action/', {'action': 'suspend', 'reason': 'x'})     # yourself
		c.post(f'/staff/users/{self.ben.pk}/action/', {'action': 'suspend', 'reason': ''})          # no reason
		self.assertFalse(AccountAction.objects.exists())

	def test_warning_banner_until_acknowledged(self):
		services.warn(self.root, self.ben, 'Please keep the Marketplace for real items.')
		c = self.as_(self.ben)
		html = c.get('/home/').content.decode()
		self.assertIn('Please keep the Marketplace for real items.', html)
		w = AccountAction.objects.get()
		self.as_(self.ada).post(f'/staff/notice/{w.pk}/ok/')                    # someone else can't acknowledge it
		self.assertIsNone(AccountAction.objects.get().acknowledged_at)
		self.as_(self.ben).post(f'/staff/notice/{w.pk}/ok/')
		self.assertNotIn('Please keep the Marketplace', self.as_(self.ben).get('/home/').content.decode())


class UniversityAnnouncementRoleTests(Base):
	def test_universities_and_structure(self):
		self.as_(self.root).post('/staff/universities/', {'name': 'University of Lagos', 'short_name': 'UNILAG', 'email_domain': 'unilag.edu.ng'})
		lag = University.objects.get(short_name='UNILAG')
		self.assertFalse(lag.is_active)                                                # not open until set up
		self.as_(self.uniadmin).post(f'/staff/universities/{self.unn.pk}/', {'what': 'faculty', 'name': 'Engineering'})
		self.assertTrue(self.unn.faculties.filter(name='Engineering').exists())
		self.assertEqual(self.as_(self.uniadmin).post(f'/staff/universities/{self.unn.pk}/', {'what': 'update', 'name': 'X'}).status_code, 403)
		self.assertTrue(AdminLog.objects.filter(action='university.create').exists())

	def test_announcements_reach_the_right_students(self):
		self.as_(self.root).post('/staff/announcements/', {'title': 'Maintenance Saturday', 'body': 'Down 2-4am', 'audience': 'everyone', 'kind': 'maintenance'})
		self.as_(self.uniadmin).post('/staff/announcements/', {'title': 'UNN exam week', 'body': 'Good luck', 'audience': 'everyone'})
		unn = Announcement.objects.get(title='UNN exam week')
		self.assertEqual((unn.audience, unn.university), (Announcement.UNIVERSITY, self.unn))   # can't post globally
		ada = self.as_(self.ada).get('/home/').content.decode()
		eve = self.as_(self.eve).get('/home/').content.decode()
		self.assertIn('Maintenance Saturday', ada)
		self.assertIn('UNN exam week', ada)
		self.assertIn('Maintenance Saturday', eve)
		self.assertNotIn('UNN exam week', eve)
		self.as_(self.root).post(f'/staff/announcements/{unn.pk}/action/', {'action': 'unpublish'})
		self.assertNotIn('UNN exam week', self.as_(self.ada).get('/home/').content.decode())

	def test_roles(self):
		c = self.as_(self.uniadmin)
		c.post('/staff/settings/', {'what': 'assign', 'user': 'ada', 'role': 'moderator'})
		self.assertEqual((AdminRole.objects.get(user=self.ada).role, AdminRole.objects.get(user=self.ada).university), ('moderator', self.unn))
		c.post('/staff/settings/', {'what': 'assign', 'user': 'ben', 'role': 'super_admin'})
		c.post('/staff/settings/', {'what': 'assign', 'user': 'eve', 'role': 'moderator'})               # other university
		self.assertFalse(AdminRole.objects.filter(user__in=[self.ben, self.eve]).exists())
		self.assertEqual(self.as_(self.mod).post('/staff/settings/', {'what': 'assign', 'user': 'ben', 'role': 'moderator'}).status_code, 403)
		self.as_(self.root).post('/staff/settings/', {'what': 'assign', 'user': 'ben', 'role': 'university_admin', 'university': self.ui.pk})
		self.assertEqual(AdminRole.objects.get(user=self.ben).university, self.ui)
		self.assertTrue(AdminLog.objects.filter(action='role.assign').count() >= 2)


class StatsTests(Base):
	def test_overview_numbers_come_from_the_database(self):
		p = Post.objects.create(author=self.ben, content='x')
		Like.objects.create(post=p, user=self.ada)
		Like.objects.create(post=p, user=self.eve)
		services.file_report(self.ada, KINDS['posts'], p, 'spam')
		cards = {c['key']: c for c in stats.overview_cards(admin_for(self.root), 7)}
		self.assertEqual(cards['users']['value'], StudentProfile.objects.count())
		self.assertEqual(cards['posts']['value'], 1)
		self.assertEqual(cards['reports']['value'], 1)
		self.assertEqual(cards['active']['value'], 3)                    # ben posted, ada and eve liked: distinct
		unn = {c['key']: c for c in stats.overview_cards(admin_for(self.uniadmin), 7)}
		self.assertEqual(unn['active']['value'], 2)                      # eve is at UI
		self.assertEqual(unn['universities']['value'], 1)

	def test_change_badge(self):
		self.assertEqual(stats.change(12, 10), ('20%', 'up'))
		self.assertEqual(stats.change(5, 10), ('50%', 'down'))
		self.assertEqual(stats.change(3, 0), ('New', 'up'))
		self.assertEqual(stats.change(0, 0), ('0%', 'flat'))

	def test_every_page_renders(self):
		post = Post.objects.create(author=self.ben, content='x')
		r = services.file_report(self.ada, KINDS['posts'], post, 'spam')
		c = self.as_(self.root)
		for url in ['/staff/', '/staff/?days=30', '/staff/?days=90', '/staff/users/', '/staff/users/?status=flagged', f'/staff/users/{self.ben.pk}/',
				'/staff/moderation/', '/staff/moderation/?tab=comments', '/staff/moderation/?tab=media', '/staff/reports/', f'/staff/reports/{r.pk}/',
				'/staff/universities/', f'/staff/universities/{self.unn.pk}/', '/staff/marketplace/', '/staff/bookshop/', '/staff/events/',
				'/staff/groups/', '/staff/groups/?tab=communities', '/staff/analytics/', '/staff/announcements/', '/staff/logs/',
				'/staff/settings/', '/staff/help/', '/staff/search/?q=ben', '/staff/search/?q=%23' + str(r.pk)]:
			self.assertEqual(c.get(url).status_code, 200, url)
		html = c.get('/staff/').content.decode()
		for text in ['Total Users', 'Active Users', 'Total Posts', 'Pending Reports', 'Suspended Accounts', 'Total Universities',
				'Events', 'Groups &amp; Communities', 'User Registration Trend', 'Platform Activity', 'Most Active Universities',
				'Recent Reports', 'Recent Activity', 'Quick Actions', 'System Status']:
			self.assertIn(text, html)


class MakeAdminCommandTests(Base):
	def test_student_account_becomes_admin_and_keeps_its_feed(self):
		from io import StringIO
		from django.core.management import call_command
		call_command('make_admin', 'ada', stdout=StringIO())
		ada = User.objects.get(pk=self.ada.pk)
		self.assertTrue(ada.is_superuser)
		self.assertEqual(self.as_(ada).get('/staff/').status_code, 200)
		self.assertNotIn("This is an admin account", self.as_(ada).get('/home/').content.decode())
		call_command('make_admin', 'ben', '--role', 'university_admin', '--university', 'unn', stdout=StringIO())
		self.assertEqual(admin_for(User.objects.get(pk=self.ben.pk)).role, AdminRole.UNIVERSITY_ADMIN)
		call_command('make_admin', 'ada', '--remove', stdout=StringIO())
		self.assertEqual(self.as_(User.objects.get(pk=self.ada.pk)).get('/staff/').status_code, 403)

	def test_from_env_skips_unknown_names(self):
		import os
		from io import StringIO
		from unittest import mock
		from django.core.management import call_command
		with mock.patch.dict(os.environ, {'SUPER_ADMINS': 'nobody, eve'}):
			call_command('make_admin', '--from-env', stdout=StringIO())
		self.assertTrue(User.objects.get(pk=self.eve.pk).is_superuser)
		with mock.patch.dict(os.environ, {'SUPER_ADMINS': ''}):
			call_command('make_admin', '--from-env', stdout=StringIO())     # nothing to do, no error

	def test_admin_only_account_gets_an_explanation_not_a_blank_feed(self):
		html = self.as_(self.root).get('/home/').content.decode()
		self.assertIn("This is an admin account", html)
		self.assertIn('/staff/', html)


class StaffOnlyAdminTests(Base):
	"""Admins who aren't students: where they land, read-only viewing, accounts made from Settings."""

	def setUp(self):
		super().setUp()
		self.staff = User.objects.create_user('staff1', email='staff1@uniconnect.test', password='x', is_staff=True)
		AdminRole.objects.create(user=self.staff, role=AdminRole.MODERATOR)
		self.unn_staff = User.objects.create_user('staff2', email='staff2@uniconnect.test', password='x', is_staff=True)
		AdminRole.objects.create(user=self.unn_staff, role=AdminRole.UNIVERSITY_ADMIN, university=self.unn)
		self.ui_post = Post.objects.create(author=self.eve, content='Hello from Ibadan')
		self.unn_post = Post.objects.create(author=self.ben, content='Hello from Nsukka')

	def test_sign_in_lands_on_the_dashboard_but_students_still_go_home(self):
		self.assertRedirects(self.as_(self.staff).get('/dashboard/'), '/staff/', fetch_redirect_response=False)
		self.assertRedirects(self.as_(self.ada).get('/dashboard/'), '/home/', fetch_redirect_response=False)
		AdminRole.objects.create(user=self.ben, role=AdminRole.MODERATOR)       # student + admin: still their feed
		self.assertRedirects(self.as_(self.ben).get('/dashboard/'), '/home/', fetch_redirect_response=False)
		self.assertRedirects(self.as_(self.ben).get('/staff/view/'), '/home/', fetch_redirect_response=False)

	def test_viewing_a_university_read_only(self):
		c = self.as_(self.staff)
		self.assertIn('This is an admin account', c.get('/home/').content.decode())     # not viewing yet
		self.assertEqual(c.get('/staff/view/').status_code, 200)                       # picker
		c.post('/staff/view/', {'university': self.ui.pk})
		html = c.get('/home/').content.decode()
		self.assertIn('Hello from Ibadan', html)
		self.assertNotIn('Hello from Nsukka', html)
		self.assertIn('Viewing University of Ibadan as an admin', html)
		r = c.post('/post/new/', {'content': 'should not appear'})
		self.assertEqual(r.status_code, 302)
		self.assertFalse(Post.objects.filter(content='should not appear').exists())
		r = c.post(f'/post/{self.ui_post.pk}/like/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		self.assertEqual(r.status_code, 403)
		self.assertFalse(Like.objects.exists())
		self.assertFalse(StudentProfile.objects.filter(user=self.staff).exists())     # the stand-in is never saved
		self.assertEqual(c.get('/staff/').status_code, 200)                              # dashboard still works
		c.get('/staff/view/stop/')
		self.assertNotIn('Hello from Ibadan', c.get('/home/').content.decode())

	def test_university_admin_can_only_view_their_own(self):
		c = self.as_(self.unn_staff)
		c.get('/staff/view/')                                     # goes straight in
		c.post('/staff/view/', {'university': self.ui.pk})        # can't switch
		html = c.get('/home/').content.decode()
		self.assertIn('Hello from Nsukka', html)
		self.assertNotIn('Hello from Ibadan', html)
		self.assertNotIn('Switch university', html)

	def test_students_never_get_the_stand_in(self):
		c = self.as_(self.ada)
		s = c.session; s['staff_view_uni'] = self.ui.pk; s.save()
		self.assertNotIn('Hello from Ibadan', c.get('/home/').content.decode())

	def test_create_staff_account_and_invite(self):
		from django.core import mail
		c = self.as_(self.root)
		c.post('/staff/settings/', {'what': 'create', 'first_name': 'Ngozi', 'last_name': 'Okafor',
			'email': 'Ngozi@UniConnect.test', 'role': 'university_admin', 'university': self.unn.pk})
		u = User.objects.get(email='ngozi@uniconnect.test')
		self.assertFalse(u.has_usable_password())
		self.assertEqual((u.admin_role.role, u.admin_role.university), ('university_admin', self.unn))
		self.assertFalse(hasattr(u, 'student_profile'))
		self.assertEqual(len(mail.outbox), 1)
		link = re.search(r'https?://\S+/password/reset/\S+/', mail.outbox[0].body).group(0)
		r = self.client.get(link, follow=True)
		self.assertEqual(r.status_code, 200)
		r = self.client.post(r.redirect_chain[-1][0], {'new_password1': 'A-long-pass-2026', 'new_password2': 'A-long-pass-2026'})
		u.refresh_from_db()
		self.assertTrue(u.check_password('A-long-pass-2026'))
		self.assertTrue(AdminLog.objects.filter(action='staff.create').exists())
		self.assertTrue(AdminLog.objects.filter(action='staff.invite').exists())
		c.post('/staff/settings/', {'what': 'create', 'first_name': 'X', 'email': 'ada@x.com', 'role': 'support'})
		self.assertEqual(User.objects.filter(email__iexact='ada@x.com').count(), 1)   # email already used

	def test_university_admin_creates_only_moderators_and_support_at_home(self):
		c = self.as_(self.uniadmin)
		c.post('/staff/settings/', {'what': 'create', 'first_name': 'A', 'email': 'a@uniconnect.test', 'role': 'super_admin'})
		self.assertFalse(User.objects.filter(email='a@uniconnect.test').exists())
		c.post('/staff/settings/', {'what': 'create', 'first_name': 'B', 'email': 'b@uniconnect.test', 'role': 'support', 'university': self.ui.pk})
		self.assertEqual(User.objects.get(email='b@uniconnect.test').admin_role.university, self.unn)
		self.assertEqual(self.as_(self.mod).post('/staff/settings/', {'what': 'create', 'first_name': 'C', 'email': 'c@uniconnect.test', 'role': 'support'}).status_code, 403)

	def test_invite_failure_keeps_the_account_and_resend_works(self):
		from unittest import mock
		from django.core import mail
		c = self.as_(self.root)
		with mock.patch('django.core.mail.send_mail', side_effect=OSError('no server')):
			r = c.post('/staff/settings/', {'what': 'create', 'first_name': 'D', 'email': 'd@uniconnect.test', 'role': 'support'}, follow=True)
		self.assertIn("couldn&#x27;t be sent", r.content.decode())
		role = AdminRole.objects.get(user__email='d@uniconnect.test')
		self.assertIn('Invite pending', c.get('/staff/settings/').content.decode())
		c.post('/staff/settings/', {'what': 'resend', 'role_id': role.pk})
		self.assertEqual(len(mail.outbox), 1)
