from django.urls import path

from . import views

urlpatterns = [
	path('', views.home, name='bookshop'),
	path('browse/', views.browse, name='bookshop_browse'),
	path('sell/', views.sell, name='bookshop_sell'),
	path('mine/', views.mine, name='bookshop_mine'),
	path('saved/', views.saved, name='bookshop_saved'),
	path('<int:book_id>/', views.detail, name='bookshop_detail'),
	path('<int:book_id>/edit/', views.edit, name='bookshop_edit'),
	path('<int:book_id>/status/', views.set_status, name='bookshop_status'),
	path('<int:book_id>/delete/', views.delete, name='bookshop_delete'),
	path('<int:book_id>/save/', views.toggle_save, name='bookshop_save'),
	path('<int:book_id>/contact/', views.contact, name='bookshop_contact'),
]
