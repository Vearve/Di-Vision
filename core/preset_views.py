"""
Views for managing drill size, equipment, and consumable presets.

Contractors can create and submit presets to clients for approval.
Approved presets auto-populate BOQ line items with locked rates.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone

from accounts.decorators import supervisor_required
from .models import DrillSizePreset, EquipmentPreset, ConsumablePreset, AdditionalChargePreset, Client, Workspace, WorkspaceMembership
from .forms import DrillSizePresetForm, EquipmentPresetForm, ConsumablePresetForm, AdditionalChargePresetForm


# ──────────────────────────────────────────────────────────────────────────────
# Client Preset Approval Views (For Clients to Approve Presets)
# ──────────────────────────────────────────────────────────────────────────────

@login_required
def client_preset_approval_dashboard(request):
    """
    Dashboard for clients to review and approve presets submitted to them.
    Shows all pending presets from all contractors.
    """
    # Get user's client profile
    if not hasattr(request.user, 'client_profile'):
        messages.error(request, 'You must be a client user to access this page.')
        return redirect('core:home_dashboard')
    
    client = request.user.client_profile
    
    # Get all pending presets for this client (across all types)
    pending_drill_size = DrillSizePreset.objects.filter(
        submitted_to_client=client,
        client_status=DrillSizePreset.CLIENT_PENDING
    ).select_related('contractor_workspace', 'created_by').order_by('-created_at')
    
    pending_equipment = EquipmentPreset.objects.filter(
        submitted_to_client=client,
        client_status=EquipmentPreset.CLIENT_PENDING
    ).select_related('contractor_workspace', 'created_by').order_by('-created_at')
    
    pending_consumables = ConsumablePreset.objects.filter(
        submitted_to_client=client,
        client_status=ConsumablePreset.CLIENT_PENDING
    ).select_related('contractor_workspace', 'created_by').order_by('-created_at')
    
    pending_additional_charges = AdditionalChargePreset.objects.filter(
        submitted_to_client=client,
        client_status=AdditionalChargePreset.CLIENT_PENDING
    ).select_related('workspace', 'created_by').order_by('-created_at')
    
    # Get approved presets as well
    approved_drill_size = DrillSizePreset.objects.filter(
        submitted_to_client=client,
        client_status=DrillSizePreset.CLIENT_APPROVED
    ).select_related('contractor_workspace').order_by('-client_approved_at')
    
    approved_equipment = EquipmentPreset.objects.filter(
        submitted_to_client=client,
        client_status=EquipmentPreset.CLIENT_APPROVED
    ).select_related('contractor_workspace').order_by('-client_approved_at')
    
    approved_consumables = ConsumablePreset.objects.filter(
        submitted_to_client=client,
        client_status=ConsumablePreset.CLIENT_APPROVED
    ).select_related('contractor_workspace').order_by('-client_approved_at')
    
    approved_additional_charges = AdditionalChargePreset.objects.filter(
        submitted_to_client=client,
        client_status=AdditionalChargePreset.CLIENT_APPROVED
    ).select_related('workspace').order_by('-client_approved_at')
    
    # Calculate totals
    total_pending = pending_drill_size.count() + pending_equipment.count() + pending_consumables.count() + pending_additional_charges.count()
    
    context = {
        'client': client,
        'pending_drill_size': pending_drill_size,
        'pending_equipment': pending_equipment,
        'pending_consumables': pending_consumables,
        'pending_additional_charges': pending_additional_charges,
        'approved_drill_size': approved_drill_size,
        'approved_equipment': approved_equipment,
        'approved_consumables': approved_consumables,
        'approved_additional_charges': approved_additional_charges,
        'total_pending': total_pending,
    }
    return render(request, 'core/client_preset_approval_dashboard.html', context)


# ──────────────────────────────────────────────────────────────────────────────
# Unified Preset List (All Types)
# ──────────────────────────────────────────────────────────────────────────────

@login_required
@supervisor_required
def preset_list(request):
    """
    Unified list view showing all preset types (drill size, equipment, consumable)
    for the current user's contractor workspace.
    """
    # Get user's contractor workspace
    try:
        contractor_ws = WorkspaceMembership.objects.filter(
            user=request.user,
            workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
        ).first()
        
        if not contractor_ws:
            messages.warning(request, 'You are not assigned to a contractor workspace.')
            return redirect('core:home_dashboard')
        
        contractor_workspace = contractor_ws.workspace
    except Exception as e:
        messages.error(request, f'Error accessing workspace: {str(e)}')
        return redirect('core:home_dashboard')
    
    # Get all presets for this workspace
    drill_size_presets = DrillSizePreset.objects.filter(
        contractor_workspace=contractor_workspace
    ).select_related('submitted_to_client', 'client_approved_by').order_by('-created_at')
    
    equipment_presets = EquipmentPreset.objects.filter(
        contractor_workspace=contractor_workspace
    ).select_related('submitted_to_client', 'client_approved_by').order_by('-created_at')
    
    consumable_presets = ConsumablePreset.objects.filter(
        contractor_workspace=contractor_workspace
    ).select_related('submitted_to_client', 'client_approved_by').order_by('-created_at')
    
    additional_charge_presets = AdditionalChargePreset.objects.filter(
        workspace=contractor_workspace
    ).select_related('submitted_to_client', 'client_approved_by').order_by('-created_at')
    
    context = {
        'drill_size_presets': drill_size_presets,
        'equipment_presets': equipment_presets,
        'consumable_presets': consumable_presets,
        'additional_charge_presets': additional_charge_presets,
        'contractor_workspace': contractor_workspace,
    }
    return render(request, 'core/preset_list.html', context)


# ──────────────────────────────────────────────────────────────────────────────
# Drill Size Preset Management
# ──────────────────────────────────────────────────────────────────────────────

@login_required
@supervisor_required
def drill_size_preset_list(request):
    """
    List drill size presets for the current user's contractor workspace.
    """
    # Get user's contractor workspace
    try:
        contractor_ws = WorkspaceMembership.objects.filter(
            user=request.user,
            workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
        ).first()
        
        if not contractor_ws:
            messages.warning(request, 'You are not assigned to a contractor workspace.')
            return redirect('core:home_dashboard')
        
        contractor_workspace = contractor_ws.workspace
    except Exception as e:
        messages.error(request, f'Error accessing workspace: {str(e)}')
        return redirect('core:home_dashboard')
    
    # Get presets for this workspace
    presets = DrillSizePreset.objects.filter(
        contractor_workspace=contractor_workspace
    ).select_related('submitted_to_client', 'client_approved_by').order_by('-created_at')
    
    # Optional status filter
    status = request.GET.get('status', '')
    if status:
        presets = presets.filter(status=status)
    
    context = {
        'presets': presets,
        'contractor_workspace': contractor_workspace,
        'status_choices': [
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
        ],
        'selected_status': status,
    }
    return render(request, 'core/preset_drill_size_list.html', context)


@login_required
@supervisor_required
def drill_size_preset_create(request):
    """
    Create a new drill size preset.
    """
    # Get user's contractor workspace
    try:
        contractor_ws = WorkspaceMembership.objects.filter(
            user=request.user,
            workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
        ).first()
        
        if not contractor_ws:
            messages.warning(request, 'You are not assigned to a contractor workspace.')
            return redirect('drill_size_preset_list')
        
        contractor_workspace = contractor_ws.workspace
    except Exception:
        messages.error(request, 'Error accessing workspace.')
        return redirect('core:home_dashboard')
    
    if request.method == 'POST':
        form = DrillSizePresetForm(request.POST, user=request.user)
        if form.is_valid():
            preset = form.save(commit=False)
            preset.contractor_workspace = contractor_workspace
            preset.created_by = request.user
            preset.status = DrillSizePreset.STATUS_DRAFT
            preset.save()
            messages.success(request, f'Drill size preset "{preset.name}" created successfully.')
            return redirect('drill_size_preset_detail', pk=preset.pk)
    else:
        form = DrillSizePresetForm(user=request.user)
    
    context = {
        'form': form,
        'contractor_workspace': contractor_workspace,
        'title': 'Create Drill Size Preset',
    }
    return render(request, 'core/preset_form.html', context)


@login_required
def drill_size_preset_detail(request, pk):
    """
    View details of a drill size preset.
    """
    preset = get_object_or_404(
        DrillSizePreset.objects.select_related('contractor_workspace', 'submitted_to_client', 'client_approved_by')
        , pk=pk
    )
    
    # Check permissions
    is_contractor = (
        request.user.is_superuser or 
        (hasattr(request.user, 'workspace_memberships') and 
         preset.contractor_workspace in [m.workspace for m in request.user.workspace_memberships.all()])
    )
    is_client = (
        hasattr(request.user, 'client_profile') and 
        request.user.client_profile == preset.submitted_to_client
    )
    
    if not (is_contractor or is_client or request.user.is_superuser):
        messages.error(request, 'You do not have permission to view this preset.')
        return redirect('core:home_dashboard')
    
    can_edit = is_contractor and preset.status == DrillSizePreset.STATUS_DRAFT
    can_submit = is_contractor and preset.status == DrillSizePreset.STATUS_DRAFT and preset.submitted_to_client
    can_approve = is_client and preset.client_status == DrillSizePreset.CLIENT_PENDING
    
    context = {
        'preset': preset,
        'can_edit': can_edit,
        'can_submit': can_submit,
        'can_approve': can_approve,
        'is_contractor': is_contractor,
        'is_client': is_client,
    }
    return render(request, 'core/preset_drill_size_detail.html', context)


@login_required
@supervisor_required
def drill_size_preset_edit(request, pk):
    """
    Edit a draft drill size preset.
    """
    preset = get_object_or_404(DrillSizePreset, pk=pk)
    
    # Verify user owns the preset
    try:
        contractor_ws = WorkspaceMembership.objects.filter(
            user=request.user,
            workspace=preset.contractor_workspace
        ).first()
        if not contractor_ws and not request.user.is_superuser:
            messages.error(request, 'You do not have permission to edit this preset.')
            return redirect('drill_size_preset_detail', pk=preset.pk)
    except Exception:
        messages.error(request, 'Error verifying permissions.')
        return redirect('core:home_dashboard')
    
    # Only allow editing of draft presets
    if preset.status != DrillSizePreset.STATUS_DRAFT:
        messages.error(request, 'Only draft presets can be edited.')
        return redirect('drill_size_preset_detail', pk=preset.pk)
    
    if request.method == 'POST':
        form = DrillSizePresetForm(request.POST, instance=preset, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, f'Drill size preset "{preset.name}" updated successfully.')
            return redirect('drill_size_preset_detail', pk=preset.pk)
    else:
        form = DrillSizePresetForm(instance=preset, user=request.user)
    
    context = {
        'form': form,
        'preset': preset,
        'title': 'Edit Drill Size Preset',
    }
    return render(request, 'core/preset_form.html', context)


@login_required
@supervisor_required
def drill_size_preset_submit(request, pk):
    """
    Submit a draft preset to a client for approval.
    """
    preset = get_object_or_404(DrillSizePreset, pk=pk)
    
    # Verify user owns the preset
    try:
        contractor_ws = WorkspaceMembership.objects.filter(
            user=request.user,
            workspace=preset.contractor_workspace
        ).first()
        if not contractor_ws and not request.user.is_superuser:
            messages.error(request, 'You do not have permission to submit this preset.')
            return redirect('drill_size_preset_detail', pk=preset.pk)
    except Exception:
        return redirect('core:home_dashboard')
    
    if preset.status != DrillSizePreset.STATUS_DRAFT:
        messages.error(request, 'Only draft presets can be submitted.')
        return redirect('drill_size_preset_detail', pk=preset.pk)
    
    if not preset.submitted_to_client:
        messages.error(request, 'Please assign a client before submitting.')
        return redirect('drill_size_preset_detail', pk=preset.pk)
    
    if request.method == 'POST':
        preset.status = DrillSizePreset.STATUS_SUBMITTED
        preset.client_status = DrillSizePreset.CLIENT_PENDING
        preset.submitted_to_client_at = timezone.now()
        preset.save()
        
        messages.success(request, f'Preset "{preset.name}" submitted to {preset.submitted_to_client.name} for approval.')
        return redirect('drill_size_preset_detail', pk=preset.pk)
    
    return redirect('drill_size_preset_detail', pk=preset.pk)


@login_required
def drill_size_preset_approve(request, pk):
    """
    Client approves or rejects a submitted preset.
    """
    preset = get_object_or_404(DrillSizePreset, pk=pk)
    
    # Verify user is the client
    is_client = (
        hasattr(request.user, 'client_profile') and 
        request.user.client_profile == preset.submitted_to_client
    )
    
    if not (is_client or request.user.is_superuser):
        messages.error(request, 'You do not have permission to approve this preset.')
        return redirect('core:home_dashboard')
    
    if preset.client_status != DrillSizePreset.CLIENT_PENDING:
        messages.error(request, 'This preset is not pending approval.')
        return redirect('drill_size_preset_detail', pk=preset.pk)
    
    if request.method == 'POST':
        decision = request.POST.get('decision')
        comments = request.POST.get('comments', '')
        
        if decision == 'approved':
            preset.client_status = DrillSizePreset.CLIENT_APPROVED
            preset.client_approved_at = timezone.now()
            preset.client_approved_by = request.user
            preset.client_comments = comments
            preset.save()
            messages.success(request, f'Preset "{preset.name}" approved successfully.')
        elif decision == 'rejected':
            preset.client_status = DrillSizePreset.CLIENT_REJECTED
            preset.client_comments = comments
            preset.save()
            messages.warning(request, f'Preset "{preset.name}" rejected. Contractor can revise and resubmit.')
        else:
            messages.error(request, 'Invalid decision.')
        
        return redirect('drill_size_preset_detail', pk=preset.pk)
    
    return redirect('drill_size_preset_detail', pk=preset.pk)


# ──────────────────────────────────────────────────────────────────────────────
# Equipment Preset Management
# ──────────────────────────────────────────────────────────────────────────────

@login_required
@supervisor_required
def equipment_preset_list(request):
    """List equipment presets for the current user's contractor workspace."""
    try:
        contractor_ws = WorkspaceMembership.objects.filter(
            user=request.user,
            workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
        ).first()
        
        if not contractor_ws:
            messages.warning(request, 'You are not assigned to a contractor workspace.')
            return redirect('core:home_dashboard')
        
        contractor_workspace = contractor_ws.workspace
    except Exception as e:
        messages.error(request, f'Error accessing workspace: {str(e)}')
        return redirect('core:home_dashboard')
    
    presets = EquipmentPreset.objects.filter(
        contractor_workspace=contractor_workspace
    ).select_related('submitted_to_client', 'client_approved_by').order_by('-created_at')
    
    status = request.GET.get('status', '')
    if status:
        presets = presets.filter(status=status)
    
    context = {
        'presets': presets,
        'contractor_workspace': contractor_workspace,
        'status_choices': [
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
        ],
        'selected_status': status,
    }
    return render(request, 'core/preset_equipment_list.html', context)


@login_required
@supervisor_required
def equipment_preset_create(request):
    """Create a new equipment preset."""
    try:
        contractor_ws = WorkspaceMembership.objects.filter(
            user=request.user,
            workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
        ).first()
        
        if not contractor_ws:
            messages.warning(request, 'You are not assigned to a contractor workspace.')
            return redirect('equipment_preset_list')
        
        contractor_workspace = contractor_ws.workspace
    except Exception:
        messages.error(request, 'Error accessing workspace.')
        return redirect('core:home_dashboard')
    
    if request.method == 'POST':
        form = EquipmentPresetForm(request.POST, user=request.user)
        if form.is_valid():
            preset = form.save(commit=False)
            preset.contractor_workspace = contractor_workspace
            preset.created_by = request.user
            preset.status = EquipmentPreset.STATUS_DRAFT
            preset.save()
            messages.success(request, f'Equipment preset "{preset.name}" created successfully.')
            return redirect('equipment_preset_detail', pk=preset.pk)
    else:
        form = EquipmentPresetForm(user=request.user)
    
    context = {
        'form': form,
        'contractor_workspace': contractor_workspace,
        'title': 'Create Equipment Preset',
    }
    return render(request, 'core/preset_form.html', context)


@login_required
def equipment_preset_detail(request, pk):
    """View details of an equipment preset."""
    preset = get_object_or_404(
        EquipmentPreset.objects.select_related('contractor_workspace', 'submitted_to_client', 'client_approved_by'),
        pk=pk
    )
    
    is_contractor = (
        request.user.is_superuser or 
        (hasattr(request.user, 'workspace_memberships') and 
         preset.contractor_workspace in [m.workspace for m in request.user.workspace_memberships.all()])
    )
    is_client = (
        hasattr(request.user, 'client_profile') and 
        request.user.client_profile == preset.submitted_to_client
    )
    
    if not (is_contractor or is_client or request.user.is_superuser):
        messages.error(request, 'You do not have permission to view this preset.')
        return redirect('core:home_dashboard')
    
    can_edit = is_contractor and preset.status == EquipmentPreset.STATUS_DRAFT
    can_submit = is_contractor and preset.status == EquipmentPreset.STATUS_DRAFT and preset.submitted_to_client
    can_approve = is_client and preset.client_status == EquipmentPreset.CLIENT_PENDING
    
    context = {
        'preset': preset,
        'can_edit': can_edit,
        'can_submit': can_submit,
        'can_approve': can_approve,
        'is_contractor': is_contractor,
        'is_client': is_client,
    }
    return render(request, 'core/preset_equipment_detail.html', context)


# ──────────────────────────────────────────────────────────────────────────────
# Consumable Preset Management
# ──────────────────────────────────────────────────────────────────────────────

@login_required
@supervisor_required
def consumable_preset_list(request):
    """List consumable presets for the current user's contractor workspace."""
    try:
        contractor_ws = WorkspaceMembership.objects.filter(
            user=request.user,
            workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
        ).first()
        
        if not contractor_ws:
            messages.warning(request, 'You are not assigned to a contractor workspace.')
            return redirect('core:home_dashboard')
        
        contractor_workspace = contractor_ws.workspace
    except Exception as e:
        messages.error(request, f'Error accessing workspace: {str(e)}')
        return redirect('core:home_dashboard')
    
    presets = ConsumablePreset.objects.filter(
        contractor_workspace=contractor_workspace
    ).select_related('submitted_to_client', 'client_approved_by').order_by('-created_at')
    
    status = request.GET.get('status', '')
    if status:
        presets = presets.filter(status=status)
    
    context = {
        'presets': presets,
        'contractor_workspace': contractor_workspace,
        'status_choices': [
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
        ],
        'selected_status': status,
    }
    return render(request, 'core/preset_consumable_list.html', context)


@login_required
@supervisor_required
def consumable_preset_create(request):
    """Create a new consumable preset."""
    try:
        contractor_ws = WorkspaceMembership.objects.filter(
            user=request.user,
            workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
        ).first()
        
        if not contractor_ws:
            messages.warning(request, 'You are not assigned to a contractor workspace.')
            return redirect('consumable_preset_list')
        
        contractor_workspace = contractor_ws.workspace
    except Exception:
        messages.error(request, 'Error accessing workspace.')
        return redirect('core:home_dashboard')
    
    if request.method == 'POST':
        form = ConsumablePresetForm(request.POST, user=request.user)
        if form.is_valid():
            preset = form.save(commit=False)
            preset.contractor_workspace = contractor_workspace
            preset.created_by = request.user
            preset.status = ConsumablePreset.STATUS_DRAFT
            preset.save()
            messages.success(request, f'Consumable preset "{preset.name}" created successfully.')
            return redirect('consumable_preset_detail', pk=preset.pk)
    else:
        form = ConsumablePresetForm(user=request.user)
    
    context = {
        'form': form,
        'contractor_workspace': contractor_workspace,
        'title': 'Create Consumable Preset',
    }
    return render(request, 'core/preset_form.html', context)


@login_required
def consumable_preset_detail(request, pk):
    """View details of a consumable preset."""
    preset = get_object_or_404(
        ConsumablePreset.objects.select_related('contractor_workspace', 'submitted_to_client', 'client_approved_by'),
        pk=pk
    )
    
    is_contractor = (
        request.user.is_superuser or 
        (hasattr(request.user, 'workspace_memberships') and 
         preset.contractor_workspace in [m.workspace for m in request.user.workspace_memberships.all()])
    )
    is_client = (
        hasattr(request.user, 'client_profile') and 
        request.user.client_profile == preset.submitted_to_client
    )
    
    if not (is_contractor or is_client or request.user.is_superuser):
        messages.error(request, 'You do not have permission to view this preset.')
        return redirect('core:home_dashboard')
    
    can_edit = is_contractor and preset.status == ConsumablePreset.STATUS_DRAFT
    can_submit = is_contractor and preset.status == ConsumablePreset.STATUS_DRAFT and preset.submitted_to_client
    can_approve = is_client and preset.client_status == ConsumablePreset.CLIENT_PENDING
    
    context = {
        'preset': preset,
        'can_edit': can_edit,
        'can_submit': can_submit,
        'can_approve': can_approve,
        'is_contractor': is_contractor,
        'is_client': is_client,
    }
    return render(request, 'core/preset_consumable_detail.html', context)


# ──────────────────────────────────────────────────────────────────────────────
# Additional Charge Preset Management
# ──────────────────────────────────────────────────────────────────────────────

@login_required
def additional_charge_preset_list(request):
    """
    List additional charge presets for the current user's workspace.
    Shows both contractor charges and client deductions.
    """
    try:
        # Get user's workspaces (could be contractor or client)
        user_workspaces = WorkspaceMembership.objects.filter(user=request.user).values_list('workspace', flat=True)
        
        if not user_workspaces:
            messages.warning(request, 'You are not assigned to any workspace.')
            return redirect('core:home_dashboard')
        
        # Get presets for user's workspaces
        presets = AdditionalChargePreset.objects.filter(
            workspace__in=user_workspaces
        ).select_related('workspace', 'submitted_to_client', 'client_approved_by').order_by('-created_at')
        
        # Filter by status if requested
        status = request.GET.get('status')
        if status:
            presets = presets.filter(status=status)
        
        workspace = Workspace.objects.filter(pk__in=user_workspaces).first()
        
    except Exception as e:
        messages.error(request, f'Error accessing workspace: {str(e)}')
        return redirect('core:home_dashboard')
    
    context = {
        'presets': presets,
        'workspace': workspace,
        'status_choices': [
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        'selected_status': status,
    }
    return render(request, 'core/preset_additional_charge_list.html', context)


@login_required
def additional_charge_preset_create(request):
    """
    Create a new additional charge preset.
    Contractors create charges, clients create deductions.
    """
    try:
        # Get user's workspaces
        user_workspaces = WorkspaceMembership.objects.filter(user=request.user).values_list('workspace', flat=True)
        
        if not user_workspaces:
            messages.warning(request, 'You are not assigned to any workspace.')
            return redirect('additional_charge_preset_list')
        
        workspace = Workspace.objects.filter(pk__in=user_workspaces).first()
        
    except Exception as e:
        messages.error(request, f'Error accessing workspace: {str(e)}')
        return redirect('core:home_dashboard')
    
    if request.method == 'POST':
        form = AdditionalChargePresetForm(request.POST, user=request.user)
        if form.is_valid():
            preset = form.save(commit=False)
            preset.created_by = request.user
            preset.status = AdditionalChargePreset.STATUS_DRAFT
            
            # Set charge_type based on workspace type
            if workspace.workspace_type == Workspace.WORKSPACE_CONTRACTOR:
                preset.charge_type = AdditionalChargePreset.CHARGE_TYPE_CHARGE
            else:  # Client workspace
                preset.charge_type = AdditionalChargePreset.CHARGE_TYPE_DEDUCTION
            
            preset.save()
            messages.success(request, f'Additional charge preset "{preset.name}" created successfully.')
            return redirect('additional_charge_preset_detail', pk=preset.pk)
    else:
        form = AdditionalChargePresetForm(user=request.user)
    
    context = {
        'form': form,
        'workspace': workspace,
        'title': 'Create Additional Charge Preset',
    }
    return render(request, 'core/preset_form.html', context)


@login_required
def additional_charge_preset_detail(request, pk):
    """
    View details of an additional charge preset.
    """
    preset = get_object_or_404(
        AdditionalChargePreset.objects.select_related('workspace', 'submitted_to_client', 'client_approved_by'),
        pk=pk
    )
    
    # Check permissions - user must be in the same workspace
    user_workspaces = [m.workspace for m in request.user.workspace_memberships.all()]
    is_owner = preset.workspace in user_workspaces
    is_client = (
        hasattr(request.user, 'client_profile') and 
        request.user.client_profile == preset.submitted_to_client
    )
    
    if not (is_owner or is_client or request.user.is_superuser):
        messages.error(request, 'You do not have permission to view this preset.')
        return redirect('core:home_dashboard')
    
    can_edit = is_owner and preset.status == AdditionalChargePreset.STATUS_DRAFT
    can_submit = is_owner and preset.status == AdditionalChargePreset.STATUS_DRAFT and preset.submitted_to_client
    can_approve = is_client and preset.client_status == AdditionalChargePreset.CLIENT_PENDING
    
    context = {
        'preset': preset,
        'can_edit': can_edit,
        'can_submit': can_submit,
        'can_approve': can_approve,
        'is_owner': is_owner,
        'is_client': is_client,
    }
    return render(request, 'core/preset_additional_charge_detail.html', context)


@login_required
def additional_charge_preset_edit(request, pk):
    """
    Edit an additional charge preset.
    """
    preset = get_object_or_404(AdditionalChargePreset, pk=pk)
    
    # Check permissions
    user_workspaces = [m.workspace for m in request.user.workspace_memberships.all()]
    if preset.workspace not in user_workspaces and not request.user.is_superuser:
        messages.error(request, 'You do not have permission to edit this preset.')
        return redirect('additional_charge_preset_detail', pk=pk)
    
    if preset.status != AdditionalChargePreset.STATUS_DRAFT:
        messages.error(request, 'Only draft presets can be edited.')
        return redirect('additional_charge_preset_detail', pk=pk)
    
    if request.method == 'POST':
        form = AdditionalChargePresetForm(request.POST, instance=preset, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, f'Additional charge preset "{preset.name}" updated successfully.')
            return redirect('additional_charge_preset_detail', pk=pk)
    else:
        form = AdditionalChargePresetForm(instance=preset, user=request.user)
    
    context = {
        'form': form,
        'preset': preset,
        'title': 'Edit Additional Charge Preset',
    }
    return render(request, 'core/preset_form.html', context)


@login_required
def additional_charge_preset_submit(request, pk):
    """
    Submit an additional charge preset to client for approval.
    """
    preset = get_object_or_404(AdditionalChargePreset, pk=pk)
    
    # Check permissions
    user_workspaces = [m.workspace for m in request.user.workspace_memberships.all()]
    if preset.workspace not in user_workspaces and not request.user.is_superuser:
        messages.error(request, 'You do not have permission to submit this preset.')
        return redirect('additional_charge_preset_detail', pk=pk)
    
    if preset.status != AdditionalChargePreset.STATUS_DRAFT:
        messages.error(request, 'Only draft presets can be submitted.')
        return redirect('additional_charge_preset_detail', pk=pk)
    
    if not preset.submitted_to_client:
        messages.error(request, 'Please select a client to submit to before submitting.')
        return redirect('additional_charge_preset_detail', pk=pk)
    
    preset.status = AdditionalChargePreset.STATUS_SUBMITTED
    preset.submitted_at = timezone.now()
    preset.save()
    
    messages.success(request, f'Additional charge preset "{preset.name}" submitted to {preset.submitted_to_client.name} for approval.')
    return redirect('additional_charge_preset_detail', pk=pk)


@login_required
def additional_charge_preset_approve(request, pk):
    """
    Client approves an additional charge preset.
    """
    preset = get_object_or_404(AdditionalChargePreset, pk=pk)
    
    # Check permissions
    if not hasattr(request.user, 'client_profile') or request.user.client_profile != preset.submitted_to_client:
        messages.error(request, 'You do not have permission to approve this preset.')
        return redirect('additional_charge_preset_detail', pk=pk)
    
    if preset.client_status != AdditionalChargePreset.CLIENT_PENDING:
        messages.error(request, 'This preset is not pending approval.')
        return redirect('additional_charge_preset_detail', pk=pk)
    
    preset.client_status = AdditionalChargePreset.CLIENT_APPROVED
    preset.client_approved_at = timezone.now()
    preset.client_approved_by = request.user
    preset.save()
    
    messages.success(request, f'Additional charge preset "{preset.name}" approved successfully.')
    return redirect('additional_charge_preset_detail', pk=pk)
