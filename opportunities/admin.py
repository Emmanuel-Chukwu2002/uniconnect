from django.contrib import admin

from .models import Opportunity, OpportunitySave


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
	list_display = ('title', 'organization', 'kind', 'university', 'deadline', 'is_closed', 'posted_by', 'created_at')
	list_filter = ('kind', 'is_closed', 'university')
	search_fields = ('title', 'organization', 'description')


admin.site.register(OpportunitySave)
