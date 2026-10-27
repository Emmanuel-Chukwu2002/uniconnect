from django.urls import path

from . import views

urlpatterns = [
	path('home/', views.home, name='home'),
	path('follow/<int:user_id>/', views.follow_toggle, name='follow_toggle'),
	path('events/', views.events_list, name='events'),

	# Honest placeholders — real feature not built yet, but the nav link
	# goes somewhere real rather than a dead link or a 404.
	path('communities/', views.coming_soon,
		{'title': 'Communities', 'icon': 'bi-people', 'description': "Department, level, and interest-based communities are coming soon."},
		name='communities'),
	path('profile/', views.coming_soon,
		{'title': 'Profile', 'icon': 'bi-person-circle', 'description': "Your public profile page is coming soon."},
		name='profile'),
	path('messages/', views.coming_soon,
		{'title': 'Messages', 'icon': 'bi-chat-dots', 'description': "Direct messaging is coming soon."},
		name='messages'),
	path('notifications/', views.coming_soon,
		{'title': 'Notifications', 'icon': 'bi-bell', 'description': "Notifications are coming soon."},
		name='notifications'),
	path('bookmarks/', views.coming_soon,
		{'title': 'Bookmarks', 'icon': 'bi-bookmark', 'description': "Saving posts and resources is coming soon."},
		name='bookmarks'),
	path('settings/', views.coming_soon,
		{'title': 'Settings', 'icon': 'bi-gear', 'description': "Account settings are coming soon."},
		name='account_settings'),
	path('marketplace/', views.coming_soon,
		{'title': 'Marketplace', 'icon': 'bi-shop', 'description': "Buy and sell with fellow students — coming soon."},
		name='marketplace'),
	path('bookshop/', views.coming_soon,
		{'title': 'Bookshop', 'icon': 'bi-book', 'description': "The bookshop is coming soon."},
		name='bookshop'),
	path('groups/', views.coming_soon,
		{'title': 'Groups', 'icon': 'bi-collection', 'description': "Custom interest groups are coming soon."},
		name='groups'),
	path('top-stories/', views.coming_soon,
		{'title': 'Top Stories', 'icon': 'bi-fire', 'description': "Trending campus stories are coming soon."},
		name='top_stories'),
]
