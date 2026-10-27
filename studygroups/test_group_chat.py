"""A group's page with its chat built in (Chat tab, tiles, replies, Seen by, search)."""
import json

from asgiref.sync import async_to_sync
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase, override_settings

from chat import services as S
from chat.models import ConversationParticipant as P, Message
from chat.routing import websocket_urlpatterns
from .models import GroupPost, StudyGroup
from .tests import MEDIA, GroupTests


class Helpers:
	"""GroupTests' set-up and helpers, without re-running its tests."""
	setUp = GroupTests.setUp
	student = GroupTests.student
	create = GroupTests.create
	as_user = GroupTests.as_user
	join = GroupTests.join

LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


@override_settings(MEDIA_ROOT=MEDIA)
class GroupPageChatTests(Helpers, TestCase):
	def setUp(self):
		Helpers.setUp(self)
		self.g = self.create()
		self.join(self.g, self.ben)
		self.as_user(self.ada)

	def test_chat_opens_in_messages(self):
		"""The group chat lives in Messages: the page links there, old ?tab=chat links go there."""
		GroupPost.objects.create(group=self.g, author=self.ada, is_announcement=True, pinned=True,
			body='Assignment Deadline Update\nMoved to Friday.')
		page = self.client.get(f'/groups/{self.g.pk}/')
		self.assertEqual(page.context['tab'], 'posts')                       # first tab now
		self.assertNotIn('chat', dict(page.context['tabs']))
		html = page.content.decode()
		chat_url = f'/messages/c/{self.g.conversation_id}/'
		self.assertIn(f'href="{chat_url}" class="gp-msg"', html)                  # the Messages button beside Joined
		for text in ('Notifications', 'Announcements', 'Group Settings', 'Course Group'):
			self.assertIn(text, html)
		self.assertNotIn('gcConfig', html)                                    # no chat on the page any more
		self.assertRedirects(self.client.get(f'/groups/{self.g.pk}/?tab=chat'), chat_url, fetch_redirect_response=False)
		self.assertRedirects(self.client.get(f'/groups/{self.g.pk}/?tab=chat&m=5'), chat_url + '?m=5', fetch_redirect_response=False)
		# ...and from the chat in Messages, back to the group page
		self.assertContains(self.client.get(chat_url), 'Open the group page')
		only = self.client.get(f'/groups/{self.g.pk}/?tab=posts&show=announcements')
		self.assertEqual(only.context['show'], 'announcements')
		self.assertTrue(all(p.is_announcement for p in only.context['posts']))

	def test_outsiders_get_no_chat(self):
		self.as_user(self.cy)                                   # same university, not a member
		page = self.client.get(f'/groups/{self.g.pk}/')
		self.assertNotEqual(page.context['tab'], 'chat')
		self.assertNotIn('gcConfig', page.content.decode())
		self.assertEqual(self.client.get(f'/groups/{self.g.pk}/chat/seen/').status_code, 404)
		self.assertEqual(self.client.get(f'/groups/{self.g.pk}/chat/search/?q=hi').status_code, 404)

	def test_reply_seen_and_search(self):
		conv = self.g.conversation
		first = S.create_message(conv, self.ben, Message.TEXT, 'Who has the week 6 notes?')
		reply = S.create_message(conv, self.ada, Message.TEXT, 'Me', reply_to=S.reply_target(conv, first.pk))
		data = S.serialize_message(Message.objects.get(pk=reply.pk))
		self.assertEqual((data['reply_to']['id'], data['reply_to']['text']), (first.pk, 'Who has the week 6 notes?'))
		other, _ = S.direct_conversation(self.ada, self.cy)
		elsewhere = S.create_message(other, self.cy, Message.TEXT, 'secret')
		self.assertIsNone(S.reply_target(conv, elsewhere.pk))   # only messages in the same chat
		S.mark_read(self.ben, conv.pk)
		reads = self.client.get(f'/groups/{self.g.pk}/chat/seen/').json()['reads']
		self.assertIn(str(self.ben.pk), reads)
		self.assertNotIn(str(self.ada.pk), reads)               # not yourself
		found = self.client.get(f'/groups/{self.g.pk}/chat/search/?q=week+6').json()['results']
		self.assertEqual([m['id'] for m in found], [first.pk])

	def test_notifications_tile_mutes_the_chat(self):
		self.client.post(f'/messages/c/{self.g.conversation_id}/action/', {'action': 'mute'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		self.assertTrue(P.objects.get(conversation=self.g.conversation, user=self.ada).is_muted)
		self.assertIn('bi-bell-slash', self.client.get(f'/groups/{self.g.pk}/').content.decode())


@override_settings(CHANNEL_LAYERS=LAYERS)
class GroupChatLiveTests(TransactionTestCase):
	"""Replies over the WebSocket, and the 'seen' event behind "Seen by N"."""
	def test_reply_and_seen_events(self):
		from django.contrib.auth import get_user_model
		User = get_user_model()
		a = User.objects.create_user('ada', password='x', first_name='Ada')
		b = User.objects.create_user('ben', password='x', first_name='Ben')
		conv = S.create_group(a, 'COS 401', [a, b])
		first = S.create_message(conv, b, Message.TEXT, 'Question 3?')

		def connect(user):
			comm = WebsocketCommunicator(URLRouter(websocket_urlpatterns), '/ws/chat/')
			comm.scope['user'] = user
			return comm

		async def expect(comm, kind):
			for _ in range(10):
				d = await comm.receive_json_from(timeout=2)
				if d.get('type') == kind:
					return d
			raise AssertionError(kind)

		async def run():
			ca, cb = connect(a), connect(b)
			await ca.connect(); await expect(ca, 'hello')
			await cb.connect(); await expect(cb, 'hello')
			await ca.send_json_to({'type': 'message', 'conversation': conv.pk, 'content': 'It wants JSON', 'reply_to': first.pk})
			got = await expect(cb, 'message')
			self.assertEqual(got['message']['reply_to']['id'], first.pk)
			await cb.send_json_to({'type': 'read', 'conversation': conv.pk})
			seen = await expect(ca, 'seen')
			self.assertEqual(seen['user'], b.pk)
			await ca.disconnect(); await cb.disconnect()
		async_to_sync(run)()


@override_settings(MEDIA_ROOT=MEDIA)
class ChatAndPostsTogetherTests(Helpers, TestCase):
	"""Posts with titles and files, saving, editing, finding; sharing posts into
	chat; one Files library; rules; the Posts switch; new-message pop-ups."""
	def setUp(self):
		Helpers.setUp(self)
		self.g = self.create(rules='Be respectful\n\n  Keep it about COS 401 ')
		self.join(self.g, self.ben)
		self.as_user(self.ada)

	def post(self, **data):
		from django.core.files.uploadedfile import SimpleUploadedFile
		files = data.pop('files', [])
		return self.client.post(f'/groups/{self.g.pk}/posts/new/', dict(data, files=files))

	def pdf(self, name='COS401_Assignment_2.pdf'):
		from django.core.files.uploadedfile import SimpleUploadedFile
		return SimpleUploadedFile(name, b'%PDF-1.4 test', content_type='application/pdf')

	def test_post_with_title_files_edit_save_find(self):
		from django.core.files.uploadedfile import SimpleUploadedFile
		self.post(title='  COS 401   Assignment 2 ', body='Submit by Friday. Covers normalization.',
			files=[self.pdf(), SimpleUploadedFile('walkthrough.mp4', b'\x00\x00\x00\x18ftypmp42', content_type='video/mp4')])
		p = GroupPost.objects.get(title='COS 401 Assignment 2')
		self.assertEqual(sorted(f.name for f in p.attachments.all()), ['COS401_Assignment_2.pdf', 'walkthrough.mp4'])
		html = self.client.get(f'/groups/{self.g.pk}/?tab=posts').content.decode()
		self.assertIn('<video', html)
		self.assertIn('COS401_Assignment_2.pdf', html)
		self.post(files=[self.pdf('notes.pdf')])                         # files alone are a post too
		self.assertTrue(GroupPost.objects.filter(attachments__name='notes.pdf').exists())
		# Edit: your own only.
		self.as_user(self.ben)
		self.client.post(f'/groups/{self.g.pk}/posts/{p.pk}/edit/', {'title': 'Hacked', 'body': 'x'})
		p.refresh_from_db(); self.assertEqual(p.title, 'COS 401 Assignment 2')
		self.as_user(self.ada)
		self.client.post(f'/groups/{self.g.pk}/posts/{p.pk}/edit/', {'title': 'COS 401 Assignment 2: Instructions', 'body': p.body})
		p.refresh_from_db(); self.assertEqual((p.title, p.is_edited), ('COS 401 Assignment 2: Instructions', True))
		# Save, then find it.
		self.assertTrue(self.client.post(f'/groups/{self.g.pk}/posts/{p.pk}/save/', HTTP_X_REQUESTED_WITH='XMLHttpRequest').json()['saved'])
		self.assertEqual([x.pk for x in self.client.get(f'/groups/{self.g.pk}/?tab=posts&show=saved').context['posts']], [p.pk])
		self.assertContains(self.client.get('/bookmarks/?tab=groups'), 'COS 401 Assignment 2: Instructions')
		self.assertEqual([x.pk for x in self.client.get(f'/groups/{self.g.pk}/?tab=posts&q=normalization').context['posts']], [p.pk])
		self.assertEqual(len(self.client.get(f'/groups/{self.g.pk}/?tab=posts&show=files').context['posts']), 2)

	def test_share_into_chat_and_post_from_chat(self):
		self.post(title='Database Normalization: Explanation and Examples', body='Start with functional dependencies.')
		p = GroupPost.objects.get()
		self.client.post(f'/groups/{self.g.pk}/posts/{p.pk}/share/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		msg = Message.objects.filter(conversation=self.g.conversation, sender=self.ada).latest('pk')
		self.assertIn('📝 Database Normalization: Explanation and Examples', msg.content)
		self.assertIn(f'/groups/{self.g.pk}/?tab=posts#p{p.pk}', msg.content)
		q = S.create_message(self.g.conversation, self.ben, Message.TEXT, 'Can someone explain database normalization?')
		page = self.client.get(f'/groups/{self.g.pk}/?tab=posts&from_msg={q.pk}')
		self.assertEqual(page.context['prefill'], 'Can someone explain database normalization?')

	def test_files_library_rules_and_posts_switch(self):
		from django.core.files.base import ContentFile
		self.post(body='Notes', files=[self.pdf('week6.pdf')])
		S.create_message(self.g.conversation, self.ben, Message.FILE, '', attachment=ContentFile(b'%PDF', name='COS401_Lecture_Week6.pdf'))
		lib = self.client.get(f'/groups/{self.g.pk}/?tab=files').context
		self.assertEqual(sorted((f.name, f.source) for f in lib['files']),
			[('COS401_Lecture_Week6.pdf', 'chat'), ('week6.pdf', 'posts')])
		self.assertEqual([f.name for f in self.client.get(f'/groups/{self.g.pk}/?tab=files&from=chat').context['files']], ['COS401_Lecture_Week6.pdf'])
		about = self.client.get(f'/groups/{self.g.pk}/?tab=about').content.decode()
		self.assertIn('Keep it about COS 401', about)
		self.assertEqual(StudyGroup.objects.get(pk=self.g.pk).rule_list, ['Be respectful', 'Keep it about COS 401'])
		StudyGroup.objects.filter(pk=self.g.pk).update(show_posts=False)
		tabs = dict(self.client.get(f'/groups/{self.g.pk}/').context['tabs'])
		self.assertNotIn('posts', tabs)
		self.assertIn('files', tabs)
		self.as_user(self.ben)
		self.client.get('/groups/new/?type=hostel')
		self.assertFalse(self.client.get('/groups/new/?type=hostel').context['form'].initial['show_posts'])

	def test_new_message_popups(self):
		first = self.client.get('/notifications/count/').json()
		self.assertNotIn('chats', first)                                  # first ask: just the clock
		S.create_message(self.g.conversation, self.ben, Message.TEXT, 'Class moved to LT 2')
		got = self.client.get('/notifications/count/', {'chat_since': first['chat_since']}).json()['chats']
		self.assertEqual([(c['title'], c['text']) for c in got], [('COS 401 · 400 Level', 'Ben: Class moved to LT 2')])
		P.objects.filter(conversation=self.g.conversation, user=self.ada).update(is_muted=True)
		S.create_message(self.g.conversation, self.ben, Message.TEXT, 'Muted one')
		self.assertEqual(self.client.get('/notifications/count/', {'chat_since': first['chat_since']}).json()['chats'], [])

	def test_videos_in_chat(self):
		from django.core.files.uploadedfile import SimpleUploadedFile
		r = self.client.post(f'/messages/c/{self.g.conversation_id}/upload/',
			{'file': SimpleUploadedFile('demo.mp4', b'\x00\x00\x00\x18ftypmp42', content_type='video/mp4')}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		self.assertEqual(r.json()['message']['kind'], 'video')
