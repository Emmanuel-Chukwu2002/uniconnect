from django.contrib import admin

from .models import Community, CommunityMember, CommunityRule


class CommunityRuleInline(admin.TabularInline):
	model = CommunityRule
	extra = 0


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
	list_display = ('name', 'university', 'topic', 'join_policy', 'is_verified', 'created_by', 'created_at')
	list_filter = ('university', 'topic', 'join_policy', 'is_verified')
	list_editable = ('is_verified',)      # the blue tick: official communities
	search_fields = ('name', 'description', 'tags')
	raw_id_fields = ('created_by',)
	inlines = [CommunityRuleInline]


@admin.register(CommunityMember)
class CommunityMemberAdmin(admin.ModelAdmin):
	list_display = ('user', 'community', 'role', 'status', 'created_at')
	list_filter = ('role', 'status')
	search_fields = ('user__username', 'user__first_name', 'user__last_name', 'community__name')
	raw_id_fields = ('user', 'community')
