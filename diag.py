#!/usr/bin/env python
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'DailyDrillReport.settings')
django.setup()

from core.models import Workspace, Client, WorkspaceMembership
from django.contrib.auth import get_user_model
U = get_user_model()

print('=== WORKSPACES ===')
for ws in Workspace.objects.all():
    print(f'  {ws.id}: {ws.name} ({ws.workspace_type}) active={ws.is_active}')

print('\n=== CLIENTS ===')
for c in Client.objects.all():
    ws_name = getattr(c.workspace, 'name', None) if c.workspace else None
    user_name = getattr(c.user, 'username', None) if c.user else None
    print(f'  {c.id}: {c.name} workspace={ws_name} user={user_name}')

print('\n=== WORKSPACE MEMBERSHIPS ===')
for m in WorkspaceMembership.objects.select_related('user', 'workspace').all():
    print(f'  {m.user.username} @ {m.workspace.name} ({m.workspace.workspace_type})')

print('\n=== YOUR USER (pc) ===')
pc = U.objects.filter(username='pc').first()
if pc:
    profile_role = getattr(pc.profile, 'role', None)
    has_client_profile = hasattr(pc, 'client_profile')
    memberships = list(pc.workspace_memberships.values_list('workspace__name', 'workspace__workspace_type'))
    print(f'  id={pc.id}, profile.role={profile_role}')
    print(f'  has_client_profile={has_client_profile}')
    print(f'  memberships={memberships}')
else:
    print('  USER NOT FOUND')
