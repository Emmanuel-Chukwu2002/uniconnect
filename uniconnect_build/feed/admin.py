from django.contrib import admin

from .models import Event, Follow


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
	list_display = ('title', 'location', 'date', 'category', 'organizer')
	list_filter = ('category',)


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
	list_display = ('follower', 'following', 'created_at')
