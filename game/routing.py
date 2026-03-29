from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/room/(?P<room_uuid>[0-9a-f-]+)/$', consumers.RoomConsumer.as_asgi()),
    re_path(r'ws/game/(?P<session_id>\d+)/$', consumers.GameConsumer.as_asgi()),
]
