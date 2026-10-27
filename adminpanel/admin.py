from django.contrib import admin

from .models import AccountAction, AdminLog, AdminRole, Announcement


@admin.register(AdminRole)
class AdminRoleAdmin(admin.ModelAdmin):
	list_display = ('user', 'role', 'university', 'assigned_by', 'created_at')
	list_filter = ('role', 'university')


@admin.register(AdminLog)
class AdminLogAdmin(admin.ModelAdmin):
	list_display = ('created_at', 'actor', 'action', 'target_type', 'target_label')
	list_filter = ('action',)

	def has_change_permission(self, request, obj=None):
		return False

	def has_delete_permission(self, request, obj=None):
		return False


admin.site.register(AccountAction)
admin.site.register(Announcement)
