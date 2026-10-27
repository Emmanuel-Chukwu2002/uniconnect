from django.urls import path

from . import calendar_feed, timetable, views

urlpatterns = [
	path('', views.index, name='courses'),
	path('new/', views.new_course, name='course_new'),
	path('timetable/', timetable.timetable, name='timetable'),
	path('timetable/add/', timetable.add_slot, name='timetable_add'),
	path('timetable/<int:slot_id>/edit/', timetable.edit_slot, name='timetable_edit'),
	path('timetable/<int:slot_id>/delete/', timetable.delete_slot, name='timetable_delete'),
	path('timetable/<int:slot_id>/change/', timetable.change_slot, name='timetable_change'),
	path('timetable/calendar.ics', calendar_feed.download, name='timetable_calendar'),
	path('timetable/calendar/<str:token>.ics', calendar_feed.subscribed, name='timetable_calendar_feed'),
	path('timetable/calendar/reset/', calendar_feed.reset, name='timetable_calendar_reset'),
	path('my/<str:section>/', views.my_section, name='courses_section'),
	path('deadlines/new/', views.deadline_add, name='deadline_add'),
	path('deadlines/<int:deadline_id>/delete/', views.deadline_delete, name='deadline_delete'),
	path('daily/<int:question_id>/answer/', views.daily_answer, name='daily_answer'),
	path('<int:pk>/', views.detail, name='course_detail'),
	path('<int:pk>/add/', views.enroll, name='course_enroll'),
	path('<int:pk>/remove/', views.unenroll, name='course_unenroll'),
	path('<int:pk>/upload/', views.upload, name='course_upload'),
	path('<int:pk>/files/<int:material_id>/', views.download, name='course_file'),
	path('<int:pk>/files/<int:material_id>/delete/', views.delete_material, name='course_file_delete'),
	path('<int:pk>/ask/', views.ask, name='course_ask'),
	path('<int:pk>/q/<int:question_id>/', views.question, name='course_question'),
	path('<int:pk>/q/<int:question_id>/delete/', views.delete_question, name='course_question_delete'),
	path('<int:pk>/q/<int:question_id>/accept/<int:answer_id>/', views.accept, name='course_answer_accept'),
	path('<int:pk>/q/<int:question_id>/answers/<int:answer_id>/delete/', views.delete_answer, name='course_answer_delete'),
]
