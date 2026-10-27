from django.contrib import admin

from .models import Attendee, Bookmark, CartItem, Event, Follow, Interaction, Listing, Notification, PostMedia, Recommendation, Repost, Story, StoryView, Venue, VideoView


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
	list_display = ('title', 'location', 'date', 'category', 'organizer')
	list_filter = ('category',)


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
	list_display = ('follower', 'following', 'created_at')


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
	list_display = ('user', 'created_at', 'expires_at', 'is_active')
	list_filter = ('is_active',)


@admin.register(StoryView)
class StoryViewAdmin(admin.ModelAdmin):
	list_display = ('story', 'viewer', 'viewed_at')


@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
	list_display = ('user', 'post', 'created_at')


@admin.register(Attendee)
class AttendeeAdmin(admin.ModelAdmin):
	list_display = ('user', 'event', 'attendee_type', 'registered_at')
	list_filter = ('attendee_type',)


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
	list_display = ('name', 'venue_type', 'capacity', 'created_by', 'created_at')
	list_filter = ('venue_type',)


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
	list_display = ('title', 'seller', 'category', 'condition', 'price', 'status', 'is_simulated', 'created_at')
	list_filter = ('category', 'condition', 'status', 'is_simulated')


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
	list_display = ('user', 'listing', 'quantity', 'added_at')


@admin.register(Interaction)
class InteractionAdmin(admin.ModelAdmin):
	list_display = ('user', 'action', 'item_type', 'item_id', 'is_simulated', 'created_at')
	list_filter = ('item_type', 'action', 'is_simulated')


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
	list_display = ('user', 'rank', 'listing', 'reason', 'score', 'created_at')
	search_fields = ('user__username', 'listing__title')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
	list_display = ('recipient', 'actor', 'type', 'is_read', 'created_at')
	list_filter = ('type', 'is_read')
	raw_id_fields = ('recipient', 'actor', 'post', 'comment', 'event', 'listing')


@admin.register(PostMedia)
class PostMediaAdmin(admin.ModelAdmin):
	list_display = ('id', 'post', 'order', 'image', 'video', 'ik_url')
	search_fields = ('ik_file_id', 'ik_url')
	raw_id_fields = ('post',)


@admin.register(VideoView)
class VideoViewAdmin(admin.ModelAdmin):
	list_display = ('post', 'user', 'created_at')
	raw_id_fields = ('post', 'user')


@admin.register(Repost)
class RepostAdmin(admin.ModelAdmin):
	list_display = ('user', 'post', 'created_at')
	raw_id_fields = ('user', 'post')


from .models import Block, Report  # noqa: E402  (blocking & reporting, feed/moderation.py)


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
	list_display = ('blocker', 'blocked', 'created_at')
	search_fields = ('blocker__username', 'blocked__username')
	raw_id_fields = ('blocker', 'blocked')


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
	"""The /moderation/ page is the friendlier way to review these."""
	list_display = ('created_at', 'reason', 'reported_user', 'post', 'reporter', 'status', 'reviewed_by')
	list_filter = ('status', 'reason')
	search_fields = ('reported_user__username', 'reporter__username', 'post_snapshot', 'details')
	raw_id_fields = ('reporter', 'reported_user', 'post', 'reviewed_by')


# Campus Pulse (feed/pulse.py)
from .models import PulseInterest, PulseReply, PulseStatus, PulseView  # noqa: E402


@admin.register(PulseStatus)
class PulseStatusAdmin(admin.ModelAdmin):
	list_display = ('user', 'kind', 'audience', 'text', 'created_at', 'expires_at', 'is_active')
	list_filter = ('kind', 'audience', 'is_active')
	search_fields = ('text', 'user__username', 'user__first_name', 'user__last_name')


@admin.register(PulseReply)
class PulseReplyAdmin(admin.ModelAdmin):
	list_display = ('status', 'user', 'answer', 'text', 'created_at')


admin.site.register(PulseView)
admin.site.register(PulseInterest)
