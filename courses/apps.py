from django.apps import AppConfig


class CoursesConfig(AppConfig):
	default_auto_field = 'django.db.models.BigAutoField'
	name = 'courses'
	verbose_name = 'Course Companion'

	def ready(self):
		from . import official  # noqa: F401  (official timetable follows enrolments: signals)
