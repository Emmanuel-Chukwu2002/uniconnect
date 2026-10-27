"""
Sample communities, so Communities doesn't look empty in a demo: a mix of
course, department, club, tech, sports and hostel communities at your
university, joined by the simulated sim_ students (and by you, as admin of
two and member of three), with rules, a pending join request and some posts.

Usage:
    python manage.py seed_communities <your username>
    python manage.py seed_communities <your username> --undo   (removes them again)

Everything created is recorded in ml_data/demo_communities.json, which
--undo uses, so real communities are never touched. (Deleting a community
also deletes its posts.)
"""
import json
import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import StudentProfile
from communities.models import Community, CommunityMember, CommunityRule
from feed.models import Comment, Like, Post

User = get_user_model()
RECORD = settings.BASE_DIR / 'ml_data' / 'demo_communities.json'

# (name, topic, join policy, description, rules, sample posts)
COMMUNITIES = [
	('CSC 400 Level', 'courses', 'restricted',
	 'Final-year Computer Science students: lecture updates, project supervision, past questions and exam prep.',
	 ['Keep it about CSC 400 Level courses and projects', 'Share materials — never sell them', 'Be kind; everyone is under pressure'],
	 ['Does anyone have the CSC 411 past questions from 2023?', 'Project defence schedule is out on the departmental board — check your slot.',
	  'Study group for CSC 433 (Networks) in the library, Thursday 4pm. All welcome.']),
	('Python Club', 'tech', 'open',
	 'Learn Python together: weekly challenges, beginner help, Django and data science projects.',
	 ['Ask any question — there are no silly ones', 'Format code in your posts', 'No spam or adverts'],
	 ['This week\'s challenge: write a function that finds the longest palindrome in a string. Post your answers!',
	  'Just deployed my first Django app 🎉 Happy to help anyone stuck on deployment.', 'Free Python crash course this Saturday, Lab 2, 10am.']),
	('Computer Science Department', 'departments', 'open',
	 'Announcements and conversations for everyone in the Department of Computer Science.',
	 ['Official announcements are marked by moderators', 'Respect staff and fellow students'],
	 ['Reminder: course registration closes Friday.', 'The department lab will be open late during exam week.']),
	('Campus Football League', 'sports', 'open',
	 'Fixtures, results and banter for the inter-faculty football league.',
	 ['Banter yes, insults no', 'Post scores with the fixture name'],
	 ['Faculty of Science 2 – 1 Engineering. What a game!', 'Who\'s coming to the semi-final on Saturday?']),
	('Hall 3 Residents', 'campus', 'restricted',
	 'For residents of Hall 3: water and light updates, lost & found, and hostel events.',
	 ['Residents only', 'Lost & found posts must include a photo or clear description'],
	 ['Water will be off tomorrow 9am–12pm for maintenance.', 'Found: a blue flash drive near the reading room. DM me.']),
	('Women in Tech', 'tech', 'open',
	 'Mentorship, internships and support for women studying tech and engineering.',
	 ['Be supportive', 'Share opportunities with deadlines'],
	 ['Google STEP internship applications are open — deadline in two weeks.']),
	('Debate & Public Speaking', 'clubs', 'open',
	 'Practise public speaking, prepare for inter-varsity debates and get feedback.',
	 ['Critique ideas, not people'],
	 ['Motion for Friday: "This house believes AI will create more jobs than it destroys."']),
	('Startup Founders', 'careers', 'open',
	 'Students building startups: ideas, co-founders, funding and pitching.',
	 ['No pyramid schemes', 'Give feedback you would want to receive'],
	 ['Looking for a frontend co-founder for an ed-tech idea. Who\'s in?']),
]


class Command(BaseCommand):
	help = 'Fill Communities with sample communities for one user (and --undo to remove them).'

	def add_arguments(self, parser):
		parser.add_argument('username')
		parser.add_argument('--undo', action='store_true')

	def handle(self, *args, **opts):
		if opts['undo']:
			return self.undo()
		try:
			me = User.objects.get(username=opts['username'])
			student = me.student_profile
		except (User.DoesNotExist, StudentProfile.DoesNotExist):
			raise CommandError(f"No student called {opts['username']!r}.")
		if RECORD.exists():
			self.stdout.write('Removing the previous sample communities first…')
			self.undo()

		people = list(User.objects.filter(student_profile__university=student.university).exclude(pk=me.pk)
					  .order_by('-username')[:40])
		if len(people) < 3:
			raise CommandError('Not enough other students at your university to fill the communities.')
		rng = random.Random(42)
		now = timezone.now()
		ids = []
		with transaction.atomic():
			for i, (name, topic, policy, description, rules, posts) in enumerate(COMMUNITIES):
				if Community.objects.filter(university=student.university, name__iexact=name).exists():
					continue
				creator = me if i in (1, 4) else people[i % len(people)]
				c = Community.objects.create(university=student.university, name=name, topic=topic, join_policy=policy,
											 description=description, created_by=creator)
				Community.objects.filter(pk=c.pk).update(created_at=now - timedelta(days=30 + i * 5))
				ids.append(c.pk)
				CommunityRule.objects.bulk_create([CommunityRule(community=c, text=t, order=n) for n, t in enumerate(rules)])
				CommunityMember.objects.create(community=c, user=creator, role=CommunityMember.ADMIN)
				members = [u for u in rng.sample(people, k=min(len(people), rng.randint(4, 14))) if u.pk != creator.pk]
				if creator != me and i in (0, 2, 3):
					members.append(me)
				for n, u in enumerate(members):
					role = CommunityMember.MODERATOR if n == 0 else CommunityMember.MEMBER
					CommunityMember.objects.get_or_create(community=c, user=u, defaults={'role': role})
				if policy == 'restricted' and creator == me:
					# Someone waiting for you to approve them.
					waiting = next((u for u in people if not CommunityMember.objects.filter(community=c, user=u).exists()), None)
					if waiting:
						CommunityMember.objects.create(community=c, user=waiting, status=CommunityMember.PENDING)
				authors = [creator] + members
				for n, text in enumerate(posts):
					author = authors[n % len(authors)]
					p = Post.objects.create(author=author, content=text, community=c)
					Post.objects.filter(pk=p.pk).update(created_at=now - timedelta(hours=3 + i * 7 + n * 11))
					for liker in rng.sample(authors, k=min(len(authors), rng.randint(0, 6))):
						Like.objects.get_or_create(user=liker, post=p)
					if n == 0 and len(authors) > 1:
						Comment.objects.create(post=p, author=authors[1], content='Thanks for sharing this!')
		RECORD.parent.mkdir(parents=True, exist_ok=True)
		RECORD.write_text(json.dumps({'communities': ids}, indent=2))
		self.stdout.write(self.style.SUCCESS(
			f'Added {len(ids)} sample communities at {student.university.short_name}. '
			f'To remove them: python manage.py seed_communities {me.username} --undo'))

	def undo(self):
		if not RECORD.exists():
			self.stdout.write('Nothing to undo.')
			return
		ids = json.loads(RECORD.read_text()).get('communities', [])
		n, _ = Community.objects.filter(pk__in=ids).delete()
		RECORD.unlink()
		self.stdout.write(self.style.SUCCESS(f'Removed the sample communities ({n} rows).'))
