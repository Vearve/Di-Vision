from django.urls import path

from .consumers import GeologyMapConsumer


websocket_urlpatterns = [
    path('ws/geology/map/', GeologyMapConsumer.as_asgi()),
]
