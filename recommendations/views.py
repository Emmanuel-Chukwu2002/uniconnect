"""POST /recommendations/feedback/ — Interested / Not Interested / Undo.

    item_type   post | listing | book | event | group | community | user
    item_id     the item's id
    value       interested | not_interested | (empty = undo)

Signed-in students only, CSRF-protected (Django's middleware), and only on
items the student can open (engine.can_access): you can't leave feedback on
an invite-only group, a blocked person's listing, your own post, and so on.
The feedback always belongs to request.user, so nobody can change anyone
else's. People You May Know only takes Not interested (following is the
positive action there).
"""
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .engine import can_access
from .feedback import set_feedback
from .models import Feedback as F

TYPES = {t for t, _ in F.ITEM_TYPE_CHOICES}


@login_required
@require_POST
def feedback(request):
	item_type = request.POST.get('item_type', '')
	value = request.POST.get('value') or None
	try:
		item_id = int(request.POST.get('item_id', ''))
	except (TypeError, ValueError):
		item_id = 0
	if item_type not in TYPES or item_id <= 0 or value not in (None, F.INTERESTED, F.NOT_INTERESTED):
		return JsonResponse({'error': 'Invalid feedback.'}, status=400)
	if item_type == F.USER and value == F.INTERESTED:
		return JsonResponse({'error': 'Use Follow for people.'}, status=400)
	if not can_access(request.user, item_type, item_id):
		raise Http404
	stored = set_feedback(request.user, item_type, item_id, value)
	if request.headers.get('x-requested-with') == 'XMLHttpRequest':
		return JsonResponse({'item_type': item_type, 'item_id': item_id, 'value': stored or ''})
	nxt = request.POST.get('next')
	if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
		return redirect(nxt)
	return redirect('home')
