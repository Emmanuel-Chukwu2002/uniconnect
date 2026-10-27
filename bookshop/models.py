"""
The campus Bookshop: students list books they want to sell (new or
used), others browse, save and contact the seller through UniConnect
Messages. No online payment — buyer and seller agree and meet on campus.

Like everything else in UniConnect, the shop is per university: a
student only sees books listed by students of their own university.
"""
import hashlib

from django.conf import settings
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.urls import reverse

from feed.models import validate_image_size


class Book(models.Model):
	CATEGORY_CHOICES = [
		('textbook', 'Textbooks'),
		('past_questions', 'Past questions'),
		('lecture_notes', 'Lecture notes'),
		('novel', 'Novels & fiction'),
		('self_help', 'Self-help'),
		('religious', 'Religious'),
		('professional', 'Professional & exams'),
		('other', 'Other'),
	]
	CATEGORY_ICONS = {
		'textbook': 'bi-journal-bookmark', 'past_questions': 'bi-question-square', 'lecture_notes': 'bi-pencil-square',
		'novel': 'bi-book-half', 'self_help': 'bi-lightbulb', 'religious': 'bi-brightness-high',
		'professional': 'bi-award', 'other': 'bi-collection',
	}
	CONDITION_NEW = 'new'
	CONDITION_CHOICES = [
		('new', 'Brand new'),
		('like_new', 'Like new'),
		('good', 'Good'),
		('fair', 'Fair'),
	]
	STATUS_AVAILABLE = 'available'
	STATUS_RESERVED = 'reserved'
	STATUS_SOLD = 'sold'
	STATUS_CHOICES = [
		(STATUS_AVAILABLE, 'Available'),
		(STATUS_RESERVED, 'Reserved'),
		(STATUS_SOLD, 'Sold'),
	]
	IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']

	seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='books')
	title = models.CharField(max_length=160)
	author = models.CharField(max_length=120)
	category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='textbook')
	condition = models.CharField(max_length=10, choices=CONDITION_CHOICES, default='good')
	price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
	course_code = models.CharField(max_length=20, blank=True, help_text="e.g. CSC 411 — helps classmates find it.")
	department = models.ForeignKey('accounts.Department', on_delete=models.SET_NULL, null=True, blank=True, related_name='books')
	edition = models.CharField(max_length=40, blank=True, help_text="e.g. 3rd edition, 2021")
	description = models.TextField(blank=True, max_length=1500)
	cover = models.ImageField(
		upload_to='book_covers', blank=True, null=True,
		validators=[FileExtensionValidator(allowed_extensions=IMAGE_EXTENSIONS), validate_image_size],
	)
	meetup_spot = models.CharField(max_length=120, blank=True, help_text="Where you can hand it over, e.g. Faculty of Science gate.")
	contact_phone = models.CharField(max_length=20, blank=True, help_text="Optional — shown so buyers can call or WhatsApp you.")
	status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_AVAILABLE)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ['-created_at']
		indexes = [models.Index(fields=['status', '-created_at'])]

	def __str__(self):
		return f'{self.title} by {self.author}'

	def get_absolute_url(self):
		return reverse('bookshop_detail', args=[self.pk])

	@property
	def is_new(self):
		return self.condition == self.CONDITION_NEW

	@property
	def is_available(self):
		return self.status == self.STATUS_AVAILABLE

	@property
	def category_icon(self):
		return self.CATEGORY_ICONS.get(self.category, 'bi-book')

	@property
	def cover_palette(self):
		"""0-7: picks the colours of the made-up cover shown when there's no photo."""
		return int(hashlib.md5(f'{self.title}|{self.author}'.encode()).hexdigest(), 16) % 8

	@property
	def price_display(self):
		return 'Free' if self.price == 0 else f'₦{self.price:,.0f}'

	@property
	def whatsapp_number(self):
		"""International digits for wa.me (Nigerian 0803… becomes 234803…)."""
		digits = ''.join(ch for ch in self.contact_phone if ch.isdigit())
		if digits.startswith('0') and len(digits) == 11:
			digits = '234' + digits[1:]
		return digits


class BookSave(models.Model):
	"""A student's saved (wishlisted) book."""
	book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='saves')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_books')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-created_at']
		constraints = [models.UniqueConstraint(fields=['book', 'user'], name='unique_book_save')]


class BookView(models.Model):
	"""Someone (other than the seller) opened a book's page — once per person."""
	book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='views')
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='book_views')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [models.UniqueConstraint(fields=['book', 'user'], name='unique_book_view')]
