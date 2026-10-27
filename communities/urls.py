from django.urls import path

from . import views

urlpatterns = [
	path('', views.index, name='communities'),
	path('new/', views.create, name='community_create'),
	path('<int:pk>/', views.detail, name='community_detail'),
	path('<int:pk>/edit/', views.edit, name='community_edit'),
	path('<int:pk>/delete/', views.delete, name='community_delete'),
	path('<int:pk>/join/', views.join, name='community_join'),
	path('<int:pk>/leave/', views.leave, name='community_leave'),
	path('<int:pk>/members/<int:member_id>/<str:action>/', views.member_action, name='community_member_action'),
]
