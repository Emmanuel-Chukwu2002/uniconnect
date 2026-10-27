from django.urls import path

from . import consumers

# One WebSocket per open tab: ws://<host>/ws/chat/
# (it joins a group for each of the user's conversations; see consumers.py)
websocket_urlpatterns = [
	path('ws/chat/', consumers.ChatConsumer.as_asgi()),
]
