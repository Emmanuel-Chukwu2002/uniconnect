"""Groups (run: python manage.py test studygroups)."""
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import Department, Faculty, Level, StudentProfile, University
from chat.models import ConversationParticipant as P, Message
from feed.models import Notification as N
from .models import GroupComment, GroupFile, GroupPollVote, GroupPost, StudyGroup, StudyGroupMember as M

User = get_user_model()
MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class GroupTests(TestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(MEDIA, ignore_errors=True)

	def setUp(self):
		self.uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		other = University.objects.create(name='University of Lagos', short_name='UNILAG', email_domain='unilag.edu.ng')
		self.ada, self.ben, self.cy = (self.student(n, self.uni) for n in ('ada', 'ben', 'cy'))
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

	def create(self, **extra):
		data = {'group_type': 'academic', 'privacy': 'public', 'course_code': 'cos  401', 'name': '400 Level',
			'description': 'Class group', 'mode': '', 'max_members': '', 'show_posts': 'on'}
		data.update(extra)
		r = self.client.post('/groups/new/', data)
		self.assertEqual(r.status_code, 302, r.content[:2000])
		return StudyGroup.objects.latest('pk')

	def as_user(self, user):
		self.client.force_login(user)

	def join(self, g, user):
		self.as_user(user)
		self.client.post(f'/groups/{g.pk}/join/')

	# --- creating ---------------------------------------------------------
	def test_create_makes_owner_and_chat(self):
		g = self.create()
		self.assertEqual((g.course_code, g.title, g.max_members), ('COS 401', 'COS 401 · 400 Level', None))
		self.assertEqual(g.members.get().role, M.OWNER)
		self.assertEqual(list(P.objects.filter(conversation=g.conversation).values_list('user', flat=True)), [self.ada.pk])
		self.assertIn('COS 401 · 400 Level', g.conversation.name)

	def test_course_code_only_kept_for_academic_groups(self):
		g = self.create(group_type='hostel', name='Block C, Room 12', course_code='XYZ 1')
		self.assertEqual((g.course_code, g.title), ('', 'Block C, Room 12'))

	def test_member_limit_range(self):
		r = self.client.post('/groups/new/', {'group_type': 'social', 'privacy': 'public', 'name': 'Hangout', 'max_members': 1})
		self.assertContains(r, 'Choose between 2 and')
		self.assertFalse(StudyGroup.objects.exists())

	# --- joining ----------------------------------------------------------
	def test_public_join_leave_and_chat_follow_membership(self):
		g = self.create()
		self.join(g, self.ben)
		self.assertTrue(P.objects.filter(conversation=g.conversation, user=self.ben).exists())
		self.assertTrue(Message.objects.filter(conversation=g.conversation, content__contains='Ben joined').exists())
		self.client.post(f'/groups/{g.pk}/leave/')
		self.assertFalse(P.objects.filter(conversation=g.conversation, user=self.ben).exists())
		self.as_user(self.ada)
		self.client.post(f'/groups/{g.pk}/leave/')                 # the owner can't leave
		self.assertTrue(M.objects.filter(group=g, user=self.ada).exists())

	def test_private_group_requests_need_approval(self):
		g = self.create(privacy='private')
		self.join(g, self.ben)
		m = M.objects.get(group=g, user=self.ben)
		self.assertEqual(m.status, M.PENDING)
		self.assertFalse(P.objects.filter(conversation=g.conversation, user=self.ben).exists())
		self.assertEqual(self.client.get(f'/groups/{g.pk}/?tab=posts').context['tab'], 'about')   # no posts before approval
		self.assertTrue(N.objects.filter(recipient=self.ada, type=N.GROUP_REQUEST, study_group=g).exists())
		self.as_user(self.ada)
		self.assertContains(self.client.get(f'/groups/{g.pk}/?tab=members'), 'Approve')
		self.client.post(f'/groups/{g.pk}/members/{m.pk}/approve/')
		m.refresh_from_db()
		self.assertEqual(m.status, M.ACTIVE)
		self.assertTrue(P.objects.filter(conversation=g.conversation, user=self.ben).exists())
		self.assertTrue(N.objects.filter(recipient=self.ben, type=N.GROUP_ACCEPTED).exists())
		self.assertFalse(N.objects.filter(type=N.GROUP_REQUEST).exists())

	def test_invite_only_is_hidden_but_link_works_across_universities(self):
		g = self.create(privacy='invite')
		self.as_user(self.ben)
		self.assertEqual(self.client.get(f'/groups/{g.pk}/').status_code, 404)
		self.assertNotIn(f'href="/groups/{g.pk}/"', self.client.get('/groups/').content.decode())
		self.as_user(self.far)                                     # another university
		self.assertContains(self.client.get(f'/groups/invite/{g.invite_code}/'), 'Join group')
		self.client.post(f'/groups/invite/{g.invite_code}/')
		self.assertTrue(M.objects.filter(group=g, user=self.far, status=M.ACTIVE).exists())
		self.assertEqual(self.client.get(f'/groups/{g.pk}/').status_code, 200)
		self.as_user(self.ada)
		old = g.invite_code
		self.client.post(f'/groups/{g.pk}/invite/reset/')
		g.refresh_from_db()
		self.assertNotEqual(g.invite_code, old)
		self.assertEqual(self.client.get(f'/groups/invite/{old}/').status_code, 404)

	def test_full_and_closed_groups_refuse_joins(self):
		g = self.create(max_members=2)
		self.join(g, self.ben)
		self.as_user(self.cy)
		self.assertContains(self.client.get(f'/groups/{g.pk}/'), 'Group is full')
		self.client.post(f'/groups/{g.pk}/join/')
		self.assertEqual(g.members.count(), 2)
		g.max_members, g.is_open = None, False
		g.save()
		self.client.post(f'/groups/{g.pk}/join/')
		self.assertEqual(g.members.count(), 2)

	def test_other_university_cannot_see_public_group(self):
		g = self.create()
		self.as_user(self.far)
		self.assertEqual(self.client.get(f'/groups/{g.pk}/').status_code, 404)
		self.assertNotIn(f'href="/groups/{g.pk}/"', self.client.get('/groups/').content.decode())

	# --- roles ------------------------------------------------------------
	def test_roles(self):
		g = self.create()
		self.join(g, self.ben)
		self.join(g, self.cy)
		self.as_user(self.ben)
		self.assertEqual(self.client.get(f'/groups/{g.pk}/edit/').status_code, 404)       # members can't edit
		self.as_user(self.ada)
		ben = M.objects.get(group=g, user=self.ben)
		self.client.post(f'/groups/{g.pk}/members/{ben.pk}/make_admin/')
		self.as_user(self.ben)
		self.assertEqual(self.client.get(f'/groups/{g.pk}/edit/').status_code, 200)       # admins can
		cy = M.objects.get(group=g, user=self.cy)
		self.client.post(f'/groups/{g.pk}/members/{cy.pk}/remove/')
		self.assertFalse(M.objects.filter(group=g, user=self.cy).exists())
		self.assertFalse(P.objects.filter(conversation=g.conversation, user=self.cy).exists())
		self.client.post(f'/groups/{g.pk}/delete/')                                       # only the owner deletes
		self.assertTrue(StudyGroup.objects.filter(pk=g.pk).exists())
		self.as_user(self.ada)
		conv_id = g.conversation_id
		self.client.post(f'/groups/{g.pk}/delete/')
		self.assertFalse(StudyGroup.objects.exists())
		self.assertTrue(Message.objects.filter(conversation_id=conv_id, content__contains='was deleted').exists())

	# --- posts, announcements, polls --------------------------------------
	def test_posts_announcements_and_comments(self):
		g = self.create()
		self.join(g, self.ben)
		self.client.post(f'/groups/{g.pk}/posts/new/', {'body': 'Anyone has past questions?', 'is_announcement': '1'})
		p = GroupPost.objects.get()
		self.assertFalse(p.is_announcement)                     # members can't announce
		self.as_user(self.far)
		self.assertEqual(self.client.post(f'/groups/{g.pk}/posts/{p.pk}/like/').status_code, 404)
		self.as_user(self.ada)
		self.client.post(f'/groups/{g.pk}/posts/new/', {'body': 'Deadline moved to Friday', 'is_announcement': '1'})
		a = GroupPost.objects.latest('pk')
		self.assertTrue(a.is_announcement and a.pinned)
		self.assertTrue(N.objects.filter(recipient=self.ben, type=N.GROUP_ANNOUNCEMENT, group_post=a).exists())
		r = self.client.post(f'/groups/{g.pk}/posts/{p.pk}/like/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		self.assertEqual(r.json(), {'liked': True, 'count': 1})
		r = self.client.post(f'/groups/{g.pk}/posts/{p.pk}/comment/', {'body': 'I have 2022'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		self.assertIn('I have 2022', r.json()['html'])
		html = self.client.get(f'/groups/{g.pk}/?tab=posts').content.decode()
		self.assertLess(html.index('Deadline moved'), html.index('Anyone has past'))    # pinned first
		self.as_user(self.ben)
		c = GroupComment.objects.get()
		self.client.post(f'/groups/{g.pk}/comments/{c.pk}/delete/')                      # not his comment
		self.assertTrue(GroupComment.objects.exists())
		self.client.post(f'/groups/{g.pk}/posts/{a.pk}/delete/')                         # not his post
		self.assertTrue(GroupPost.objects.filter(pk=a.pk).exists())

	def test_polls(self):
		g = self.create()
		self.join(g, self.ben)
		r = self.client.post(f'/groups/{g.pk}/posts/new/', {'body': 'When?', 'is_poll': '1', 'option_1': 'Mon', 'option_2': 'mon'})
		self.assertFalse(GroupPost.objects.exists())             # needs two different options
		self.client.post(f'/groups/{g.pk}/posts/new/', {'body': 'When?', 'is_poll': '1', 'option_1': 'Mon', 'option_2': 'Wed', 'option_3': ''})
		p = GroupPost.objects.get()
		mon, wed = p.options.all()
		self.client.post(f'/groups/{g.pk}/posts/{p.pk}/vote/', {'option': mon.pk})
		self.client.post(f'/groups/{g.pk}/posts/{p.pk}/vote/', {'option': wed.pk})       # single choice: moves the vote
		self.assertEqual(list(GroupPollVote.objects.values_list('option', flat=True)), [wed.pk])
		self.client.post(f'/groups/{g.pk}/posts/{p.pk}/vote/', {'option': wed.pk})       # tap again: takes it back
		self.assertFalse(GroupPollVote.objects.exists())
		self.client.post(f'/groups/{g.pk}/posts/{p.pk}/close/')
		self.client.post(f'/groups/{g.pk}/posts/{p.pk}/vote/', {'option': mon.pk})
		self.assertFalse(GroupPollVote.objects.exists())          # closed
		self.assertContains(self.client.get(f'/groups/{g.pk}/?tab=posts'), 'Closed')

	# --- files ------------------------------------------------------------
	def test_files_are_for_members_only(self):
		g = self.create()
		self.client.post(f'/groups/{g.pk}/files/upload/', {'file': SimpleUploadedFile('notes.pdf', b'%PDF-1.4 hi', 'application/pdf')})
		self.client.post(f'/groups/{g.pk}/files/upload/', {'file': SimpleUploadedFile('virus.exe', b'MZ', 'application/octet-stream')})
		f = GroupFile.objects.get()
		self.assertEqual((f.name, f.size, f.kind), ('notes.pdf', 11, 'pdf'))
		r = self.client.get(f'/groups/{g.pk}/files/{f.pk}/')
		self.assertEqual(b''.join(r.streaming_content), b'%PDF-1.4 hi')
		self.as_user(self.ben)                                    # same university, not a member
		self.assertEqual(self.client.get(f'/groups/{g.pk}/files/{f.pk}/').status_code, 404)
		self.client.post(f'/groups/{g.pk}/join/')
		self.assertEqual(self.client.get(f'/groups/{g.pk}/files/{f.pk}/').status_code, 200)
		self.client.post(f'/groups/{g.pk}/files/{f.pk}/delete/')                         # not his upload
		self.assertTrue(GroupFile.objects.exists())
		self.as_user(self.ada)
		self.client.post(f'/groups/{g.pk}/files/{f.pk}/delete/')
		self.assertFalse(GroupFile.objects.exists())

	# --- list -------------------------------------------------------------
	def test_list_tabs_types_and_search(self):
		cls = self.create()
		hostel = self.create(group_type='hostel', name='Eni Njoku Hall', course_code='')
		link = lambda g: f'href="/groups/{g.pk}/"'
		html = self.client.get('/groups/?q=cos 401').content.decode()
		self.assertIn(link(cls), html)
		self.assertNotIn(link(hostel), html)
		self.as_user(self.ben)                                    # Discover leaves out groups you're in
		html = self.client.get('/groups/?type=hostel').content.decode()
		self.assertIn(link(hostel), html)
		self.assertNotIn(link(cls), html)
		self.assertIn('not in any group', self.client.get('/groups/?tab=mine').content.decode())

	def test_seed_command(self):
		from django.core.management import call_command
		from io import StringIO
		from studygroups.management.commands.seed_studygroups import SAMPLES, STUDY
		n = len(SAMPLES) + len(STUDY)
		call_command('seed_studygroups', stdout=StringIO())
		self.assertEqual(StudyGroup.objects.count(), n)
		self.assertTrue(StudyGroup.objects.filter(name='Algebra Warriors', posts__comments__isnull=False).exists())
		self.assertTrue(GroupFile.objects.exists())
		call_command('seed_studygroups', '--reset', stdout=StringIO())
		self.assertEqual(StudyGroup.objects.count(), n)

	def test_study_groups_get_the_soft_page(self):
		study = self.create()
		hostel = self.create(group_type='hostel', name='Block C', course_code='')
		self.assertContains(self.client.get(f'/groups/{study.pk}/'), 'class="gp is-soft"')
		html = self.client.get(f'/groups/{hostel.pk}/').content.decode()
		self.assertNotIn('is-soft', html)
		self.assertIn('pexels-photo-5965612', html)                         # the hostel photo banner
		self.assertIn('pc-card', self.client.get('/groups/').content.decode())   # Groups: the card list, not the dashboard

	def test_comments_sheet_replies_likes_edit(self):
		from .models import GroupCommentLike
		g = self.create()
		self.join(g, self.ben)
		p = GroupPost.objects.create(group=g, author=self.ada, title='Ladder', body='How do I draw it?')
		url = f'/groups/{g.pk}/posts/{p.pk}/comment/'
		ajax = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
		self.client.post(url, {'body': 'Take moments about the foot.'}, **ajax)
		top = GroupComment.objects.get()
		self.as_user(self.ada)
		self.client.post(url, {'body': 'Thanks!', 'parent': top.pk}, **ajax)
		reply = GroupComment.objects.latest('pk')
		self.assertEqual(reply.parent, top)
		self.client.post(url, {'body': '@Ben one more', 'parent': reply.pk}, **ajax)     # a reply to a reply joins the thread
		self.assertEqual(GroupComment.objects.latest('pk').parent, top)
		r = self.client.post(f'/groups/{g.pk}/comments/{top.pk}/like/', **ajax)
		self.assertTrue(GroupCommentLike.objects.filter(comment=top, user=self.ada).exists())
		html = r.json()['html']
		self.assertIn('data-count="3"', html)                  # the sheet shows all 3 comments
		self.assertIn('View 2 replies', html)
		self.assertIn('comment-like-btn js-sgc-like liked', html)
		self.client.post(f'/groups/{g.pk}/comments/{top.pk}/like/', **ajax)
		self.assertFalse(GroupCommentLike.objects.exists())
		self.assertEqual(self.client.post(f'/groups/{g.pk}/comments/{top.pk}/edit/', {'body': 'x'}).status_code, 404)   # not ada's
		self.as_user(self.ben)
		self.client.post(f'/groups/{g.pk}/comments/{top.pk}/edit/', {'body': 'Take moments about the foot of the ladder.'}, **ajax)
		top.refresh_from_db()
		self.assertTrue(top.is_edited)
		self.assertIn('ladder.', top.body)
		self.client.post(f'/groups/{g.pk}/comments/{top.pk}/delete/', **ajax)
		self.assertFalse(GroupComment.objects.exists())            # deleting a comment removes its replies
		page = self.client.get(f'/groups/{g.pk}/?tab=posts').content.decode()
		self.assertIn('id="sgCommentsModal"', page)
		self.assertNotIn('sg-comment-bubble', page)                # the old chat-bubble comments are gone

	def test_group_photo_and_subject_icons(self):
		from io import BytesIO
		from PIL import Image
		g = self.create(course_code='MTH 201', name='Matrix crew')
		self.assertIn('/photos/6256061/', g.icon_url)                 # maths: equation on a blackboard
		g.course_code = 'CHM 101'
		self.assertIn('/photos/248152/', g.icon_url)                  # chemistry: lab glassware
		g.course_code, g.name = 'PHY 301', 'Fans of Stephen Hawking'
		self.assertIn('/photos/7480/', g.icon_url)                    # a space word in the name wins
		g.course_code, g.name = '', 'Study buddies'
		self.assertIn('/photos/5676678/', g.icon_url)                 # no subject: students studying
		buf = BytesIO(); Image.new('RGB', (40, 40), 'red').save(buf, 'PNG')
		photo = SimpleUploadedFile('icon.png', buf.getvalue(), content_type='image/png')
		data = {'group_type': 'academic', 'privacy': 'public', 'course_code': 'MTH 201', 'name': 'Matrix crew',
			'description': '', 'mode': '', 'max_members': '', 'show_posts': 'on', 'photo': photo}
		self.assertEqual(self.client.post(f'/groups/{g.pk}/edit/', data).status_code, 302)
		g.refresh_from_db()
		self.assertTrue(g.photo and g.icon_url.startswith('/media/') or g.icon_url == g.photo.url)
		html = self.client.get(f'/groups/{g.pk}/').content.decode()
		self.assertIn(g.photo.url, html)
		self.assertIn('w=1260&amp;h=420', html)                        # the cover: a wide photo for the subject
		self.assertIn('/photos/6256061/', g.cover_url)
		self.assertIn('js-view-cover-photo', html)                     # tap to view the cover…
		self.assertIn(f'js-view-profile-photo" data-photo-url="{g.photo.url}"', html)   # …and the round picture

	def test_about_tab(self):
		g = self.create(description='We revise together.', rules='Be kind\nNo exam leaks')
		html = self.client.get(f'/groups/{g.pk}/?tab=about').content.decode()
		for text in ('About 400 Level', 'A study group for COS 401', 'We revise together.', '<b>Academic</b>',
				'<b>Public</b>', '<b>Started</b>', 'Group rules', 'No exam leaks', 'Admins', 'Owner'):
			self.assertIn(text, html)

	def test_tabs_switch_in_place(self):
		g = self.create()
		html = self.client.get(f'/groups/{g.pk}/').content.decode()
		self.assertIn('<div class="gp-panel">', html)                   # the part that changes
		self.assertIn('<nav class="gp-tabs" aria-label="Group sections" data-soft-swap=".gp-tabs, .gp-panel">', html)
		self.assertIn('class="gp-tiles" data-soft-swap', html)
