from django.contrib import admin

from .models import Course, CourseAnswer, CourseEnrollment, CourseMaterial, CourseQuestion


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
	list_display = ('code', 'title', 'university', 'department', 'created_by', 'created_at')
	list_filter = ('university',)
	search_fields = ('code', 'title')


@admin.register(CourseMaterial)
class CourseMaterialAdmin(admin.ModelAdmin):
	list_display = ('title', 'course', 'kind', 'year', 'uploaded_by', 'downloads', 'created_at')
	list_filter = ('kind',)
	search_fields = ('title', 'course__code')


class AnswerInline(admin.TabularInline):
	model = CourseAnswer
	extra = 0


@admin.register(CourseQuestion)
class CourseQuestionAdmin(admin.ModelAdmin):
	list_display = ('title', 'course', 'author', 'created_at')
	search_fields = ('title', 'body', 'course__code')
	inlines = [AnswerInline]


admin.site.register(CourseEnrollment)
