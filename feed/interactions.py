"""Recording what users do, for the recommender.

Views call log_interaction() after a user views a listing, adds it to
their cart, likes a post, and so on. It is deliberately fail-safe: a
problem writing the log must never break the page the user asked for,
so any database error is caught and logged instead of raised.
"""
import logging

from .models import Interaction

logger = logging.getLogger(__name__)


def log_interaction(user, item_type, item_id, action):
	if user is None or not user.is_authenticated or item_id is None:
		return
	try:
		Interaction.objects.create(user=user, item_type=item_type, item_id=item_id, action=action)
	except Exception:
		logger.exception('Could not log interaction %s %s #%s', action, item_type, item_id)
