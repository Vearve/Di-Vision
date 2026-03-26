import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'DailyDrillReport.settings')
django.setup()

from core.models import Client, DrillShift

c = Client.objects.first()
print('Client object:', repr(c))
if c:
    print('Client str:', str(c), 'Client name:', c.name, 'Workspace:', c.workspace.name if c.workspace else None)
else:
    print('No client found')

s = DrillShift.objects.first()
print('Shift client:', s.client if s else None)
if s and s.client:
    print('Shift client str:', str(s.client), 'name:', s.client.name, 'workspace:', s.client.workspace.name if s.client.workspace else None)
