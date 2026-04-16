from django.urls import path
from . import views
from . import preset_views
from . import geology_views

app_name = 'core'

urlpatterns = [
    # Home and Analytics dashboards
    path('', views.home_dashboard, name='home_dashboard'),
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),
    
    # Shift List and CRUD
    path('shifts/', views.shift_list, name='shift_list'),
    path('shifts/create/', views.shift_create, name='shift_create'),
    path('shifts/<int:pk>/', views.shift_detail, name='shift_detail'),
    path('shifts/<int:pk>/edit/', views.shift_update, name='shift_update'),
    
    # Workflow actions
    path('shifts/<int:pk>/submit/', views.shift_submit, name='shift_submit'),
    path('shifts/<int:pk>/approve/', views.shift_approve, name='shift_approve'),
    
    # Client workflow
    path('shifts/<int:pk>/submit-to-client/', views.shift_submit_to_client, name='shift_submit_to_client'),
    path('shifts/<int:pk>/client-approve/', views.client_approve_shift, name='client_approve_shift'),
    path('client-dashboard/', views.client_dashboard, name='client_dashboard'),
    path('boq/', views.boq_report_list, name='boq_report_list'),
    path('boq/create/', views.boq_report_create, name='boq_report_create'),
    path('boq/<int:pk>/', views.boq_report_detail, name='boq_report_detail'),
    path('boq/<int:pk>/export/', views.boq_report_export, name='boq_report_export'),
    path('boq/<int:pk>/additional-charge/add/', views.boq_add_additional_charge, name='boq_add_additional_charge'),
    path('boq/<int:pk>/additional-charge/<int:charge_pk>/action/', views.boq_update_additional_charge, name='boq_update_additional_charge'),
    path('boq/<int:pk>/submit/', views.boq_submit_to_client, name='boq_submit_to_client'),
    path('boq/<int:pk>/review/', views.client_review_boq, name='client_review_boq'),
    
    # Export functionality
    path('export/shifts/', views.export_shifts, name='export_shifts'),
    path('export/boq/', views.export_boq, name='export_boq'),
    path('shifts/<int:pk>/export/pdf/', views.shift_pdf_export, name='shift_pdf_export'),
    
    # ── Client Preset Approval ──────────────────────────────────────────────────
    path('presets/approval/', preset_views.client_preset_approval_dashboard, name='client_preset_approval_dashboard'),
    
    # ── Presets (Unified) ───────────────────────────────────────────────────────
    path('presets/', preset_views.preset_list, name='preset_list'),
    
    # ── Drill Size Presets ──────────────────────────────────────────────────────
    path('presets/drill-size/', preset_views.drill_size_preset_list, name='drill_size_preset_list'),
    path('presets/drill-size/create/', preset_views.drill_size_preset_create, name='drill_size_preset_create'),
    path('presets/drill-size/<int:pk>/', preset_views.drill_size_preset_detail, name='drill_size_preset_detail'),
    path('presets/drill-size/<int:pk>/edit/', preset_views.drill_size_preset_edit, name='drill_size_preset_edit'),
    path('presets/drill-size/<int:pk>/submit/', preset_views.drill_size_preset_submit, name='drill_size_preset_submit'),
    path('presets/drill-size/<int:pk>/approve/', preset_views.drill_size_preset_approve, name='drill_size_preset_approve'),
    
    # ── Equipment Presets ───────────────────────────────────────────────────────
    path('presets/equipment/', preset_views.equipment_preset_list, name='equipment_preset_list'),
    path('presets/equipment/create/', preset_views.equipment_preset_create, name='equipment_preset_create'),
    path('presets/equipment/<int:pk>/', preset_views.equipment_preset_detail, name='equipment_preset_detail'),
    path('presets/equipment/<int:pk>/edit/', preset_views.equipment_preset_edit, name='equipment_preset_edit'),
    path('presets/equipment/<int:pk>/submit/', preset_views.equipment_preset_submit, name='equipment_preset_submit'),
    path('presets/equipment/<int:pk>/approve/', preset_views.equipment_preset_approve, name='equipment_preset_approve'),
    
    # ── Consumable Presets ──────────────────────────────────────────────────────
    path('presets/consumable/', preset_views.consumable_preset_list, name='consumable_preset_list'),
    path('presets/consumable/create/', preset_views.consumable_preset_create, name='consumable_preset_create'),
    path('presets/consumable/<int:pk>/', preset_views.consumable_preset_detail, name='consumable_preset_detail'),
    path('presets/consumable/<int:pk>/edit/', preset_views.consumable_preset_edit, name='consumable_preset_edit'),
    path('presets/consumable/<int:pk>/submit/', preset_views.consumable_preset_submit, name='consumable_preset_submit'),
    path('presets/consumable/<int:pk>/approve/', preset_views.consumable_preset_approve, name='consumable_preset_approve'),
    
    # ── Additional Charge Presets ───────────────────────────────────────────────
    path('presets/additional-charge/', preset_views.additional_charge_preset_list, name='additional_charge_preset_list'),
    path('presets/additional-charge/create/', preset_views.additional_charge_preset_create, name='additional_charge_preset_create'),
    path('presets/additional-charge/<int:pk>/', preset_views.additional_charge_preset_detail, name='additional_charge_preset_detail'),
    path('presets/additional-charge/<int:pk>/edit/', preset_views.additional_charge_preset_edit, name='additional_charge_preset_edit'),
    path('presets/additional-charge/<int:pk>/submit/', preset_views.additional_charge_preset_submit, name='additional_charge_preset_submit'),
    path('presets/additional-charge/<int:pk>/approve/', preset_views.additional_charge_preset_approve, name='additional_charge_preset_approve'),

    # ── Geology / Lithology ─────────────────────────────────────────────────────
    path('geology/holes/', geology_views.drill_hole_list, name='drill_hole_list'),
    path('geology/holes/create/', geology_views.drill_hole_create, name='drill_hole_create'),
    path('geology/holes/<int:pk>/', geology_views.drill_hole_detail, name='drill_hole_detail'),
    path('geology/holes/<int:pk>/edit/', geology_views.drill_hole_edit, name='drill_hole_edit'),
    path('geology/holes/<int:pk>/delete/', geology_views.drill_hole_delete, name='drill_hole_delete'),
    path('geology/holes/<int:pk>/survey/', geology_views.drill_hole_survey_edit, name='drill_hole_survey_edit'),
    path('geology/holes/<int:pk>/path-3d/', geology_views.drill_hole_path_3d, name='drill_hole_path_3d'),
    path('geology/holes/<int:pk>/path-3d/data/', geology_views.drill_hole_path_data, name='drill_hole_path_data'),
    path('geology/paths-3d/', geology_views.drill_hole_paths_3d, name='drill_hole_paths_3d'),
    path('geology/paths-3d/export/', geology_views.drill_hole_paths_3d_export, name='drill_hole_paths_3d_export'),
    path('geology/map/', geology_views.geology_map, name='geology_map'),
    path('geology/map/data/', geology_views.geology_map_data, name='geology_map_data'),
    path('geology/cross-section/', geology_views.cross_section, name='cross_section'),
]
