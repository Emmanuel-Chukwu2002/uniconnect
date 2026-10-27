from django.urls import path

from . import views

urlpatterns = [
	path('', views.board, name='opportunities'),
	path('new/', views.create, name='opportunity_create'),
	path('<int:pk>/', views.detail, name='opportunity_detail'),
	path('<int:pk>/edit/', views.edit, name='opportunity_edit'),
	path('<int:pk>/close/', views.toggle_closed, name='opportunity_close'),
	path('<int:pk>/delete/', views.delete, name='opportunity_delete'),
	path('<int:pk>/save/', views.toggle_save, name='opportunity_save'),
]
