"""Removes the sample (seeded) data before a demo or launch, keeping real accounts and their own posts.

    python manage.py clear_sample_data           shows what would be removed (changes nothing)
    python manage.py clear_sample_data --yes     saves a backup (backup_db), then removes it

What counts as sample data — everything the seed_* commands and
generate_simulated_data added, found by the marks they leave:
  * the simulated students (usernames starting sim_) and everything they posted,
    commented, liked, followed, listed or sent;
  * chats that include a simulated student, and the sample Messages / Bookshop /
    Communities / notifications recorded in ml_data/demo_*.json;
  * sample courses (no "added by" person) with their notes, past questions,
    questions, enrolments, timetable slots, deadlines and questions of the day;
  * sample study groups, opportunities, hashtag posts, post views, events and
    marketplace listings (each seed marks them; real ones never carry the mark).
Kept: every real account (anyone who isn't sim_), their own posts, chats with
each other, universities, faculties, departments and levels.
Your previous data comes back with `python manage.py restore_db <backup file>`.
"""
import importlib
import json

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

SIM = 'sim_'
# The per-user seeds that record what they made in ml_data/demo_*.json (each has an undo()).
RECORDED = [
	('Sample chats, calls and statuses (seed_chat)', 'chat.management.commands.seed_chat'),
	('Sample books (seed_bookshop)', 'bookshop.management.commands.seed_bookshop'),
	('Sample communities (seed_communities)', 'communities.management.commands.seed_communities'),
	('Sample notifications (demo_notifications)', 'feed.management.commands.demo_notifications'),
]
DEMO_EVENTS = ['AI & Machine Learning Summit', 'Intro to Web Development Workshop', 'Campus Live: End of Semester Concert',
	'Inter-Faculty Football Championship', 'Final Year Projects Exhibition', 'Tech Careers Networking Night',
	'Cultural Day Festival', 'Chess & Board Games Night']
DEMO_VENUES = ['Main Auditorium', 'Open Field', 'Student Center Hall', 'Virtual Meeting Room']
DEMO_LISTINGS = ['Calculus: Early Transcendentals (8th Ed.)', 'HP EliteBook Laptop (Core i5, 8GB RAM)',
	'Reading Lamp with USB Port', 'Department Hoodie (Computer Science, Size L)', 'Electric Kettle (1.5L)',
	'Badminton Racket Set (2 rackets + shuttlecocks)', 'End of Semester Concert Ticket (VIP)',
	'Scientific Calculator (Casio fx-991ES)', 'Mini Fridge (Table-top, 45L)',
	'Data Structures & Algorithms Notes (Printed)', 'Desk Organizer Set', 'Wireless Earbuds (Bluetooth 5.0)']


def _recorded(module_path):
	"""(command, number of recorded rows) for a per-user seed, or (None, 0) if it has nothing recorded."""
	try:
		mod = importlib.import_module(module_path)
	except ImportError:
		return None, 0
	record = getattr(mod, 'RECORD', None)
	if not record or not record.exists():
		return None, 0
	data = json.loads(record.read_text())
	n = sum(len(v) for v in data.values() if isinstance(v, list)) if isinstance(data, dict) else 0
	return mod.Command(), n


def _delete_files(qs, field):
	for obj in qs:
		f = getattr(obj, field, None)
		if f:
			f.delete(save=False)


class Command(BaseCommand):
	help = 'Removes seeded sample data (dry run unless --yes; backs up first).'

	def add_arguments(self, parser):
		parser.add_argument('--yes', action='store_true', help='Really remove it (a backup is saved first).')
		parser.add_argument('--no-backup', action='store_true', help="Don't save a backup first.")

	def plan(self):
		"""[(label, count, remove-function)] in the order they're removed."""
		from bookshop.models import Book
		from chat.models import Conversation
		from courses.management.commands.seed_today import DMARK, MARK as QMARK
		from courses.models import ClassSlot, Course, CourseMaterial, DailyQuestion, Deadline
		from feed.management.commands.seed_hashtags import POSTS
		from feed.models import Event, Listing, Post, PostView, Venue
		from opportunities.management.commands.seed_opportunities import MARK as OMARK
		from opportunities.models import Opportunity
		from studygroups.management.commands.seed_studygroups import MARK as GMARK
		from studygroups.models import GroupFile, StudyGroup

		User = get_user_model()
		sims = User.objects.filter(username__startswith=SIM)
		steps = []

		for label, path in RECORDED:
			cmd, n = _recorded(path)
			if cmd:
				cmd.stdout = self.stdout
				steps.append((label, n, cmd.undo))

		chats = Conversation.objects.filter(participants__user__in=sims).distinct()
		steps.append(('Chats that include a simulated student', chats.count(), lambda: Conversation.objects.filter(
			pk__in=list(chats.values_list('pk', flat=True))).delete()))

		groups = StudyGroup.objects.filter(description__contains=GMARK)
		def drop_groups():
			_delete_files(GroupFile.objects.filter(group__in=groups), 'file')
			for g in groups:
				if g.conversation_id:
					Conversation.objects.filter(pk=g.conversation_id).delete()
				g.delete()
		steps.append(('Sample study groups (seed_studygroups)', groups.count(), drop_groups))

		opps = Opportunity.objects.filter(description__contains=OMARK)
		steps.append(('Sample opportunities (seed_opportunities)', opps.count(), opps.delete))

		courses = Course.objects.filter(created_by__isnull=True)
		def drop_courses():
			_delete_files(CourseMaterial.objects.filter(course__in=courses), 'file')
			courses.delete()
		steps.append(('Sample courses (seed_courses), with their files, timetable slots and deadlines',
			courses.count(), drop_courses))
		marked = (Deadline.objects.filter(title__endswith=DMARK), DailyQuestion.objects.filter(explanation__startswith=QMARK))
		steps.append(('Sample deadlines and questions of the day (seed_today)', sum(q.count() for q in marked),
			lambda: [q.delete() for q in marked]))

		tags = Post.all_objects.filter(content__in=POSTS)
		steps.append(('Sample hashtag posts (seed_hashtags)', tags.count(), tags.delete))
		views = PostView.objects.filter(is_simulated=True)
		steps.append(('Sample post views (seed_post_views)', views.count(), views.delete))

		events = Event.objects.filter(title__in=DEMO_EVENTS)
		venues = Venue.objects.filter(name__in=DEMO_VENUES)
		def drop_events():
			_delete_files(events, 'image')
			events.delete()
			venues.delete()
		steps.append(('Sample events and venues (seed_demo_events)', events.count() + venues.count(), drop_events))
		listings = Listing.objects.filter(Q(is_simulated=True) | Q(title__in=DEMO_LISTINGS))
		steps.append(('Sample marketplace listings (seed_demo_listings, generate_simulated_data)', listings.count(),
			listings.delete))

		steps.append(('Simulated students and everything they made (generate_simulated_data)', sims.count(),
			lambda: call_command('generate_simulated_data', clear=True, stdout=self.stdout)))
		left = Book.objects.filter(seller__username__startswith=SIM)
		steps.append(('Books still listed by simulated students', left.count(), left.delete))
		return steps

	def handle(self, *args, **opts):
		steps = self.plan()
		real = get_user_model().objects.exclude(username__startswith=SIM)
		self.stdout.write('Sample data found:')
		total = 0
		for label, n, _ in steps:
			self.stdout.write(f'  {n:>6}  {label}')
			total += n
		self.stdout.write(f'Kept: {real.count()} real account(s) — ' + ', '.join(real.values_list('username', flat=True)[:6]))
		if not total:
			self.stdout.write(self.style.SUCCESS('No sample data left.'))
			return
		if not opts['yes']:
			self.stdout.write(self.style.WARNING('Nothing was removed. Run with --yes to remove it (a backup is saved first).'))
			return
		if not opts['no_backup']:
			call_command('backup_db', stdout=self.stdout)
		with transaction.atomic():
			for label, n, remove in steps:
				if n:
					self.stdout.write(f'Removing: {label}…')
					remove()
		self.stdout.write(self.style.SUCCESS('Done. The sample data is gone; real accounts and their own posts are kept.'))
