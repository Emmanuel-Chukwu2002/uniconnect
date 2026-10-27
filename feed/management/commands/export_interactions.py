"""
Exports the recommender's training data as CSV files, for the Jupyter
notebook where the models are built and evaluated:

    ml_data/interactions.csv   one row per logged interaction
    ml_data/users.csv          one row per student (department, level, group)
    ml_data/listings.csv       one row per marketplace listing

Plain CSV, standard library only, so this works before pandas or
scikit-learn are installed.

Usage:
    python manage.py export_interactions
    python manage.py export_interactions --out my_folder --real-only
"""
import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from accounts.models import StudentProfile
from feed.groups import department_group
from feed.management.commands.generate_simulated_data import SIM_PREFIX
from feed.models import Interaction, Listing


class Command(BaseCommand):
	help = "Export interactions, users and listings to CSV for the recommender notebook."

	def add_arguments(self, parser):
		parser.add_argument('--out', default='ml_data', help="Output folder (relative to the project).")
		parser.add_argument('--real-only', action='store_true', help="Leave out simulated data.")

	def handle(self, *args, **opts):
		out = Path(opts['out'])
		if not out.is_absolute():
			out = Path(settings.BASE_DIR) / out
		out.mkdir(parents=True, exist_ok=True)

		interactions = Interaction.objects.order_by('created_at')
		listings = Listing.objects.all()
		profiles = StudentProfile.objects.select_related('user', 'department', 'level', 'faculty')
		if opts['real_only']:
			interactions = interactions.filter(is_simulated=False)
			listings = listings.filter(is_simulated=False)
			profiles = profiles.exclude(user__username__startswith=SIM_PREFIX)

		n = self.write(out / 'interactions.csv',
			['user_id', 'item_type', 'item_id', 'action', 'weight', 'timestamp', 'is_simulated'],
			([i.user_id, i.item_type, i.item_id, i.action, i.weight, i.created_at.isoformat(), int(i.is_simulated)]
			 for i in interactions.iterator()))
		self.stdout.write(f"  interactions.csv  {n} rows")

		n = self.write(out / 'users.csv',
			['user_id', 'faculty', 'department', 'level', 'group', 'is_simulated'],
			([p.user_id, p.faculty.name, p.department.name, p.level.name, department_group(p.department.name),
			  int(p.user.username.startswith(SIM_PREFIX))]
			 for p in profiles.iterator()))
		self.stdout.write(f"  users.csv         {n} rows")

		n = self.write(out / 'listings.csv',
			['listing_id', 'seller_id', 'title', 'description', 'category', 'condition', 'price', 'status', 'created_at', 'is_simulated'],
			([l.id, l.seller_id, l.title, l.description, l.category, l.condition, l.price, l.status,
			  l.created_at.isoformat(), int(l.is_simulated)]
			 for l in listings.iterator()))
		self.stdout.write(f"  listings.csv      {n} rows")

		self.stdout.write(self.style.SUCCESS(f"\nExported to {out}"))

	@staticmethod
	def write(path, header, rows):
		count = 0
		with open(path, 'w', newline='', encoding='utf-8') as f:
			writer = csv.writer(f)
			writer.writerow(header)
			for row in rows:
				writer.writerow(row)
				count += 1
		return count
