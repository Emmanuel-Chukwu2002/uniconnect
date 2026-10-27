"""Adds sample posts with #hashtags so Trending and hashtag pages have something to show.

    python manage.py seed_hashtags            add them (safe to run again — it skips ones already there)
    python manage.py seed_hashtags --reset    remove them first, then add them again

For every university with sample students (accounts that have never signed
in), it adds the posts below from those students, spread over the last
ten days, with a few likes. Your own posts and accounts are never touched;
--reset removes only posts whose text is exactly one of these.
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import StudentProfile, University
from feed.models import Like, Post

POSTS = [
	'Exams start in two weeks and my reading table is still a mystery 😅 Who else? #ExamSeason',
	'Library extends opening hours till 10pm from Monday. Use it well! #ExamSeason #LibraryLife',
	'Past questions for COS 401 are in the Course Companion — check the files tab #ExamSeason #COS401',
	'Finally submitted chapter three of my project 🎉 Supervisor said "good, but…" #FinalYearProject',
	'Anyone else building with Django for their final year project? Let\'s share notes #FinalYearProject #Django',
	'Free Python crash course in the ICT centre this Saturday, 10am. Bring a laptop #TechOnCampus #Python',
	'Our hackathon team needs one designer 👀 DM me #TechOnCampus #Hackathon',
	'Power is back in the hostel after three days. NEPA, we forgive you 😂 #HostelLife',
	'Who has a spare extension box? Will return it tomorrow #HostelLife',
	'Departmental week starts Monday — football, quiz and dinner on Friday #DeptWeek',
	'Matching outfits for Cultural Day? We\'re doing green and white #CulturalDay #DeptWeek',
	'SIWES letters are ready at the department office #SIWES',
	'Tips for SIWES interviews: know your CV, be early, ask questions #SIWES #Careers',
	'Statistics tutorial moved to LT 2 today #STA422 #ExamSeason',
]


class Command(BaseCommand):
	help = 'Adds sample posts with #hashtags (python manage.py seed_hashtags [--reset]).'

	def add_arguments(self, parser):
		parser.add_argument('--reset', action='store_true', help='Remove the sample hashtag posts first.')

	def handle(self, *args, **opts):
		if opts['reset']:
			n, _ = Post.objects.filter(content__in=POSTS).delete()
			self.stdout.write(f'Removed {n} sample hashtag posts (and their likes).')
		rng = random.Random(7)
		added = 0
		now = timezone.now()
		for uni in University.objects.all():
			samples = [s.user for s in StudentProfile.objects.filter(university=uni, user__is_active=True, user__last_login__isnull=True).select_related('user')]
			if len(samples) < 3:
				continue
			everyone = [s.user for s in StudentProfile.objects.filter(university=uni, user__is_active=True).select_related('user')]
			for text in POSTS:
				if Post.objects.filter(content=text, author__student_profile__university=uni).exists():
					continue
				post = Post.objects.create(author=rng.choice(samples), content=text)
				Post.objects.filter(pk=post.pk).update(created_at=now - timedelta(hours=rng.randint(2, 240)))
				fans = rng.sample(everyone, k=min(len(everyone), rng.randint(0, 12)))
				Like.objects.bulk_create([Like(user=u, post=post) for u in fans if u.pk != post.author_id], ignore_conflicts=True)
				added += 1
		self.stdout.write(self.style.SUCCESS(f'Added {added} posts with hashtags. Open /explore/ or /search/ to see what\'s trending.'))
