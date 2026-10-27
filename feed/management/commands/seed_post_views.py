"""Adds two weeks of sample view history so Post analytics has something to show.

    python manage.py seed_post_views            add sample views (safe to run again)
    python manage.py seed_post_views --reset    remove the sample views first

For the posts of everyone who has signed in (so: you), it adds views from
other students at the same university over the last 14 days — more on the
day a post went up, fewer after, like real posts. The rows are marked
is_simulated, so they can be told apart from real views and removed.
Real views (people actually scrolling past your posts) are never touched.
"""
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import StudentProfile
from feed.models import Post, PostView


class Command(BaseCommand):
	help = 'Adds sample post views for Post analytics (python manage.py seed_post_views [--reset]).'

	def add_arguments(self, parser):
		parser.add_argument('--reset', action='store_true', help='Remove earlier sample views first.')

	def handle(self, *args, **opts):
		if opts['reset']:
			n, _ = PostView.objects.filter(is_simulated=True).delete()
			self.stdout.write(f'Removed {n} sample views.')
		rng = random.Random(28)
		today = timezone.localdate()
		authors = get_user_model().objects.filter(last_login__isnull=False, student_profile__isnull=False).select_related('student_profile')
		rows = []
		for author in authors:
			others = list(StudentProfile.objects.filter(university=author.student_profile.university, user__is_active=True)
				.exclude(user=author).values_list('user_id', flat=True))
			if not others:
				continue
			for post in Post.objects.filter(author=author, created_at__date__gte=today - timedelta(days=60)):
				posted = max(timezone.localdate(post.created_at), today - timedelta(days=13))
				audience = rng.sample(others, k=min(len(others), rng.randint(15, 70)))
				for i, uid in enumerate(audience):
					# Most people see it in the first couple of days.
					offset = min(int(rng.expovariate(0.7)), (today - posted).days)
					day = posted + timedelta(days=offset)
					rows.append(PostView(post=post, user_id=uid, kind=PostView.FEED, day=day, is_simulated=True))
					if rng.random() < 0.18:
						rows.append(PostView(post=post, user_id=uid, kind=PostView.DETAIL, day=day, is_simulated=True))
		PostView.objects.bulk_create(rows, ignore_conflicts=True, batch_size=1000)
		self.stdout.write(self.style.SUCCESS(f'Added up to {len(rows)} sample views. Open /analytics/ to see them.'))
