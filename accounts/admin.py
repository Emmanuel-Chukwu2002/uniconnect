from django.contrib import admin

from .models import University, Faculty, Department, Level, StudentProfile, EmailVerificationToken


class FacultyInline(admin.TabularInline):
	model = Faculty
	extra = 1


@admin.register(University)
class UniversityAdmin(admin.ModelAdmin):
	list_display = ('name', 'short_name', 'email_domain', 'is_active')
	inlines = [FacultyInline]


class DepartmentInline(admin.TabularInline):
	model = Department
	extra = 1


@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
	list_display = ('name', 'university')
	list_filter = ('university',)
	inlines = [DepartmentInline]


class LevelInline(admin.TabularInline):
	model = Level
	extra = 1


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
	list_display = ('name', 'faculty')
	list_filter = ('faculty__university', 'faculty')
	inlines = [LevelInline]


@admin.register(Level)
class LevelAdmin(admin.ModelAdmin):
	list_display = ('name', 'department', 'order')
	list_filter = ('department__faculty__university',)


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
	list_display = ('user', 'university', 'department', 'level', 'matric_number', 'is_verified')
	list_filter = ('university', 'is_verified')
	search_fields = ('matric_number', 'user__first_name', 'user__last_name', 'university_email')


admin.site.register(EmailVerificationToken)
