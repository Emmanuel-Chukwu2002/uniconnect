"""Saves the whole database to a file in the backups/ folder.

    python manage.py backup_db                 save a backup now
    python manage.py backup_db --media         ...and zip the media/ folder (uploads) too
    python manage.py backup_db --keep 20       keep the 20 newest backups (default 10)

PostgreSQL: uses pg_dump (installed with PostgreSQL; found on PATH or in
C:\\Program Files\\PostgreSQL\\<version>\\bin) and writes backups/uniconnect-<date>.dump.
SQLite: copies db.sqlite3 to backups/uniconnect-<date>.sqlite3.
Put it back with `python manage.py restore_db <file>`.
"""
import glob
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections


def find_pg_tool(name):
	"""pg_dump / pg_restore: on PATH, or in PostgreSQL's usual install folders."""
	found = shutil.which(name)
	if found:
		return found
	patterns = [rf'C:\Program Files\PostgreSQL\*\bin\{name}.exe', rf'C:\Program Files (x86)\PostgreSQL\*\bin\{name}.exe',
		f'/usr/lib/postgresql/*/bin/{name}', f'/Library/PostgreSQL/*/bin/{name}', f'/opt/homebrew/bin/{name}']
	hits = sorted((h for p in patterns for h in glob.glob(p)), key=lambda h: [int(x) if x.isdigit() else x for x in Path(h).parts])
	if hits:
		return hits[-1]          # the newest PostgreSQL version
	raise CommandError(f"Couldn't find {name}. It comes with PostgreSQL: add PostgreSQL's bin folder to PATH, "
		r'e.g. C:\Program Files\PostgreSQL\18\bin.')


def pg_env(db):
	env = dict(os.environ)
	env['PGPASSWORD'] = db.get('PASSWORD') or ''
	return env


def pg_args(db):
	return ['-h', db.get('HOST') or 'localhost', '-p', str(db.get('PORT') or 5432), '-U', db.get('USER') or 'postgres']


class Command(BaseCommand):
	help = 'Saves the whole database to backups/ (python manage.py backup_db [--media] [--keep N]).'

	def add_arguments(self, parser):
		parser.add_argument('--media', action='store_true', help='Also zip the media/ folder (uploaded files).')
		parser.add_argument('--keep', type=int, default=10, help='How many backups to keep (oldest are deleted). Default 10.')
		parser.add_argument('--dir', default=str(Path(settings.BASE_DIR) / 'backups'), help='Folder to save into.')

	def handle(self, *args, **opts):
		folder = Path(opts['dir'])
		folder.mkdir(parents=True, exist_ok=True)
		stamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
		db = connections['default'].settings_dict

		if connections['default'].vendor == 'postgresql':
			out = folder / f'uniconnect-{stamp}.dump'
			cmd = [find_pg_tool('pg_dump'), *pg_args(db), '-F', 'c', '-f', str(out), db['NAME']]
			done = subprocess.run(cmd, env=pg_env(db), capture_output=True, text=True)
			if done.returncode != 0:
				out.unlink(missing_ok=True)
				raise CommandError('pg_dump failed: ' + (done.stderr or done.stdout).strip())
			pattern = 'uniconnect-*.dump'
		else:
			out = folder / f'uniconnect-{stamp}.sqlite3'
			src = sqlite3.connect(db['NAME'])
			dst = sqlite3.connect(out)
			with dst:
				src.backup(dst)          # a consistent copy even while the server is running
			src.close(); dst.close()
			pattern = 'uniconnect-*.sqlite3'

		size = out.stat().st_size / 1024 / 1024
		self.stdout.write(self.style.SUCCESS(f'Database saved: {out} ({size:.1f} MB)'))

		if opts['media']:
			media = Path(settings.MEDIA_ROOT)
			if media.exists():
				zipped = shutil.make_archive(str(folder / f'media-{stamp}'), 'zip', media)
				self.stdout.write(self.style.SUCCESS(f'Uploads saved: {zipped}'))
			else:
				self.stdout.write('No media/ folder to save.')

		keep = max(1, opts['keep'])
		for pat in (pattern, 'media-*.zip'):
			old = sorted(folder.glob(pat))[:-keep]
			for f in old:
				f.unlink()
			if old:
				self.stdout.write(f'Removed {len(old)} older backup(s) ({pat}), keeping the newest {keep}.')
