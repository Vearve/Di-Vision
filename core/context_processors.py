from .models import Workspace


def user_workspace(request):
    """
    Adds the user's primary workspace name to every template context.
    - Client users:     their Client.workspace name
    - Contractor users: first contractor WorkspaceMembership
    - Superusers/staff with no membership: None (graceful fallback)
    """
    if not request.user.is_authenticated:
        return {'user_workspace': None, 'user_workspace_name': None}

    # Client users: workspace comes from their linked client_profile
    client_profile = getattr(request.user, 'client_profile', None)
    if client_profile and client_profile.workspace:
        ws = client_profile.workspace
        return {'user_workspace': ws, 'user_workspace_name': ws.name}

    # Contractor / staff users: first contractor workspace membership
    membership = (
        request.user.workspace_memberships
        .select_related('workspace')
        .filter(workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR, workspace__is_active=True)
        .order_by('role', 'id')
        .first()
    )
    if membership:
        ws = membership.workspace
        return {'user_workspace': ws, 'user_workspace_name': ws.name}

    return {'user_workspace': None, 'user_workspace_name': None}
