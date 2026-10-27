"""Finishes scheduled posts whose time has come (tells anyone they @mention).

    python manage.py publish_scheduled_posts

Scheduled posts already appear on time by themselves (feed/scheduling.py);
UniConnect also does this step whenever someone uses the site. Run this
from a scheduler only if you want mention notifications sent on time even
when nobody is online.
"""
from django.core.management.base import BaseCommand

from feed.scheduling import publish_due


class Command(BaseCommand):
	help = 'Sends mention notifications for scheduled posts that just went out.'

	def handle(self, *args, **opts):
		n = publish_due()
		self.stdout.write(self.style.SUCCESS(f'Finished {n} scheduled post{"" if n == 1 else "s"}.'))
