def chat_badge(request):
	"""Unread chats count for the Messages link in UniConnect's sidebar."""
	user = getattr(request, 'user', None)
	if user is None or not user.is_authenticated:
		return {}
	from .services import unread_chats_count
	return {'chat_unread': unread_chats_count(user)}
