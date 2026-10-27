"""
Copies the activity already stored in UniConnect's own tables (likes,
bookmarks, comments, cart items, event registrations, follows) into the
Interaction log, so the recommender also learns from everything that
happened before interaction logging was added.

Safe to re-run: a row is skipped if the same user/item/action is already
in the log.

Usage:
    python manage.py backfill_interactions
"""
from django.core.management.base import BaseCommand

from feed.models import Attendee, Bookmark, CartItem, Comment, Follow, Interaction, Like


class Command(BaseCommand):
	help = "Copy existing likes, bookmarks, comments, carts, registrations and follows into the Interaction log."

	def handle(self, *args, **options):
		existing = set(
			Interaction.objects.values_list('user_id', 'item_type', 'item_id', 'action')
		)

		# (label, queryset, item_type, action, user field, item field, time field)
		sources = [
			('likes', Like.objects.all(), Interaction.ITEM_POST, Interaction.ACTION_LIKE, 'user_id', 'post_id', 'created_at'),
			('bookmarks', Bookmark.objects.all(), Interaction.ITEM_POST, Interaction.ACTION_BOOKMARK, 'user_id', 'post_id', 'created_at'),
			('comments', Comment.objects.all(), Interaction.ITEM_POST, Interaction.ACTION_COMMENT, 'author_id', 'post_id', 'created_at'),
			('cart items', CartItem.objects.all(), Interaction.ITEM_LISTING, Interaction.ACTION_CART, 'user_id', 'listing_id', 'added_at'),
			('event registrations', Attendee.objects.all(), Interaction.ITEM_EVENT, Interaction.ACTION_REGISTER, 'user_id', 'event_id', 'registered_at'),
			('follows', Follow.objects.all(), Interaction.ITEM_USER, Interaction.ACTION_FOLLOW, 'follower_id', 'following_id', 'created_at'),
		]

		total = 0
		for label, queryset, item_type, action, user_field, item_field, time_field in sources:
			new_rows = []
			for user_id, item_id, created_at in queryset.values_list(user_field, item_field, time_field):
				key = (user_id, item_type, item_id, action)
				if key in existing:
					continue
				existing.add(key)
				new_rows.append(Interaction(
					user_id=user_id, item_type=item_type, item_id=item_id,
					action=action, created_at=created_at,
				))
			Interaction.objects.bulk_create(new_rows)
			total += len(new_rows)
			self.stdout.write(f"  {label:<20} {len(new_rows)} new")

		self.stdout.write(self.style.SUCCESS(f"\nDone. {total} interactions added from existing activity."))
