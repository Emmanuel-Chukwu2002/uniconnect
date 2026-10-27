from django.urls import path

from . import views

# Mounted at /messages/ (uniconnect/urls.py). The name 'messages' is
# what the sidebar's existing Messages link already uses.
urlpatterns = [
	path('', views.chats, name='messages'),
	path('archived/', views.archived, name='chat_archived'),
	path('starred/', views.starred, name='chat_starred'),
	path('c/<int:conversation_id>/', views.conversation, name='chat_conversation'),
	path('c/<int:conversation_id>/history/', views.conversation_history, name='chat_history'),
	path('c/<int:conversation_id>/upload/', views.upload, name='chat_upload'),
	path('c/<int:conversation_id>/action/', views.chat_action, name='chat_action'),
	path('c/<int:conversation_id>/members/', views.conversation_members, name='chat_members'),
	path('c/<int:conversation_id>/poll/', views.poll_create, name='chat_poll_create'),
	path('m/<int:message_id>/star/', views.message_star, name='chat_message_star'),
	path('m/<int:message_id>/forward/', views.message_forward, name='chat_message_forward'),
	path('forward/chats/', views.forward_targets, name='chat_forward_targets'),
	path('m/<int:message_id>/edit/', views.message_edit, name='chat_message_edit'),
	path('m/<int:message_id>/pin/', views.message_pin, name='chat_message_pin'),
	path('poll/<int:message_id>/vote/', views.poll_vote, name='chat_poll_vote'),
	path('poll/<int:message_id>/close/', views.poll_close, name='chat_poll_close'),
	path('c/<int:conversation_id>/info/', views.conversation_info, name='chat_info'),
	path('row/<int:conversation_id>/', views.chat_row, name='chat_row'),
	path('people/', views.people, name='chat_people'),
	path('search/', views.search, name='chat_search'),
	path('start/<int:user_id>/', views.start_direct, name='chat_start'),
	path('groups/new/', views.new_group, name='chat_new_group'),
	path('updates/', views.updates, name='chat_updates'),
	path('communities/', views.communities, name='chat_communities'),
	path('communities/new/', views.new_community, name='chat_new_community'),
	path('communities/<int:community_id>/', views.community_detail, name='chat_community'),
	path('communities/<int:community_id>/groups/new/', views.community_new_group, name='chat_community_new_group'),
	path('communities/<int:community_id>/groups/<int:conversation_id>/join/', views.community_join_group, name='chat_community_join'),
	path('communities/<int:community_id>/members/add/', views.community_add_members, name='chat_community_add_members'),
	path('calls/', views.calls, name='chat_calls'),
	path('you/', views.you, name='chat_you'),
	path('you/settings/', views.update_settings, name='chat_settings'),
]
