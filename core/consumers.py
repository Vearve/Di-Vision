import json

from channels.generic.websocket import AsyncWebsocketConsumer


class GeologyMapConsumer(AsyncWebsocketConsumer):
    """Broadcasts map refresh events to all connected geology map clients."""

    group_name = 'geology_map_updates'

    async def connect(self):
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def geology_map_refresh(self, event):
        await self.send(text_data=json.dumps({
            'type': 'refresh',
            'reason': event.get('reason', 'data_changed'),
        }))
