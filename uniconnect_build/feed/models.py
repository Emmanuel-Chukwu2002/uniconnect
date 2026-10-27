from django.conf import settings
from django.db import models


class Event(models.Model):
	"""A campus event shown in the 'Events' sidebar widget. Deliberately
	minimal for now — full RSVP/calendar functionality is a later module
	in the project plan; this just needs to be real data, not fake HTML."""
	CATEGORY_CHOICES = [
		('primary', 'Primary'),
		('danger', 'Danger'),
		('success', 'Success'),
	]

	title = models.CharField(max_length=200)
	location = models.CharField(max_length=200)
	date = models.DateField()
	category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, default='primary')
	organizer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['date']

	def __str__(self):
		return self.title


class Follow(models.Model):
	"""A simple, direct follow relationship (no approval step) between
	two students — backs the 'Who to follow' widget."""
	follower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='following')
	following = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='followers')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		unique_together = ('follower', 'following')

	def __str__(self):
		return f'{self.follower} follows {self.following}'
