from django.contrib import admin
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Q
from django.utils.text import slugify
from django.utils.crypto import get_random_string
from .models import (
    BOQReport, BOQLineItem, Client, DrillShift, DrillingProgress, ActivityLog, MaterialUsed, 
    ApprovalHistory, Survey, Casing, Workspace, WorkspaceMembership,
    DrillSizePreset, EquipmentPreset, ConsumablePreset, AdditionalChargePreset,
    DrillHole, LithologyInterval, DrillHoleSurveyStation,
)

# Customize admin site
admin.site.site_header = getattr(settings, 'ADMIN_SITE_HEADER', 'Di-VisioN')
admin.site.site_title = getattr(settings, 'ADMIN_SITE_TITLE', 'Di-VisioN Admin')
admin.site.index_title = getattr(settings, 'ADMIN_INDEX_TITLE', 'Daily Shift Report Administration')


# ──────────────────────────────────────────────────────────────────────────────
# Workspace & Membership Administration
# ──────────────────────────────────────────────────────────────────────────────

class WorkspaceMembershipInline(admin.TabularInline):
    model = WorkspaceMembership
    extra = 1
    fields = ('user', 'role', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'workspace_type', 'is_active', 'member_count', 'created_at')
    list_filter = ('workspace_type', 'is_active')
    search_fields = ('name', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [WorkspaceMembershipInline]
    fieldsets = (
        ('Workspace Information', {
            'fields': ('name', 'slug', 'workspace_type', 'description', 'is_active')
        }),
        ('Branding', {
            'fields': ('logo',),
            'description': 'Optional company logo used in exports and UI.',
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',),
        }),
    )
    readonly_fields = ('created_at',)

    def member_count(self, obj):
        return obj.memberships.count()
    member_count.short_description = 'Members'


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'workspace', 'role', 'created_at')
    list_filter = ('workspace', 'role', 'workspace__workspace_type')
    search_fields = ('user__username', 'workspace__name')
    ordering = ('workspace__name', 'user__username')


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_person', 'email', 'phone', 'user', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'contact_person', 'email')
    ordering = ('name',)
    fieldsets = (
        ('Client Information', {
            'fields': ('name', 'contact_person', 'email', 'phone', 'address', 'is_active')
        }),
        ('User Account', {
            'fields': ('user',),
            'description': 'Link to user account for client login. Create a user first, then link here.'
        }),
    )
    fieldsets = (
        ('Company Information', {
            'fields': ('name', 'contact_person', 'email', 'phone', 'address', 'is_active')
        }),
        ('Workspace', {
            'fields': ('workspace',),
            'description': 'Link to a Workspace of type "Client Company". Create the workspace first.',
        }),
        ('User Account', {
            'fields': ('user',),
            'description': 'Link to user account for client login. Create user first in Users section.'
        }),
    )
    # Keep a real dropdown for user selection in admin (instead of raw ID input)
    autocomplete_fields = ()

    actions = ['create_or_reset_client_login']

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.user:
            from accounts.models import UserProfile
            profile, _ = UserProfile.objects.get_or_create(user=obj.user)
            if profile.role != UserProfile.ROLE_CLIENT:
                profile.role = UserProfile.ROLE_CLIENT
                profile.save(update_fields=['role'])

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Show all users in username order for client account linking."""
        if db_field.name == 'user':
            current_user_id = None
            object_id = request.resolver_match.kwargs.get('object_id') if request.resolver_match else None
            if object_id:
                try:
                    current_user_id = Client.objects.only('user_id').get(pk=object_id).user_id
                except Client.DoesNotExist:
                    current_user_id = None
            kwargs['queryset'] = User.objects.filter(
                Q(client_profile__isnull=True) | Q(pk=current_user_id)
            ).order_by('username').distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.action(description="Create/Reset client login and show temporary password")
    def create_or_reset_client_login(self, request, queryset):
        created = 0
        updated = 0
        for client in queryset:
            # Generate a username based on client name
            base_username = slugify(client.name)[:20] or 'client'
            username = base_username
            suffix = 1
            # Find unique username if creating new
            if not client.user:
                while User.objects.filter(username=username).exists():
                    suffix += 1
                    username = f"{base_username}{suffix}"

            # Generate a secure temporary password
            temp_password = get_random_string(12)

            if client.user:
                user = client.user
                user.is_active = True
                user.set_password(temp_password)
                user.save()
                updated += 1
            else:
                user = User.objects.create_user(
                    username=username,
                    email=(client.email or ''),
                    password=temp_password,
                )
                client.user = user
                client.save(update_fields=['user'])
                created += 1

            # Ensure profile exists and is client role
            profile = getattr(user, 'profile', None)
            if profile is None:
                from accounts.models import UserProfile
                profile = UserProfile.objects.create(user=user, role=UserProfile.ROLE_CLIENT)
            else:
                try:
                    from accounts.models import UserProfile
                    if profile.role != UserProfile.ROLE_CLIENT:
                        profile.role = UserProfile.ROLE_CLIENT
                        profile.save(update_fields=['role'])
                except Exception:
                    pass

            # Show credentials (advise password reset)
            messages.info(
                request,
                f"Credentials for {client.name}: username='{user.username}', temporary password='{temp_password}'. "
                "Ask the client to log in and change their password (or use 'Forgot password')."
            )

        if created or updated:
            messages.success(request, f"Client login accounts processed: created {created}, reset {updated}.")
        else:
            messages.warning(request, "No clients selected or no changes made.")


@admin.register(DrillShift)
class DrillShiftAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'shift_type', 'client', 'rig', 'location', 'supervisor_name', 'status', 'client_status', 'is_locked', 'created_at')
    list_filter = ('status', 'client_status', 'shift_type', 'date', 'is_locked', 'client', 'standby_client', 'standby_constructor')
    search_fields = ('rig', 'location', 'created_by__username', 'supervisor_name', 'driller_name')
    readonly_fields = ('created_at', 'updated_at', 'submitted_to_client_at', 'client_approved_at')
    fieldsets = (
        ('Basic Information', {
            'fields': ('date', 'shift_type', 'client', 'contractor_workspace', 'rig', 'location')
        }),
        ('Staff', {
            'fields': ('created_by', 'supervisor_name', 'driller_name', 'helper1_name', 'helper2_name', 'helper3_name', 'helper4_name')
        }),
        ('Time', {
            'fields': ('start_time', 'end_time')
        }),
        ('Standby Information', {
            'fields': (
                'standby_client', 'standby_client_reason', 'standby_client_remarks',
                'standby_constructor', 'standby_constructor_reason', 'standby_constructor_remarks'
            ),
            'classes': ('collapse',)
        }),
        ('Internal Status', {
            'fields': ('status', 'is_locked', 'notes')
        }),
        ('Client Approval', {
            'fields': ('client_status', 'client_comments', 'submitted_to_client_at', 'client_approved_at', 'client_approved_by'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(DrillingProgress)
class DrillingProgressAdmin(admin.ModelAdmin):
    list_display = ('id', 'shift', 'hole_number', 'start_depth', 'end_depth', 'meters_drilled', 'recovery_percentage', 'penetration_rate')
    search_fields = ('shift__id', 'hole_number')
    readonly_fields = ('recovery_percentage', 'penetration_rate')


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'shift', 'activity_type', 'duration_minutes', 'timestamp', 'performed_by')
    list_filter = ('activity_type',)


@admin.register(MaterialUsed)
class MaterialUsedAdmin(admin.ModelAdmin):
    list_display = ('id', 'shift', 'material_name', 'quantity', 'unit')


@admin.register(Survey)
class SurveyAdmin(admin.ModelAdmin):
    list_display = ('id', 'shift', 'survey_type', 'depth', 'dip_angle', 'azimuth', 'surveyor_name', 'survey_time')
    list_filter = ('survey_type', 'survey_time')
    search_fields = ('shift__id', 'surveyor_name')
    ordering = ('-survey_time',)


@admin.register(Casing)
class CasingAdmin(admin.ModelAdmin):
    list_display = ('id', 'shift', 'casing_size', 'casing_type', 'start_depth', 'end_depth', 'length', 'installed_at')
    list_filter = ('casing_size', 'casing_type', 'installed_at')
    search_fields = ('shift__id',)
    ordering = ('-installed_at',)


@admin.register(ApprovalHistory)
class ApprovalHistoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'shift', 'approver', 'role', 'decision', 'timestamp')
    list_filter = ('decision',)


class BOQLineItemInline(admin.TabularInline):
    model = BOQLineItem
    extra = 1
    fields = ('item_type', 'item_name', 'quantity', 'unit', 'locked_rate', 'total_amount', 'notes')
    readonly_fields = ('total_amount',)


@admin.register(BOQReport)
class BOQReportAdmin(admin.ModelAdmin):
    list_display = ('title', 'client', 'period_start', 'period_end', 'status', 'client_status', 'created_by', 'submitted_to_client_at')
    list_filter = ('status', 'client_status', 'client', 'period_start', 'period_end')
    search_fields = ('title', 'client__name', 'created_by__username')
    ordering = ('-period_end', '-created_at')
    inlines = [BOQLineItemInline]


@admin.register(BOQLineItem)
class BOQLineItemAdmin(admin.ModelAdmin):
    list_display = ('boq_report', 'item_type', 'item_name', 'quantity', 'unit', 'locked_rate', 'total_amount')
    list_filter = ('item_type', 'boq_report__client')
    search_fields = ('item_name', 'boq_report__title')
    readonly_fields = ('total_amount',)


# ──────────────────────────────────────────────────────────────────────────────
# Preset Administration (Drill Sizes, Equipment, Consumables)
# ──────────────────────────────────────────────────────────────────────────────

@admin.register(DrillSizePreset)
class DrillSizePresetAdmin(admin.ModelAdmin):
    list_display = ('name', 'contractor_workspace', 'submitted_to_client', 'rate_per_meter', 'status', 'client_status', 'created_at')
    list_filter = ('status', 'client_status', 'contractor_workspace', 'submitted_to_client')
    search_fields = ('name', 'contractor_workspace__name', 'submitted_to_client__name')
    readonly_fields = ('created_at', 'updated_at', 'submitted_to_client_at', 'client_approved_at')
    fieldsets = (
        ('Preset Information', {
            'fields': ('name', 'rate_per_meter', 'contractor_workspace')
        }),
        ('Submission & Approval', {
            'fields': ('status', 'submitted_to_client', 'submitted_to_client_at', 
                      'client_status', 'client_approved_at', 'client_approved_by', 'client_comments')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    ordering = ('-created_at',)


@admin.register(EquipmentPreset)
class EquipmentPresetAdmin(admin.ModelAdmin):
    list_display = ('name', 'contractor_workspace', 'submitted_to_client', 'period', 'rate', 'status', 'client_status', 'created_at')
    list_filter = ('status', 'client_status', 'period', 'contractor_workspace', 'submitted_to_client')
    search_fields = ('name', 'contractor_workspace__name', 'submitted_to_client__name')
    readonly_fields = ('created_at', 'updated_at', 'submitted_to_client_at', 'client_approved_at')
    fieldsets = (
        ('Preset Information', {
            'fields': ('name', 'rate', 'period', 'contractor_workspace')
        }),
        ('Submission & Approval', {
            'fields': ('status', 'submitted_to_client', 'submitted_to_client_at',
                      'client_status', 'client_approved_at', 'client_approved_by', 'client_comments')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    ordering = ('-created_at',)


@admin.register(ConsumablePreset)
class ConsumablePresetAdmin(admin.ModelAdmin):
    list_display = ('name', 'contractor_workspace', 'submitted_to_client', 'unit', 'rate', 'status', 'client_status', 'created_at')
    list_filter = ('status', 'client_status', 'contractor_workspace', 'submitted_to_client')
    search_fields = ('name', 'contractor_workspace__name', 'submitted_to_client__name')
    readonly_fields = ('created_at', 'updated_at', 'submitted_to_client_at', 'client_approved_at')
    fieldsets = (
        ('Preset Information', {
            'fields': ('name', 'rate', 'unit', 'contractor_workspace')
        }),
        ('Submission & Approval', {
            'fields': ('status', 'submitted_to_client', 'submitted_to_client_at',
                      'client_status', 'client_approved_at', 'client_approved_by', 'client_comments')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    ordering = ('-created_at',)


@admin.register(AdditionalChargePreset)
class AdditionalChargePresetAdmin(admin.ModelAdmin):
    list_display = ('name', 'workspace', 'charge_type', 'submitted_to_client', 'unit', 'rate', 'status', 'client_status', 'created_at')
    list_filter = ('status', 'client_status', 'workspace', 'submitted_to_client', 'charge_type')
    search_fields = ('name', 'workspace__name', 'submitted_to_client__name')
    readonly_fields = ('created_at', 'updated_at', 'submitted_to_client_at', 'client_approved_at')
    fieldsets = (
        ('Preset Information', {
            'fields': ('name', 'rate', 'unit', 'charge_type', 'workspace')
        }),
        ('Submission & Approval', {
            'fields': ('status', 'submitted_to_client', 'submitted_to_client_at',
                      'client_status', 'client_approved_at', 'client_approved_by', 'client_comments')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    ordering = ('-created_at',)



# ──────────────────────────────────────────────────────────────────────────────
# Geology Administration
# ──────────────────────────────────────────────────────────────────────────────

class LithologyIntervalInline(admin.TabularInline):
    model = LithologyInterval
    extra = 1
    fields = ('depth_from', 'depth_to', 'lithology_code', 'description', 'hardness', 'weathering', 'recovery_pct')
    ordering = ('depth_from',)


class DrillHoleSurveyStationInline(admin.TabularInline):
    model = DrillHoleSurveyStation
    extra = 1
    fields = ('measured_depth', 'dip', 'azimuth')
    ordering = ('measured_depth',)


@admin.register(DrillHole)
class DrillHoleAdmin(admin.ModelAdmin):
    list_display = ('hole_id', 'client', 'project_name', 'latitude', 'longitude', 'total_depth', 'drilled_date', 'created_by', 'created_at')
    list_filter = ('client', 'drilled_date')
    search_fields = ('hole_id', 'project_name', 'location_description')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [LithologyIntervalInline, DrillHoleSurveyStationInline]
    fieldsets = (
        ('Hole Identification', {
            'fields': ('hole_id', 'client', 'project_name', 'location_description', 'drilled_date')
        }),
        ('GPS Coordinates', {
            'fields': ('latitude', 'longitude', 'elevation')
        }),
        ('Local Grid', {
            'fields': ('easting', 'northing'),
            'classes': ('collapse',),
        }),
        ('Hole Geometry', {
            'fields': ('total_depth', 'dip', 'azimuth')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


@admin.register(LithologyInterval)
class LithologyIntervalAdmin(admin.ModelAdmin):
    list_display = ('drill_hole', 'depth_from', 'depth_to', 'lithology_code', 'hardness', 'weathering', 'recovery_pct')
    list_filter = ('lithology_code', 'hardness', 'weathering', 'drill_hole__client')
    search_fields = ('drill_hole__hole_id', 'description')
    ordering = ('drill_hole__hole_id', 'depth_from')


@admin.register(DrillHoleSurveyStation)
class DrillHoleSurveyStationAdmin(admin.ModelAdmin):
    list_display = ('drill_hole', 'measured_depth', 'dip', 'azimuth', 'created_at')
    list_filter = ('drill_hole__client',)
    search_fields = ('drill_hole__hole_id',)
    ordering = ('drill_hole__hole_id', 'measured_depth')
