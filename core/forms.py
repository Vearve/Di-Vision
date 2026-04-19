from django import forms
from django.forms import inlineformset_factory
from .models import (
    BOQReport, BOQAdditionalCharge, DrillShift, DrillingProgress, ActivityLog, MaterialUsed, Survey, Casing, 
    WorkspaceMembership, Workspace, DrillSizePreset, EquipmentPreset, ConsumablePreset, AdditionalChargePreset,
    DrillHole, LithologyInterval, DrillHoleSurveyStation,
)


class DrillShiftForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        if user:
            client_profile = getattr(user, 'client_profile', None)
            if client_profile and 'client' in self.fields:
                self.fields['client'].queryset = client_profile.__class__.objects.filter(pk=client_profile.pk)
                self.fields['client'].initial = client_profile
            elif 'client' in self.fields:
                self.fields['client'].queryset = self.fields['client'].queryset.filter(is_active=True)

            try:
                contractor_ws = WorkspaceMembership.objects.filter(
                    user=user,
                    workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
                ).first()
                if contractor_ws and 'contractor_workspace' in self.fields:
                    self.fields['contractor_workspace'].initial = contractor_ws.workspace
                    self.fields['contractor_workspace'].queryset = Workspace.objects.filter(pk=contractor_ws.workspace.pk)
            except Exception:
                pass

        if 'shift_type' in self.fields:
            self.fields['shift_type'].required = False
            self.fields['shift_type'].initial = DrillShift.SHIFT_DAY

    class Meta:
        model = DrillShift
        fields = ['date', 'shift_type', 'client', 'contractor_workspace', 'rig', 'location',
                  'supervisor_name', 'driller_name', 'helper1_name', 'helper2_name', 'helper3_name', 'helper4_name',
                  'start_time', 'end_time', 'notes',
                  'standby_client', 'standby_client_reason', 'standby_client_remarks', 'standby_client_start_time', 'standby_client_end_time',
                  'standby_constructor', 'standby_constructor_reason', 'standby_constructor_remarks', 'standby_constructor_start_time', 'standby_constructor_end_time']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
            'standby_client_remarks': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Additional details about client standby'}),
            'standby_client_start_time': forms.TimeInput(attrs={'type': 'time'}),
            'standby_client_end_time': forms.TimeInput(attrs={'type': 'time'}),
            'standby_constructor_remarks': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Additional details about constructor standby'}),
            'standby_constructor_start_time': forms.TimeInput(attrs={'type': 'time'}),
            'standby_constructor_end_time': forms.TimeInput(attrs={'type': 'time'}),
        }


class DrillingProgressForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        if 'hole_number' in self.fields:
            hole_choices = [('', 'Select hole')]
            client_profile = getattr(user, 'client_profile', None) if user else None

            if client_profile:
                holes_qs = DrillHole.objects.filter(client=client_profile).order_by('hole_id')
            else:
                holes_qs = DrillHole.objects.all().order_by('hole_id')

            hole_choices.extend((hole.hole_id, hole.hole_id) for hole in holes_qs)

            # Keep existing value visible for legacy rows even if not in current queryset.
            current_hole = self.initial.get('hole_number') or getattr(self.instance, 'hole_number', '')
            if current_hole and all(value != current_hole for value, _label in hole_choices):
                hole_choices.append((current_hole, f"{current_hole} (legacy)"))

            self.fields['hole_number'] = forms.ChoiceField(
                choices=hole_choices,
                required=False,
                label='Hole Number',
            )

        if user is not None:
            try:
                contractor_ws = WorkspaceMembership.objects.filter(
                    user=user,
                    workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
                ).first()
                if contractor_ws:
                    approved_size_presets = DrillSizePreset.objects.filter(
                        contractor_workspace=contractor_ws.workspace,
                        client_status=DrillSizePreset.CLIENT_APPROVED
                    ).order_by('name')
                    if approved_size_presets.exists() and 'size' in self.fields:
                        choices = [('', 'Select bit size')] + [(preset.name, preset.name) for preset in approved_size_presets]
                        self.fields['size'].choices = choices
            except Exception:
                pass

        if 'size' in self.fields:
            self.fields['size'].required = False
            self.fields['size'].initial = 'HQ'

        for optional_field in ['core_loss', 'core_gain']:
            if optional_field in self.fields:
                self.fields[optional_field].required = False

    def save(self, commit=True):
        instance = super().save(commit=False)
        hole_id = self.cleaned_data.get('hole_number') or ''
        if hole_id:
            try:
                instance.drill_hole = DrillHole.objects.get(hole_id=hole_id)
            except DrillHole.DoesNotExist:
                instance.drill_hole = None
        else:
            instance.drill_hole = None
        if commit:
            instance.save()
        return instance

    class Meta:
        model = DrillingProgress
        fields = ['hole_number', 'size', 'start_depth', 'end_depth', 'meters_drilled',
                  'core_loss', 'core_gain', 'start_time', 'end_time', 'core_tray_image', 'remarks']
        widgets = {
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
        }


class ActivityLogForm(forms.ModelForm):
    class Meta:
        model = ActivityLog
        fields = ['activity_type', 'description', 'duration_minutes']


class MaterialUsedForm(forms.ModelForm):
    class Meta:
        model = MaterialUsed
        fields = ['material_name', 'quantity', 'unit', 'remarks']
        widgets = {
            'unit': forms.TextInput(attrs={'style': 'min-width: 100px;', 'placeholder': 'e.g., litres, bags, kg'}),
        }


class SurveyForm(forms.ModelForm):
    class Meta:
        model = Survey
        fields = ['survey_type', 'depth', 'dip_angle', 'azimuth', 'findings', 'surveyor_name']
        widgets = {
            'surveyor_name': forms.TextInput(attrs={'placeholder': 'Surveyor name'}),
        }


class CasingForm(forms.ModelForm):
    class Meta:
        model = Casing
        fields = ['casing_size', 'casing_type', 'start_depth', 'end_depth', 'length', 'remarks']
        widgets = {
            'remarks': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Installation notes'}),
        }


class BOQReportForm(forms.ModelForm):
    """
    Form for creating/editing BOQ Reports with preset selection.
    """
    drill_size_presets = forms.ModelMultipleChoiceField(
        queryset=DrillSizePreset.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Select approved drill size presets to include in this BOQ"
    )
    equipment_presets = forms.ModelMultipleChoiceField(
        queryset=EquipmentPreset.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Select approved equipment presets to include in this BOQ"
    )
    consumable_presets = forms.ModelMultipleChoiceField(
        queryset=ConsumablePreset.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Select approved consumable presets to include in this BOQ"
    )
    additional_charge_presets = forms.ModelMultipleChoiceField(
        queryset=AdditionalChargePreset.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Select approved contractor charges (+) and client deductions (-) to include in this BOQ"
    )
    
    def __init__(self, *args, client=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Filter presets to only approved ones for the selected client
        if client:
            self.fields['drill_size_presets'].queryset = DrillSizePreset.objects.filter(
                submitted_to_client=client,
                client_status=DrillSizePreset.CLIENT_APPROVED
            ).order_by('name')
            self.fields['equipment_presets'].queryset = EquipmentPreset.objects.filter(
                submitted_to_client=client,
                client_status=EquipmentPreset.CLIENT_APPROVED
            ).order_by('name')
            self.fields['consumable_presets'].queryset = ConsumablePreset.objects.filter(
                submitted_to_client=client,
                client_status=ConsumablePreset.CLIENT_APPROVED
            ).order_by('name')
            # Additional charge presets: both contractor charges and client deductions
            contractor_charges = AdditionalChargePreset.objects.filter(
                submitted_to_client=client,
                client_status=AdditionalChargePreset.CLIENT_APPROVED,
                charge_type=AdditionalChargePreset.CHARGE_TYPE_CHARGE
            )
            client_deductions = AdditionalChargePreset.objects.filter(
                workspace=client.workspace,
                charge_type=AdditionalChargePreset.CHARGE_TYPE_DEDUCTION
            ) if client.workspace else AdditionalChargePreset.objects.none()
            self.fields['additional_charge_presets'].queryset = (contractor_charges | client_deductions).order_by('charge_type', 'name')
        else:
            # When no client is selected, show all approved presets so user can see the fields exist
            self.fields['drill_size_presets'].queryset = DrillSizePreset.objects.filter(
                client_status=DrillSizePreset.CLIENT_APPROVED
            ).order_by('name')
            self.fields['equipment_presets'].queryset = EquipmentPreset.objects.filter(
                client_status=EquipmentPreset.CLIENT_APPROVED
            ).order_by('name')
            self.fields['consumable_presets'].queryset = ConsumablePreset.objects.filter(
                client_status=ConsumablePreset.CLIENT_APPROVED
            ).order_by('name')
            # Additional charge presets: show all approved charges and all deductions
            contractor_charges = AdditionalChargePreset.objects.filter(
                client_status=AdditionalChargePreset.CLIENT_APPROVED,
                charge_type=AdditionalChargePreset.CHARGE_TYPE_CHARGE
            )
            client_deductions = AdditionalChargePreset.objects.filter(
                charge_type=AdditionalChargePreset.CHARGE_TYPE_DEDUCTION
            )
            self.fields['additional_charge_presets'].queryset = (contractor_charges | client_deductions).order_by('charge_type', 'name')
    
    class Meta:
        model = BOQReport
        fields = ['title', 'client', 'period_start', 'period_end', 'contractor_comments']
        widgets = {
            'period_start': forms.DateInput(attrs={'type': 'date'}),
            'period_end': forms.DateInput(attrs={'type': 'date'}),
            'contractor_comments': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional notes to accompany this BOQ draft'}),
        }


class BOQAdditionalChargeForm(forms.ModelForm):
    class Meta:
        model = BOQAdditionalCharge
        fields = ['description', 'amount']
        widgets = {
            'description': forms.TextInput(attrs={'placeholder': 'e.g., Rig relocation fee'}),
            'amount': forms.NumberInput(attrs={'step': '0.01'}),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Preset Forms (Drill Sizes, Equipment, Consumables)
# ──────────────────────────────────────────────────────────────────────────────

class DrillSizePresetForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and not user.is_superuser:
            # Filter to user's contractor workspace
            try:
                contractor_ws = WorkspaceMembership.objects.filter(
                    user=user,
                    workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
                ).first()
                if contractor_ws:
                    self.fields['contractor_workspace'].queryset = Workspace.objects.filter(pk=contractor_ws.workspace.pk)
                    self.fields['contractor_workspace'].initial = contractor_ws.workspace
            except Exception:
                pass

    class Meta:
        model = DrillSizePreset
        fields = ['name', 'rate_per_meter']
        widgets = {
            'rate_per_meter': forms.NumberInput(attrs={'step': '0.01', 'placeholder': 'Rate per meter'}),
        }


class EquipmentPresetForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and not user.is_superuser:
            try:
                contractor_ws = WorkspaceMembership.objects.filter(
                    user=user,
                    workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
                ).first()
                if contractor_ws:
                    self.fields['contractor_workspace'].queryset = Workspace.objects.filter(pk=contractor_ws.workspace.pk)
                    self.fields['contractor_workspace'].initial = contractor_ws.workspace
            except Exception:
                pass

    class Meta:
        model = EquipmentPreset
        fields = ['name', 'rate', 'period']
        widgets = {
            'rate': forms.NumberInput(attrs={'step': '0.01', 'placeholder': 'Rate amount'}),
        }


class ConsumablePresetForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and not user.is_superuser:
            try:
                contractor_ws = WorkspaceMembership.objects.filter(
                    user=user,
                    workspace__workspace_type=Workspace.WORKSPACE_CONTRACTOR
                ).first()
                if contractor_ws:
                    self.fields['contractor_workspace'].queryset = Workspace.objects.filter(pk=contractor_ws.workspace.pk)
                    self.fields['contractor_workspace'].initial = contractor_ws.workspace
            except Exception:
                pass

    class Meta:
        model = ConsumablePreset
        fields = ['name', 'rate', 'unit']
        widgets = {
            'rate': forms.NumberInput(attrs={'step': '0.01'}),
            'unit': forms.TextInput(attrs={'placeholder': 'e.g., per unit, per meter'}),
        }


class AdditionalChargePresetForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and not user.is_superuser:
            try:
                # Get user's workspaces (could be contractor or client)
                user_workspaces = WorkspaceMembership.objects.filter(user=user).values_list('workspace', flat=True)
                if user_workspaces:
                    self.fields['workspace'].queryset = Workspace.objects.filter(pk__in=user_workspaces)
                    # Set initial workspace if only one
                    if len(user_workspaces) == 1:
                        self.fields['workspace'].initial = user_workspaces[0]
            except Exception:
                pass

    class Meta:
        model = AdditionalChargePreset
        fields = ['name', 'rate', 'unit', 'charge_type']
        widgets = {
            'rate': forms.NumberInput(attrs={'step': '0.01'}),
            'unit': forms.TextInput(attrs={'placeholder': 'e.g., per unit, per trip, per day'}),
        }


# Create formsets for inline editing
DrillingProgressFormSet = inlineformset_factory(
    DrillShift, DrillingProgress,
    form=DrillingProgressForm,
    extra=1, can_delete=True,
    min_num=0, validate_min=False
)

# Create formsets for inline editing
DrillingProgressFormSet = inlineformset_factory(
    DrillShift, DrillingProgress,
    form=DrillingProgressForm,
    extra=1, can_delete=True,
    min_num=0, validate_min=False
)

ActivityLogFormSet = inlineformset_factory(
    DrillShift, ActivityLog,
    form=ActivityLogForm,
    extra=1, can_delete=True,
    min_num=0, validate_min=False
)

MaterialUsedFormSet = inlineformset_factory(
    DrillShift, MaterialUsed,
    form=MaterialUsedForm,
    extra=1, can_delete=True,
    min_num=0, validate_min=False
)

SurveyFormSet = inlineformset_factory(
    DrillShift, Survey,
    form=SurveyForm,
    extra=1, can_delete=True,
    min_num=0, validate_min=False
)

CasingFormSet = inlineformset_factory(
    DrillShift, Casing,
    form=CasingForm,
    extra=1, can_delete=True,
    min_num=0, validate_min=False
)


# ─────────────────────────────────────────────────────────────────────────────
# Geology Forms
# ─────────────────────────────────────────────────────────────────────────────

class DrillHoleForm(forms.ModelForm):
    class Meta:
        model = DrillHole
        fields = [
            'hole_id', 'client', 'project_name', 'location_description',
            'latitude', 'longitude', 'elevation',
            'easting', 'northing',
            'total_depth', 'dip', 'azimuth',
            'drilled_date', 'notes',
        ]
        widgets = {
            'drilled_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
            'location_description': forms.TextInput(attrs={'placeholder': 'e.g. Northern paddock, 200 m east of bore BH-001'}),
        }


class LithologyIntervalForm(forms.ModelForm):
    class Meta:
        model = LithologyInterval
        fields = [
            'depth_from', 'depth_to', 'lithology_code', 'description',
            'colour', 'hardness', 'weathering', 'recovery_pct', 'notes',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Rock description…'}),
            'notes': forms.Textarea(attrs={'rows': 1}),
            'colour': forms.TextInput(attrs={'type': 'color'}),
        }


LithologyIntervalFormSet = inlineformset_factory(
    DrillHole, LithologyInterval,
    form=LithologyIntervalForm,
    extra=1, can_delete=True,
)


class DrillHoleSurveyStationForm(forms.ModelForm):
    class Meta:
        model = DrillHoleSurveyStation
        fields = ['measured_depth', 'dip', 'azimuth']


DrillHoleSurveyStationFormSet = inlineformset_factory(
    DrillHole,
    DrillHoleSurveyStation,
    form=DrillHoleSurveyStationForm,
    extra=1,
    can_delete=True,
)
