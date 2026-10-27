"""Sample Campus Pulse updates from the simulated students (usernames starting sim_),
so the bar on Home has something to show: python manage.py seed_pulse

  --reset   remove the earlier sample updates first
They are posted by sim_ students, so clear_sample_data removes them along with those students."""
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import University
from courses.models import Course
from feed.models import Event, PulseStatus as P
from feed.pulse import expiry_for

User = get_user_model()

SAMPLES = [
	(P.STUDY, 'Trying to understand BIBD. Anyone available to explain the examples?', {'topic': 'Design of Experiments'}),
	(P.STUDY, 'Reading for the test tonight in the library. Who wants to study together?', {}),
	(P.CAMPUS, 'The atmosphere on campus today is amazing!', {}),
	(P.CAMPUS, 'Long queue at the cafeteria, go early if you want jollof.', {}),
	(P.EVENT, 'Bring your laptop. Beginners welcome!', {'event_title': 'Django Workshop', 'event_place': 'Computer Science Department', 'hours_ahead': 5}),
	(P.QUESTION, 'Does anyone know whether COS 401 lectures have been moved to another venue?', {}),
	(P.QUESTION, "Has anyone confirmed tomorrow's lecture time?", {}),
	(P.AVAILABLE, 'Library, 2nd floor', {'activity': 'study', 'hours': 3}),
	(P.AVAILABLE, '', {'activity': 'project', 'hours': 6}),
	(P.PEOPLE, 'Looking for two people to build a Django project with.', {}),
	(P.OPPORTUNITY, 'Our department is organising a student coding challenge. Prizes for the top 3!', {'audience': P.EVERYONE}),
]


class Command(BaseCommand):
	help = 'Adds sample Campus Pulse updates from the simulated (sim_) students.'

	def add_arguments(self, parser):
		parser.add_argument('--reset', action='store_true', help='Remove earlier sample updates first.')

	def handle(self, *args, **opts):
		sims = User.objects.filter(username__startswith='sim_', student_profile__isnull=False)
		if opts['reset']:
			n = P.objects.filter(user__in=sims).delete()[0]
			self.stdout.write(f'Removed {n} sample rows.')
		made = 0
		rng = random.Random(7)
		for uni in University.objects.filter(students__user__in=sims).distinct():
			people = list(sims.filter(student_profile__university=uni).select_related('student_profile')[:40])
			if not people:
				continue
			courses = list(Course.objects.filter(university=uni)[:20])
			now = timezone.now()
			for i, (kind, text, extra) in enumerate(SAMPLES):
				who = people[i % len(people)]
				created = now - timedelta(minutes=rng.randint(0, 600))
				s = P(user=who, kind=kind, text=text, university=uni, audience=extra.get('audience', P.UNIVERSITY), created_at=created)
				if kind in (P.STUDY, P.AVAILABLE) and courses:
					s.course = rng.choice(courses)
				s.topic = extra.get('topic', '')
				s.activity = extra.get('activity', '')
				if kind == P.EVENT:
					s.event_title, s.event_place = extra['event_title'], extra['event_place']
					s.event_at = now + timedelta(hours=extra['hours_ahead'])
					s.event = Event.objects.filter(date__gte=timezone.localdate()).order_by('date').first()
				s.expires_at = expiry_for(kind, created, s.event_at, extra.get('hours'))
				if s.expires_at <= now:
					s.expires_at = now + timedelta(hours=2)
				s.save()
				made += 1
		self.stdout.write(self.style.SUCCESS(f'Added {made} Campus Pulse updates.' if made else
			'No simulated (sim_) students found — run generate_simulated_data first.'))
