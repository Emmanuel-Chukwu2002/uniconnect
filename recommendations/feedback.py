"""Interested / Not Interested: reading and changing a student's explicit feedback.

    feedback_map(user, item_type)          {item_id: 'interested' | 'not_interested'}
    set_feedback(user, item_type, id, v)   v = 'interested', 'not_interested' or None (undo)

One row per student and item (Feedback's unique constraint), so a second
click changes the row rather than adding another, and None deletes it.
For posts, "not interested" is feed.HiddenPost (the post menu's existing
choice, which also hides the post from Home and Search): setting one value
clears the other, so a post is never both.

Only the signed-in student's own rows are ever touched: the user always
comes from request.user, never from the request body.
"""
from django.db import IntegrityError, transaction

from .models import Feedback as F

VALUES = (F.INTERESTED, F.NOT_INTERESTED)


def feedback_map(user, item_type):
	if not getattr(user, 'is_authenticated', False):
		return {}
	rows = dict(F.objects.filter(user=user, item_type=item_type).values_list('item_id', 'value'))
	if item_type == F.POST:
		from feed.models import HiddenPost
		for pid in HiddenPost.objects.filter(user=user).values_list('post_id', flat=True):
			rows[pid] = F.NOT_INTERESTED
	return rows


def get_feedback(user, item_type, item_id):
	return feedback_map(user, item_type).get(item_id) if item_type != F.POST else _post_value(user, item_id)


def _post_value(user, post_id):
	from feed.models import HiddenPost
	if HiddenPost.objects.filter(user=user, post_id=post_id).exists():
		return F.NOT_INTERESTED
	return F.objects.filter(user=user, item_type=F.POST, item_id=post_id).values_list('value', flat=True).first()


@transaction.atomic
def set_feedback(user, item_type, item_id, value):
	"""Returns the value now stored (None after an undo)."""
	if value not in VALUES and value is not None:
		raise ValueError(value)
	if item_type == F.POST:
		return _set_post(user, item_id, value)
	if value is None:
		F.objects.filter(user=user, item_type=item_type, item_id=item_id).delete()
		return None
	try:
		with transaction.atomic():
			F.objects.update_or_create(user=user, item_type=item_type, item_id=item_id, defaults={'value': value})
	except IntegrityError:          # two clicks at once: the other request created it first
		F.objects.filter(user=user, item_type=item_type, item_id=item_id).update(value=value)
	return value


def _set_post(user, post_id, value):
	from feed.models import HiddenPost
	if value == F.NOT_INTERESTED:
		F.objects.filter(user=user, item_type=F.POST, item_id=post_id).delete()
		HiddenPost.objects.get_or_create(user=user, post_id=post_id)
		return value
	HiddenPost.objects.filter(user=user, post_id=post_id).delete()
	if value is None:
		F.objects.filter(user=user, item_type=F.POST, item_id=post_id).delete()
		return None
	F.objects.update_or_create(user=user, item_type=F.POST, item_id=post_id, defaults={'value': value})
	return value


def clear_post_interest(user, post_id):
	"""The post menu's existing "Not interested" (HiddenPost) wins over an earlier Interested."""
	F.objects.filter(user=user, item_type=F.POST, item_id=post_id).delete()
