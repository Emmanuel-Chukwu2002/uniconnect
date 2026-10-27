"""The redesigned Communities pages: Explore's Recommended / All Communities,
and a community's Posts / Members / About / Events / Resources tabs."""
from unittest import mock

from django.test import override_settings

from feed.models import Event, LinkPreview, Post
from .models import Community, CommunityMember
from .tests import CommunityTestCase


class ExploreTests(CommunityTestCase):
	def test_recommended_skips_yours_and_tags_and_sort(self):
		mine = self.community(self.ada, 'Python Club')
		chess = self.community(self.ben, 'Chess Society')
		Community.objects.filter(pk=chess.pk).update(tags='Chess, Strategy, Tournaments, Openings, Blitz')
		page = self.as_(self.ada).get('/communities/?tab=explore')
		rec = [c.pk for c in page.context['recommended']]
		self.assertIn(chess.pk, rec)
		self.assertNotIn(mine.pk, rec)                                      # already in it
		html = page.content.decode()
		self.assertIn('Recommended for You', html)
		self.assertIn('All Communities', html)
		self.assertIn('+1', html)                                            # 5 tags: 4 shown, +1
		self.assertEqual([c.name for c in self.client.get('/communities/?tab=explore&sort=name').context['results']],
			['Chess Society', 'Python Club'])
		found = self.client.get('/communities/?tab=explore&q=strategy').context['results']   # tags are searched
		self.assertEqual([c.pk for c in found], [chess.pk])
		self.assertNotIn('recommended', self.client.get('/communities/?tab=explore&q=strategy').context)

	def test_tags_are_cleaned_on_save(self):
		c = self.community(self.ada)
		self.as_(self.ada).post(f'/communities/{c.pk}/edit/', {'name': c.name, 'description': 'x', 'topic': 'tech',
			'join_policy': 'open', 'tags': ' #Python,django , python,  Web   Dev ,'})
		c.refresh_from_db()
		self.assertEqual(c.tag_list, ['Python', 'django', 'Web Dev'])


class CommunityPageTests(CommunityTestCase):
	def test_tabs_roles_and_old_links(self):
		c = self.community(self.ada)
		CommunityMember.objects.create(community=c, user=self.ben)
		Post.objects.create(author=self.ben, content='Need help with channels #Django #Channels', community=c)
		Post.objects.create(author=self.ada, content='Slides: https://example.com/slides.pdf', community=c)
		html = self.as_(self.ben).get(f'/communities/{c.pk}/').content.decode()
		for text in ('Posts', 'Members', 'About', 'Events', 'Resources', 'Admin', 'Student', 'post-card-tag'):
			self.assertIn(text, html)
		self.assertIn('Need help with channels</div>', html)                # trailing tags become chips
		res = self.client.get(f'/communities/{c.pk}/?tab=resources').content.decode()
		self.assertIn('slides.pdf', res)
		self.assertNotIn('Need help with channels', res)
		self.assertEqual(self.client.get(f'/communities/{c.pk}/?tab=media').context['tab'], 'resources')
		self.assertIn('Need help', self.client.get(f'/communities/{c.pk}/?q=channels').content.decode())
		self.assertNotIn('Slides', self.client.get(f'/communities/{c.pk}/?q=channels').content.decode())

	def test_members_add_events_outsiders_cannot_attach(self):
		c = self.community(self.ada)
		data = {'title': 'Hack night', 'category': 'workshop', 'date': '2099-01-10', 'location': 'Lab 2', 'price': '0', 'community': c.pk}
		r = self.as_(self.ada).post('/events/new/', data)
		self.assertRedirects(r, f'/communities/{c.pk}/?tab=events', fetch_redirect_response=False)
		self.assertEqual(Event.objects.get(title='Hack night').community, c)
		self.assertContains(self.client.get(f'/communities/{c.pk}/?tab=events'), 'Hack night')
		self.as_(self.cy).post('/events/new/', dict(data, title='Sneaky'))
		self.assertIsNone(Event.objects.get(title='Sneaky').community)      # not a member: a normal event


class LinkPreviewTests(CommunityTestCase):
	@override_settings(LINK_PREVIEW_ALLOW_PRIVATE=False)
	def test_private_addresses_are_never_fetched(self):
		from feed import link_previews
		with mock.patch('urllib.request.OpenerDirector.open') as opened:
			for url in ('http://127.0.0.1:8000/admin/', 'http://localhost/', 'http://10.0.0.5/', 'http://169.254.169.254/latest/', 'file:///etc/passwd'):
				self.assertIsNone(link_previews.fetch(url))
			opened.assert_not_called()

	def test_post_gets_a_card(self):
		page = {'title': 'Django 5.2 Tutorial', 'description': 'A guide', 'image_url': 'https://x.test/a.png', 'site_name': 'tutorialspoint.com'}
		with mock.patch('feed.link_previews.fetch', return_value=page) as fetched:
			self.as_(self.ada).post('/post/new/', {'content': 'Read this https://www.tutorialspoint.com/django/.'})
			self.as_(self.ada).post('/post/new/', {'content': 'Again https://www.tutorialspoint.com/django/'})
		self.assertEqual(fetched.call_count, 1)                              # saved once, reused
		post = Post.objects.get(content__startswith='Read this')
		self.assertEqual(post.link_preview.url, 'https://www.tutorialspoint.com/django/')
		self.assertContains(self.client.get(f'/post/{post.pk}/'), 'Django 5.2 Tutorial')
		with mock.patch('feed.link_previews.fetch', return_value=None):
			self.as_(self.ada).post('/post/new/', {'content': 'Broken https://nothing.test/'})
		self.assertIsNone(Post.objects.get(content__startswith='Broken').link_preview)
		self.assertFalse(LinkPreview.objects.get(url='https://nothing.test/').ok)
