"""
Geology views for Di-VisioN.

Covers three phases:
  Phase 1 – Smart Lithology Logging  (drill hole CRUD + strip log)
  Phase 2 – 2D Map                   (Leaflet.js plot of collars)
  Phase 3 – Cross Sections           (SVG depth slice across two or more holes)
"""
import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from .forms import DrillHoleForm, LithologyIntervalFormSet
from .models import Client, DrillHole, LithologyInterval


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 – Drill Hole list / CRUD
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def drill_hole_list(request):
    """List all drill holes, optionally filtered by client."""
    holes = DrillHole.objects.select_related('client').prefetch_related('lithology_intervals')

    # Client filter for non-client users
    filter_client_id = request.GET.get('client_id', '')
    if filter_client_id and filter_client_id.isdigit():
        holes = holes.filter(client_id=int(filter_client_id))

    clients = Client.objects.filter(is_active=True).order_by('name')
    return render(request, 'core/drill_hole_list.html', {
        'holes': holes,
        'clients': clients,
        'filter_client_id': filter_client_id,
    })


@login_required
def drill_hole_create(request):
    """Create a new drill hole with lithology intervals."""
    if request.method == 'POST':
        form = DrillHoleForm(request.POST)
        formset = LithologyIntervalFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            hole = form.save(commit=False)
            hole.created_by = request.user
            hole.save()
            formset.instance = hole
            formset.save()
            messages.success(request, f'Drill hole {hole.hole_id} created successfully.')
            return redirect('core:drill_hole_detail', pk=hole.pk)
    else:
        form = DrillHoleForm()
        formset = LithologyIntervalFormSet()

    return render(request, 'core/drill_hole_form.html', {
        'form': form,
        'formset': formset,
        'action': 'Create',
    })


@login_required
def drill_hole_detail(request, pk):
    """Strip-log view for a single drill hole."""
    hole = get_object_or_404(DrillHole.objects.select_related('client', 'created_by'), pk=pk)
    intervals = hole.lithology_intervals.order_by('depth_from')

    # Build strip-log data: list of dicts with percentage heights for the SVG bars
    max_depth = float(hole.get_max_logged_depth()) or 1
    strip_log = []
    for interval in intervals:
        depth_from = float(interval.depth_from)
        depth_to = float(interval.depth_to)
        strip_log.append({
            'interval': interval,
            'top_pct': (depth_from / max_depth) * 100,
            'height_pct': max(((depth_to - depth_from) / max_depth) * 100, 0.5),
            'colour': interval.display_colour,
        })

    return render(request, 'core/drill_hole_detail.html', {
        'hole': hole,
        'intervals': intervals,
        'strip_log': strip_log,
        'max_depth': max_depth,
    })


@login_required
def drill_hole_edit(request, pk):
    """Edit an existing drill hole and its lithology intervals."""
    hole = get_object_or_404(DrillHole, pk=pk)
    if request.method == 'POST':
        form = DrillHoleForm(request.POST, instance=hole)
        formset = LithologyIntervalFormSet(request.POST, instance=hole)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, f'Drill hole {hole.hole_id} updated.')
            return redirect('core:drill_hole_detail', pk=hole.pk)
    else:
        form = DrillHoleForm(instance=hole)
        formset = LithologyIntervalFormSet(instance=hole)

    return render(request, 'core/drill_hole_form.html', {
        'form': form,
        'formset': formset,
        'hole': hole,
        'action': 'Edit',
    })


@login_required
def drill_hole_delete(request, pk):
    """Confirm and delete a drill hole."""
    hole = get_object_or_404(DrillHole, pk=pk)
    if request.method == 'POST':
        hole_id = hole.hole_id
        hole.delete()
        messages.success(request, f'Drill hole {hole_id} deleted.')
        return redirect('core:drill_hole_list')
    return render(request, 'core/drill_hole_confirm_delete.html', {'hole': hole})


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 – 2D Map
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def geology_map(request):
    """Render the Leaflet.js map page."""
    clients = Client.objects.filter(is_active=True).order_by('name')
    filter_client_id = request.GET.get('client_id', '')
    return render(request, 'core/geology_map.html', {
        'clients': clients,
        'filter_client_id': filter_client_id,
    })


@login_required
@require_GET
def geology_map_data(request):
    """
    JSON endpoint returning drill hole collar locations for the Leaflet map.
    Each feature includes the top lithology colour for the map marker.
    """
    holes = DrillHole.objects.select_related('client').prefetch_related('lithology_intervals')

    filter_client_id = request.GET.get('client_id', '')
    if filter_client_id and filter_client_id.isdigit():
        holes = holes.filter(client_id=int(filter_client_id))

    features = []
    for hole in holes:
        if not hole.has_coordinates():
            continue

        top_interval = hole.lithology_intervals.order_by('depth_from').first()
        marker_colour = top_interval.display_colour if top_interval else '#888888'
        top_litho = top_interval.get_lithology_code_display() if top_interval else 'No log'

        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [float(hole.longitude), float(hole.latitude)],
            },
            'properties': {
                'id': hole.pk,
                'hole_id': hole.hole_id,
                'project': hole.project_name,
                'client': str(hole.client) if hole.client else '',
                'total_depth': float(hole.total_depth) if hole.total_depth else None,
                'elevation': float(hole.elevation) if hole.elevation else None,
                'top_litho': top_litho,
                'marker_colour': marker_colour,
                'detail_url': reverse('core:drill_hole_detail', kwargs={'pk': hole.pk}),
            },
        })

    return JsonResponse({'type': 'FeatureCollection', 'features': features})


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 – Cross Sections
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def cross_section(request):
    """
    Render a vertical cross-section through two or more selected drill holes.

    Query params:
        holes  – comma-separated list of hole PKs (min 2)
    """
    hole_ids_raw = request.GET.get('holes', '')
    selected_ids = [int(x) for x in hole_ids_raw.split(',') if x.strip().isdigit()]

    all_holes = DrillHole.objects.select_related('client').order_by('hole_id')
    selected_holes = []
    section_data = []

    if len(selected_ids) >= 2:
        selected_holes = list(
            DrillHole.objects.filter(pk__in=selected_ids)
            .prefetch_related('lithology_intervals')
        )
        # Preserve order given by the user
        order_map = {pk: idx for idx, pk in enumerate(selected_ids)}
        selected_holes.sort(key=lambda h: order_map.get(h.pk, 999))

        max_depth = max(
            (float(h.get_max_logged_depth()) for h in selected_holes),
            default=1,
        ) or 1

        for hole in selected_holes:
            intervals = list(hole.lithology_intervals.order_by('depth_from'))
            bars = []
            for iv in intervals:
                d_from = float(iv.depth_from)
                d_to = float(iv.depth_to)
                bars.append({
                    'depth_from': d_from,
                    'depth_to': d_to,
                    'height_pct': max(((d_to - d_from) / max_depth) * 100, 0.5),
                    'top_pct': (d_from / max_depth) * 100,
                    'colour': iv.display_colour,
                    'label': iv.get_lithology_code_display(),
                    'description': iv.description,
                })
            section_data.append({
                'hole': hole,
                'bars': bars,
                'max_depth': max_depth,
            })

    # Build depth axis ticks: 11 evenly-spaced labels (0 %, 10 %, …, 100 %)
    if section_data:
        axis_max = section_data[0]['max_depth']
        depth_axis_ticks = [
            {'pct': pct, 'depth': round((pct / 100) * axis_max, 1)}
            for pct in range(0, 101, 10)
        ]
    else:
        depth_axis_ticks = []

    return render(request, 'core/cross_section.html', {
        'all_holes': all_holes,
        'selected_holes': selected_holes,
        'selected_ids': selected_ids,
        'section_data': section_data,
        'hole_ids_raw': hole_ids_raw,
        'depth_axis_ticks': depth_axis_ticks,
    })
