"""Puts a backup made by `python manage.py backup_db` back, replacing what's in the database now.

    python manage.py restore_db backups\\uniconnect-2026-10-22_19-00.dump
    python manage.py restore_db backups\\uniconnect-2026-10-22_19-00.dump --yes     (no question)

Everything added since that backup is lost, so it asks first. Stop the server
(Ctrl+C) before restoring. A media-<date>.zip, if you saved one, is put back by
unzipping it into the media/ folder.
"""
import shutil
import sqlite3
import subprocess
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from .backup_db import find_pg_tool, pg_args, pg_env


class Command(BaseCommand):
	help = 'Restores a backup from backups/ (replaces the current data).'

	def add_arguments(self, parser):
		parser.add_argument('file', help='The .dump (PostgreSQL) or .sqlite3 (SQLite) file to restore.')
		parser.add_argument('--yes', action='store_true', help="Don't ask for confirmation.")

	def handle(self, *args, **opts):
		path = Path(opts['file'])
		if not path.exists():
			raise CommandError(f'No such file: {path}')
		conn = connections['default']
		db = conn.settings_dict
		pg = conn.vendor == 'postgresql'
		if pg and path.suffix != '.dump':
			raise CommandError('This project is on PostgreSQL: choose a .dump file made by backup_db.')
		if not pg and path.suffix != '.sqlite3':
			raise CommandError('This project is on SQLite: choose a .sqlite3 file made by backup_db.')
		if not opts['yes']:
			answer = input(f'This replaces everything in the "{db["NAME"]}" database with {path.name}. '
				'Anything added since that backup is lost. Type yes to continue: ')
			if answer.strip().lower() != 'yes':
				self.stdout.write('Cancelled — nothing changed.')
				return
		conn.close()
		if pg:
			cmd = [find_pg_tool('pg_restore'), *pg_args(db), '-d', db['NAME'], '--clean', '--if-exists', '--no-owner', str(path)]
			done = subprocess.run(cmd, env=pg_env(db), capture_output=True, text=True)
			if done.returncode != 0:
				raise CommandError('pg_restore failed: ' + (done.stderr or done.stdout).strip())
		else:
			src = sqlite3.connect(path)
			dst = sqlite3.connect(db['NAME'])
			with dst:
				src.backup(dst)
			src.close(); dst.close()
		self.stdout.write(self.style.SUCCESS(f'Restored {path.name}. Start the server again.'))
