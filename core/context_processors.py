from .models import Workspace


def user_workspace(request):
    """
    Adds the user's primary workspace name to every template context.
    - Client users:     their Client.workspace name
    - Contractor users: first contractor WorkspaceMembership
    - Superusers/staff with no membership: None (graceful fallback)
    """
    if not request.user.is_authenticated:
        return {
            'user_workspace': None,
            'user_workspace_name': None,
            'user_is_client_workspace': False,
        }

    # Client users: client_profile is the primary source of truth.
    # Some legacy client records may not have client_profile.workspace linked yet.
    client_profile = getattr(request.user, 'client_profile', None)
    if client_profile:
        ws = client_profile.workspace
        return {
            'user_workspace': ws,
            'user_workspace_name': ws.name if ws else client_profile.name,
            'user_is_client_workspace': True,
        }

    # Client workspace membership fallback (handles stale UserProfile role values)
    client_membership = (
        request.user.workspace_memberships
        .select_related('workspace')
        .filter(workspace__workspace_type=Workspace.WORKSPACE_CLIENT, workspace__is_active=True)
        .order_by('role', 'id')
        .first()
    )
    if client_membership:
        ws = client_membership.workspace
        return {
            'user_workspace': ws,
            'user_workspace_name': ws.name,
            'user_is_client_workspace': True,
        }

    # Legacy fallback: some client users are still represented only by UserProfile.role.
    profile = getattr(request.user, 'profile', None)
    if profile and getattr(profile, 'is_client', False):
        return {
            'user_workspace': None,
            'user_workspace_name': profile.company or request.user.username,
            'user_is_client_workspace': True,
        }

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
        return {
            'user_workspace': ws,
            'user_workspace_name': ws.name,
            'user_is_client_workspace': False,
        }

    return {
        'user_workspace': None,
        'user_workspace_name': None,
        'user_is_client_workspace': False,
    }
