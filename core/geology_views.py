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

from .forms import (
    DrillHoleForm,
    LithologyIntervalFormSet,
    DrillHoleSurveyStationFormSet,
    LithologyQARequestForm,
    LithologyQAReviewForm,
    LithologyQACommentForm,
)
from .models import (
    Client,
    DrillHole,
    LithologyInterval,
    CoordinateSuggestion,
    LithologyQARequest,
    LithologyQAComment,
)


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


@login_required
def drill_hole_survey_edit(request, pk):
    """Edit survey stations used for curved 3D hole-path calculations."""
    hole = get_object_or_404(DrillHole, pk=pk)

    if request.method == 'POST':
        formset = DrillHoleSurveyStationFormSet(request.POST, instance=hole)
        if formset.is_valid():
            formset.save()
            messages.success(request, f'Survey stations updated for {hole.hole_id}.')
            return redirect('core:drill_hole_path_3d', pk=hole.pk)
    else:
        formset = DrillHoleSurveyStationFormSet(instance=hole)

    return render(request, 'core/drill_hole_survey_form.html', {
        'hole': hole,
        'formset': formset,
    })


@login_required
def drill_hole_path_3d(request, pk):
    """Interactive 3D trajectory page for a single drill hole."""
    hole = get_object_or_404(DrillHole.objects.select_related('client'), pk=pk)
    stations = hole.survey_stations.order_by('measured_depth')
    path_points = hole.calculate_path_points()
    survey_warnings = hole.get_survey_quality_warnings()

    return render(request, 'core/drill_hole_path_3d.html', {
        'hole': hole,
        'stations': stations,
        'path_points': path_points,
        'survey_warnings': survey_warnings,
    })


@login_required
@require_GET
def drill_hole_path_data(request, pk):
    """JSON endpoint returning 3D path points for Plotly rendering."""
    hole = get_object_or_404(DrillHole, pk=pk)
    return JsonResponse({
        'hole_id': hole.hole_id,
        'points': hole.calculate_path_points(),
        'warnings': hole.get_survey_quality_warnings(),
    })


@login_required
def drill_hole_paths_3d(request):
    """Interactive multi-hole 3D trajectory comparison."""
    hole_ids_raw = request.GET.get('holes', '')
    selected_ids = [int(x) for x in hole_ids_raw.split(',') if x.strip().isdigit()]

    all_holes = DrillHole.objects.select_related('client').order_by('hole_id')
    filter_client_id = request.GET.get('client_id', '')
    filter_project = request.GET.get('project', '')

    if filter_client_id and filter_client_id.isdigit():
        all_holes = all_holes.filter(client_id=int(filter_client_id))
    if filter_project:
        all_holes = all_holes.filter(project_name__icontains=filter_project)

    selected_holes = []
    traces = []
    warning_rows = []

    if selected_ids:
        selected_holes = list(
            DrillHole.objects.filter(pk__in=selected_ids).select_related('client').prefetch_related('survey_stations')
        )
        order_map = {pk: idx for idx, pk in enumerate(selected_ids)}
        selected_holes.sort(key=lambda h: order_map.get(h.pk, 999))

        for hole in selected_holes:
            points = hole.calculate_path_points()
            if not points:
                continue
            traces.append({
                'hole_id': hole.hole_id,
                'pk': hole.pk,
                'x': [p['x'] for p in points],
                'y': [p['y'] for p in points],
                'z': [p['z'] for p in points],
                'md': [p['measured_depth'] for p in points],
            })
            warning_rows.append({
                'hole': hole,
                'warnings': hole.get_survey_quality_warnings(),
            })

    clients = Client.objects.filter(is_active=True).order_by('name')

    return render(request, 'core/drill_hole_paths_3d.html', {
        'all_holes': all_holes,
        'clients': clients,
        'filter_client_id': filter_client_id,
        'filter_project': filter_project,
        'selected_holes': selected_holes,
        'selected_ids': selected_ids,
        'hole_ids_raw': hole_ids_raw,
        'traces_json': json.dumps(traces),
        'warning_rows': warning_rows,
    })


@login_required
@require_GET
def drill_hole_paths_3d_export(request):
    """Export multi-hole 3D comparison as Plotly HTML file."""
    from django.http import HttpResponse
    from datetime import datetime
    
    hole_ids_raw = request.GET.get('holes', '')
    selected_ids = [int(x) for x in hole_ids_raw.split(',') if x.strip().isdigit()]

    if not selected_ids:
        return JsonResponse({'error': 'No holes selected'}, status=400)

    selected_holes = list(
        DrillHole.objects.filter(pk__in=selected_ids)
        .select_related('client')
        .prefetch_related('survey_stations')
    )
    order_map = {pk: idx for idx, pk in enumerate(selected_ids)}
    selected_holes.sort(key=lambda h: order_map.get(h.pk, 999))

    traces = []
    for hole in selected_holes:
        points = hole.calculate_path_points()
        if not points:
            continue
        traces.append({
            'hole_id': hole.hole_id,
            'x': [p['x'] for p in points],
            'y': [p['y'] for p in points],
            'z': [p['z'] for p in points],
            'md': [p['measured_depth'] for p in points],
        })

    if not traces:
        return JsonResponse({'error': 'No valid trajectories found'}, status=400)

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>3D Drill Hole Trajectory Comparison</title>
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        #plot {{ height: 80vh; }}
        .metadata {{ background: #f5f5f5; padding: 10px; border-radius: 4px; margin-bottom: 20px; }}
        .metadata p {{ margin: 5px 0; }}
    </style>
</head>
<body>
    <h1>3D Drill Hole Trajectory Comparison</h1>
    <div class="metadata">
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
        <p><strong>Holes:</strong> {', '.join([h.hole_id for h in selected_holes])}</p>
        <p><strong>Total Traces:</strong> {len(traces)}</p>
    </div>
    <div id="plot"></div>
    <script>
        const tracesPayload = {json.dumps(traces)};
        const traces = tracesPayload.map((item) => ({{
            x: item.x,
            y: item.y,
            z: item.z,
            text: item.md,
            type: 'scatter3d',
            mode: 'lines',
            line: {{ width: 7 }},
            name: item.hole_id,
            hovertemplate: `${{item.hole_id}}<br>MD: %{{text}} m<br>X: %{{x:.2f}}<br>Y: %{{y:.2f}}<br>Z: %{{z:.2f}}<extra></extra>`,
        }}));
        Plotly.newPlot('plot', traces, {{
            margin: {{ l: 0, r: 0, t: 40, b: 0 }},
            title: '3D Trajectory Comparison',
            paper_bgcolor: '#ffffff',
            scene: {{
                xaxis: {{ title: 'Easting (m)' }},
                yaxis: {{ title: 'Northing (m)' }},
                zaxis: {{ title: 'Elevation (m)' }},
                aspectmode: 'data',
            }},
            legend: {{ orientation: 'h' }},
        }}, {{ responsive: true, displaylogo: false }});
    </script>
</body>
</html>"""

    filename = f"3d-comparison-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html"
    response = HttpResponse(html_content, content_type='text/html;charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


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


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 – Client Read-Only Geo Views
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def client_drill_hole_list(request):
    """List drill holes for the logged-in client (read-only)."""
    from .views import _is_client_user
    if not _is_client_user(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Client view only.")
    
    client_profile = getattr(request.user, 'client_profile', None)
    if not client_profile:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("No client profile linked.")
    
    holes = DrillHole.objects.filter(
        client=client_profile
    ).select_related('client').prefetch_related('lithology_intervals').order_by('hole_id')
    
    return render(request, 'core/client_drill_hole_list.html', {
        'holes': holes,
        'client': client_profile,
    })


@login_required
def client_drill_hole_detail(request, pk):
    """Client read-only view of a drill hole strip-log."""
    from .views import _is_client_user
    if not _is_client_user(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Client view only.")
    
    client_profile = getattr(request.user, 'client_profile', None)
    if not client_profile:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("No client profile linked.")
    
    hole = get_object_or_404(DrillHole.objects.select_related('client', 'created_by'), pk=pk, client=client_profile)
    intervals = hole.lithology_intervals.order_by('depth_from')

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

    return render(request, 'core/client_drill_hole_detail.html', {
        'hole': hole,
        'intervals': intervals,
        'strip_log': strip_log,
        'max_depth': max_depth,
        'is_client_view': True,
    })


@login_required
def client_geology_map(request):
    """Client read-only map of their drill hole collars."""
    from .views import _is_client_user
    if not _is_client_user(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Client view only.")
    
    client_profile = getattr(request.user, 'client_profile', None)
    if not client_profile:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("No client profile linked.")
    
    holes = DrillHole.objects.filter(client=client_profile).select_related('client').order_by('hole_id')
    
    return render(request, 'core/client_geology_map.html', {
        'holes': holes,
        'client': client_profile,
        'is_client_view': True,
    })


@login_required
@require_GET
def client_geology_map_data(request):
    """JSON endpoint for client geology map (collar coordinates)."""
    from .views import _is_client_user
    if not _is_client_user(request.user):
        return JsonResponse({'error': 'Client view only.'}, status=403)
    
    client_profile = getattr(request.user, 'client_profile', None)
    if not client_profile:
        return JsonResponse({'error': 'No client profile linked.'}, status=403)
    
    holes = DrillHole.objects.filter(client=client_profile).select_related('client').order_by('hole_id')
    
    features = []
    for hole in holes:
        if hole.collar_latitude is not None and hole.collar_longitude is not None:
            features.append({
                'type': 'Feature',
                'geometry': {
                    'type': 'Point',
                    'coordinates': [float(hole.collar_longitude), float(hole.collar_latitude)],
                },
                'properties': {
                    'hole_id': hole.hole_id,
                    'collar_elevation': float(hole.collar_elevation) if hole.collar_elevation else None,
                    'total_depth': float(hole.total_depth) if hole.total_depth else None,
                    'dip': float(hole.dip) if hole.dip else None,
                    'azimuth': float(hole.azimuth) if hole.azimuth else None,
                    'url': reverse('core:client_drill_hole_detail', args=[hole.pk]),
                },
            })
    
    return JsonResponse({
        'type': 'FeatureCollection',
        'features': features,
    })


@login_required
@require_GET
def client_geology_map_export(request):
    """Download client geology map collar points as GeoJSON."""
    from .views import _is_client_user
    if not _is_client_user(request.user):
        return JsonResponse({'error': 'Client view only.'}, status=403)

    client_profile = getattr(request.user, 'client_profile', None)
    if not client_profile:
        return JsonResponse({'error': 'No client profile linked.'}, status=403)

    holes = DrillHole.objects.filter(client=client_profile).select_related('client').order_by('hole_id')

    features = []
    for hole in holes:
        if hole.collar_latitude is not None and hole.collar_longitude is not None:
            features.append({
                'type': 'Feature',
                'geometry': {
                    'type': 'Point',
                    'coordinates': [float(hole.collar_longitude), float(hole.collar_latitude)],
                },
                'properties': {
                    'hole_id': hole.hole_id,
                    'collar_elevation': float(hole.collar_elevation) if hole.collar_elevation else None,
                    'total_depth': float(hole.total_depth) if hole.total_depth else None,
                    'dip': float(hole.dip) if hole.dip else None,
                    'azimuth': float(hole.azimuth) if hole.azimuth else None,
                },
            })

    response = JsonResponse({
        'type': 'FeatureCollection',
        'features': features,
    })
    safe_client_name = client_profile.name.replace(' ', '_')
    response['Content-Disposition'] = f'attachment; filename="collars_{safe_client_name}.geojson"'
    return response


@login_required
def client_drill_hole_paths_3d(request):
    """Client read-only 3D visualization of their drill hole paths."""
    from .views import _is_client_user
    if not _is_client_user(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Client view only.")
    
    client_profile = getattr(request.user, 'client_profile', None)
    if not client_profile:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("No client profile linked.")
    
    holes = DrillHole.objects.filter(client=client_profile).select_related('client').order_by('hole_id')
    
    return render(request, 'core/client_drill_hole_paths_3d.html', {
        'holes': holes,
        'client': client_profile,
        'is_client_view': True,
    })


@login_required
@require_GET
def client_drill_hole_paths_3d_export(request):
    """Export client's drill hole paths as GeoJSON."""
    from .views import _is_client_user
    if not _is_client_user(request.user):
        return JsonResponse({'error': 'Client view only.'}, status=403)
    
    client_profile = getattr(request.user, 'client_profile', None)
    if not client_profile:
        return JsonResponse({'error': 'No client profile linked.'}, status=403)
    
    holes = DrillHole.objects.filter(client=client_profile).prefetch_related('survey_stations').order_by('hole_id')
    
    features = []
    for hole in holes:
        stations = list(hole.survey_stations.order_by('measured_depth'))
        if len(stations) >= 2:
            coords = []
            for station in stations:
                if station.easting is not None and station.northing is not None:
                    coords.append([float(station.easting), float(station.northing), float(station.elevation)])
            
            if coords:
                features.append({
                    'type': 'Feature',
                    'geometry': {
                        'type': 'LineString',
                        'coordinates': coords,
                    },
                    'properties': {
                        'hole_id': hole.hole_id,
                        'total_depth': float(hole.total_depth) if hole.total_depth else None,
                    },
                })
    
    response = JsonResponse({
        'type': 'FeatureCollection',
        'features': features,
    })
    response['Content-Disposition'] = f'attachment; filename="drill_paths_{client_profile.name.replace(" ", "_")}.geojson"'
    return response


@login_required
def client_cross_section(request):
    """Client read-only cross-section view of their drill holes."""
    from .views import _is_client_user
    if not _is_client_user(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Client view only.")
    
    client_profile = getattr(request.user, 'client_profile', None)
    if not client_profile:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("No client profile linked.")
    
    all_holes = DrillHole.objects.filter(client=client_profile).select_related('client').order_by('hole_id')
    
    hole_ids_raw = request.GET.get('holes', '').strip()
    selected_ids = set()
    selected_holes = []
    
    if hole_ids_raw:
        try:
            raw_ids = [int(x.strip()) for x in hole_ids_raw.split(',') if x.strip().isdigit()]
            selected_holes = [hole for hole in all_holes if hole.pk in raw_ids]
            selected_ids = set(raw_ids)
        except (ValueError, TypeError):
            pass
    
    section_data = []
    max_depth = 0
    
    if selected_holes:
        for hole in selected_holes:
            max_depth = max(max_depth, float(hole.get_max_logged_depth() or 1))
    
    if max_depth == 0:
        max_depth = request.GET.get('max_depth', 1)
        if isinstance(max_depth, str):
            try:
                max_depth = float(max_depth)
            except ValueError:
                max_depth = 1
    else:
        max_depth = request.GET.get('max_depth', None) or max_depth
        if isinstance(max_depth, str):
            try:
                max_depth = float(max_depth)
            except ValueError:
                max_depth = 1
    
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
    
    if section_data:
        axis_max = section_data[0]['max_depth']
        depth_axis_ticks = [
            {'pct': pct, 'depth': round((pct / 100) * axis_max, 1)}
            for pct in range(0, 101, 10)
        ]
    else:
        depth_axis_ticks = []
    
    return render(request, 'core/client_cross_section.html', {
        'all_holes': all_holes,
        'selected_holes': selected_holes,
        'selected_ids': selected_ids,
        'section_data': section_data,
        'hole_ids_raw': hole_ids_raw,
        'depth_axis_ticks': depth_axis_ticks,
        'is_client_view': True,
    })


@login_required
@require_GET
def client_cross_section_export(request):
    """Export selected client cross-section data as JSON."""
    from .views import _is_client_user
    if not _is_client_user(request.user):
        return JsonResponse({'error': 'Client view only.'}, status=403)

    client_profile = getattr(request.user, 'client_profile', None)
    if not client_profile:
        return JsonResponse({'error': 'No client profile linked.'}, status=403)

    all_holes = DrillHole.objects.filter(client=client_profile).order_by('hole_id')
    hole_ids_raw = request.GET.get('holes', '').strip()
    if not hole_ids_raw:
        return JsonResponse({'error': 'Please provide hole IDs using ?holes=1,2,3'}, status=400)

    try:
        raw_ids = [int(x.strip()) for x in hole_ids_raw.split(',') if x.strip().isdigit()]
    except (ValueError, TypeError):
        raw_ids = []

    selected_holes = [hole for hole in all_holes if hole.pk in raw_ids]
    if not selected_holes:
        return JsonResponse({'error': 'No matching holes found for requested IDs.'}, status=404)

    max_depth = 0
    for hole in selected_holes:
        max_depth = max(max_depth, float(hole.get_max_logged_depth() or 1))
    if max_depth == 0:
        max_depth = 1

    section_data = []
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
            'hole_id': hole.hole_id,
            'hole_pk': hole.pk,
            'max_depth': max_depth,
            'bars': bars,
        })

    response = JsonResponse({
        'client': client_profile.name,
        'requested_hole_ids': raw_ids,
        'max_depth': max_depth,
        'section_data': section_data,
    })
    safe_client_name = client_profile.name.replace(' ', '_')
    response['Content-Disposition'] = f'attachment; filename="cross_section_{safe_client_name}.json"'
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 – Coordinate Suggestion Workflow (Client QA)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def client_coordinate_suggestion_list(request):
    """List coordinate suggestions for client's drill holes."""
    from .views import _is_client_user
    if not _is_client_user(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Client view only.")
    
    client_profile = getattr(request.user, 'client_profile', None)
    if not client_profile:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("No client profile linked.")
    
    from .models import CoordinateSuggestion
    suggestions = CoordinateSuggestion.objects.filter(
        drill_hole__client=client_profile
    ).select_related('drill_hole', 'suggested_by', 'reviewed_by').order_by('-created_at')
    
    return render(request, 'core/client_coordinate_suggestion_list.html', {
        'suggestions': suggestions,
    })


@login_required
def client_coordinate_suggestion_create(request, hole_pk):
    """Client creates a coordinate suggestion for a drill hole."""
    from .views import _is_client_user
    if not _is_client_user(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Client view only.")
    
    client_profile = getattr(request.user, 'client_profile', None)
    if not client_profile:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("No client profile linked.")
    
    hole = get_object_or_404(DrillHole, pk=hole_pk, client=client_profile)
    
    if request.method == 'POST':
        from .forms import CoordinateSuggestionForm
        form = CoordinateSuggestionForm(request.POST)
        if form.is_valid():
            suggestion = form.save(commit=False)
            suggestion.drill_hole = hole
            suggestion.suggested_by = request.user
            suggestion.save()
            messages.success(request, f'Coordinate suggestion for {hole.hole_id} submitted successfully.')
            return redirect('core:client_coordinate_suggestion_detail', pk=suggestion.pk)
    else:
        from .forms import CoordinateSuggestionForm
        form = CoordinateSuggestionForm(initial={
            'suggested_collar_latitude': hole.collar_latitude,
            'suggested_collar_longitude': hole.collar_longitude,
            'suggested_collar_elevation': hole.collar_elevation,
            'suggested_dip': hole.dip,
            'suggested_azimuth': hole.azimuth,
        })
    
    return render(request, 'core/client_coordinate_suggestion_form.html', {
        'form': form,
        'hole': hole,
    })


@login_required
def client_coordinate_suggestion_detail(request, pk):
    """Client views a coordinate suggestion."""
    from .views import _is_client_user
    if not _is_client_user(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Client view only.")
    
    client_profile = getattr(request.user, 'client_profile', None)
    if not client_profile:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("No client profile linked.")
    
    from .models import CoordinateSuggestion
    suggestion = get_object_or_404(CoordinateSuggestion, pk=pk, drill_hole__client=client_profile)
    
    return render(request, 'core/client_coordinate_suggestion_detail.html', {
        'suggestion': suggestion,
    })


@login_required
def contractor_coordinate_suggestion_list(request):
    """Contractor views coordinate suggestions needing review."""
    from accounts.decorators import _is_client_context
    if _is_client_context(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Contractor view only.")
    
    from .models import CoordinateSuggestion
    suggestions = CoordinateSuggestion.objects.select_related(
        'drill_hole', 'suggested_by', 'reviewed_by'
    ).order_by('-created_at')
    
    # Filter by status if requested
    status_filter = request.GET.get('status', '')
    if status_filter in ['pending', 'approved', 'rejected']:
        suggestions = suggestions.filter(status=status_filter)
    
    return render(request, 'core/contractor_coordinate_suggestion_list.html', {
        'suggestions': suggestions,
        'status_filter': status_filter,
    })


@login_required
def contractor_coordinate_suggestion_review(request, pk):
    """Contractor reviews and approves/rejects a coordinate suggestion."""
    from accounts.decorators import _is_client_context
    if _is_client_context(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Contractor view only.")
    
    from .models import CoordinateSuggestion
    from .forms import CoordinateSuggestionReviewForm
    suggestion = get_object_or_404(CoordinateSuggestion, pk=pk)
    
    if request.method == 'POST':
        form = CoordinateSuggestionReviewForm(request.POST, instance=suggestion)
        decision = request.POST.get('REVIEW_CHOICE', '')
        
        if decision == 'approve':
            suggestion.approve(reviewed_by_user=request.user, apply_changes=True)
            messages.success(request, f'Coordinate suggestion for {suggestion.drill_hole.hole_id} approved and applied.')
            return redirect('core:contractor_coordinate_suggestion_list')
        elif decision == 'reject':
            if not form.is_valid():
                messages.error(request, 'Please provide a rejection reason.')
                return render(request, 'core/contractor_coordinate_suggestion_review.html', {
                    'suggestion': suggestion,
                    'form': form,
                })
            reason = form.cleaned_data.get('rejection_reason', '')
            suggestion.reject(reviewed_by_user=request.user, reason=reason)
            messages.success(request, f'Coordinate suggestion for {suggestion.drill_hole.hole_id} rejected.')
            return redirect('core:contractor_coordinate_suggestion_list')
    else:
        form = CoordinateSuggestionReviewForm()
    
    return render(request, 'core/contractor_coordinate_suggestion_review.html', {
        'suggestion': suggestion,
        'form': form,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 – Lithology QA Workflow (Client/Contractor)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def client_lithology_qa_list(request):
    """List QA requests for client-owned lithology intervals."""
    from .views import _is_client_user
    from django.http import HttpResponseForbidden

    if not _is_client_user(request.user):
        return HttpResponseForbidden('Client view only.')

    client_profile = getattr(request.user, 'client_profile', None)
    if not client_profile:
        return HttpResponseForbidden('No client profile linked.')

    qa_requests = LithologyQARequest.objects.filter(
        interval__drill_hole__client=client_profile
    ).select_related(
        'interval',
        'interval__drill_hole',
        'requested_by',
        'reviewed_by',
    ).order_by('-created_at')

    return render(request, 'core/client_lithology_qa_list.html', {
        'qa_requests': qa_requests,
    })


@login_required
def client_lithology_qa_create(request, interval_pk):
    """Create a QA request for a lithology interval in the client scope."""
    from .views import _is_client_user
    from django.http import HttpResponseForbidden

    if not _is_client_user(request.user):
        return HttpResponseForbidden('Client view only.')

    client_profile = getattr(request.user, 'client_profile', None)
    if not client_profile:
        return HttpResponseForbidden('No client profile linked.')

    interval = get_object_or_404(
        LithologyInterval.objects.select_related('drill_hole'),
        pk=interval_pk,
        drill_hole__client=client_profile,
    )

    if request.method == 'POST':
        form = LithologyQARequestForm(request.POST)
        if form.is_valid():
            qa_request = form.save(commit=False)
            qa_request.interval = interval
            qa_request.requested_by = request.user
            qa_request.save()
            messages.success(request, 'Lithology QA request submitted successfully.')
            return redirect('core:client_lithology_qa_detail', pk=qa_request.pk)
    else:
        form = LithologyQARequestForm()

    return render(request, 'core/client_lithology_qa_form.html', {
        'form': form,
        'interval': interval,
    })


@login_required
def client_lithology_qa_detail(request, pk):
    """View QA request details and comment thread as client."""
    from .views import _is_client_user
    from django.http import HttpResponseForbidden

    if not _is_client_user(request.user):
        return HttpResponseForbidden('Client view only.')

    client_profile = getattr(request.user, 'client_profile', None)
    if not client_profile:
        return HttpResponseForbidden('No client profile linked.')

    qa_request = get_object_or_404(
        LithologyQARequest.objects.select_related(
            'interval',
            'interval__drill_hole',
            'requested_by',
            'reviewed_by',
        ).prefetch_related('comments__author', 'comments__replies__author'),
        pk=pk,
        interval__drill_hole__client=client_profile,
    )

    if request.method == 'POST':
        comment_form = LithologyQACommentForm(request.POST)
        if comment_form.is_valid():
            comment = comment_form.save(commit=False)
            comment.qa_request = qa_request
            comment.author = request.user
            parent_comment_id = request.POST.get('parent_comment_id')
            if parent_comment_id and parent_comment_id.isdigit():
                comment.parent_comment_id = int(parent_comment_id)
            comment.save()
            messages.success(request, 'Comment posted.')
            return redirect('core:client_lithology_qa_detail', pk=qa_request.pk)
    else:
        comment_form = LithologyQACommentForm()

    top_comments = qa_request.comments.filter(parent_comment__isnull=True).select_related('author')
    return render(request, 'core/client_lithology_qa_detail.html', {
        'qa_request': qa_request,
        'comment_form': comment_form,
        'top_comments': top_comments,
    })


@login_required
def contractor_lithology_qa_queue(request):
    """Contractor queue for lithology QA review."""
    from accounts.decorators import _is_client_context
    from django.http import HttpResponseForbidden

    if _is_client_context(request.user):
        return HttpResponseForbidden('Contractor view only.')

    status_filter = request.GET.get('status', '').strip()
    qa_requests = LithologyQARequest.objects.select_related(
        'interval',
        'interval__drill_hole',
        'requested_by',
        'reviewed_by',
    ).order_by('-created_at')
    if status_filter in {
        LithologyQARequest.STATUS_PENDING,
        LithologyQARequest.STATUS_IN_REVIEW,
        LithologyQARequest.STATUS_APPROVED,
        LithologyQARequest.STATUS_REJECTED,
    }:
        qa_requests = qa_requests.filter(status=status_filter)

    return render(request, 'core/contractor_lithology_qa_queue.html', {
        'qa_requests': qa_requests,
        'status_filter': status_filter,
    })


@login_required
def contractor_lithology_qa_review(request, pk):
    """Review and action lithology QA request as contractor."""
    from accounts.decorators import _is_client_context
    from django.http import HttpResponseForbidden

    if _is_client_context(request.user):
        return HttpResponseForbidden('Contractor view only.')

    qa_request = get_object_or_404(
        LithologyQARequest.objects.select_related(
            'interval',
            'interval__drill_hole',
            'requested_by',
            'reviewed_by',
        ).prefetch_related('comments__author', 'comments__replies__author'),
        pk=pk,
    )

    if request.method == 'POST' and request.POST.get('form_action') == 'review':
        review_form = LithologyQAReviewForm(request.POST, instance=qa_request)
        if review_form.is_valid():
            decision = review_form.cleaned_data.get('DECISION')
            response_text = review_form.cleaned_data.get('contractor_response', '')
            if decision == 'approve':
                qa_request.approve(reviewer=request.user, response=response_text)
                messages.success(request, 'QA request approved.')
            elif decision == 'reject':
                qa_request.reject(reviewer=request.user, response=response_text)
                messages.success(request, 'QA request rejected.')
            else:
                qa_request.mark_in_review(reviewer=request.user)
                if response_text:
                    qa_request.contractor_response = response_text
                    qa_request.save(update_fields=['contractor_response'])
                messages.success(request, 'QA request marked as in review.')
            return redirect('core:contractor_lithology_qa_review', pk=qa_request.pk)
    else:
        review_form = LithologyQAReviewForm(instance=qa_request)

    if request.method == 'POST' and request.POST.get('form_action') == 'comment':
        comment_form = LithologyQACommentForm(request.POST)
        if comment_form.is_valid():
            comment = comment_form.save(commit=False)
            comment.qa_request = qa_request
            comment.author = request.user
            parent_comment_id = request.POST.get('parent_comment_id')
            if parent_comment_id and parent_comment_id.isdigit():
                comment.parent_comment_id = int(parent_comment_id)
            comment.save()
            messages.success(request, 'Comment posted.')
            return redirect('core:contractor_lithology_qa_review', pk=qa_request.pk)
    else:
        comment_form = LithologyQACommentForm()

    top_comments = qa_request.comments.filter(parent_comment__isnull=True).select_related('author')
    return render(request, 'core/contractor_lithology_qa_review.html', {
        'qa_request': qa_request,
        'review_form': review_form,
        'comment_form': comment_form,
        'top_comments': top_comments,
    })
