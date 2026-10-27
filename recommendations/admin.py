from django.contrib import admin

from .models import Feedback


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
	list_display = ('user', 'item_type', 'item_id', 'value', 'updated_at')
	list_filter = ('item_type', 'value')
	search_fields = ('user__username',)
