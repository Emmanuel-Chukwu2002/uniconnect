"""Event, listing and opportunity detail pages (feed/details.py)."""
from datetime import time, timedelta
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Faculty, Level, StudentProfile, University
from feed.models import Attendee, Event, Listing

User = get_user_model()


class DetailPageTests(TestCase):
	def setUp(self):
		uni = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		fac = Faculty.objects.create(university=uni, name='Sciences')
		dep = Department.objects.create(faculty=fac, name='Computer Science')
		lvl = Level.objects.create(department=dep, name='400 Level')
		self.uni = uni
		self.ada, self.ben = (self.student(n, uni, fac, dep, lvl) for n in ('ada', 'ben'))
		self.client.force_login(self.ben)

	def student(self, name, uni, fac, dep, lvl):
		user = User.objects.create_user(name, password='x', first_name=name.title())
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=name, university_email=f'{name}@unn.edu.ng')
		return user

	def test_event_page_register_and_calendar(self):
		e = Event.objects.create(title='Tech Career Fair', location='University Auditorium', category='networking',
			date=timezone.localdate() + timedelta(days=5), time=time(10, 0), organizer=self.ada, description='Meet companies.')
		r = self.client.get(f'/events/{e.pk}/')
		self.assertContains(r, 'Tech Career Fair')
		self.assertContains(r, 'Attending (0)')
		self.assertContains(r, 'Save my spot')
		self.client.post('/events/attend/toggle/', {'event_id': e.pk, 'next': f'/events/{e.pk}/'})
		self.assertTrue(Attendee.objects.filter(event=e, user=self.ben).exists())
		self.assertContains(self.client.get(f'/events/{e.pk}/'), "You're registered")
		ics = self.client.get(f'/events/{e.pk}/calendar.ics')
		self.assertEqual(ics['Content-Type'], 'text/calendar; charset=utf-8')
		body = ics.content.decode()
		self.assertIn('SUMMARY:Tech Career Fair', body)
		self.assertIn('DTSTART:', body)

	def test_listing_chat_and_offer_open_a_chat_with_a_draft(self):
		item = Listing.objects.create(seller=self.ada, title='HP Laptop', price=280000, condition='good', location='UNN Campus')
		r = self.client.get(f'/marketplace/{item.pk}/')
		self.assertContains(r, 'Chat Seller')
		self.assertContains(r, 'Make Offer')
		self.assertContains(r, 'Verified student')
		r = self.client.post(f'/marketplace/{item.pk}/chat/')
		draft = parse_qs(urlparse(r['Location']).query)['draft'][0]
		self.assertIn('HP Laptop', draft)
		self.assertIn('₦280,000', draft)
		r = self.client.post(f'/marketplace/{item.pk}/offer/', {'amount': '250,000'})
		self.assertIn('Would you take ₦250,000', parse_qs(urlparse(r['Location']).query)['draft'][0])
		r = self.client.post(f'/marketplace/{item.pk}/offer/', {'amount': 'abc'})
		self.assertEqual(r['Location'], f'/marketplace/{item.pk}/')
		self.client.force_login(self.ada)                     # the seller doesn't chat with himself
		self.assertEqual(self.client.post(f'/marketplace/{item.pk}/chat/')['Location'], f'/marketplace/{item.pk}/')
		self.assertNotContains(self.client.get(f'/marketplace/{item.pk}/'), 'Chat Seller')

	def test_opportunity_page(self):
		from opportunities.models import Opportunity
		o = Opportunity.objects.create(university=self.uni, posted_by=self.ada, title='Software Engineering Internship',
			organization='Tech Corp', kind='internship', is_remote=True, description='Real projects.',
			eligibility='Currently in 300L or 400L; Basic knowledge of Python or JavaScript; Good communication skills',
			apply_url='https://example.com/apply')
		r = self.client.get(f'/opportunities/{o.pk}/')
		self.assertContains(r, 'About the role')
		self.assertContains(r, '<li>Basic knowledge of Python or JavaScript</li>', html=True)
		self.assertContains(r, 'Apply Now')
		self.assertContains(r, '>TC<')


class SaveEventAndReviewTests(DetailPageTests):
	def test_save_event_shows_in_bookmarks(self):
		from feed.models import EventSave
		e = Event.objects.create(title='Hackathon', location='Lab 3', category='workshop',
			date=timezone.localdate() + timedelta(days=3), organizer=self.ada)
		self.assertContains(self.client.get(f'/events/{e.pk}/'), 'Save Event')
		r = self.client.post(f'/events/{e.pk}/save/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
		self.assertEqual(r.json(), {'saved': True})
		self.assertContains(self.client.get('/bookmarks/?tab=events'), 'Hackathon')
		self.assertFalse(Attendee.objects.exists())          # saving is not registering
		self.client.post(f'/events/{e.pk}/save/', {'next': '/bookmarks/?tab=events'})
		self.assertFalse(EventSave.objects.exists())

	def test_only_buyers_who_chatted_can_review(self):
		from chat import services as S
		from chat.models import Message
		from feed.models import SellerReview
		item = Listing.objects.create(seller=self.ada, title='HP Laptop', price=280000)
		url = '/marketplace/sellers/ada/'
		self.assertContains(self.client.get(url), "after you've chatted")
		self.client.post(url, {'rating': 5})
		self.assertFalse(SellerReview.objects.exists())
		conv, _ = S.direct_conversation(self.ben, self.ada)
		S.create_message(conv, self.ben, Message.TEXT, 'Still available?')
		self.client.post(url, {'rating': 5})
		self.assertFalse(SellerReview.objects.exists())      # the seller hasn't replied yet
		S.create_message(conv, self.ada, Message.TEXT, 'Yes!')
		self.client.post(url, {'rating': 4, 'comment': 'Smooth meetup', 'listing': item.pk})
		r = SellerReview.objects.get()
		self.assertEqual((r.rating, r.comment, r.listing), (4, 'Smooth meetup', item))
		self.client.post(url, {'rating': 5})                 # writing again updates it
		self.assertEqual(SellerReview.objects.get().rating, 5)
		self.client.post(url, {'rating': 9})
		self.assertEqual(SellerReview.objects.get().rating, 5)
		self.assertContains(self.client.get(f'/marketplace/{item.pk}/'), '5.0 (1 review)')
		self.client.force_login(self.ada)                    # sellers can't review themselves
		self.assertNotContains(self.client.get(url), 'Rate this seller')
		self.client.force_login(self.ben)
		self.client.post(url, {'action': 'delete'})
		self.assertFalse(SellerReview.objects.exists())
