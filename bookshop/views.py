"""
Bookshop pages:
  /bookshop/                 Discover: hero search, category chips and shelves
  /bookshop/browse/          Every book, with search, filters and sorting
  /bookshop/<id>/            A book: cover, details, seller, Message seller
  /bookshop/sell/            List a book for sale
  /bookshop/<id>/edit/       Edit your listing
  /bookshop/mine/            Your listings (mark reserved / sold, edit, delete)
  /bookshop/saved/           Books you saved
No payments: "Message seller" opens a chat in UniConnect Messages with a
ready-made first message; buyer and seller meet on campus.
"""
import re
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import BookForm
from .models import Book, BookSave, BookView

SHELF_SIZE = 12
PAGE_SIZE = 24
SORTS = {
	'newest': ('Newest first', ['-created_at']),
	'price_low': ('Price: low to high', ['price', '-created_at']),
	'price_high': ('Price: high to low', ['-price', '-created_at']),
	'popular': ('Most saved', ['-n_saves', '-created_at']),
}
COURSE_CODE = re.compile(r'^([A-Za-z]{2,4})\s*(\d{3})$')


def _university_books(user):
	"""Books listed by students of the user's own university."""
	qs = Book.objects.select_related('seller', 'seller__student_profile', 'department')
	student = getattr(user, 'student_profile', None)
	if student is None:
		return qs.none()
	return qs.filter(seller__student_profile__university=student.university)


def _with_saved(books, user):
	"""Marks each book with .is_saved (did the viewer like it?) and .likes
	(how many people liked it) — two small queries for the whole list."""
	books = list(books)
	saved = set(BookSave.objects.filter(user=user, book__in=books).values_list('book_id', flat=True))
	likes = dict(BookSave.objects.filter(book__in=books).values('book').annotate(n=Count('id')).values_list('book', 'n'))
	for b in books:
		b.is_saved = b.pk in saved
		b.likes = likes.get(b.pk, 0)
	return books


def _search(qs, q):
	q = (q or '').strip()
	if not q:
		return qs
	m = COURSE_CODE.match(q)
	if m:  # "csc411" finds "CSC 411"
		q_code = f'{m.group(1).upper()} {m.group(2)}'
		return qs.filter(Q(course_code__iexact=q_code) | Q(title__icontains=q) | Q(description__icontains=q))
	for word in q.split():
		qs = qs.filter(Q(title__icontains=word) | Q(author__icontains=word) | Q(course_code__icontains=word)
					   | Q(description__icontains=word) | Q(department__name__icontains=word))
	return qs


# ---------------------------------------------------------------------
# Browsing
# ---------------------------------------------------------------------
@login_required
def home(request):
	user = request.user
	books = _university_books(user)
	available = books.filter(status=Book.STATUS_AVAILABLE)
	student = getattr(user, 'student_profile', None)

	shelves = []
	def shelf(key, title, subtitle, qs, link, icon):
		items = _with_saved(qs[:SHELF_SIZE], user)
		if items:
			shelves.append({'key': key, 'title': title, 'subtitle': subtitle, 'books': items, 'link': link, 'icon': icon})

	shelf('fresh', 'Fresh on the shelf', 'Just listed by students', available, reverse('bookshop_browse'), 'bi-stars')
	if student and student.department_id:
		shelf('dept', f'For {student.department.name}', 'Books for your courses',
			  available.filter(department_id=student.department_id), reverse('bookshop_browse') + '?dept=mine', 'bi-mortarboard')
	shelf('new', 'Brand new', 'Never been read', available.filter(condition=Book.CONDITION_NEW),
		  reverse('bookshop_browse') + '?condition=new', 'bi-patch-check')
	shelf('used', 'Used & affordable', 'Pre-loved books, lowest prices first',
		  available.exclude(condition=Book.CONDITION_NEW).order_by('price', '-created_at'),
		  reverse('bookshop_browse') + '?condition=used&sort=price_low', 'bi-recycle')
	shelf('budget', 'Under ₦3,000', 'Easy on your pocket', available.filter(price__lte=3000).order_by('price'),
		  reverse('bookshop_browse') + '?max=3000&sort=price_low', 'bi-tag')

	# "Recommended for you" (recommendations/engine.py): your courses and department,
	# people you know, and what you said you're Interested / Not interested in.
	from recommendations.engine import recommend
	recs = recommend(user, 'book', limit=8)

	counts = dict(available.values_list('category').annotate(n=Count('id')))
	categories = [{'code': c, 'label': label, 'icon': Book.CATEGORY_ICONS[c], 'count': counts.get(c, 0)}
				  for c, label in Book.CATEGORY_CHOICES]
	return render(request, 'bookshop/home.html', {
		'shelves': shelves, 'categories': categories, 'tab': 'discover', 'recs': recs,
		'total_available': available.count(),
		'seller_count': available.values('seller').distinct().count(),
	})


@login_required
def browse(request):
	user = request.user
	student = getattr(user, 'student_profile', None)
	qs = _university_books(user).filter(status=Book.STATUS_AVAILABLE)
	q = request.GET.get('q', '').strip()
	category = request.GET.get('category', '')
	condition = request.GET.get('condition', '')
	dept = request.GET.get('dept', '')
	sort = request.GET.get('sort', 'newest')
	max_price = request.GET.get('max', '')

	qs = _search(qs, q)
	if category in dict(Book.CATEGORY_CHOICES):
		qs = qs.filter(category=category)
	if condition == 'new':
		qs = qs.filter(condition=Book.CONDITION_NEW)
	elif condition == 'used':
		qs = qs.exclude(condition=Book.CONDITION_NEW)
	if dept == 'mine' and student:
		qs = qs.filter(department_id=student.department_id)
	if max_price.isdigit():
		qs = qs.filter(price__lte=int(max_price))
	if sort not in SORTS:
		sort = 'newest'
	qs = qs.annotate(n_saves=Count('saves')).order_by(*SORTS[sort][1])

	page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get('page'))
	books = _with_saved(page.object_list, user)
	params = {k: v for k, v in {'q': q, 'category': category, 'condition': condition, 'dept': dept,
								'sort': sort if sort != 'newest' else '', 'max': max_price}.items() if v}

	def link(**changes):
		p = dict(params)
		p.pop('page', None)
		for k, v in changes.items():
			if v:
				p[k] = v
			else:
				p.pop(k, None)
		return '?' + urlencode(p) if p else '?'

	chips = [{'label': 'All', 'href': link(category=''), 'active': not category, 'icon': 'bi-grid'}] + [
		{'label': label, 'href': link(category=c), 'active': category == c, 'icon': Book.CATEGORY_ICONS[c]}
		for c, label in Book.CATEGORY_CHOICES]
	conditions = [
		{'label': 'Any condition', 'href': link(condition=''), 'active': not condition},
		{'label': 'Brand new', 'href': link(condition='new'), 'active': condition == 'new'},
		{'label': 'Used', 'href': link(condition='used'), 'active': condition == 'used'},
	]
	return render(request, 'bookshop/browse.html', {
		'tab': 'browse', 'page': page, 'books': books, 'total': page.paginator.count,
		'q': q, 'category': category, 'category_label': dict(Book.CATEGORY_CHOICES).get(category, ''),
		'condition': condition, 'dept': dept, 'sort': sort, 'max_price': max_price,
		'sorts': [(k, v[0]) for k, v in SORTS.items()], 'chips': chips, 'conditions': conditions,
		'dept_link': link(dept='' if dept == 'mine' else 'mine'), 'clear_link': '?',
		'page_query': urlencode(params),
		'has_filters': bool(q or category or condition or dept or max_price),
	})


@login_required
def detail(request, book_id):
	user = request.user
	book = get_object_or_404(_university_books(user), pk=book_id)
	is_mine = book.seller_id == user.pk
	if not is_mine:
		BookView.objects.get_or_create(book=book, user=user)
	book.is_saved = BookSave.objects.filter(book=book, user=user).exists()
	others = _university_books(user).filter(status=Book.STATUS_AVAILABLE).exclude(pk=book.pk)
	from_seller = _with_saved(others.filter(seller_id=book.seller_id)[:6], user)
	similar_q = Q(category=book.category)
	if book.course_code:
		similar_q |= Q(course_code=book.course_code)
	if book.department_id:
		similar_q |= Q(department_id=book.department_id)
	similar = _with_saved(others.exclude(seller_id=book.seller_id).filter(similar_q)[:12], user)
	seller = book.seller
	first = seller.first_name or seller.username
	extra_shelves = [sh for sh in (
		{'key': 'seller', 'title': f'More from {first}', 'subtitle': '', 'books': from_seller, 'icon': 'bi-person',
		 'link': ''},
		{'key': 'similar', 'title': 'You might also like', 'subtitle': 'Similar books from other students', 'books': similar,
		 'icon': 'bi-stars', 'link': reverse('bookshop_browse') + f'?category={book.category}'},
	) if sh['books']]
	return render(request, 'bookshop/detail.html', {
		'book': book, 'is_mine': is_mine, 'extra_shelves': extra_shelves,
		'seller': seller, 'seller_profile': getattr(seller, 'student_profile', None),
		'seller_books': seller.books.filter(status=Book.STATUS_AVAILABLE).count(),
		'seller_sold': seller.books.filter(status=Book.STATUS_SOLD).count(),
		'views_count': book.views.count(), 'saves_count': book.saves.count(),
		'share_url': request.build_absolute_uri(book.get_absolute_url()),
		'tab': '',
	})


# ---------------------------------------------------------------------
# Selling
# ---------------------------------------------------------------------
@login_required
def sell(request):
	if request.method == 'POST':
		form = BookForm(request.POST, request.FILES, user=request.user)
		if form.is_valid():
			book = form.save(commit=False)
			book.seller = request.user
			# A form that didn't send a department (e.g. a quick API-style post) gets the seller's own.
			if 'department' not in request.POST and not book.department_id:
				student = getattr(request.user, 'student_profile', None)
				if student:
					book.department_id = student.department_id
			book.save()
			messages.success(request, f'“{book.title}” is now on sale in the Bookshop.')
			return redirect(book)
	else:
		form = BookForm(user=request.user)
	return render(request, 'bookshop/form.html', {'form': form, 'tab': 'sell', 'editing': False})


def _own_book(request, book_id):
	book = get_object_or_404(Book, pk=book_id)
	if book.seller_id != request.user.pk:
		raise PermissionDenied('You can only change your own listings.')
	return book


@login_required
def edit(request, book_id):
	book = _own_book(request, book_id)
	if request.method == 'POST':
		form = BookForm(request.POST, request.FILES, instance=book, user=request.user)
		if form.is_valid():
			if request.POST.get('remove_cover') == '1' and not request.FILES.get('cover'):
				form.instance.cover = None
			form.save()
			messages.success(request, 'Your listing was updated.')
			return redirect(book)
	else:
		form = BookForm(instance=book, user=request.user)
	return render(request, 'bookshop/form.html', {'form': form, 'book': book, 'tab': 'mine', 'editing': True})


@login_required
@require_POST
def set_status(request, book_id):
	book = _own_book(request, book_id)
	status = request.POST.get('status')
	if status in dict(Book.STATUS_CHOICES):
		book.status = status
		book.save(update_fields=['status', 'updated_at'])
		messages.success(request, {
			Book.STATUS_AVAILABLE: f'“{book.title}” is available again.',
			Book.STATUS_RESERVED: f'“{book.title}” is marked as reserved.',
			Book.STATUS_SOLD: f'Congrats! “{book.title}” is marked as sold.',
		}[status])
	return redirect(request.POST.get('next') or 'bookshop_mine')


@login_required
@require_POST
def delete(request, book_id):
	book = _own_book(request, book_id)
	title = book.title
	if book.cover:
		book.cover.delete(save=False)
	book.delete()
	messages.success(request, f'“{title}” was removed from the Bookshop.')
	return redirect('bookshop_mine')


@login_required
def mine(request):
	status = request.GET.get('status', 'active')
	qs = request.user.books.select_related('department').annotate(
		n_views=Count('views', distinct=True), n_saves=Count('saves', distinct=True))
	counts = {
		'active': qs.exclude(status=Book.STATUS_SOLD).count(),
		'sold': qs.filter(status=Book.STATUS_SOLD).count(),
	}
	books = qs.filter(status=Book.STATUS_SOLD) if status == 'sold' else qs.exclude(status=Book.STATUS_SOLD)
	return render(request, 'bookshop/mine.html', {'books': books, 'status': status, 'counts': counts, 'tab': 'mine'})


# ---------------------------------------------------------------------
# Saving + contacting
# ---------------------------------------------------------------------
@login_required
def saved(request):
	books = _with_saved([s.book for s in BookSave.objects.filter(user=request.user)
						 .select_related('book', 'book__seller', 'book__seller__student_profile', 'book__department')], request.user)
	return render(request, 'bookshop/saved.html', {'books': books, 'tab': 'saved'})


@login_required
@require_POST
def toggle_save(request, book_id):
	book = get_object_or_404(_university_books(request.user), pk=book_id)
	save, created = BookSave.objects.get_or_create(book=book, user=request.user)
	if not created:
		save.delete()
	return JsonResponse({'saved': created, 'saves': book.saves.count()})


@login_required
@require_POST
def contact(request, book_id):
	"""Opens (or creates) a chat with the seller in Messages, with a
	ready-made first message the buyer can edit before sending."""
	book = get_object_or_404(_university_books(request.user), pk=book_id)
	if book.seller_id == request.user.pk:
		return redirect(book)
	from chat import services as chat
	conv, created = chat.direct_conversation(request.user, book.seller)
	if created:
		chat.announce_new_conversation(conv)
	link = request.build_absolute_uri(book.get_absolute_url())
	draft = f'Hi! Is your book “{book.title}” ({book.price_display}) still available? {link}'
	return redirect(reverse('chat_conversation', args=[conv.pk]) + '?' + urlencode({'draft': draft}))
