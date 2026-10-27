"""Gives sample students a few skills so Explore > People and skill search
have something to show.

    python manage.py seed_skills            add 2-5 skills to students who have none
    python manage.py seed_skills --reset    remove the sample skills first

Only students who have never signed in (sample accounts) get skills; your
own profile is left for you to fill in. Sample skills are the ones on those
accounts, so --reset never touches real students' skills.
"""
import random

from django.core.management.base import BaseCommand

from accounts.models import StudentProfile
from feed.models import ProfileSkill, SkillEndorsement
from feed.skills import COMMON


class Command(BaseCommand):
	help = 'Adds sample skills to sample students (python manage.py seed_skills [--reset]).'

	def add_arguments(self, parser):
		parser.add_argument('--reset', action='store_true')

	def handle(self, *args, **opts):
		samples = ProfileSkill.objects.filter(user__last_login__isnull=True)
		if opts['reset']:
			n = samples.count()
			samples.delete()
			self.stdout.write(f'Removed {n} sample skills.')
		rng = random.Random(7)
		users = [s.user for s in StudentProfile.objects.filter(user__last_login__isnull=True, user__is_active=True).select_related('user')]
		have = set(ProfileSkill.objects.values_list('user_id', flat=True))
		added = []
		for u in users:
			if u.pk in have:
				continue
			for name in rng.sample(COMMON, k=rng.randint(2, 5)):
				added.append(ProfileSkill.objects.create(user=u, name=name))
		everyone = [s.user for s in StudentProfile.objects.filter(user__is_active=True).select_related('user')]
		ends = []
		for skill in added:
			for u in rng.sample(everyone, k=min(len(everyone), rng.randint(0, 6))):
				if u.pk != skill.user_id:
					ends.append(SkillEndorsement(skill=skill, user=u))
		SkillEndorsement.objects.bulk_create(ends, ignore_conflicts=True)
		self.stdout.write(self.style.SUCCESS(f'Added {len(added)} skills to {len({s.user_id for s in added})} students.'))
