"""
Recomputes every student's "Recommended for you" listings and saves them
(the Recommendation table), using the model in feed/recommender.py with the
weights tuned in notebooks/recommender.ipynb.

Run it whenever you want recommendations to reflect new activity and new
listings, e.g. once a day:

    python manage.py train_recommender
    python manage.py train_recommender --show <username>   # also print one student's list
"""
import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from feed.models import Listing, Recommendation
from feed.recommender import build_recommendations


class Command(BaseCommand):
	help = "Recompute and save Marketplace recommendations for every student."

	def add_arguments(self, parser):
		parser.add_argument('--k', type=int, default=None, help="Recommendations per student (default from settings).")
		parser.add_argument('--show', metavar='USERNAME', help="Print this student's recommendations afterwards.")

	def handle(self, *args, **opts):
		try:
			import sklearn  # noqa: F401
		except ImportError:
			raise CommandError("scikit-learn isn't installed in this environment. Run: pip install -r requirements-ml.txt")

		started = time.time()
		recommendations, info = build_recommendations(k=opts['k'])
		if not recommendations:
			self.stdout.write(self.style.WARNING(f"No recommendations produced ({info})."))
			return

		rows = [
			Recommendation(user_id=user_id, listing_id=listing_id, rank=rank, score=score, reason=reason)
			for user_id, items in recommendations.items()
			for rank, (listing_id, score, reason) in enumerate(items, start=1)
		]
		with transaction.atomic():  # swap old for new in one step, so the page never sees a half-built set
			Recommendation.objects.all().delete()
			Recommendation.objects.bulk_create(rows, batch_size=1000)

		self.stdout.write(self.style.SUCCESS(
			f"Saved {len(rows)} recommendations for {len(recommendations)} of {info['students']} students "
			f"in {time.time() - started:.1f}s\n"
			f"  listings: {info['listings']}, ratings used: {info['ratings']}\n"
			f"  weights: {info['weights']} (from {info['settings_file']})"
		))

		if opts['show']:
			user = get_user_model().objects.filter(username=opts['show']).first()
			if not user:
				raise CommandError(f"No user called {opts['show']!r}.")
			titles = dict(Listing.objects.values_list('id', 'title'))
			self.stdout.write(f"\nRecommended for {user.get_full_name() or user.username}:")
			for rank, listing_id, reason in Recommendation.objects.filter(user=user).values_list('rank', 'listing_id', 'reason'):
				self.stdout.write(f"  {rank}. {titles[listing_id]}  ({reason})")
