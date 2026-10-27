"""Explicit recommendation feedback (recommendations/feedback.py).

Interested / Not Interested is a deliberate choice by the student, so it is
stored apart from the implicit signals (views, likes, saves, joins), which
stay in their own tables. One row per student and item: changing your mind
updates the row, Undo deletes it.

Posts are the one exception for "Not interested": the post menu already
stored that as feed.HiddenPost (it also takes the post out of Home and
Search), so it stays there and isn't duplicated here. feedback.py keeps the
two consistent: a post can't be both Interested and hidden.
"""
from django.conf import settings
from django.db import models


class Feedback(models.Model):
	INTERESTED = 'interested'
	NOT_INTERESTED = 'not_interested'
	VALUE_CHOICES = [(INTERESTED, 'Interested'), (NOT_INTERESTED, 'Not interested')]

	POST = 'post'
	LISTING = 'listing'
	BOOK = 'book'
	EVENT = 'event'
	GROUP = 'group'
	COMMUNITY = 'community'
	USER = 'user'          # People You May Know: "Not interested" dismisses a suggestion
	ITEM_TYPE_CHOICES = [
		(POST, 'Post'), (LISTING, 'Marketplace listing'), (BOOK, 'Book'), (EVENT, 'Event'),
		(GROUP, 'Group'), (COMMUNITY, 'Community'), (USER, 'Person'),
	]

	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='recommendation_feedback')
	# A plain id, like feed.Interaction: the item can be one of several models.
	# Feedback on something that's later deleted is simply never matched again.
	item_type = models.CharField(max_length=10, choices=ITEM_TYPE_CHOICES)
	item_id = models.PositiveIntegerField()
	value = models.CharField(max_length=14, choices=VALUE_CHOICES)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['user', 'item_type', 'item_id'], name='one_feedback_per_student_per_item'),
		]
		indexes = [models.Index(fields=['user', 'item_type'])]

	def __str__(self):
		return f'{self.user} {self.value} {self.item_type} #{self.item_id}'
