"""Copies everything from the old SQLite file (db.sqlite3) into PostgreSQL, once.

    python manage.py move_to_postgres

Before running it: install PostgreSQL, create the database and user, and put
DB_NAME / DB_USER / DB_PASSWORD in the .env file (see DATABASES in settings.py).
It then:
  1. builds every table in PostgreSQL (migrate),
  2. copies all rows across — users, profiles, posts, chats, courses, groups... —
     keeping the same ids, so links and uploaded files still match,
  3. resets PostgreSQL's id counters so new rows get fresh ids,
  4. compares row counts table by table.
db.sqlite3 is only read, never changed, so you can always go back by
removing DB_NAME from .env.
"""
import os
import tempfile

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connections

SKIP = ['contenttypes', 'auth.permission', 'admin.logentry', 'sessions']


class Command(BaseCommand):
	help = 'Copies all data from db.sqlite3 into the PostgreSQL database set in .env (run once).'

	def add_arguments(self, parser):
		parser.add_argument('--force', action='store_true', help='Copy even if PostgreSQL already has users in it.')

	def handle(self, *args, **opts):
		if 'sqlite' not in connections.databases or connections['default'].vendor != 'postgresql':
			raise CommandError('PostgreSQL isn\'t set up yet: put DB_NAME, DB_USER and DB_PASSWORD in the .env file '
				'next to manage.py (see DATABASES in uniconnect/settings.py), then run this again.')
		if not os.path.exists(connections.databases['sqlite']['NAME']):
			raise CommandError('There is no db.sqlite3 to copy from.')

		self.stdout.write('1/4  Building the tables in PostgreSQL…')
		call_command('migrate', database='default', interactive=False, verbosity=0)

		User = apps.get_model('auth', 'User')
		if User.objects.using('default').exists() and not opts['force']:
			raise CommandError('PostgreSQL already has users in it, so it looks copied already. '
				'Use --force to copy again into an empty database only.')

		self.stdout.write('2/4  Copying the data (this can take a minute)…')
		fd, path = tempfile.mkstemp(suffix='.json')
		os.close(fd)
		try:
			with open(path, 'w', encoding='utf-8') as out:
				call_command('dumpdata', database='sqlite', exclude=SKIP, natural_foreign=True,
					stdout=out, verbosity=0)
			call_command('loaddata', path, database='default', verbosity=0)
		finally:
			os.remove(path)

		self.stdout.write('3/4  Resetting id counters…')
		models = [m for m in apps.get_models(include_auto_created=True) if not m._meta.proxy]
		sql = connections['default'].ops.sequence_reset_sql(no_style(), models)
		with connections['default'].cursor() as cur:
			for line in sql:
				cur.execute(line)

		self.stdout.write('4/4  Checking row counts…')
		bad = []
		total = 0
		for m in apps.get_models():
			if m._meta.proxy or not m._meta.managed or f'{m._meta.app_label}.{m._meta.model_name}' in SKIP or m._meta.app_label in SKIP:
				continue
			manager = m._base_manager
			old, new = manager.using('sqlite').count(), manager.using('default').count()
			total += new
			if old != new:
				bad.append(f'  {m._meta.label}: SQLite {old}, PostgreSQL {new}')
		if bad:
			self.stdout.write(self.style.WARNING('These tables don\'t match:\n' + '\n'.join(bad)))
		else:
			self.stdout.write(self.style.SUCCESS(f'Done: {total} rows copied and every table matches. '
				'UniConnect now runs on PostgreSQL (db.sqlite3 was left untouched).'))
