"""Detail pages in the "app" style (templates/feed/event_detail.html,
templates/feed/listing_detail.html, templates/opportunities/detail.html;
styles in restyle.css, "Detail pages"):

    /events/<id>/                     one event: banner with the date, place and time,
                                      who's attending, Register, Add to calendar
    /events/<id>/calendar.ics         the event as a calendar file (phones and
                                      Google/Outlook calendars open it)
    /marketplace/<id>/chat/           POST: open a chat with the seller, with a
                                      ready-made first message ("Chat seller")
    /marketplace/<id>/offer/          POST amount: the same, offering a price ("Make offer")
    /events/<id>/save/                POST: save / unsave an event for later (Bookmarks > Events)
    /marketplace/sellers/<username>/  a seller's reviews (stars and comments), and the
                                      form to review them once you've chatted with them

When an event or opportunity has no photo of its own, its banner is a free
Pexels photo for its kind (loaded from Pexels' servers; nothing is stored).
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count
from django.http import Http404, HttpResponse, JsonResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Attendee, Event, EventSave, Listing, SellerReview


def pexels(photo_id, w=1260, h=600):
	return f'https://images.pexels.com/photos/{photo_id}/pexels-photo-{photo_id}.jpeg?auto=compress&cs=tinysrgb&w={w}&h={h}&fit=crop'


EVENT_PHOTOS = {
	'conference': 30688592, 'workshop': 5940711, 'concert': 29589096, 'sports': 14658684,
	'exhibition': 29589096, 'networking': 30688592, 'festival': 6147001, 'other': 2305098,
	'primary': 30688592, 'danger': 14658684, 'success': 5940711,
}


def event_banner(event):
	return event.image.url if event.image else pexels(EVENT_PHOTOS.get(event.category, 2305098))


@login_required
def event_detail(request, event_id):
	event = get_object_or_404(Event.objects.select_related('organizer', 'organizer__student_profile'), pk=event_id)
	attendees = list(event.attendees.select_related('user', 'user__student_profile').order_by('-registered_at'))
	mine = next((a for a in attendees if a.user_id == request.user.pk), None)
	count = len(attendees)
	return render(request, 'feed/event_detail.html', {
		'saved': EventSave.objects.filter(user=request.user, event=event).exists(),
		'event': event, 'banner': event_banner(event), 'faces': attendees[:5], 'more': max(0, count - 5),
		'count': count, 'registered': mine is not None, 'is_organizer': event.organizer_id == request.user.pk,
		'full': event.capacity is not None and count >= event.capacity, 'is_past': event.date < timezone.localdate(),
		'share_url': request.build_absolute_uri(reverse('event_detail', args=[event.pk])),
	})


def _ics_text(text):
	return (text or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


@login_required
def event_ics(request, event_id):
	"""The event as an .ics file. Without a start time it's an all-day
	event; with one it's two hours long (events don't store an end time)."""
	event = get_object_or_404(Event, pk=event_id)
	stamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
	if event.time:
		start_utc = timezone.make_aware(datetime.combine(event.date, event.time)).astimezone(dt_timezone.utc)
		end_utc = start_utc + timedelta(hours=2)
		when = [f'DTSTART:{start_utc:%Y%m%dT%H%M%SZ}', f'DTEND:{end_utc:%Y%m%dT%H%M%SZ}']
	else:
		when = [f'DTSTART;VALUE=DATE:{event.date:%Y%m%d}', f'DTEND;VALUE=DATE:{event.date + timedelta(days=1):%Y%m%d}']
	url = request.build_absolute_uri(reverse('event_detail', args=[event.pk]))
	lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//UniConnect//Events//EN', 'BEGIN:VEVENT',
		f'UID:event-{event.pk}@uniconnect', f'DTSTAMP:{stamp}', *when,
		f'SUMMARY:{_ics_text(event.title)}', f'LOCATION:{_ics_text(event.location)}',
		f'DESCRIPTION:{_ics_text((event.description or "") + chr(10) + chr(10) + url)}', f'URL:{url}',
		'END:VEVENT', 'END:VCALENDAR']
	response = HttpResponse('\r\n'.join(lines) + '\r\n', content_type='text/calendar; charset=utf-8')
	safe = ''.join(c if c.isalnum() else '-' for c in event.title).strip('-')[:40] or 'event'
	response['Content-Disposition'] = f'attachment; filename="{safe}.ics"'
	return response


def _chat_with_seller(request, listing, draft):
	from chat import services as chat
	conv, created = chat.direct_conversation(request.user, listing.seller)
	if created:
		chat.announce_new_conversation(conv)
	return redirect(reverse('chat_conversation', args=[conv.pk]) + '?' + urlencode({'draft': draft}))


def _naira(amount):
	return f'₦{amount:,.0f}' if amount == amount.to_integral() else f'₦{amount:,.2f}'


@login_required
@require_POST
def listing_chat(request, listing_id):
	listing = get_object_or_404(Listing.objects.select_related('seller'), pk=listing_id)
	if listing.seller_id == request.user.pk:
		return redirect('listing_detail', listing_id=listing.pk)
	link = request.build_absolute_uri(reverse('listing_detail', args=[listing.pk]))
	return _chat_with_seller(request, listing, f'Hi! Is your “{listing.title}” ({_naira(listing.price)}) still available? {link}')


@login_required
@require_POST
def listing_offer(request, listing_id):
	listing = get_object_or_404(Listing.objects.select_related('seller'), pk=listing_id)
	back = redirect('listing_detail', listing_id=listing.pk)
	if listing.seller_id == request.user.pk or listing.is_sold:
		return back
	try:
		amount = Decimal(str(request.POST.get('amount', '')).replace(',', '').replace('₦', '').strip())
	except (InvalidOperation, ValueError):
		amount = None
	if amount is None or amount <= 0 or amount > Decimal('99999999'):
		messages.error(request, 'Enter the amount you want to offer, in naira.')
		return back
	link = request.build_absolute_uri(reverse('listing_detail', args=[listing.pk]))
	return _chat_with_seller(request, listing,
		f'Hi! Would you take {_naira(amount)} for your “{listing.title}” (listed at {_naira(listing.price)})? {link}')


# ---------------------------------------------------------------------
# Save Event
# ---------------------------------------------------------------------
@login_required
@require_POST
def event_save(request, event_id):
	event = get_object_or_404(Event, pk=event_id)
	save, created = EventSave.objects.get_or_create(user=request.user, event=event)
	if not created:
		save.delete()
	if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
		return JsonResponse({'saved': created})
	nxt = request.POST.get('next')
	if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
		return redirect(nxt)
	return redirect('event_detail', event_id=event.pk)


# ---------------------------------------------------------------------
# Seller reviews
# ---------------------------------------------------------------------
def seller_rating(seller):
	"""{'avg': 4.8, 'count': 12} for a seller (avg is None with no reviews)."""
	r = SellerReview.objects.filter(seller=seller).aggregate(avg=Avg('rating'), count=Count('id'))
	avg = round(r['avg'], 1) if r['avg'] is not None else None
	return {'avg': avg, 'count': r['count'], 'full': int(avg + 0.5) if avg else 0}


def can_review(reviewer, seller):
	"""Only buyers who have really been in touch with the seller can review
	them: both of them sent at least one message in their direct chat."""
	if reviewer.pk == seller.pk:
		return False
	from chat.models import Conversation, Message
	conv = Conversation.objects.filter(direct_key=Conversation.make_direct_key(reviewer.pk, seller.pk)).first()
	if conv is None:
		return False
	senders = set(Message.objects.filter(conversation=conv, sender_id__in=[reviewer.pk, seller.pk])
		.values_list('sender_id', flat=True).distinct())
	return {reviewer.pk, seller.pk} <= senders


@login_required
def seller_reviews(request, username):
	seller = get_object_or_404(get_user_model().objects.select_related('student_profile', 'student_profile__university'),
		username=username, is_active=True)
	reviews = list(SellerReview.objects.filter(seller=seller).select_related('reviewer', 'reviewer__student_profile', 'listing'))
	mine = next((r for r in reviews if r.reviewer_id == request.user.pk), None)
	allowed = can_review(request.user, seller)

	if request.method == 'POST':
		if request.POST.get('action') == 'delete':
			if mine:
				mine.delete()
				messages.success(request, 'Your review was removed.')
			return redirect('seller_reviews', username=seller.username)
		if not allowed:
			messages.error(request, 'You can review a seller after you have chatted with them about an item.')
			return redirect('seller_reviews', username=seller.username)
		try:
			rating = int(request.POST.get('rating', 0))
		except ValueError:
			rating = 0
		if not 1 <= rating <= 5:
			messages.error(request, 'Choose from 1 to 5 stars.')
			return redirect('seller_reviews', username=seller.username)
		listing = Listing.objects.filter(pk=request.POST.get('listing') or 0, seller=seller).first()
		SellerReview.objects.update_or_create(seller=seller, reviewer=request.user, defaults={
			'rating': rating, 'comment': (request.POST.get('comment') or '').strip()[:600], 'listing': listing})
		messages.success(request, 'Thanks — your review is up.' if mine is None else 'Your review was updated.')
		return redirect('seller_reviews', username=seller.username)

	rating = seller_rating(seller)
	bars = []
	for stars in (5, 4, 3, 2, 1):
		n = sum(1 for r in reviews if r.rating == stars)
		bars.append({'stars': stars, 'n': n, 'percent': round(100 * n / len(reviews)) if reviews else 0})
	return render(request, 'feed/seller_reviews.html', {
		'seller': seller, 'reviews': reviews, 'mine': mine, 'can_review': allowed, 'rating': rating, 'bars': bars,
		'is_me': seller.pk == request.user.pk,
		'listings': Listing.objects.filter(seller=seller).order_by('-created_at')[:30],
		'back': request.GET.get('from', ''),
	})
