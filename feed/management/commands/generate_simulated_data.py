"""
Generates a SIMULATED dataset for training and evaluating the recommender:
simulated students, simulated marketplace listings, and the interactions
(listing views, add-to-carts, follows) those students "perform".

Why simulated: a recommender learns from many users interacting with many
items. A final-year demo database has a handful of real accounts, which is
far too little to train or evaluate anything. So the data is generated
from a stated, explainable model of student behaviour (below), and every
simulated row is flagged so it can be reported honestly and removed.

How the simulated students behave (this is the "ground truth" a good
recommender should be able to discover from the interactions alone):

  1. Each department belongs to a GROUP (tech, engineering, science, arts,
     social, law). Each group has typical CATEGORY tastes, e.g. tech
     students lean towards electronics, law students towards textbooks.
  2. Level matters: 100-level students are setting up hostel rooms, so they
     lean towards furniture and appliances.
  3. Each student also has personal taste, so two students in the same
     department are similar but not identical (60% group, 40% personal).
  4. Many items are tied to a subject TOPIC (a law textbook, an Arduino
     kit). Students strongly prefer items matching their own group's topic,
     which category alone can't capture; the item's title says it.
  5. Some items are simply more popular than others.
  6. Students follow others, mostly in their own department and level,
     plus some friends-of-friends.

Every simulated user has a username starting with "sim_" and cannot log in
(unusable password). Simulated listings and interactions carry
is_simulated=True.

Usage:
    python manage.py generate_simulated_data             # 300 students, 200 listings
    python manage.py generate_simulated_data --students 500 --listings 300 --seed 7
    python manage.py generate_simulated_data --clear     # delete all simulated data
"""
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Department, Level, StudentProfile, University
from feed.groups import department_group
from feed.models import Follow, Interaction, Listing

User = get_user_model()

SIM_PREFIX = 'sim_'

CATEGORIES = ['textbooks', 'electronics', 'furniture', 'clothing', 'appliances', 'sports', 'tickets', 'other']

# Typical category taste per department group (relative weights, same order
# as CATEGORIES). This table IS the behaviour model — describe it in the report.
GROUP_TASTES = {
	'tech':        [3, 6, 1, 1, 1, 1, 1, 1],
	'engineering': [3, 4, 1, 1, 2, 2, 1, 1],
	'science':     [5, 3, 1, 1, 1, 1, 1, 1],
	'arts':        [4, 1, 1, 4, 1, 1, 3, 1],
	'social':      [3, 2, 1, 3, 1, 1, 4, 1],
	'law':         [6, 1, 2, 2, 1, 1, 1, 1],
	'general':     [2, 2, 2, 2, 2, 2, 2, 2],
}

# How much a student likes an item depending on the item's topic.
TOPIC_MATCH = 3.0       # item topic == student's group (a law book for a law student)
TOPIC_GENERAL = 1.0     # item useful to anyone (a kettle)
TOPIC_MISMATCH = 0.25   # item for a different group (a law book for an engineer)

# Product catalogue: category -> list of (title, topic, low price, high price).
CATALOGUE = {
	'textbooks': [
		('Introduction to Algorithms (CLRS) textbook', 'tech', 6000, 15000),
		('Python Programming textbook', 'tech', 3000, 8000),
		('Computer Networks by Tanenbaum', 'tech', 4000, 10000),
		('Database System Concepts textbook', 'tech', 4000, 9000),
		('Engineering Mathematics by K.A. Stroud', 'engineering', 4000, 9000),
		('Fundamentals of Electric Circuits textbook', 'engineering', 5000, 12000),
		('Strength of Materials textbook', 'engineering', 3500, 8000),
		('University Physics (Young & Freedman)', 'science', 5000, 12000),
		('Linear Algebra textbook', 'science', 3000, 7000),
		('Calculus past questions and solutions', 'science', 1000, 3000),
		('Things Fall Apart and African literature set', 'arts', 2000, 5000),
		('History of West Africa textbook', 'arts', 2500, 6000),
		('Introduction to Literary Theory', 'arts', 2500, 6000),
		('Principles of Economics (Mankiw)', 'social', 4000, 10000),
		('Introduction to Political Science textbook', 'social', 2500, 6000),
		('Statistics for Economists textbook', 'social', 3000, 7000),
		('Nigerian Constitutional Law textbook', 'law', 6000, 14000),
		('Law of Contract casebook', 'law', 5000, 12000),
		('Criminal Law in Nigeria textbook', 'law', 5000, 12000),
	],
	'electronics': [
		('Raspberry Pi 4 starter kit', 'tech', 35000, 60000),
		('Mechanical keyboard for programming', 'tech', 15000, 30000),
		('External SSD 500GB', 'tech', 25000, 45000),
		('Laptop cooling pad', 'tech', 5000, 12000),
		('Digital multimeter', 'engineering', 6000, 15000),
		('Arduino Uno starter kit', 'engineering', 15000, 30000),
		('Soldering iron kit', 'engineering', 5000, 12000),
		('Scientific calculator Casio fx-991ES', 'science', 6000, 14000),
		('Power bank 20000mAh', 'general', 8000, 18000),
		('Bluetooth speaker', 'general', 7000, 20000),
		('Wireless mouse', 'general', 3000, 8000),
		('USB flash drive 64GB', 'general', 3000, 7000),
		('Used Tecno smartphone', 'general', 40000, 90000),
		('Over-ear headphones', 'general', 8000, 25000),
	],
	'furniture': [
		('Plastic reading chair', 'general', 6000, 12000),
		('Foldable study table', 'general', 10000, 25000),
		('3-tier bookshelf', 'general', 12000, 25000),
		('Single mattress (6 inch)', 'general', 20000, 45000),
		('Shoe rack', 'general', 4000, 9000),
		('Clothes hanger stand', 'general', 5000, 12000),
	],
	'clothing': [
		('Ankara shirt', 'arts', 5000, 12000),
		('Senator native attire', 'social', 10000, 25000),
		('Black suit for moot court', 'law', 20000, 45000),
		('Corporate shirt and tie set', 'law', 7000, 15000),
		('White lab coat', 'science', 4000, 9000),
		('Safety boots for workshop', 'engineering', 12000, 25000),
		('Workshop coverall', 'engineering', 6000, 12000),
		('Sneakers', 'general', 10000, 30000),
		('Hoodie', 'general', 7000, 15000),
		('Jeans trousers', 'general', 6000, 14000),
	],
	'appliances': [
		('Electric kettle', 'general', 5000, 12000),
		('Mini fridge', 'general', 40000, 80000),
		('Standing fan', 'general', 15000, 30000),
		('Pressing iron', 'general', 5000, 12000),
		('Single-plate electric stove', 'general', 8000, 18000),
		('Rechargeable fan', 'general', 12000, 25000),
		('Blender', 'general', 12000, 28000),
	],
	'sports': [
		('Football (size 5)', 'general', 5000, 12000),
		('Football jersey', 'general', 6000, 15000),
		('Badminton rackets pair', 'general', 6000, 15000),
		('Dumbbells pair (5kg)', 'general', 10000, 20000),
		('Skipping rope', 'general', 1500, 4000),
		('Table tennis bats', 'general', 4000, 10000),
	],
	'tickets': [
		('Tech conference pass', 'tech', 3000, 10000),
		('Engineering week dinner ticket', 'engineering', 3000, 8000),
		('Science fair gala ticket', 'science', 2000, 6000),
		('Drama and poetry night ticket', 'arts', 1500, 5000),
		('Comedy show ticket', 'social', 3000, 8000),
		('Faculty week party ticket', 'social', 2000, 6000),
		('Law dinner ticket', 'law', 5000, 12000),
		('Campus concert ticket', 'general', 2000, 6000),
	],
	'other': [
		('Mosquito net', 'general', 2500, 6000),
		('Bucket and basin set', 'general', 3000, 7000),
		('4-way extension box', 'general', 3000, 7000),
		('Umbrella', 'general', 2000, 5000),
		('Desk organizer', 'general', 2000, 5000),
		('Rechargeable reading lamp', 'general', 4000, 10000),
	],
}

CONDITIONS = ['new', 'like_new', 'good', 'fair']
CONDITION_WEIGHTS = [2, 3, 4, 2]
CONDITION_WORDS = {'new': 'Brand new', 'like_new': 'Barely used', 'good': 'Used but in good shape', 'fair': 'Well used, still works'}
LOCATIONS = ['Hostel Block A', 'Hostel Block B', 'Hostel Block C', 'Main Gate', 'Student Center', 'Faculty building', 'Library entrance']

FIRST_NAMES = ['Chinedu', 'Amaka', 'Tunde', 'Fatima', 'Emeka', 'Ngozi', 'Ibrahim', 'Aisha', 'Segun', 'Blessing',
	'Uche', 'Halima', 'Kelechi', 'Funmi', 'Musa', 'Chioma', 'Femi', 'Zainab', 'Ifeanyi', 'Bisi',
	'Obinna', 'Hauwa', 'Kunle', 'Adaeze', 'Yusuf', 'Ebere', 'Dayo', 'Maryam', 'Nnamdi', 'Temitope']
LAST_NAMES = ['Okafor', 'Adeyemi', 'Bello', 'Eze', 'Ogunleye', 'Abubakar', 'Nwosu', 'Balogun', 'Okeke', 'Ibrahim',
	'Chukwu', 'Adebayo', 'Musa', 'Obi', 'Afolabi', 'Danjuma', 'Onyeka', 'Lawal', 'Nwachukwu', 'Usman']


def normalise(weights):
	total = sum(weights)
	return [w / total for w in weights]


class Command(BaseCommand):
	help = "Generate (or --clear) simulated students, listings and interactions for the recommender."

	def add_arguments(self, parser):
		parser.add_argument('--students', type=int, default=300)
		parser.add_argument('--listings', type=int, default=200)
		parser.add_argument('--days', type=int, default=60, help="Spread activity over this many past days.")
		parser.add_argument('--seed', type=int, default=42, help="Same seed = exactly the same dataset.")
		parser.add_argument('--clear', action='store_true', help="Delete all simulated data and stop.")

	def handle(self, *args, **opts):
		if opts['clear']:
			self.clear()
			return

		if User.objects.filter(username__startswith=SIM_PREFIX).exists():
			raise CommandError("Simulated data already exists. Run with --clear first to regenerate it.")

		self.rng = random.Random(opts['seed'])
		self.now = timezone.now()
		self.days = opts['days']

		university = self.pick_university()
		departments = list(Department.objects.filter(faculty__university=university).select_related('faculty'))
		levels_by_dept = {}
		for level in Level.objects.filter(department__in=departments).order_by('order'):
			levels_by_dept.setdefault(level.department_id, []).append(level)
		departments = [d for d in departments if levels_by_dept.get(d.id)]
		if not departments:
			raise CommandError(f"{university} has no departments with levels. Run seed_universities first.")

		with transaction.atomic():
			students = self.create_students(opts['students'], university, departments, levels_by_dept)
			listings = self.create_listings(opts['listings'], students)
			n_views, n_carts = self.simulate_marketplace(students, listings)
			n_follows = self.simulate_follows(students)

		groups = {}
		for s in students:
			groups[s['group']] = groups.get(s['group'], 0) + 1
		self.stdout.write(self.style.SUCCESS(
			f"\nSimulated data created at {university.short_name} (seed {opts['seed']}):\n"
			f"  students:     {len(students)}  ({', '.join(f'{g} {n}' for g, n in sorted(groups.items()))})\n"
			f"  listings:     {len(listings)}\n"
			f"  views:        {n_views}\n"
			f"  add-to-carts: {n_carts}\n"
			f"  follows:      {n_follows}\n"
			f"Remove it all with: python manage.py generate_simulated_data --clear"
		))

	# ------------------------------------------------------------------

	def clear(self):
		interactions = Interaction.objects.filter(is_simulated=True).delete()[0]
		listings = Listing.objects.filter(is_simulated=True).delete()[0]
		users = User.objects.filter(username__startswith=SIM_PREFIX)
		n_users = users.count()
		users.delete()  # cascades to their profiles, follows and remaining listings
		self.stdout.write(self.style.SUCCESS(
			f"Deleted {n_users} simulated students, {listings} simulated listing rows "
			f"and {interactions} simulated interaction rows."
		))

	def pick_university(self):
		profile = StudentProfile.objects.exclude(user__username__startswith=SIM_PREFIX).select_related('university').first()
		if profile:
			return profile.university
		university = University.objects.first()
		if not university:
			raise CommandError("No universities found. Run seed_universities first.")
		return university

	def random_time(self, earliest_days_ago, latest_days_ago=0):
		days_ago = self.rng.uniform(latest_days_ago, earliest_days_ago)
		return self.now - timedelta(days=days_ago)

	def create_students(self, count, university, departments, levels_by_dept):
		students = []
		domain = university.email_domain
		for i in range(1, count + 1):
			dept = self.rng.choice(departments)
			levels = levels_by_dept[dept.id]
			level = self.rng.choice(levels)
			first, last = self.rng.choice(FIRST_NAMES), self.rng.choice(LAST_NAMES)
			username = f'{SIM_PREFIX}{i:04d}'
			user = User.objects.create(
				username=username, first_name=first, last_name=last,
				email=f'{username}@{domain}', password=make_password(None),  # unusable: can't log in
			)
			StudentProfile.objects.create(
				user=user, university=university, faculty=dept.faculty, department=dept, level=level,
				matric_number=f'SIM/{i:04d}', university_email=f'{username}@{domain}', is_verified=True,
			)

			group = department_group(dept.name)
			taste = list(GROUP_TASTES[group])
			if level == levels[0]:  # first year: furnishing a hostel room
				taste[CATEGORIES.index('furniture')] += 3
				taste[CATEGORIES.index('appliances')] += 3
			group_part = normalise(taste)
			personal_part = normalise([self.rng.gammavariate(1.0, 1.0) for _ in CATEGORIES])  # Dirichlet(1)
			preference = [0.6 * g + 0.4 * p for g, p in zip(group_part, personal_part)]

			students.append({
				'user': user, 'group': group, 'department_id': dept.id, 'level_id': level.id,
				'preference': dict(zip(CATEGORIES, preference)),
				# Activity varies a lot between people: most browse a little, a few browse a lot.
				'activity': self.rng.lognormvariate(0, 0.6),
				'joined': self.random_time(self.days, self.days * 0.3),
			})
		return students

	def create_listings(self, count, students):
		listings = []
		for _ in range(count):
			category = self.rng.choices(CATEGORIES, weights=[5, 4, 2, 3, 3, 2, 2, 2])[0]
			title, topic, low, high = self.rng.choice(CATALOGUE[category])
			condition = self.rng.choices(CONDITIONS, weights=CONDITION_WEIGHTS)[0]
			price = round(self.rng.uniform(low, high) * (1.0 if condition in ('new', 'like_new') else 0.75), -2)
			seller = self.rng.choice(students)
			listing = Listing.objects.create(
				seller=seller['user'], title=title, category=category, condition=condition,
				price=price, quantity_available=self.rng.choice([1, 1, 1, 2, 3]),
				location=self.rng.choice(LOCATIONS), is_simulated=True,
				description=f"{CONDITION_WORDS[condition]}. {title}, selling because I no longer need it. "
				            f"Pick-up on campus.",
			)
			created = self.random_time(self.days, 2)
			Listing.objects.filter(pk=listing.pk).update(created_at=created)  # auto_now_add ignores a passed value
			listings.append({
				'listing': listing, 'category': category, 'topic': topic, 'seller_id': seller['user'].id,
				'created': created,
				# Some items are just more appealing (good photos, good price...).
				'appeal': self.rng.lognormvariate(0, 0.5),
			})
		return listings

	def item_score(self, student, item):
		if item['topic'] == student['group']:
			topic = TOPIC_MATCH
		elif item['topic'] == 'general':
			topic = TOPIC_GENERAL
		else:
			topic = TOPIC_MISMATCH
		return student['preference'][item['category']] * topic * item['appeal']

	def simulate_marketplace(self, students, listings):
		rows = []
		n_views = n_carts = 0
		for student in students:
			candidates = [item for item in listings if item['seller_id'] != student['user'].id]
			scores = [self.item_score(student, item) for item in candidates]
			max_score = max(scores)

			n_to_view = max(3, min(60, round(12 * student['activity'])))
			viewed = set()
			for _ in range(n_to_view):
				# 90% of the time a student browses what appeals to them; 10% of
				# the time they click something at random (exploration/noise).
				if self.rng.random() < 0.1:
					index = self.rng.randrange(len(candidates))
				else:
					index = self.rng.choices(range(len(candidates)), weights=scores)[0]
				if index in viewed:
					continue
				viewed.add(index)
				item = candidates[index]
				start = max(student['joined'], item['created'])
				when = start + (self.now - start) * self.rng.random()

				rows.append(self.interaction(student, item['listing'].id, Interaction.ITEM_LISTING, Interaction.ACTION_VIEW, when))
				n_views += 1
				if self.rng.random() < 0.3:  # came back to look again
					rows.append(self.interaction(student, item['listing'].id, Interaction.ITEM_LISTING, Interaction.ACTION_VIEW,
						when + timedelta(hours=self.rng.uniform(1, 48))))
					n_views += 1

				# The more an item appeals to them, the likelier they add it to cart.
				p_cart = 0.05 + 0.35 * (scores[index] / max_score)
				if self.rng.random() < p_cart:
					rows.append(self.interaction(student, item['listing'].id, Interaction.ITEM_LISTING, Interaction.ACTION_CART,
						when + timedelta(minutes=self.rng.uniform(1, 30))))
					n_carts += 1

		rows = [r for r in rows if r.created_at <= self.now]
		Interaction.objects.bulk_create(rows, batch_size=1000)
		return n_views, n_carts

	def simulate_follows(self, students):
		follows = {}  # follower user id -> set of followed user ids

		def weight(a, b):
			w = 1.0
			if a['department_id'] == b['department_id']:
				w *= 6
			if a['level_id'] == b['level_id']:
				w *= 3
			return w

		# Pass 1: people you meet — mostly your own department and level.
		for student in students:
			others = [s for s in students if s is not student]
			k = max(1, min(25, round(self.rng.gauss(6, 3) * student['activity'])))
			chosen = set()
			weights = [weight(student, o) for o in others]
			for _ in range(k):
				chosen.add(self.rng.choices(range(len(others)), weights=weights)[0])
			follows[student['user'].id] = {others[i]['user'].id for i in chosen}

		# Pass 2: friends of friends — following someone your friends follow.
		for student in students:
			mine = follows[student['user'].id]
			friends_of_friends = set()
			for friend in mine:
				friends_of_friends |= follows.get(friend, set())
			friends_of_friends -= mine | {student['user'].id}
			for candidate in friends_of_friends:
				if self.rng.random() < 0.08:
					mine.add(candidate)

		by_id = {s['user'].id: s for s in students}
		follow_rows, interaction_rows = [], []
		for follower_id, targets in follows.items():
			follower = by_id[follower_id]
			for target_id in targets:
				when = max(follower['joined'], by_id[target_id]['joined'])
				when = when + (self.now - when) * self.rng.random()
				follow_rows.append(Follow(follower_id=follower_id, following_id=target_id, status=Follow.STATUS_ACCEPTED))
				interaction_rows.append(self.interaction(follower, target_id, Interaction.ITEM_USER, Interaction.ACTION_FOLLOW, when))
		Follow.objects.bulk_create(follow_rows, batch_size=1000)
		Interaction.objects.bulk_create(interaction_rows, batch_size=1000)
		return len(follow_rows)

	def interaction(self, student, item_id, item_type, action, when):
		return Interaction(
			user=student['user'], item_type=item_type, item_id=item_id,
			action=action, is_simulated=True, created_at=when,
		)
