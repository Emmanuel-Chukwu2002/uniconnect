"""Tests for the Bookshop (run: python manage.py test bookshop)."""
import io
import shutil
import tempfile
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from accounts.models import Department, Faculty, Level, StudentProfile, University
from .models import Book, BookSave, BookView

User = get_user_model()
TMP_MEDIA = tempfile.mkdtemp()


def png():
	buf = io.BytesIO()
	Image.new('RGB', (60, 90), (30, 60, 200)).save(buf, 'PNG')
	return SimpleUploadedFile('cover.png', buf.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class BookshopTests(TestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(TMP_MEDIA, ignore_errors=True)

	def setUp(self):
		self.unn = University.objects.create(name='University of Nigeria', short_name='UNN', email_domain='unn.edu.ng')
		other = University.objects.create(name='Other University', short_name='OU', email_domain='ou.edu.ng')
		self.me = self.student('ada', self.unn, 'Computer Science')
		self.seller = self.student('ben', self.unn, 'Computer Science')
		self.outsider = self.student('out', other, 'Physics')
		self.client.force_login(self.me)

	def student(self, username, uni, dept):
		user = User.objects.create_user(username, password='x', first_name=username.title())
		fac = Faculty.objects.get_or_create(university=uni, name='Sciences')[0]
		dep = Department.objects.get_or_create(faculty=fac, name=dept)[0]
		lvl = Level.objects.get_or_create(department=dep, name='400 Level')[0]
		StudentProfile.objects.create(user=user, university=uni, faculty=fac, department=dep, level=lvl,
			matric_number=username, university_email=f'{username}@{uni.email_domain}')
		return user

	def book(self, seller=None, **kw):
		data = dict(title='Operating System Concepts', author='Silberschatz', price=12000, condition='good', category='textbook')
		data.update(kw)
		return Book.objects.create(seller=seller or self.seller, **data)

	# ---------- browsing ----------
	def test_home_shows_shelves_for_my_university_only(self):
		self.book(title='Ours', condition='new')
		self.book(seller=self.outsider, title='Theirs')
		html = self.client.get('/bookshop/').content.decode()
		self.assertIn('Fresh on the shelf', html)
		self.assertIn('Brand new', html)
		self.assertIn('Ours', html)
		self.assertNotIn('Theirs', html)

	def test_empty_shop(self):
		self.assertContains(self.client.get('/bookshop/'), 'The shelves are empty')

	def test_search_by_title_author_and_course_code(self):
		self.book(title='Operating System Concepts', course_code='CSC 411')
		self.book(title='Things Fall Apart', author='Chinua Achebe', category='novel')
		self.assertContains(self.client.get('/bookshop/browse/?q=csc411'), 'Operating System Concepts')
		html = self.client.get('/bookshop/browse/?q=achebe').content.decode()
		self.assertIn('Things Fall Apart', html)
		self.assertNotIn('Operating System Concepts', html)

	def test_filters_and_sorting(self):
		self.book(title='Cheap used', price=1000, condition='fair')
		self.book(title='Pricey new', price=9000, condition='new')
		self.book(title='Sold one', status=Book.STATUS_SOLD)
		html = self.client.get('/bookshop/browse/?condition=new').content.decode()
		self.assertIn('Pricey new', html)
		self.assertNotIn('Cheap used', html)
		html = self.client.get('/bookshop/browse/?sort=price_low').content.decode()
		self.assertLess(html.index('Cheap used'), html.index('Pricey new'))
		self.assertNotIn('Sold one', html)            # sold books aren't listed
		self.assertContains(self.client.get('/bookshop/browse/?max=3000'), '1</strong> book')

	def test_detail_counts_one_view_per_person_not_the_seller(self):
		b = self.book()
		self.client.get(f'/bookshop/{b.pk}/')
		self.client.get(f'/bookshop/{b.pk}/')
		self.assertEqual(BookView.objects.filter(book=b).count(), 1)
		self.client.force_login(self.seller)
		self.assertContains(self.client.get(f'/bookshop/{b.pk}/'), 'This is your listing')
		self.assertEqual(BookView.objects.filter(book=b).count(), 1)

	def test_other_universities_books_are_hidden(self):
		b = self.book(seller=self.outsider)
		self.assertEqual(self.client.get(f'/bookshop/{b.pk}/').status_code, 404)

	# ---------- selling ----------
	def test_sell_a_book_with_cover(self):
		r = self.client.post('/bookshop/sell/', {
			'title': 'Python Crash Course', 'author': 'Eric Matthes', 'category': 'textbook', 'condition': 'like_new',
			'price': '6500', 'course_code': 'csc  201', 'contact_phone': '0803 123 4567', 'cover': png(),
		})
		book = Book.objects.get(title='Python Crash Course')
		self.assertRedirects(r, f'/bookshop/{book.pk}/')
		self.assertEqual((book.seller, book.course_code, book.whatsapp_number), (self.me, 'CSC 201', '2348031234567'))
		self.assertTrue(book.cover)
		self.assertEqual(book.department, self.me.student_profile.department)   # defaults to mine

	def test_sell_form_validation(self):
		r = self.client.post('/bookshop/sell/', {'title': '', 'author': 'x', 'category': 'textbook', 'condition': 'good',
												 'price': '-5', 'contact_phone': 'call me'})
		self.assertEqual(r.status_code, 200)
		self.assertFalse(Book.objects.exists())
		self.assertContains(r, 'has-error')

	def test_only_the_seller_can_edit_change_status_or_delete(self):
		b = self.book()
		self.assertEqual(self.client.get(f'/bookshop/{b.pk}/edit/').status_code, 403)
		self.assertEqual(self.client.post(f'/bookshop/{b.pk}/status/', {'status': 'sold'}).status_code, 403)
		self.assertEqual(self.client.post(f'/bookshop/{b.pk}/delete/').status_code, 403)
		self.client.force_login(self.seller)
		self.client.post(f'/bookshop/{b.pk}/status/', {'status': 'reserved'})
		b.refresh_from_db()
		self.assertEqual(b.status, 'reserved')
		self.client.post(f'/bookshop/{b.pk}/delete/')
		self.assertFalse(Book.objects.filter(pk=b.pk).exists())

	def test_my_books_tabs(self):
		self.book(seller=self.me, title='Mine on sale')
		self.book(seller=self.me, title='Mine sold', status=Book.STATUS_SOLD)
		html = self.client.get('/bookshop/mine/').content.decode()
		self.assertIn('Mine on sale', html)
		self.assertNotIn('Mine sold', html)
		self.assertContains(self.client.get('/bookshop/mine/?status=sold'), 'Mine sold')

	# ---------- saving + contacting ----------
	def test_save_toggle_and_saved_page(self):
		b = self.book()
		self.assertEqual(self.client.post(f'/bookshop/{b.pk}/save/').json(), {'saved': True, 'saves': 1})
		self.assertContains(self.client.get('/bookshop/saved/'), b.title)
		self.assertEqual(self.client.post(f'/bookshop/{b.pk}/save/').json()['saved'], False)
		self.assertFalse(BookSave.objects.exists())

	def test_cards_show_the_like_count(self):
		b = self.book(title='Liked book')
		BookSave.objects.create(book=b, user=self.seller)
		BookSave.objects.create(book=b, user=self.outsider)
		html = self.client.get('/bookshop/browse/').content.decode()
		self.assertIn('js-bs-like-count">2</span>', html)
		self.assertEqual(self.client.post(f'/bookshop/{b.pk}/save/').json(), {'saved': True, 'saves': 3})
		self.assertIn('js-bs-like-count">3</span>', self.client.get('/bookshop/saved/').content.decode())
		self.assertContains(self.client.get(f'/bookshop/{b.pk}/'), '3</span> likes')

	def test_message_seller_opens_chat_with_a_ready_made_message(self):
		b = self.book(price=12000)
		r = self.client.post(f'/bookshop/{b.pk}/contact/')
		url = urlparse(r['Location'])
		self.assertTrue(url.path.startswith('/messages/c/'))
		draft = parse_qs(url.query)['draft'][0]
		self.assertIn('“Operating System Concepts” (₦12,000) still available?', draft)
		self.assertIn(f'/bookshop/{b.pk}/', draft)
		# The same chat is reused the second time.
		self.assertEqual(urlparse(self.client.post(f'/bookshop/{b.pk}/contact/')['Location']).path, url.path)

	def test_contact_needs_post(self):
		b = self.book()
		self.assertEqual(self.client.get(f'/bookshop/{b.pk}/contact/').status_code, 405)

	def test_pages_need_login(self):
		self.client.logout()
		for url in ('/bookshop/', '/bookshop/browse/', '/bookshop/sell/', '/bookshop/mine/', '/bookshop/saved/'):
			self.assertEqual(self.client.get(url).status_code, 302, url)
