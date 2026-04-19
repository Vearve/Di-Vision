from datetime import datetime, timedelta
import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Avg, Q, Count, F
from django.urls import reverse
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, FileResponse, JsonResponse
from django.utils import timezone
from django.utils.text import slugify
from decimal import Decimal
import json
from .models import BOQReport, BOQAdditionalCharge, DrillShift, DrillingProgress, ActivityLog, MaterialUsed, ApprovalHistory, Client, Alert, BOQLineItem, WorkspaceMembership, Workspace
from .forms import (BOQReportForm, BOQAdditionalChargeForm, DrillShiftForm, DrillingProgressFormSet, ActivityLogFormSet, 
                    MaterialUsedFormSet, SurveyFormSet, CasingFormSet)
from .utils import export_shifts_to_csv, export_monthly_boq, calculate_daily_progress
from accounts.decorators import role_required
from accounts.decorators import (
    client_required, supervisor_required, manager_required, supervisor_or_manager_required,
    can_approve_shifts
)


logger = logging.getLogger(__name__)


def _is_client_user(user):
    """Workspace-aware client detection used across view guards and redirects."""
    if not user.is_authenticated or user.is_superuser:
        return False
    if hasattr(user, 'client_profile'):
        logger.info('role_diag client_user=True source=client_profile user_id=%s', getattr(user, 'id', None))
        return True
    has_client_workspace = WorkspaceMembership.objects.filter(
        user=user,
        workspace__workspace_type=Workspace.WORKSPACE_CLIENT,
        workspace__is_active=True,
    ).exists()
    if has_client_workspace:
        logger.info('role_diag client_user=True source=workspace_membership user_id=%s', getattr(user, 'id', None))
        return True

    # Legacy fallback: some users are client-only via profile.role without client_profile/workspace link.
    profile = getattr(user, 'profile', None)
    is_client = bool(profile and profile.is_client)
    if is_client:
        logger.info('role_diag client_user=True source=legacy_profile user_id=%s', getattr(user, 'id', None))
    return is_client


def _get_client_queryset_for_user(user):
    """Return all active client companies the user can access."""
    if not getattr(user, 'is_authenticated', False):
        return Client.objects.none()

    direct_client = getattr(user, 'client_profile', None)
    if direct_client:
        return Client.objects.filter(pk=direct_client.pk, is_active=True)

    workspace_ids = WorkspaceMembership.objects.filter(
        user=user,
        workspace__workspace_type=Workspace.WORKSPACE_CLIENT,
        workspace__is_active=True,
    ).values_list('workspace_id', flat=True)

    if workspace_ids:
        return Client.objects.filter(workspace_id__in=workspace_ids, is_active=True).distinct()

    profile = getattr(user, 'profile', None)
    if profile and getattr(profile, 'is_client', False):
        return Client.objects.filter(user=user, is_active=True)

    return Client.objects.none()


def _get_primary_client_for_user(user):
    """Return a primary client object for client-scoped pages."""
    return _get_client_queryset_for_user(user).order_by('id').first()


@login_required
def home_dashboard(request):
    """
    Manager-focused home dashboard showing high-level KPIs and alerts.
    Supports period filters: This Week / This Month / Last Month / Year / Custom
    and an optional Client filter.
    """
    has_client_profile = hasattr(request.user, 'client_profile')
    has_client_workspace_membership = WorkspaceMembership.objects.filter(
        user=request.user,
        workspace__workspace_type=Workspace.WORKSPACE_CLIENT,
        workspace__is_active=True,
    ).exists()
    is_client_user = has_client_profile or has_client_workspace_membership

    if not request.user.is_superuser and is_client_user:
        return redirect('core:client_dashboard')

    today = timezone.now().date()
    yesterday = today - timedelta(days=1)
    last_24h = timezone.now() - timedelta(hours=24)

    # ── Period filter ──────────────────────────────────────────────────────────
    period = request.GET.get('period', 'this_month')
    year_str = request.GET.get('year', str(today.year))
    date_from_str = request.GET.get('date_from', '')
    date_to_str = request.GET.get('date_to', '')
    filter_client_id = request.GET.get('client_id', '')

    if period == 'this_week':
        filter_start = today - timedelta(days=today.weekday())
        filter_end = today
    elif period == 'last_month':
        month_start_this = today.replace(day=1)
        filter_end = month_start_this - timedelta(days=1)
        filter_start = filter_end.replace(day=1)
    elif period == 'year':
        selected_year = int(year_str) if year_str.isdigit() else today.year
        filter_start = today.replace(year=selected_year, month=1, day=1)
        filter_end = today.replace(year=selected_year, month=12, day=31)
    elif period == 'custom':
        try:
            filter_start = datetime.strptime(date_from_str, '%Y-%m-%d').date() if date_from_str else today.replace(day=1)
            filter_end = datetime.strptime(date_to_str, '%Y-%m-%d').date() if date_to_str else today
        except ValueError:
            filter_start = today.replace(day=1)
            filter_end = today
    else:  # this_month (default)
        period = 'this_month'
        filter_start = today.replace(day=1)
        filter_end = today

    # ── Client filter ──────────────────────────────────────────────────────────
    filter_client_obj = None
    if filter_client_id and filter_client_id.isdigit():
        try:
            filter_client_obj = Client.objects.get(pk=int(filter_client_id))
        except Client.DoesNotExist:
            filter_client_id = ''

    # Extra kwargs applied to progress queries: shift__client
    prog_client_q = {'shift__client': filter_client_obj} if filter_client_obj else {}
    # Extra kwargs applied to shift queries: client
    shift_client_q = {'client': filter_client_obj} if filter_client_obj else {}

    all_clients = Client.objects.filter(is_active=True).order_by('name')

    # ── Operational KPIs (fixed: today / last 24 h) ────────────────────────────
    meters_today = DrillingProgress.objects.filter(
        shift__date=today,
        shift__status=DrillShift.STATUS_APPROVED,
        **prog_client_q,
    ).aggregate(total=Sum('meters_drilled'))['total'] or 0

    avg_rop_24h = DrillingProgress.objects.filter(
        shift__date__gte=yesterday,
        shift__status=DrillShift.STATUS_APPROVED,
        penetration_rate__isnull=False,
        **prog_client_q,
    ).aggregate(avg=Avg('penetration_rate'))['avg'] or 0

    avg_recovery_24h = DrillingProgress.objects.filter(
        shift__date__gte=yesterday,
        shift__status=DrillShift.STATUS_APPROVED,
        recovery_percentage__isnull=False,
        **prog_client_q,
    ).aggregate(avg=Avg('recovery_percentage'))['avg'] or 0

    downtime_data = ActivityLog.objects.filter(
        shift__date__gte=yesterday,
        shift__status=DrillShift.STATUS_APPROVED,
    ).values('activity_type').annotate(
        total_hours=Sum('duration_minutes') / 60
    ).order_by('-total_hours')

    rig_perf_with_recovery = DrillingProgress.objects.filter(
        shift__date__gte=yesterday,
        shift__status=DrillShift.STATUS_APPROVED,
        shift__rig__isnull=False,
        **prog_client_q,
    ).exclude(shift__rig='').values('shift__rig').annotate(
        total_meters=Sum('meters_drilled'),
        avg_recovery=Avg('recovery_percentage'),
    ).order_by('-total_meters')[:10]

    downtime_labels = [item['activity_type'] for item in downtime_data]
    downtime_values = [float(item['total_hours']) for item in downtime_data]
    rig_labels = [item['shift__rig'] for item in rig_perf_with_recovery]
    rig_values = [float(item['total_meters']) for item in rig_perf_with_recovery]
    rig_recovery = [float(item['avg_recovery']) if item['avg_recovery'] else 0 for item in rig_perf_with_recovery]

    # ── Period-based KPIs ─────────────────────────────────────────────────────
    meters_period = DrillingProgress.objects.filter(
        shift__date__range=[filter_start, filter_end],
        shift__status=DrillShift.STATUS_APPROVED,
        **prog_client_q,
    ).aggregate(total=Sum('meters_drilled'))['total'] or 0

    client_performance = DrillingProgress.objects.filter(
        shift__date__range=[filter_start, filter_end],
        shift__status=DrillShift.STATUS_APPROVED,
        shift__client__isnull=False,
        **prog_client_q,
    ).values('shift__client__name').annotate(
        total_meters=Sum('meters_drilled'),
        avg_recovery=Avg('recovery_percentage'),
        avg_rop=Avg('penetration_rate'),
        shift_count=Count('shift', distinct=True),
    ).order_by('-total_meters')

    location_performance = DrillingProgress.objects.filter(
        shift__date__range=[filter_start, filter_end],
        shift__status=DrillShift.STATUS_APPROVED,
        shift__location__isnull=False,
        **prog_client_q,
    ).exclude(shift__location='').values('shift__location').annotate(
        total_meters=Sum('meters_drilled'),
        avg_recovery=Avg('recovery_percentage'),
        shift_count=Count('shift', distinct=True),
    ).order_by('-total_meters')[:10]

    shifts_period_qs = DrillShift.objects.filter(
        date__range=[filter_start, filter_end],
        **shift_client_q,
    )
    draft_count = shifts_period_qs.filter(status=DrillShift.STATUS_DRAFT).count()
    submitted_count = shifts_period_qs.filter(status=DrillShift.STATUS_SUBMITTED).count()
    approved_count = shifts_period_qs.filter(status=DrillShift.STATUS_APPROVED).count()
    rejected_count = shifts_period_qs.filter(status=DrillShift.STATUS_REJECTED).count()

    active_clients_count = DrillShift.objects.filter(
        date__range=[filter_start, filter_end],
        status=DrillShift.STATUS_APPROVED,
        client__isnull=False,
        **shift_client_q,
    ).values('client').distinct().count()

    client_pending_count = shifts_period_qs.filter(status=DrillShift.STATUS_APPROVED, client_status=DrillShift.CLIENT_PENDING).count()
    client_approved_count = shifts_period_qs.filter(status=DrillShift.STATUS_APPROVED, client_status=DrillShift.CLIENT_APPROVED).count()
    client_rejected_count = shifts_period_qs.filter(status=DrillShift.STATUS_APPROVED, client_status=DrillShift.CLIENT_REJECTED).count()

    # Top 3 issues from latest shifts in period
    recent_shifts_with_issues = DrillShift.objects.filter(
        date__range=[filter_start, filter_end],
        status=DrillShift.STATUS_APPROVED,
        notes__isnull=False,
        **shift_client_q,
    ).exclude(notes='').order_by('-date', '-id')[:5]

    top_issues = []
    for shift in recent_shifts_with_issues:
        if shift.notes and len(shift.notes.strip()) > 10:
            top_issues.append({
                'date': shift.date,
                'rig': shift.rig,
                'issue': shift.notes[:200],
                'shift_id': shift.id,
            })
            if len(top_issues) >= 3:
                break

    # Active alerts
    active_alerts_qs = Alert.objects.filter(
        is_active=True,
        is_acknowledged=False,
    ).select_related('shift').order_by('-severity', '-created_at')

    alert_counts = {
        'critical': active_alerts_qs.filter(severity=Alert.SEVERITY_CRITICAL).count(),
        'high': active_alerts_qs.filter(severity=Alert.SEVERITY_HIGH).count(),
        'medium': active_alerts_qs.filter(severity=Alert.SEVERITY_MEDIUM).count(),
        'low': active_alerts_qs.filter(severity=Alert.SEVERITY_LOW).count(),
    }
    active_alerts = active_alerts_qs[:10]

    off_target_alerts = Alert.objects.filter(
        is_active=True,
        severity__in=[Alert.SEVERITY_HIGH, Alert.SEVERITY_CRITICAL],
    ).select_related('shift').order_by('-created_at')[:8]

    from django.db.models import Min
    approvals = ApprovalHistory.objects.filter(
        shift__in=shifts_period_qs,
        decision=ApprovalHistory.DECISION_APPROVED,
    ).values('shift_id').annotate(first_approved=Min('timestamp'))
    approved_map = {a['shift_id']: a['first_approved'] for a in approvals}
    days_to_approve_values = []
    for s in shifts_period_qs.filter(status=DrillShift.STATUS_APPROVED):
        ts = approved_map.get(s.id)
        if ts:
            days_to_approve_values.append((ts.date() - s.date).days)
    avg_days_to_approve = round(sum(days_to_approve_values) / len(days_to_approve_values), 1) if days_to_approve_values else 0

    # Build a human-readable period label for display
    period_labels = {
        'this_week': 'This Week',
        'this_month': 'This Month',
        'last_month': 'Last Month',
        'year': year_str,
        'custom': f"{filter_start} – {filter_end}",
    }
    period_label = period_labels.get(period, 'This Month')

    context = {
        'meters_today': float(meters_today),
        'meters_month': float(meters_period),  # kept as meters_month for template compatibility
        'avg_rop_24h': round(float(avg_rop_24h), 2),
        'avg_recovery_24h': round(float(avg_recovery_24h), 2),
        'downtime_labels': json.dumps(downtime_labels),
        'downtime_values': json.dumps(downtime_values),
        'rig_labels': json.dumps(rig_labels),
        'rig_values': json.dumps(rig_values),
        'rig_recovery': json.dumps(rig_recovery),
        'top_issues': top_issues,
        'active_alerts': active_alerts,
        'alert_counts': alert_counts,
        'total_active_alerts': active_alerts.count(),
        # Workflow metrics
        'draft_count': draft_count,
        'submitted_count': submitted_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'client_pending_count': client_pending_count,
        'client_approved_count': client_approved_count,
        'client_rejected_count': client_rejected_count,
        'avg_days_to_approve': avg_days_to_approve,
        'off_target_alerts': off_target_alerts,
        'client_performance': client_performance,
        'location_performance': location_performance,
        'active_clients_count': active_clients_count,
        # Filter state
        'period': period,
        'period_label': period_label,
        'filter_start': filter_start,
        'filter_end': filter_end,
        'year_str': year_str,
        'date_from_str': date_from_str,
        'date_to_str': date_to_str,
        'filter_client_id': filter_client_id,
        'filter_client_obj': filter_client_obj,
        'all_clients': all_clients,
        'period_options': [
            ('this_week', 'This Week'),
            ('this_month', 'This Month'),
            ('last_month', 'Last Month'),
            ('year', 'Year'),
            ('custom', 'Custom'),
        ],
    }
    return render(request, 'core/home_dashboard.html', context)


@login_required
def analytics_dashboard(request):
    """
    Analytics dashboard showing 30-day trends and performance metrics.
    
    Displays trends using Chart.js:
    - Daily meters drilled (last 30 days)
    - ROP trend (last 30 days)
    - Core recovery trend (last 30 days)
    - Downtime trend (stacked by category)
    - Material usage trend
    - Bit/lifter performance (meters per bit type)
    
    Returns:
        Rendered analytics template with trend data for charts
    """
    if _is_client_user(request.user):
        messages.info(request, 'Clients do not have access to the analytics dashboard.')
        return redirect('core:client_dashboard')

    # Calculate date range (last 30 days)
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=30)
    
    # Allow filtering by date range
    custom_start = request.GET.get('start_date')
    custom_end = request.GET.get('end_date')
    
    if custom_start and custom_end:
        try:
            start_date = datetime.strptime(custom_start, '%Y-%m-%d').date()
            end_date = datetime.strptime(custom_end, '%Y-%m-%d').date()
        except ValueError:
            messages.warning(request, 'Invalid date format. Using default 30-day range.')
    
    # Trend 1: Daily meters drilled
    daily_meters = DrillingProgress.objects.filter(
        shift__date__range=[start_date, end_date],
        shift__status=DrillShift.STATUS_APPROVED
    ).values('shift__date').annotate(
        total_meters=Sum('meters_drilled')
    ).order_by('shift__date')
    
    # Trend 2: ROP trend (daily average)
    daily_rop = DrillingProgress.objects.filter(
        shift__date__range=[start_date, end_date],
        shift__status=DrillShift.STATUS_APPROVED,
        penetration_rate__isnull=False
    ).values('shift__date').annotate(
        avg_rop=Avg('penetration_rate')
    ).order_by('shift__date')
    
    # Trend 3: Core recovery trend (daily average)
    daily_recovery = DrillingProgress.objects.filter(
        shift__date__range=[start_date, end_date],
        shift__status=DrillShift.STATUS_APPROVED,
        recovery_percentage__isnull=False
    ).values('shift__date').annotate(
        avg_recovery=Avg('recovery_percentage')
    ).order_by('shift__date')
    
    # Trend 4: Downtime by category (grouped)
    downtime_by_category = ActivityLog.objects.filter(
        shift__date__range=[start_date, end_date],
        shift__status=DrillShift.STATUS_APPROVED,
        duration_minutes__gt=0
    ).exclude(activity_type='drilling').values('shift__date', 'activity_type').annotate(
        total_hours=Sum('duration_minutes') / 60
    ).order_by('shift__date', 'activity_type')
    
    # Trend 5: Material usage (sum by material type)
    material_usage = MaterialUsed.objects.filter(
        shift__date__range=[start_date, end_date],
        shift__status=DrillShift.STATUS_APPROVED
    ).values('material_name').annotate(
        total_quantity=Sum('quantity')
    ).order_by('-total_quantity')[:10]  # Top 10 materials
    
    # Trend 6: Bit performance (meters per bit size)
    bit_performance = DrillingProgress.objects.filter(
        shift__date__range=[start_date, end_date],
        shift__status=DrillShift.STATUS_APPROVED,
        size__isnull=False
    ).values('size').annotate(
        total_meters=Sum('meters_drilled'),
        avg_recovery=Avg('recovery_percentage'),
        count=Count('id')
    ).order_by('-total_meters')
    
    # Format data for Chart.js
    
    # Daily meters chart
    meters_dates = [item['shift__date'].strftime('%Y-%m-%d') for item in daily_meters]
    meters_values = [float(item['total_meters']) for item in daily_meters]
    
    # ROP trend chart
    rop_dates = [item['shift__date'].strftime('%Y-%m-%d') for item in daily_rop]
    rop_values = [float(item['avg_rop']) for item in daily_rop]
    
    # Recovery trend chart
    recovery_dates = [item['shift__date'].strftime('%Y-%m-%d') for item in daily_recovery]
    recovery_values = [float(item['avg_recovery']) for item in daily_recovery]
    
    # Downtime stacked chart - organize by activity type
    downtime_datasets = {}
    downtime_dates_set = set()
    for item in downtime_by_category:
        date_str = item['shift__date'].strftime('%Y-%m-%d')
        downtime_dates_set.add(date_str)
        activity = item['activity_type']
        if activity not in downtime_datasets:
            downtime_datasets[activity] = {}
        downtime_datasets[activity][date_str] = float(item['total_hours'])
    
    downtime_dates = sorted(list(downtime_dates_set))
    downtime_chart_data = []
    downtime_has_data = False
    for activity, data in downtime_datasets.items():
        values = [data.get(date, 0) for date in downtime_dates]
        if any(v > 0 for v in values):
            downtime_has_data = True
        downtime_chart_data.append({
            'label': activity,
            'data': values
        })

    # Aggregate totals per activity for pie/donut chart
    downtime_totals = {}
    for item in downtime_by_category:
        act = item['activity_type']
        hours = float(item['total_hours']) if item['total_hours'] else 0
        downtime_totals[act] = downtime_totals.get(act, 0) + hours

    downtime_activity_labels = list(downtime_totals.keys())
    downtime_activity_values = [round(downtime_totals[l], 2) for l in downtime_activity_labels]
    
    # Material usage chart
    material_labels = [item['material_name'] for item in material_usage]
    material_values = [float(item['total_quantity']) for item in material_usage]
    
    # Bit performance chart
    bit_labels = [item['size'] for item in bit_performance]
    bit_meters = [float(item['total_meters']) for item in bit_performance]
    bit_recovery = [float(item['avg_recovery']) if item['avg_recovery'] else 0 for item in bit_performance]

    # Monthly rig performance (current month)
    rig_month = DrillingProgress.objects.filter(
        shift__date__gte=start_date.replace(day=1),
        shift__date__lte=end_date,
        shift__status=DrillShift.STATUS_APPROVED,
        shift__rig__isnull=False
    ).exclude(shift__rig='').values('shift__rig').annotate(
        total_meters=Sum('meters_drilled'),
        avg_recovery=Avg('recovery_percentage'),
        avg_rop=Avg('penetration_rate')
    ).order_by('-total_meters')
    rig_month_labels = [r['shift__rig'] for r in rig_month]
    rig_month_meters = [float(r['total_meters']) for r in rig_month]
    rig_month_recovery = [float(r['avg_recovery']) if r['avg_recovery'] else 0 for r in rig_month]
    rig_month_rop = [float(r['avg_rop']) if r['avg_rop'] else 0 for r in rig_month]
    
    context = {
        'start_date': start_date,
        'end_date': end_date,
        # Chart data as JSON
        'meters_dates': json.dumps(meters_dates),
        'meters_values': json.dumps(meters_values),
        'rop_dates': json.dumps(rop_dates),
        'rop_values': json.dumps(rop_values),
        'recovery_dates': json.dumps(recovery_dates),
        'recovery_values': json.dumps(recovery_values),
        'downtime_dates': json.dumps(downtime_dates),
        'downtime_datasets': json.dumps(downtime_chart_data),
        'downtime_has_data': downtime_has_data,
        'downtime_activity_labels': json.dumps(downtime_activity_labels),
        'downtime_activity_values': json.dumps(downtime_activity_values),
        'material_labels': json.dumps(material_labels),
        'material_values': json.dumps(material_values),
        'bit_labels': json.dumps(bit_labels),
        'bit_meters': json.dumps(bit_meters),
        'bit_recovery': json.dumps(bit_recovery),
        'rig_month_labels': json.dumps(rig_month_labels),
        'rig_month_meters': json.dumps(rig_month_meters),
        'rig_month_recovery': json.dumps(rig_month_recovery),
        'rig_month_rop': json.dumps(rig_month_rop),
    }
    return render(request, 'core/analytics_dashboard.html', context)


@login_required
def shift_list(request):
    """
    Display a list of drill shifts grouped by machine and date (24-hour view).
    
    Shows one row per rig per date, combining day and night shifts.
    
    Applies filters based on user role:
    - Clients: Only approved shifts
    - Supervisors: Own shifts + submitted/approved shifts
    - Managers: Submitted and approved shifts
    - Superusers: All shifts
    
    Args:
        request: HTTP request object
        
    Returns:
        Rendered shift list template with grouped shifts
        
    Query Parameters:
        status: Filter shifts by status (draft/submitted/approved/rejected)
        hole_number: Filter by specific hole number
    """

    # Base queryset with optimized related data loading
    shifts = DrillShift.objects.select_related(
        'created_by',
        'created_by__profile',
        'client'
    ).prefetch_related(
        'progress',
        'activities'
    ).all()
    
    # Apply role-based filters
    if not request.user.is_superuser:
        profile = request.user.profile
        if _is_client_user(request.user):
            # Clients can only see approved shifts
            shifts = shifts.filter(status=DrillShift.STATUS_APPROVED)
        elif profile.is_supervisor:
            # Supervisors can see all shifts they created plus submitted/approved ones
            shifts = shifts.filter(
                Q(created_by=request.user) |
                Q(status__in=[DrillShift.STATUS_SUBMITTED, DrillShift.STATUS_APPROVED])
            )
        elif profile.is_manager:
            # Managers can see submitted and approved shifts
            shifts = shifts.filter(
                status__in=[DrillShift.STATUS_SUBMITTED, DrillShift.STATUS_APPROVED]
            )
    
    # Filter by status if provided
    status = request.GET.get('status')
    if status:
        shifts = shifts.filter(status=status)
    
    # Filter by hole number if provided
    hole_number = request.GET.get('hole_number')
    if hole_number:
        shifts = shifts.filter(progress__hole_number=hole_number).distinct()
    
    # Group shifts by date and rig (24-hour periods)
    grouped_shifts = {}
    for shift in shifts:
        key = (shift.date, shift.rig)
        if key not in grouped_shifts:
            grouped_shifts[key] = {'day': None, 'night': None, 'date': shift.date, 'rig': shift.rig, 'location': shift.location, 'client': shift.client}
        
        if shift.shift_type == 'day':
            grouped_shifts[key]['day'] = shift
        else:
            grouped_shifts[key]['night'] = shift
    
    # Convert to list and sort by date (newest first)
    shift_groups = sorted(grouped_shifts.values(), key=lambda x: x['date'], reverse=True)
    
    # Get all unique hole numbers for filter dropdown
    all_hole_numbers = DrillingProgress.objects.filter(
        hole_number__isnull=False
    ).exclude(
        hole_number=''
    ).values_list('hole_number', flat=True).distinct().order_by('hole_number')
    
    context = {
        'shifts': shifts,
        'shift_groups': shift_groups,
        'status_choices': DrillShift.STATUS_CHOICES,
        'hole_numbers': list(all_hole_numbers),
        'selected_hole': hole_number,
    }
    return render(request, 'core/shift_list.html', context)


@login_required
def shift_detail(request, pk):
    """
    Display detailed view of a single drill shift.
    
    Shows all related data including progress, activities, materials,
    and approval history. Implements role-based access control.
    
    Args:
        request: HTTP request object
        pk: Primary key of the shift to display
        
    Returns:
        Rendered shift detail template with shift data and permissions
        
    Raises:
        Http404: If shift with given pk doesn't exist
        Redirect: If user doesn't have permission to view the shift
    """
    shift = get_object_or_404(
        DrillShift.objects.select_related('created_by')
        .prefetch_related('progress', 'activities', 'materials', 'approvals'),
        pk=pk
    )
    
    # Check permissions based on role
    profile = request.user.profile
    if not request.user.is_superuser:
        is_client_user = _is_client_user(request.user)
        if is_client_user:
            client_ids = set(_get_client_queryset_for_user(request.user).values_list('id', flat=True))
            if shift.status != DrillShift.STATUS_APPROVED:
                messages.error(request, 'You can only view approved shifts for your company.')
                return redirect('core:client_dashboard')
            # Legacy compatibility: some client users are role-based but not yet mapped to a Client record.
            if client_ids and shift.client_id not in client_ids:
                messages.error(request, 'You can only view approved shifts for your company.')
                return redirect('core:client_dashboard')
        elif profile.is_supervisor and shift.created_by != request.user and shift.status == DrillShift.STATUS_DRAFT:
            messages.error(request, 'You cannot view draft shifts created by others.')
            return redirect('core:shift_list')
        elif profile.is_manager and shift.status == DrillShift.STATUS_DRAFT:
            messages.error(request, 'You cannot view draft shifts.')
            return redirect('core:shift_list')
    
    # Calculate summary data for current shift
    total_meters = shift.progress.aggregate(
        total=Sum('meters_drilled')
    )['total'] or 0
    
    # Calculate total activity hours
    total_activity_minutes = shift.activities.aggregate(
        total=Sum('duration_minutes')
    )['total'] or 0
    total_activity_hours = round(total_activity_minutes / 60, 1) if total_activity_minutes else 0
    
    # Get shift hours
    shift_hours = shift.get_shift_hours()
    
    # Calculate man hours (simplified - could be enhanced with actual crew count)
    total_man_hours = round(shift_hours * 2, 1)  # Assuming 2 people per shift, rounded to 1 decimal
    
    # Get companion shift (day/night pair for same date and rig)
    companion_shift = None
    companion_meters = 0
    companion_activity_hours = 0
    companion_man_hours = 0
    
    if shift.date and shift.rig:
        # Find the opposite shift type for the same date and rig
        opposite_shift_type = 'night' if shift.shift_type == 'day' else 'day'
        companion_shift = DrillShift.objects.filter(
            date=shift.date,
            rig=shift.rig,
            shift_type=opposite_shift_type
        ).select_related('created_by').prefetch_related('progress', 'activities').first()
        
        if companion_shift:
            # Calculate companion shift metrics
            companion_meters = companion_shift.progress.aggregate(
                total=Sum('meters_drilled')
            )['total'] or 0
            
            companion_activity_minutes = companion_shift.activities.aggregate(
                total=Sum('duration_minutes')
            )['total'] or 0
            companion_activity_hours = round(companion_activity_minutes / 60, 1) if companion_activity_minutes else 0
            
            companion_shift_hours = companion_shift.get_shift_hours()
            companion_man_hours = round(companion_shift_hours * 2, 1)
    
    # Calculate 24-hour totals
    total_24h_meters = float(total_meters) + float(companion_meters)
    total_24h_man_hours = total_man_hours + companion_man_hours
    total_24h_activity_hours = total_activity_hours + companion_activity_hours
    
    context = {
        'shift': shift,
        'companion_shift': companion_shift,  # Day or night counterpart
        'total_meters': total_meters,
        'total_man_hours': total_man_hours,
        'total_activity_hours': total_activity_hours,
        # 24-hour totals
        'total_24h_meters': total_24h_meters,
        'total_24h_man_hours': total_24h_man_hours,
        'total_24h_activity_hours': total_24h_activity_hours,
        'companion_meters': companion_meters,
        'companion_activity_hours': companion_activity_hours,
        'companion_man_hours': companion_man_hours,
        'can_edit': request.user.is_superuser or (
            profile.is_supervisor and 
            shift.created_by == request.user and 
            not shift.is_locked
        ),
        'can_submit': request.user.is_superuser or (
            profile.is_supervisor and 
            shift.created_by == request.user and 
            shift.status == DrillShift.STATUS_DRAFT
        ),
        'can_approve': request.user.is_superuser or (
            not _is_client_user(request.user) and 
            shift.status == DrillShift.STATUS_SUBMITTED
        )
    }
    return render(request, 'core/shift_detail.html', context)


@supervisor_required
def shift_create(request):
    """
    Create a new drill shift with related data.
    
    Handles creation of a shift along with inline formsets for:
    - Drilling progress records
    - Activity logs
    - Material usage records
    - Survey records
    - Casing records
    
    Only supervisors can create new shifts. The shift is automatically
    assigned to the current user as creator.
    
    Args:
        request: HTTP request object
        
    Returns:
        Rendered form template (GET) or redirect to shift detail (POST success)
    """
    if request.method == 'POST':
        form = DrillShiftForm(request.POST, user=request.user)
        progress_formset = DrillingProgressFormSet(request.POST, request.FILES, prefix='progress', form_kwargs={'user': request.user})
        activity_formset = ActivityLogFormSet(request.POST, prefix='activity')
        material_formset = MaterialUsedFormSet(request.POST, prefix='material')
        survey_formset = SurveyFormSet(
            request.POST if 'survey-TOTAL_FORMS' in request.POST else None,
            prefix='survey'
        )
        casing_formset = CasingFormSet(
            request.POST if 'casing-TOTAL_FORMS' in request.POST else None,
            prefix='casing'
        )

        survey_is_valid = (not survey_formset.is_bound) or survey_formset.is_valid()
        casing_is_valid = (not casing_formset.is_bound) or casing_formset.is_valid()

        if (form.is_valid() and progress_formset.is_valid()
            and activity_formset.is_valid() and material_formset.is_valid()
            and survey_is_valid and casing_is_valid):
            
            # Use transaction to ensure all saves succeed or none do
            from django.db import transaction
            try:
                with transaction.atomic():
                    shift = form.save(commit=False)
                    shift.created_by = request.user
                    shift.save()
                    
                    # Save formsets
                    progress_formset.instance = shift
                    progress_formset.save()
                    
                    activity_formset.instance = shift
                    activity_formset.save()
                    
                    material_formset.instance = shift
                    material_formset.save()

                    if survey_formset.is_bound:
                        survey_formset.instance = shift
                        survey_formset.save()

                    if casing_formset.is_bound:
                        casing_formset.instance = shift
                        casing_formset.save()
                
                messages.success(request, 'Shift created successfully.')
                return redirect('core:shift_detail', pk=shift.pk)
            except Exception as e:
                messages.error(request, f'Error saving shift: {str(e)}. Please try again.')
                # Form will re-render with data preserved
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = DrillShiftForm(user=request.user)
        progress_formset = DrillingProgressFormSet(prefix='progress', form_kwargs={'user': request.user})
        activity_formset = ActivityLogFormSet(prefix='activity')
        material_formset = MaterialUsedFormSet(prefix='material')
        survey_formset = SurveyFormSet(prefix='survey')
        casing_formset = CasingFormSet(prefix='casing')
    
    context = {
        'form': form,
        'progress_formset': progress_formset,
        'activity_formset': activity_formset,
        'material_formset': material_formset,
        'survey_formset': survey_formset,
        'casing_formset': casing_formset,
    }
    return render(request, 'core/shift_form.html', context)


@supervisor_required
def shift_update(request, pk):
    """
    Update an existing drill shift.
    
    Only the creator of a shift can update it, and only if it's not locked.
    Handles updating the shift and all related formsets.
    
    Args:
        request: HTTP request object
        pk: Primary key of the shift to update
        
    Returns:
        Rendered form template (GET) or redirect to shift detail (POST success)
        
    Raises:
        Http404: If shift with given pk doesn't exist
        Redirect: If user doesn't have permission or shift is locked
    """
    shift = get_object_or_404(DrillShift, pk=pk)
    
    # Check if the user is the creator of the shift
    if shift.created_by != request.user and not request.user.is_superuser:
        messages.error(request, 'You can only edit shifts that you created.')
        return redirect('core:shift_detail', pk=shift.pk)
    
    if shift.is_locked:
        messages.error(request, 'This shift is locked and cannot be edited.')
        return redirect('core:shift_detail', pk=shift.pk)
    
    if request.method == 'POST':
        form = DrillShiftForm(request.POST, instance=shift, user=request.user)
        progress_formset = DrillingProgressFormSet(
            request.POST, request.FILES, instance=shift, prefix='progress', form_kwargs={'user': request.user}
        )
        activity_formset = ActivityLogFormSet(
            request.POST, instance=shift, prefix='activity'
        )
        material_formset = MaterialUsedFormSet(
            request.POST, instance=shift, prefix='material'
        )
        survey_formset = SurveyFormSet(
            request.POST if 'survey-TOTAL_FORMS' in request.POST else None,
            instance=shift, prefix='survey'
        )
        casing_formset = CasingFormSet(
            request.POST if 'casing-TOTAL_FORMS' in request.POST else None,
            instance=shift, prefix='casing'
        )

        survey_is_valid = (not survey_formset.is_bound) or survey_formset.is_valid()
        casing_is_valid = (not casing_formset.is_bound) or casing_formset.is_valid()

        if (form.is_valid() and progress_formset.is_valid()
            and activity_formset.is_valid() and material_formset.is_valid()
            and survey_is_valid and casing_is_valid):
            
            # Use transaction to ensure all updates succeed or none do
            from django.db import transaction
            try:
                with transaction.atomic():
                    form.save()
                    progress_formset.save()
                    activity_formset.save()
                    material_formset.save()
                    if survey_formset.is_bound:
                        survey_formset.save()
                    if casing_formset.is_bound:
                        casing_formset.save()
                
                messages.success(request, 'Shift updated successfully.')
                return redirect('core:shift_detail', pk=shift.pk)
            except Exception as e:
                messages.error(request, f'Error updating shift: {str(e)}. Please try again.')
                # Form will re-render with data preserved
        else:
            # Show validation errors
            messages.error(request, 'Please correct the errors below.')
    else:
        form = DrillShiftForm(instance=shift, user=request.user)
        progress_formset = DrillingProgressFormSet(instance=shift, prefix='progress', form_kwargs={'user': request.user})
        activity_formset = ActivityLogFormSet(instance=shift, prefix='activity')
        material_formset = MaterialUsedFormSet(instance=shift, prefix='material')
        survey_formset = SurveyFormSet(instance=shift, prefix='survey')
        casing_formset = CasingFormSet(instance=shift, prefix='casing')
    
    context = {
        'form': form,
        'progress_formset': progress_formset,
        'activity_formset': activity_formset,
        'material_formset': material_formset,
        'survey_formset': survey_formset,
        'casing_formset': casing_formset,
        'shift': shift,
    }
    return render(request, 'core/shift_form.html', context)


@supervisor_required
def shift_submit(request, pk):
    """
    Submit a draft shift for approval.
    
    Changes shift status from draft to submitted and creates an initial
    approval history entry. Only the creator can submit their own shifts.
    
    Args:
        request: HTTP request object (must be POST)
        pk: Primary key of the shift to submit
        
    Returns:
        Redirect to shift detail page
        
    Raises:
        Http404: If shift with given pk doesn't exist
        Redirect: If user doesn't have permission or shift isn't in draft status
    """
    shift = get_object_or_404(DrillShift, pk=pk)
    
    # Check if the user is the creator of the shift
    if shift.created_by != request.user and not request.user.is_superuser:
        messages.error(request, 'You can only submit shifts that you created.')
        return redirect('core:shift_detail', pk=shift.pk)
    
    if shift.status != DrillShift.STATUS_DRAFT:
        messages.error(request, 'Only draft shifts can be submitted.')
        return redirect('core:shift_detail', pk=shift.pk)
    
    if request.method == 'POST':
        shift.status = DrillShift.STATUS_SUBMITTED
        if shift.submitted_at is None:
            shift.submitted_at = timezone.now()
        shift.save()
        
        # Create approval history entry
        ApprovalHistory.objects.create(
            shift=shift,
            approver=None,  # Will be set when approved/rejected
            role='Pending Manager Review'
        )
        
        messages.success(request, 'Shift submitted for approval.')
    
    return redirect('core:shift_detail', pk=shift.pk)


@can_approve_shifts
def shift_approve(request, pk):
    """
    Approve or reject a submitted shift.
    
    Managers and authorized supervisors can approve or reject shifts.
    Approved shifts are automatically locked to prevent further editing.
    Records the decision in approval history with comments.
    
    Args:
        request: HTTP request object (must be POST)
        pk: Primary key of the shift to approve/reject
        
    Returns:
        Redirect to shift detail page
        
    Raises:
        Http404: If shift with given pk doesn't exist
        Redirect: If shift isn't in submitted status
        
    POST Parameters:
        decision: 'approved' or 'rejected'
        comments: Optional comments about the decision
    """
    shift = get_object_or_404(DrillShift, pk=pk)
    
    if shift.status != DrillShift.STATUS_SUBMITTED:
        messages.error(request, 'Only submitted shifts can be approved/rejected.')
        return redirect('core:shift_detail', pk=shift.pk)
    
    if request.method == 'POST':
        decision = request.POST.get('decision')
        comments = request.POST.get('comments', '')
        
        if decision in [ApprovalHistory.DECISION_APPROVED, ApprovalHistory.DECISION_REJECTED]:
            shift.status = DrillShift.STATUS_APPROVED if decision == ApprovalHistory.DECISION_APPROVED else DrillShift.STATUS_REJECTED
            shift.is_locked = shift.status == DrillShift.STATUS_APPROVED
            
            # If approved and client is assigned, automatically submit to client
            if decision == ApprovalHistory.DECISION_APPROVED:
                if shift.manager_approved_at is None:
                    shift.manager_approved_at = timezone.now()
            if decision == ApprovalHistory.DECISION_APPROVED and shift.client:
                shift.client_status = DrillShift.CLIENT_PENDING
                shift.submitted_to_client_at = timezone.now()
            
            shift.save()

            # Generate alerts when shift is approved
            if shift.status == DrillShift.STATUS_APPROVED:
                from .utils import evaluate_shift_alerts
                try:
                    evaluate_shift_alerts(shift)
                except Exception as e:
                    # Non-critical: do not block approval on alert generation failure
                    messages.warning(request, f'Approved but alert evaluation failed: {e}')
            
            # Record the approval decision
            ApprovalHistory.objects.create(
                shift=shift,
                approver=request.user,
                role=request.user.profile.get_role_display(),
                decision=decision,
                comments=comments
            )
            
            if decision == ApprovalHistory.DECISION_APPROVED:
                if shift.client:
                    messages.success(request, f'Shift approved and submitted to {shift.client.name} for final approval.')
                else:
                    messages.success(request, 'Shift approved.')
            else:
                messages.success(request, 'Shift rejected.')
        else:
            messages.error(request, 'Invalid decision.')
    
    return redirect('core:shift_detail', pk=shift.pk)


@login_required
def export_shifts(request):
    """
    Export shifts to CSV format.
    
    Exports shifts visible to the current user based on their role and
    any applied filters. Supports date range filtering.
    
    Args:
        request: HTTP request object
        
    Returns:
        CSV file download response
        
    Query Parameters:
        start_date: Start date for filtering (YYYY-MM-DD format)
        end_date: End date for filtering (YYYY-MM-DD format)
        status: Filter by shift status
    """
    # Get shifts based on user role and filters
    shifts = DrillShift.objects.select_related('created_by').all()
    
    # Apply role-based filters
    if not request.user.is_superuser:
        profile = request.user.profile
        if _is_client_user(request.user):
            shifts = shifts.filter(status=DrillShift.STATUS_APPROVED)
        elif profile.is_supervisor:
            shifts = shifts.filter(
                Q(created_by=request.user) |
                Q(status__in=[DrillShift.STATUS_SUBMITTED, DrillShift.STATUS_APPROVED])
            )
        elif profile.is_manager:
            shifts = shifts.filter(
                status__in=[DrillShift.STATUS_SUBMITTED, DrillShift.STATUS_APPROVED]
            )
    
    # Apply date range filter if provided
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d')
            shifts = shifts.filter(date__range=[start, end])
        except ValueError:
            messages.error(request, 'Invalid date format. Use YYYY-MM-DD.')
            return redirect('core:shift_list')
    
    # Create the response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="shifts.csv"'
    
    return export_shifts_to_csv(shifts, response)


@login_required
def export_boq(request):
    """
    Export monthly Bill of Quantities (BOQ) to Excel format.
    
    Generates a comprehensive BOQ report including:
    - Daily drilling progress
    - Material usage summaries
    - Activity time breakdown
    - Total meters drilled
    
    Args:
        request: HTTP request object
        
    Returns:
        Excel file download response
        
    Query Parameters:
        start_date: Start date for filtering (YYYY-MM-DD format)
        end_date: End date for filtering (YYYY-MM-DD format)
        status: Filter by shift status
    """
    # Get shifts based on user role and filters
    shifts = DrillShift.objects.select_related('created_by').all()
    
    # Apply role-based filters
    if not request.user.is_superuser:
        profile = request.user.profile
        if _is_client_user(request.user):
            shifts = shifts.filter(status=DrillShift.STATUS_APPROVED)
        elif profile.is_supervisor:
            shifts = shifts.filter(
                Q(created_by=request.user) |
                Q(status__in=[DrillShift.STATUS_SUBMITTED, DrillShift.STATUS_APPROVED])
            )
        elif profile.is_manager:
            shifts = shifts.filter(
                status__in=[DrillShift.STATUS_SUBMITTED, DrillShift.STATUS_APPROVED]
            )
    
    # Apply date range filter if provided
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d')
            shifts = shifts.filter(date__range=[start, end])
        except ValueError:
            messages.error(request, 'Invalid date format. Use YYYY-MM-DD.')
            return redirect('core:shift_list')
    
    # Create the response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="monthly_boq.xlsx"'
    
    return export_monthly_boq(shifts, response)


@login_required
def boq_report_list(request):
    """List BOQ reports for contractors or clients, depending on the active role."""
    reports = BOQReport.objects.select_related('client', 'created_by', 'client_reviewed_by')
    is_client_view = _is_client_user(request.user)

    if is_client_view:
        client_qs = _get_client_queryset_for_user(request.user)
        if not client_qs.exists():
            messages.error(request, 'Your account is not linked to a client company.')
            return redirect('accounts:profile')
        selected_client_id = request.GET.get('client', '')
        reports = reports.filter(client__in=client_qs)
        if selected_client_id and selected_client_id.isdigit():
            reports = reports.filter(client_id=int(selected_client_id))
        available_clients = list(client_qs.order_by('name'))
        if not selected_client_id and len(available_clients) == 1:
            selected_client_id = str(available_clients[0].id)
    else:
        contractor_workspace_ids = list(
            WorkspaceMembership.objects.filter(
                user=request.user,
                workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
            ).values_list('workspace_id', flat=True)
        )
        if not request.user.is_superuser:
            reports = reports.filter(
                Q(contractor_workspace_id__in=contractor_workspace_ids) |
                Q(created_by=request.user)
            )
        selected_client_id = request.GET.get('client', '')
        if selected_client_id:
            reports = reports.filter(client_id=selected_client_id)
        available_clients = Client.objects.filter(is_active=True).order_by('name')

    status = request.GET.get('status', '')
    if status:
        reports = reports.filter(status=status)

    client_status = request.GET.get('client_status', '')
    if client_status:
        reports = reports.filter(client_status=client_status)

    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    if start_date:
        reports = reports.filter(period_start__gte=start_date)
    if end_date:
        reports = reports.filter(period_end__lte=end_date)

    reports = reports.order_by('-period_end', '-created_at')

    context = {
        'reports': reports,
        'is_client_view': is_client_view,
        'available_clients': available_clients,
        'selected_client_id': selected_client_id,
        'status_choices': BOQReport.STATUS_CHOICES,
        'client_status_choices': BOQReport.CLIENT_STATUS_CHOICES,
        'draft_count': reports.filter(status=BOQReport.STATUS_DRAFT).count(),
        'submitted_count': reports.filter(status=BOQReport.STATUS_SUBMITTED).count(),
        'client_pending_count': reports.filter(client_status=BOQReport.CLIENT_PENDING).count(),
        'client_approved_count': reports.filter(client_status=BOQReport.CLIENT_APPROVED).count(),
        'client_rejected_count': reports.filter(client_status=BOQReport.CLIENT_REJECTED).count(),
    }
    return render(request, 'core/boq_report_list.html', context)


@login_required
@role_required(['supervisor', 'manager'])
def boq_report_create(request):
    """Create a draft BOQ report for a client and drilling period."""
    contractor_workspace = None
    if not request.user.is_superuser:
        contractor_workspace_membership = WorkspaceMembership.objects.select_related('workspace').filter(
            user=request.user,
            workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
        ).first()
        if not contractor_workspace_membership:
            messages.error(request, 'You are not assigned to a contractor workspace.')
            return redirect('core:boq_report_list')
        contractor_workspace = contractor_workspace_membership.workspace

    if request.method == 'POST':
        # Get the client from POST data to filter presets
        client_id = request.POST.get('client')
        client = get_object_or_404(Client, pk=client_id) if client_id else None
        
        form = BOQReportForm(request.POST, client=client)
        if form.is_valid():
            report = form.save(commit=False)
            report.created_by = request.user
            if contractor_workspace is not None:
                report.contractor_workspace = contractor_workspace
            report.status = BOQReport.STATUS_DRAFT
            report.client_status = BOQReport.CLIENT_PENDING
            report.save()
            
            # Create BOQLineItem instances from selected presets
            selected_drill_sizes = form.cleaned_data.get('drill_size_presets', [])
            selected_equipment = form.cleaned_data.get('equipment_presets', [])
            selected_consumables = form.cleaned_data.get('consumable_presets', [])
            
            # Process selected drill size presets
            for preset in selected_drill_sizes:
                BOQLineItem.objects.create(
                    boq_report=report,
                    item_type='drill_size',
                    item_name=preset.name,
                    quantity=1,  # Default quantity
                    unit='meter',
                    locked_rate=preset.rate_per_meter,
                    drill_size_preset=preset,
                )
            
            # Process selected equipment presets
            for preset in selected_equipment:
                BOQLineItem.objects.create(
                    boq_report=report,
                    item_type='equipment',
                    item_name=preset.name,
                    quantity=1,  # Default quantity
                    unit=preset.period,  # e.g., 'daily', 'hourly'
                    locked_rate=preset.rate,
                    equipment_preset=preset,
                )
            
            # Process selected consumable presets
            for preset in selected_consumables:
                BOQLineItem.objects.create(
                    boq_report=report,
                    item_type='consumable',
                    item_name=preset.name,
                    quantity=1,  # Default quantity
                    unit=preset.unit,
                    locked_rate=preset.rate,
                    consumable_preset=preset,
                )
            
            # Process selected additional charge presets
            selected_additional_charges = form.cleaned_data.get('additional_charge_presets', [])
            for preset in selected_additional_charges:
                BOQLineItem.objects.create(
                    boq_report=report,
                    item_type='additional_charge',
                    item_name=preset.name,
                    quantity=1,  # Default quantity
                    unit=preset.unit,
                    locked_rate=preset.effective_rate,
                    additional_charge_preset=preset,
                )
            
            messages.success(request, 'BOQ draft created successfully with line items.')
            return redirect('core:boq_report_detail', pk=report.pk)
    else:
        initial = {}
        client_id = None
        if request.GET.get('client'):
            initial['client'] = request.GET.get('client')
            client_id = request.GET.get('client')
        if request.GET.get('start_date'):
            initial['period_start'] = request.GET.get('start_date')
        if request.GET.get('end_date'):
            initial['period_end'] = request.GET.get('end_date')
        
        # Get client for form initialization to filter presets
        client = get_object_or_404(Client, pk=client_id) if client_id else None
        form = BOQReportForm(initial=initial, client=client)

    return render(request, 'core/boq_report_form.html', {'form': form})


@login_required
def boq_report_detail(request, pk):
    """Show BOQ report contents and approval state."""
    report = get_object_or_404(
        BOQReport.objects.select_related('client', 'created_by', 'client_reviewed_by'),
        pk=pk,
    )

    is_client_user = _is_client_user(request.user)
    if is_client_user:
        client_ids = set(_get_client_queryset_for_user(request.user).values_list('id', flat=True))
        if report.client_id not in client_ids:
            messages.error(request, 'You can only view BOQ reports for your company.')
            return redirect('core:boq_report_list')
    elif not request.user.is_superuser:
        contractor_workspace_ids = list(
            WorkspaceMembership.objects.filter(
                user=request.user,
                workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
            ).values_list('workspace_id', flat=True)
        )
        can_access = report.created_by_id == request.user.id or (
            report.contractor_workspace_id is not None and report.contractor_workspace_id in contractor_workspace_ids
        )
        if not can_access:
            messages.error(request, 'You do not have permission to view this BOQ report.')
            return redirect('core:boq_report_list')

    shifts = report.get_shifts_queryset().order_by('-date', '-id')
    
    # Get line items grouped by type
    line_items = report.line_items.all().order_by('item_type', 'item_name')
    line_items_by_type = {
        'drill_size': [item for item in line_items if item.item_type == 'drill_size'],
        'equipment': [item for item in line_items if item.item_type == 'equipment'],
        'consumable': [item for item in line_items if item.item_type == 'consumable'],
    }
    
    # Calculate totals by type
    type_totals = {}
    grand_total = report.get_grand_total()
    for item_type, items in line_items_by_type.items():
        total = sum(item.total_amount for item in items) if items else Decimal('0.00')
        type_totals[item_type] = total

    context = {
        'report': report,
        'shifts': shifts,
        'materials_summary': report.get_materials_summary(),
        'total_meters': report.get_total_meters(),
        'total_shifts': shifts.count(),
        'is_client_view': is_client_user,
        'can_submit_to_client': request.user.is_superuser or (not is_client_user and report.status == BOQReport.STATUS_DRAFT),
        'can_client_review': (is_client_user and report.status == BOQReport.STATUS_SUBMITTED and report.client_status == BOQReport.CLIENT_PENDING),
        'line_items': line_items,
        'line_items_by_type': line_items_by_type,
        'type_totals': type_totals,
        'additional_charges': report.additional_charges.all(),
        'additional_charges_total': report.get_additional_charges_total(),
        'grand_total': grand_total,
    }
    return render(request, 'core/boq.html', context)


@login_required
def boq_add_additional_charge(request, pk):
    report = get_object_or_404(BOQReport, pk=pk)
    is_client_user = _is_client_user(request.user)

    if is_client_user:
        client_ids = set(_get_client_queryset_for_user(request.user).values_list('id', flat=True))
        if report.client_id not in client_ids:
            messages.error(request, 'You can only add additional charges to your own BOQ reports.')
            return redirect('core:boq_report_detail', pk=pk)
    elif not request.user.is_superuser:
        contractor_workspace_ids = list(
            WorkspaceMembership.objects.filter(
                user=request.user,
                workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
            ).values_list('workspace_id', flat=True)
        )
        can_access = report.created_by_id == request.user.id or (
            report.contractor_workspace_id is not None and report.contractor_workspace_id in contractor_workspace_ids
        )
        if not can_access:
            messages.error(request, 'You do not have permission to update this BOQ report.')
            return redirect('core:boq_report_list')

    if request.method == 'POST':
        form = BOQAdditionalChargeForm(request.POST)
        if form.is_valid():
            charge = form.save(commit=False)
            charge.boq_report = report
            charge.proposed_by = request.user

            # Auto-approve by the proposing party
            if is_client_user:
                charge.client_approved = True
                charge.contractor_approved = False
            else:
                charge.contractor_approved = True
                charge.client_approved = False

            charge.save()
            messages.success(request, 'Additional charge proposal submitted. Awaiting counterparty approval.')
        else:
            messages.error(request, 'Invalid additional charge data. Please fix the errors and retry.')

    return redirect('core:boq_report_detail', pk=pk)


@login_required
def boq_update_additional_charge(request, pk, charge_pk):
    report = get_object_or_404(BOQReport, pk=pk)
    charge = get_object_or_404(BOQAdditionalCharge, pk=charge_pk, boq_report=report)
    is_client_user = _is_client_user(request.user)

    if is_client_user:
        client_ids = set(_get_client_queryset_for_user(request.user).values_list('id', flat=True))
        if report.client_id not in client_ids:
            messages.error(request, 'You can only update additional charges for your own BOQ reports.')
            return redirect('core:boq_report_detail', pk=pk)
    elif not request.user.is_superuser:
        contractor_workspace_ids = list(
            WorkspaceMembership.objects.filter(
                user=request.user,
                workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
            ).values_list('workspace_id', flat=True)
        )
        can_access = report.created_by_id == request.user.id or (
            report.contractor_workspace_id is not None and report.contractor_workspace_id in contractor_workspace_ids
        )
        if not can_access:
            messages.error(request, 'You do not have permission to update this BOQ report.')
            return redirect('core:boq_report_list')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'approve':
            if is_client_user:
                charge.client_approved = True
            else:
                charge.contractor_approved = True

            if charge.client_approved and charge.contractor_approved:
                charge.is_rejected = False

            charge.save(update_fields=['client_approved', 'contractor_approved', 'is_rejected', 'updated_at'])
            messages.success(request, 'Additional charge approval updated.')

        elif action == 'reject':
            charge.is_rejected = True
            charge.contractor_approved = False
            charge.client_approved = False
            charge.save(update_fields=['is_rejected', 'client_approved', 'contractor_approved', 'updated_at'])
            messages.warning(request, 'Additional charge rejected.')

        else:
            messages.error(request, 'Unknown action for additional charge.')

    return redirect('core:boq_report_detail', pk=pk)


@login_required
def boq_report_export(request, pk):
    """Export the exact BOQ package currently being reviewed."""
    report = get_object_or_404(BOQReport.objects.select_related('client', 'contractor_workspace'), pk=pk)
    is_client_user = _is_client_user(request.user)

    if is_client_user:
        client_ids = set(_get_client_queryset_for_user(request.user).values_list('id', flat=True))
        if report.client_id not in client_ids:
            messages.error(request, 'You can only export BOQ reports for your company.')
            return redirect('core:boq_report_list')
    elif not request.user.is_superuser:
        contractor_workspace_ids = list(
            WorkspaceMembership.objects.filter(
                user=request.user,
                workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
            ).values_list('workspace_id', flat=True)
        )
        can_access = report.created_by_id == request.user.id or (
            report.contractor_workspace_id is not None and report.contractor_workspace_id in contractor_workspace_ids
        )
        if not can_access:
            messages.error(request, 'You do not have permission to export this BOQ report.')
            return redirect('core:boq_report_list')

    shifts = list(report.get_shifts_queryset().order_by('date', 'id'))
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    filename = slugify(report.title) or f'boq-report-{report.pk}'
    response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'

    # Determine company name for export header
    company_name = 'DI-VISION'
    if report.contractor_workspace:
        company_name = report.contractor_workspace.name.upper()
    period_label = f"{report.period_start} to {report.period_end} | Client: {report.client.name}"

    return export_monthly_boq(shifts, response, company_name=company_name, period_label=period_label, boq_report=report)


@login_required
@role_required(['supervisor', 'manager'])
def boq_submit_to_client(request, pk):
    """Submit a contractor BOQ draft to the client for review."""
    report = get_object_or_404(BOQReport, pk=pk)

    if report.status != BOQReport.STATUS_DRAFT:
        messages.error(request, 'Only draft BOQ reports can be submitted to client.')
        return redirect('core:boq_report_detail', pk=pk)

    if not request.user.is_superuser:
        contractor_workspace_ids = list(
            WorkspaceMembership.objects.filter(
                user=request.user,
                workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
            ).values_list('workspace_id', flat=True)
        )
        can_access = report.created_by_id == request.user.id or (
            report.contractor_workspace_id is not None and report.contractor_workspace_id in contractor_workspace_ids
        )
        if not can_access:
            messages.error(request, 'You do not have permission to submit this BOQ report.')
            return redirect('core:boq_report_list')

    if request.method == 'POST':
        report.status = BOQReport.STATUS_SUBMITTED
        report.client_status = BOQReport.CLIENT_PENDING
        report.submitted_to_client_at = timezone.now()
        report.save(update_fields=['status', 'client_status', 'submitted_to_client_at', 'updated_at'])
        messages.success(request, f'BOQ report submitted to {report.client.name} for review.')

    return redirect('core:boq_report_detail', pk=pk)


@login_required
@client_required
def client_review_boq(request, pk):
    """Client approves or rejects a submitted BOQ report."""
    report = get_object_or_404(BOQReport.objects.select_related('client'), pk=pk)
    client_ids = set(_get_client_queryset_for_user(request.user).values_list('id', flat=True))
    if report.client_id not in client_ids:
        messages.error(request, 'You can only review BOQ reports for your company.')
        return redirect('core:boq_report_list')

    if report.status != BOQReport.STATUS_SUBMITTED or report.client_status != BOQReport.CLIENT_PENDING:
        messages.error(request, 'This BOQ is not pending client review.')
        return redirect('core:boq_report_detail', pk=pk)

    if request.method == 'POST':
        decision = request.POST.get('decision')
        comments = request.POST.get('comments', '').strip()

        if decision == 'approved':
            report.client_status = BOQReport.CLIENT_APPROVED
            report.client_comments = comments
            report.client_reviewed_at = timezone.now()
            report.client_reviewed_by = request.user
            report.save(update_fields=['client_status', 'client_comments', 'client_reviewed_at', 'client_reviewed_by', 'updated_at'])
            messages.success(request, 'BOQ approved successfully. The contractor can now proceed with invoicing.')
        elif decision == 'rejected':
            report.client_status = BOQReport.CLIENT_REJECTED
            report.client_comments = comments
            report.client_reviewed_at = timezone.now()
            report.client_reviewed_by = request.user
            report.save(update_fields=['client_status', 'client_comments', 'client_reviewed_at', 'client_reviewed_by', 'updated_at'])
            messages.warning(request, 'BOQ rejected. The contractor can revise and resubmit it.')
        else:
            messages.error(request, 'Invalid decision.')

    return redirect('core:boq_report_detail', pk=pk)


@login_required
@role_required(['manager'])
def shift_submit_to_client(request, pk):
    """
    Submit an approved shift to client for their approval.
    Only managers can submit to clients.
    """
    shift = get_object_or_404(DrillShift, pk=pk)
    
    # Check if shift is approved by manager
    if shift.status != DrillShift.STATUS_APPROVED:
        messages.error(request, 'Only approved shifts can be submitted to clients.')
        return redirect('core:shift_detail', pk=pk)
    
    # Check if client is assigned
    if not shift.client:
        messages.error(request, 'Please assign a client to this shift before submitting.')
        return redirect('core:shift_detail', pk=pk)
    
    # Submit to client
    shift.client_status = DrillShift.CLIENT_PENDING
    shift.submitted_to_client_at = timezone.now()
    shift.save()
    
    messages.success(request, f'Shift submitted to {shift.client.name} for approval.')
    return redirect('core:shift_detail', pk=pk)


@login_required
@client_required
def client_dashboard(request):
    """
    Client dashboard showing shifts submitted for their approval.
    Supports period filters (This Week / This Month / Last Month / Year / Custom)
    and a contractor workspace filter.
    
    Role Guard: Only accessible to users with a valid client profile.
    """
    # Workspace-aware role check to avoid stale profile.role causing contractor UI leakage
    has_client_profile = hasattr(request.user, 'client_profile')
    has_client_workspace_membership = WorkspaceMembership.objects.filter(
        user=request.user,
        workspace__workspace_type=Workspace.WORKSPACE_CLIENT,
        workspace__is_active=True,
    ).exists()
    if not (has_client_profile or has_client_workspace_membership):
        messages.error(request, 'You must be a client user to access this page.')
        return redirect('accounts:profile')
    
    client = _get_primary_client_for_user(request.user)
    if client is None:
        messages.error(request, 'Your account is not linked to any client company record.')
        return redirect('accounts:profile')

    today = timezone.now().date()

    # ── Period filter ──────────────────────────────────────────────────────────
    period = request.GET.get('period', 'this_month')
    year_str = request.GET.get('year', str(today.year))
    date_from_str = request.GET.get('date_from', '')
    date_to_str = request.GET.get('date_to', '')

    if period == 'this_week':
        filter_start = today - timedelta(days=today.weekday())
        filter_end = today
    elif period == 'last_month':
        month_start_this = today.replace(day=1)
        filter_end = month_start_this - timedelta(days=1)
        filter_start = filter_end.replace(day=1)
    elif period == 'year':
        selected_year = int(year_str) if year_str.isdigit() else today.year
        filter_start = today.replace(year=selected_year, month=1, day=1)
        filter_end = today.replace(year=selected_year, month=12, day=31)
    elif period == 'custom':
        try:
            filter_start = datetime.strptime(date_from_str, '%Y-%m-%d').date() if date_from_str else today.replace(day=1)
            filter_end = datetime.strptime(date_to_str, '%Y-%m-%d').date() if date_to_str else today
        except ValueError:
            filter_start = today.replace(day=1)
            filter_end = today
    else:
        period = 'this_month'
        filter_start = today.replace(day=1)
        filter_end = today

    # ── Contractor workspace filter ────────────────────────────────────────────
    contractor_ws_id = request.GET.get('contractor_workspace_id', '')
    contractor_workspaces = Workspace.objects.filter(
        workspace_type=Workspace.WORKSPACE_CONTRACTOR,
        is_active=True,
    ).order_by('name')

    # Base queryset: manager-approved shifts for this client within the period
    shifts = DrillShift.objects.filter(
        client=client,
        status=DrillShift.STATUS_APPROVED,
        date__range=[filter_start, filter_end],
    ).select_related('created_by', 'client', 'contractor_workspace').prefetch_related('progress').order_by('-date')

    # Optionally filter by contractor workspace
    if contractor_ws_id and contractor_ws_id.isdigit():
        shifts = shifts.filter(contractor_workspace_id=int(contractor_ws_id))

    # Status filter
    client_status = request.GET.get('client_status', '')
    if client_status:
        shifts = shifts.filter(client_status=client_status)

    # Summary counts (over ALL time for this client, not period-scoped)
    all_shifts = DrillShift.objects.filter(client=client, status=DrillShift.STATUS_APPROVED)
    pending_count = all_shifts.filter(Q(client_status=DrillShift.CLIENT_PENDING) | Q(client_status__isnull=True)).count()
    approved_count = all_shifts.filter(client_status=DrillShift.CLIENT_APPROVED).count()
    rejected_count = all_shifts.filter(client_status=DrillShift.CLIENT_REJECTED).count()
    total_shifts = all_shifts.count()

    period_labels = {
        'this_week': 'This Week',
        'this_month': 'This Month',
        'last_month': 'Last Month',
        'year': year_str,
        'custom': f"{filter_start} – {filter_end}",
    }
    period_label = period_labels.get(period, 'This Month')

    context = {
        'shifts': shifts,
        'client': client,
        'client_status_choices': DrillShift.CLIENT_STATUS_CHOICES,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'total_shifts': total_shifts,
        'boq_pending_count': BOQReport.objects.filter(client=client, status=BOQReport.STATUS_SUBMITTED, client_status=BOQReport.CLIENT_PENDING).count(),
        'boq_approved_count': BOQReport.objects.filter(client=client, client_status=BOQReport.CLIENT_APPROVED).count(),
        'boq_rejected_count': BOQReport.objects.filter(client=client, client_status=BOQReport.CLIENT_REJECTED).count(),
        # Filter state
        'period': period,
        'period_label': period_label,
        'filter_start': filter_start,
        'filter_end': filter_end,
        'year_str': year_str,
        'date_from_str': date_from_str,
        'date_to_str': date_to_str,
        'contractor_workspaces': contractor_workspaces,
        'contractor_ws_id': contractor_ws_id,
        'period_options': [
            ('this_week', 'This Week'),
            ('this_month', 'This Month'),
            ('last_month', 'Last Month'),
            ('year', 'Year'),
            ('custom', 'Custom'),
        ],
    }
    return render(request, 'core/client_dashboard.html', context)


@login_required
@client_required
def client_approve_shift(request, pk):
    """
    Client approves or rejects a shift with comments.
    """
    shift = get_object_or_404(DrillShift, pk=pk)
    
    client_ids = set(_get_client_queryset_for_user(request.user).values_list('id', flat=True))
    if not client_ids:
        messages.error(request, 'Your account is not linked to a client company.')
        return redirect('accounts:profile')
    
    # Check if shift belongs to this client
    if shift.client_id not in client_ids:
        messages.error(request, 'You can only approve shifts for your company.')
        return redirect('core:client_dashboard')
    
    # Allow approval if manager approved, even if not formally submitted
    if shift.status != DrillShift.STATUS_APPROVED:
        messages.error(request, 'Only manager-approved shifts can be decided by client.')
        return redirect('core:client_dashboard')
    
    if request.method == 'POST':
        decision = request.POST.get('decision')
        comments = request.POST.get('comments', '')
        
        if decision == 'approved':
            shift.client_status = DrillShift.CLIENT_APPROVED
            shift.client_approved_at = timezone.now()
            shift.client_approved_by = request.user
            shift.client_comments = comments
            shift.is_locked = True  # Lock after client approval
            shift.save()
            messages.success(request, 'Shift approved successfully.')
        elif decision == 'rejected':
            shift.client_status = DrillShift.CLIENT_REJECTED
            shift.client_comments = comments
            shift.is_locked = False  # Unlock for re-editing
            shift.save()
            messages.warning(request, 'Shift rejected. The team can now re-edit and resubmit.')
        else:
            messages.error(request, 'Invalid decision.')
        
        return redirect('core:client_dashboard')
    
    return redirect('core:shift_detail', pk=pk)


@login_required
def shift_pdf_export(request, pk):
    """
    Export a shift report as a receipt-style PDF.
    
    Args:
        request: HTTP request object
        pk: Primary key of the shift to export
        
    Returns:
        PDF file response
    """
    from .pdf_utils import generate_shift_pdf
    
    shift = get_object_or_404(
        DrillShift.objects.select_related('created_by', 'client')
        .prefetch_related('progress', 'activities', 'materials', 'surveys', 'casings'),
        pk=pk
    )

    client_ids = set(_get_client_queryset_for_user(request.user).values_list('id', flat=True))

    # Check permissions - user must be creator, staff, or client with access
    if not (shift.created_by == request.user or 
            request.user.is_staff or 
            (shift.client_id in client_ids)):
        messages.error(request, 'You do not have permission to export this shift.')
        return redirect('core:shift_list')
    
    # Generate PDF
    pdf_buffer = generate_shift_pdf(shift)
    
    # Create filename
    filename = f"Shift_Report_{shift.date.strftime('%Y%m%d')}_{shift.rig.replace(' ', '_')}_{shift.get_shift_type_display()}.pdf"
    
    # Return PDF response
    response = FileResponse(pdf_buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


def handler404(request, exception=None):
    """Custom 404 handler that renders the app-level 404 page."""
    return render(request, '404.html', status=404)


def handler500(request):
    """Custom 500 handler that renders the app-level 500 page."""
    return render(request, '500.html', status=500)

