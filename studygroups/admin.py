from django.contrib import admin

from .models import StudyGroup, StudyGroupMember


class MemberInline(admin.TabularInline):
	model = StudyGroupMember
	extra = 0


@admin.register(StudyGroup)
class StudyGroupAdmin(admin.ModelAdmin):
	list_display = ('course_code', 'name', 'university', 'mode', 'max_members', 'is_open', 'created_by', 'created_at')
	list_filter = ('mode', 'is_open', 'university')
	search_fields = ('course_code', 'name', 'description')
	inlines = [MemberInline]
