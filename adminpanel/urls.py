from django.urls import path

from . import views

urlpatterns = [
	path('', views.overview, name='staff_overview'),
	path('search/', views.search, name='staff_search'),
	path('users/', views.users, name='staff_users'),
	path('users/<int:user_id>/', views.user_detail, name='staff_user'),
	path('users/<int:user_id>/action/', views.user_action, name='staff_user_action'),
	path('moderation/', views.content_page('moderation'), name='staff_moderation'),
	path('marketplace/', views.content_page('marketplace'), name='staff_marketplace'),
	path('bookshop/', views.content_page('bookshop'), name='staff_bookshop'),
	path('events/', views.content_page('events'), name='staff_events'),
	path('groups/', views.content_page('groups'), name='staff_groups'),
	path('content/<str:key>/<int:pk>/remove/', views.content_remove, name='staff_content_remove'),
	path('reports/', views.reports, name='staff_reports'),
	path('reports/<int:pk>/', views.report_detail, name='staff_report'),
	path('reports/<int:pk>/action/', views.report_action, name='staff_report_action'),
	path('universities/', views.universities, name='staff_universities'),
	path('universities/<int:pk>/', views.university_detail, name='staff_university'),
	path('analytics/', views.analytics, name='staff_analytics'),
	path('timetable/', views.timetable, name='staff_timetable'),
	path('timetable/template.csv', views.timetable_template, name='staff_timetable_template'),
	path('timetable/<int:pk>/action/', views.timetable_action, name='staff_timetable_action'),
	path('announcements/', views.announcements, name='staff_announcements'),
	path('announcements/<int:pk>/action/', views.announcement_action, name='staff_announcement_action'),
	path('logs/', views.logs, name='staff_logs'),
	path('settings/', views.settings_page, name='staff_settings'),
	path('help/', views.help_page, name='staff_help'),
	path('view/', views.view_platform, name='staff_view'),
	path('view/stop/', views.view_platform_stop, name='staff_view_stop'),
	path('notice/<int:pk>/ok/', views.acknowledge_warning, name='staff_ack_warning'),
]
