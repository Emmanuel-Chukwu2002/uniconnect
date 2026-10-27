"""Give an existing account an admin role, so one login is both a student and an admin.

    python manage.py make_admin ada                       # Super Admin
    python manage.py make_admin ada --role moderator      # or university_admin / support
    python manage.py make_admin ada --role university_admin --university UNN
    python manage.py make_admin ada --remove              # back to a normal student

On a host without a shell (Render's free plan), set SUPER_ADMINS=ada,ben in the
environment: build.sh runs `make_admin --from-env` on every deploy, which makes
those accounts Super Admins once they have signed up. It never creates accounts
or changes passwords."""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from accounts.models import University
from adminpanel import audit
from adminpanel.models import AdminRole

User = get_user_model()
ROLES = [r for r, _ in AdminRole.ROLE_CHOICES]


class Command(BaseCommand):
	help = 'Make an existing account an admin (Super Admin unless --role is given).'

	def add_arguments(self, p):
		p.add_argument('usernames', nargs='*', help='Username(s) or email address(es)')
		p.add_argument('--role', default=AdminRole.SUPER_ADMIN, choices=ROLES)
		p.add_argument('--university', help='Short name or id; needed for university_admin')
		p.add_argument('--remove', action='store_true', help='Take admin access away again')
		p.add_argument('--from-env', action='store_true', help='Read usernames from SUPER_ADMINS')

	def handle(self, *args, usernames, role, university, remove, from_env, **kw):
		if from_env:
			usernames = [u.strip() for u in os.environ.get('SUPER_ADMINS', '').split(',') if u.strip()]
			if not usernames:
				return
		if not usernames:
			raise CommandError('Give a username, e.g. python manage.py make_admin ada')
		uni = None
		if university:
			uni = University.objects.filter(Q(short_name__iexact=university) | Q(pk=int(university) if university.isdigit() else None)).first()
			if not uni:
				raise CommandError(f'No university called {university}.')
		if role == AdminRole.UNIVERSITY_ADMIN and not uni and not remove:
			raise CommandError('A university_admin needs --university, e.g. --university UNN')
		for name in usernames:
			user = User.objects.filter(Q(username__iexact=name) | Q(email__iexact=name)).first()
			if not user:
				msg = f'No account "{name}" yet — sign up first, then run this again.'
				if from_env:
					self.stdout.write(msg)      # don't fail a deploy over it
					continue
				raise CommandError(msg)
			if remove:
				AdminRole.objects.filter(user=user).delete()
				user.is_superuser = user.is_staff = False
				user.save(update_fields=['is_superuser', 'is_staff'])
				audit.log(None, 'role.remove', 'user', user.pk, user.username, 'From the command line')
				self.stdout.write(self.style.SUCCESS(f'{user.username} is no longer an admin.'))
				continue
			if role == AdminRole.SUPER_ADMIN:
				if user.is_superuser:
					continue
				user.is_superuser = user.is_staff = True
				user.save(update_fields=['is_superuser', 'is_staff'])
			else:
				AdminRole.objects.update_or_create(user=user, defaults={'role': role, 'university': uni})
				if not user.is_staff:
					user.is_staff = True
					user.save(update_fields=['is_staff'])
			audit.log(None, 'role.assign', 'user', user.pk, user.username, f'{role} from the command line', uni)
			self.stdout.write(self.style.SUCCESS(f'{user.username} is now {dict(AdminRole.ROLE_CHOICES)[role]}. Open /staff/ to use the dashboard.'))
