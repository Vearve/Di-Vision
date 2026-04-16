from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import DrillHole, LithologyInterval


def _broadcast_map_refresh(reason):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        'geology_map_updates',
        {
            'type': 'geology_map_refresh',
            'reason': reason,
        },
    )


@receiver(post_save, sender=DrillHole)
def drill_hole_saved(sender, instance, created, **kwargs):
    _broadcast_map_refresh('hole_created' if created else 'hole_updated')


@receiver(post_delete, sender=DrillHole)
def drill_hole_deleted(sender, instance, **kwargs):
    _broadcast_map_refresh('hole_deleted')


@receiver(post_save, sender=LithologyInterval)
def lithology_saved(sender, instance, created, **kwargs):
    _broadcast_map_refresh('lithology_created' if created else 'lithology_updated')


@receiver(post_delete, sender=LithologyInterval)
def lithology_deleted(sender, instance, **kwargs):
    _broadcast_map_refresh('lithology_deleted')
