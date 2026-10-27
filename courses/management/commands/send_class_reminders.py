"""Sends class reminders to everyone with a class in the next 15 minutes.

    python manage.py send_class_reminders

UniConnect already makes reminders whenever a student has it open
(courses/reminders.py). Run this every 5 minutes from a scheduler (Windows
Task Scheduler, cron, or your host's scheduled jobs) if you also want them
waiting in the bell for students who don't have it open. Safe to run as
often as you like: each class is only reminded about once a day.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from courses.models import ClassChange, ClassSlot
from courses.reminders import LEAD_MINUTES, due_reminders


class Command(BaseCommand):
	help = 'Reminds students about classes starting in the next 15 minutes.'

	def handle(self, *args, **opts):
		now = timezone.localtime()
		soon = (now + timedelta(minutes=LEAD_MINUTES)).time()
		ids = set(ClassSlot.objects.filter(day=now.weekday(), start__gt=now.time(), start__lte=soon)
			.values_list('user_id', flat=True))
		# Classes moved to today from another day (courses/schedule.py).
		ids |= set(ClassChange.objects.filter(status=ClassChange.MOVED, new_date=now.date())
			.values_list('slot__user_id', flat=True))
		sent = 0
		for user in get_user_model().objects.filter(pk__in=ids, is_active=True):
			sent += len(due_reminders(user, now))
		self.stdout.write(self.style.SUCCESS(f'Sent {sent} class reminder{"" if sent == 1 else "s"}.'))
