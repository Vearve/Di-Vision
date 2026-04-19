from functools import wraps
import logging
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.contrib import messages


logger = logging.getLogger(__name__)


def _is_client_context(user):
    """Determine client context from client profile, workspace membership, or legacy profile role."""
    if not getattr(user, 'is_authenticated', False) or getattr(user, 'is_superuser', False):
        return False

    if hasattr(user, 'client_profile'):
        logger.info('role_diag client_context=True source=client_profile user_id=%s', getattr(user, 'id', None))
        return True

    try:
        from core.models import WorkspaceMembership, Workspace
        if WorkspaceMembership.objects.filter(
            user=user,
            workspace__workspace_type=Workspace.WORKSPACE_CLIENT,
            workspace__is_active=True,
        ).exists():
            logger.info('role_diag client_context=True source=workspace_membership user_id=%s', getattr(user, 'id', None))
            return True
    except Exception:
        # Keep decorators resilient if workspace models are unavailable.
        logger.exception('role_diag workspace_membership_lookup_failed user_id=%s', getattr(user, 'id', None))
        pass

    profile = getattr(user, 'profile', None)
    is_client = bool(profile and getattr(profile, 'is_client', False))
    if is_client:
        logger.info('role_diag client_context=True source=legacy_profile user_id=%s', getattr(user, 'id', None))
    return is_client


def role_required(roles):
    """
    Decorator that checks if the user has any of the specified roles.
    Args:
        roles: String or list of role names
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                messages.warning(request, 'Please login to continue.')
                return redirect('accounts:login')

            # Superusers can access everything
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)

            if isinstance(roles, str):
                allowed_roles = [roles]
            else:
                allowed_roles = roles

            is_client_user = _is_client_context(request.user)

            # Workspace-aware client access path.
            if 'client' in allowed_roles and is_client_user:
                logger.info(
                    'role_diag access_granted route=%s user_id=%s allowed_roles=%s reason=client_context',
                    getattr(request, 'path', ''),
                    getattr(request.user, 'id', None),
                    allowed_roles,
                )
                return view_func(request, *args, **kwargs)

            # Prevent client-context users from accessing contractor/manager-only routes.
            if is_client_user and 'client' not in allowed_roles:
                logger.warning(
                    'role_diag access_denied route=%s user_id=%s allowed_roles=%s reason=client_to_non_client_route',
                    getattr(request, 'path', ''),
                    getattr(request.user, 'id', None),
                    allowed_roles,
                )
                messages.error(request, 'You do not have permission to perform this action.')
                raise PermissionDenied('Client users cannot access this route')

            if not hasattr(request.user, 'profile'):
                messages.error(request, 'User profile not found.')
                return redirect('accounts:login')

            if request.user.profile.role not in allowed_roles:
                logger.warning(
                    'role_diag access_denied route=%s user_id=%s profile_role=%s allowed_roles=%s reason=role_mismatch',
                    getattr(request, 'path', ''),
                    getattr(request.user, 'id', None),
                    getattr(request.user.profile, 'role', None),
                    allowed_roles,
                )
                messages.error(request, 'You do not have permission to perform this action.')
                raise PermissionDenied('Insufficient permissions')

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def supervisor_required(view_func):
    """Decorator for views that require supervisor role."""
    return role_required('supervisor')(view_func)


def manager_required(view_func):
    """Decorator for views that require manager role."""
    return role_required('manager')(view_func)


def client_required(view_func):
    """Decorator for views that require client role."""
    return role_required('client')(view_func)


def supervisor_or_manager_required(view_func):
    """Decorator for views that require either supervisor or manager role."""
    return role_required(['supervisor', 'manager'])(view_func)


def can_approve_shifts(view_func):
    """Decorator for views that check if user can approve shifts."""
    return supervisor_or_manager_required(view_func)