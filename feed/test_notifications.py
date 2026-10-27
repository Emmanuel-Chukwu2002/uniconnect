"""Tests for the notification system (run: python manage.py test feed)."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Comment, Follow, Notification, Post
from .notifications import unread_count

User = get_user_model()
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class NotificationTests(TestCase):
	def setUp(self):
		self.owner = User.objects.create_user('owner', password='x', first_name='Ada', last_name='Obi')
		self.fans = [
			User.objects.create_user(f'fan{i}', password='x', first_name=name, last_name='Test')
			for i, name in enumerate(['John', 'Mary', 'David', 'Ngozi'])
		]
		self.post = Post.objects.create(author=self.owner, content='Hello')

	def client_for(self, user):
		self.client.force_login(user)
		return self.client

	def test_likes_are_grouped_and_counted_once(self):
		for fan in self.fans:
			self.client_for(fan).post(f'/like/{self.post.pk}/toggle/', **AJAX)
		self.assertEqual(Notification.objects.filter(recipient=self.owner).count(), 4)
		self.assertEqual(unread_count(self.owner), 1)  # one grouped entry

		html = self.client_for(self.owner).get('/notifications/?panel=1', **AJAX).json()['html']
		self.assertIn('<strong>Ngozi Test</strong>, <strong>David Test</strong> and 2 other people liked your post.', html)

	def test_viewing_marks_read_in_database(self):
		self.client_for(self.fans[0]).post(f'/like/{self.post.pk}/toggle/', **AJAX)
		self.assertEqual(unread_count(self.owner), 1)
		self.client_for(self.owner).get('/notifications/')
		self.assertEqual(unread_count(self.owner), 0)
		self.assertFalse(Notification.objects.filter(recipient=self.owner, is_read=False).exists())

	def test_unlike_removes_notification_and_self_actions_are_ignored(self):
		c = self.client_for(self.fans[0])
		c.post(f'/like/{self.post.pk}/toggle/', **AJAX)
		c.post(f'/like/{self.post.pk}/toggle/', **AJAX)  # unlike
		self.client_for(self.owner).post(f'/like/{self.post.pk}/toggle/', **AJAX)  # own post
		self.assertFalse(Notification.objects.filter(recipient=self.owner).exists())

	def test_comment_reply_and_mention(self):
		mine = Comment.objects.create(post=self.post, author=self.owner, content='First!')
		self.client_for(self.fans[0]).post(
			f'/post/{self.post.pk}/comments/add/', {'content': 'Nice one! @fan1', 'parent_id': mine.pk}, **AJAX,
		)
		types = set(Notification.objects.values_list('recipient__username', 'type'))
		self.assertIn(('owner', Notification.REPLY), types)
		self.assertNotIn(('owner', Notification.COMMENT), types)  # the reply already covers it
		self.assertIn(('fan1', Notification.MENTION), types)

	def test_open_marks_read_and_redirects_to_comment(self):
		self.client_for(self.fans[0]).post(f'/post/{self.post.pk}/comments/add/', {'content': 'Nice one!'}, **AJAX)
		n = Notification.objects.get(recipient=self.owner)
		response = self.client_for(self.owner).get(f'/notifications/{n.pk}/open/')
		self.assertRedirects(response, f'/post/{self.post.pk}/?comment={n.comment_id}', fetch_redirect_response=False)
		n.refresh_from_db()
		self.assertTrue(n.is_read)

	def test_follow_request_accept_turns_into_follow(self):
		self.client_for(self.fans[0]).post(f'/follow/{self.owner.pk}/', **AJAX)
		follow = Follow.objects.get(follower=self.fans[0], following=self.owner)
		self.client_for(self.owner).post(f'/follow-requests/{follow.pk}/accept/', **AJAX)
		self.assertTrue(Notification.objects.filter(recipient=self.owner, type=Notification.FOLLOW).exists())
		self.assertTrue(Notification.objects.filter(recipient=self.fans[0], type=Notification.FOLLOW_ACCEPTED).exists())

	def test_mark_unread_delete_and_other_users_rows_untouchable(self):
		self.client_for(self.fans[0]).post(f'/like/{self.post.pk}/toggle/', **AJAX)
		n = Notification.objects.get(recipient=self.owner)
		# Someone else can't change or delete it.
		self.client_for(self.fans[1]).post('/notifications/delete/', {'ids': str(n.pk)}, **AJAX)
		self.assertTrue(Notification.objects.filter(pk=n.pk).exists())
		c = self.client_for(self.owner)
		self.assertEqual(c.post('/notifications/mark/', {'ids': str(n.pk), 'state': 'read'}, **AJAX).json()['unread'], 0)
		self.assertEqual(c.post('/notifications/mark/', {'ids': str(n.pk), 'state': 'unread'}, **AJAX).json()['unread'], 1)
		self.assertEqual(c.post('/notifications/delete/', {'ids': str(n.pk)}, **AJAX).json()['unread'], 0)

	def test_badge_text(self):
		from .notifications import badge_text
		self.assertEqual(badge_text(7), '7')
		self.assertEqual(badge_text(150), '99+')
