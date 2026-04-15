from django.db import models
from django.db.models import Sum
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify
from django.core.exceptions import ValidationError
from decimal import Decimal


class Workspace(models.Model):
    """
    Represents a company workspace — either a client company or a contractor company.
    Used for multi-tenant data scoping and branding in exports / UI.
    """
    WORKSPACE_CLIENT = 'client'
    WORKSPACE_CONTRACTOR = 'contractor'
    WORKSPACE_TYPE_CHOICES = [
        (WORKSPACE_CLIENT, 'Client Company'),
        (WORKSPACE_CONTRACTOR, 'Contractor Company'),
    ]

    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    workspace_type = models.CharField(max_length=20, choices=WORKSPACE_TYPE_CHOICES)
    logo = models.ImageField(upload_to='workspace_logos/', blank=True, null=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_workspace_type_display()})"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or 'workspace'
            slug = base
            n = 1
            while Workspace.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)


class WorkspaceMembership(models.Model):
    """
    Links a user to a workspace with a specific role.
    A user can belong to multiple workspaces (e.g. a contractor working for multiple clients).
    """
    ROLE_OWNER = 'owner'
    ROLE_MEMBER = 'member'
    ROLE_VIEWER = 'viewer'
    ROLE_CHOICES = [
        (ROLE_OWNER, 'Owner'),
        (ROLE_MEMBER, 'Member'),
        (ROLE_VIEWER, 'Viewer'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='workspace_memberships',
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [('user', 'workspace')]
        ordering = ['workspace__name', 'role']

    def __str__(self):
        return f"{self.user.username} @ {self.workspace.name} ({self.role})"


class Client(models.Model):
    """
    Client/Company model for tracking different clients.
    
    Attributes:
        name: Client company name
        user: Linked user account for client login
        contact_person: Main contact person
        email: Contact email
        phone: Contact phone number
        address: Client address
        is_active: Whether client is currently active
    """
    name = models.CharField(max_length=255, unique=True)
    workspace = models.OneToOneField(
        Workspace,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='client_link',
        help_text="Linked workspace for this client company",
    )
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='client_profile', help_text="User account for client login")
    contact_person = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        # Prefer workspace name if configured, otherwise fallback to client company name.
        if self.workspace:
            return self.workspace.name

        # If workspace is not set, but client has a user membership, use that workspace name.
        if self.user:
            membership = self.user.workspace_memberships.first()
            if membership and membership.workspace:
                return membership.workspace.name

        return self.name


class DrillShift(models.Model):
    """
    Main model representing a drilling shift/report.
    
    A drill shift contains information about a single shift of drilling operations,
    including basic information, progress data, activities, and materials used.
    Shifts go through a workflow: draft → submitted → approved/rejected.
    
    Attributes:
        created_by: The user who created this shift report
        date: The date of the drilling shift
        rig: Name or identifier of the drilling rig
        location: Location where drilling took place
        start_time: When the shift started
        end_time: When the shift ended
        notes: Additional notes or comments
        status: Current workflow status (draft/submitted/approved/rejected)
        is_locked: Whether the shift is locked for editing
        created_at: Timestamp when the record was created
        updated_at: Timestamp when the record was last updated
    """
    STATUS_DRAFT = 'draft'
    STATUS_SUBMITTED = 'submitted'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SUBMITTED, 'Submitted'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    SHIFT_DAY = 'day'
    SHIFT_NIGHT = 'night'
    
    SHIFT_TYPE_CHOICES = [
        (SHIFT_DAY, 'Day Shift (07:00 - 19:00)'),
        (SHIFT_NIGHT, 'Night Shift (19:00 - 07:00)'),
    ]

    # Client approval status
    CLIENT_PENDING = 'pending_client'
    CLIENT_APPROVED = 'client_approved'
    CLIENT_REJECTED = 'client_rejected'
    
    CLIENT_STATUS_CHOICES = [
        (CLIENT_PENDING, 'Pending Client Approval'),
        (CLIENT_APPROVED, 'Client Approved'),
        (CLIENT_REJECTED, 'Client Rejected'),
    ]

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='shifts')
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='shifts', null=True, blank=True)
    contractor_workspace = models.ForeignKey(
        Workspace,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='contractor_shifts',
        limit_choices_to={'workspace_type': Workspace.WORKSPACE_CONTRACTOR},
        help_text="Contractor company that performed this shift",
    )
    date = models.DateField()
    shift_type = models.CharField(max_length=16, choices=SHIFT_TYPE_CHOICES, default=SHIFT_DAY)
    rig = models.CharField(max_length=128, blank=True)
    location = models.CharField(max_length=255, blank=True)

    # Project / Commercial tracking
    project_code = models.CharField(max_length=64, blank=True, help_text="Internal project or contract code")
    purchase_order_number = models.CharField(max_length=64, blank=True, help_text="Client PO / authorization reference")

    # KPI Targets (optional for off-target calculations)
    target_recovery_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Target recovery percentage for this project")
    target_rop = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Target average rate of penetration (m/hr)")
    target_meters_per_shift = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Target meters drilled per shift")
    
    # Staff information
    supervisor_name = models.CharField(max_length=255, blank=True, help_text="Shift Supervisor")
    driller_name = models.CharField(max_length=255, blank=True, help_text="Driller")
    helper1_name = models.CharField(max_length=255, blank=True, help_text="Helper 1")
    helper2_name = models.CharField(max_length=255, blank=True, help_text="Helper 2")
    helper3_name = models.CharField(max_length=255, blank=True, help_text="Helper 3")
    helper4_name = models.CharField(max_length=255, blank=True, help_text="Helper 4")
    
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)

    # Workflow timestamps
    submitted_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when shift was first submitted")
    manager_approved_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when manager approved shift")
    
    # Standby tracking
    STANDBY_CLIENT_REASONS = [
        ('pad_preparation', 'Pad Preparation'),
        ('order_by_client', 'Order by Client'),
        ('site_access', 'Site Access Issues'),
        ('client_delay', 'Client Delay'),
        ('other_client', 'Other (Client)'),
    ]
    
    STANDBY_CONSTRUCTOR_REASONS = [
        ('mobilizing', 'Mobilizing'),
        ('demobilizing', 'Demobilizing'),
        ('safety_incident', 'Safety Incident'),
        ('equipment_breakdown', 'Equipment Breakdown'),
        ('maintenance', 'Maintenance'),
        ('weather', 'Weather Conditions'),
        ('other_constructor', 'Other (Constructor)'),
    ]
    
    standby_client = models.BooleanField(default=False, help_text="Standby due to client reasons")
    standby_client_reason = models.CharField(max_length=50, choices=STANDBY_CLIENT_REASONS, blank=True)
    standby_client_remarks = models.TextField(blank=True, help_text="Additional details about client standby")
    standby_client_start_time = models.TimeField(null=True, blank=True, help_text="Start time of client standby")
    standby_client_end_time = models.TimeField(null=True, blank=True, help_text="End time of client standby")
    
    standby_constructor = models.BooleanField(default=False, help_text="Standby due to constructor reasons")
    standby_constructor_reason = models.CharField(max_length=50, choices=STANDBY_CONSTRUCTOR_REASONS, blank=True)
    standby_constructor_remarks = models.TextField(blank=True, help_text="Additional details about constructor standby")
    standby_constructor_start_time = models.TimeField(null=True, blank=True, help_text="Start time of constructor standby")
    standby_constructor_end_time = models.TimeField(null=True, blank=True, help_text="End time of constructor standby")
    
    # Client approval fields
    client_status = models.CharField(max_length=32, choices=CLIENT_STATUS_CHOICES, null=True, blank=True, help_text="Client approval status")
    client_comments = models.TextField(blank=True, help_text="Client feedback or rejection reason")
    submitted_to_client_at = models.DateTimeField(null=True, blank=True)
    client_approved_at = models.DateTimeField(null=True, blank=True)
    client_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='client_approvals')
    
    is_locked = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-id']
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['status']),
            models.Index(fields=['project_code']),
        ]

    def __str__(self):
        return f"Shift {self.id} - {self.date} ({self.status})"
    
    def get_total_meters_drilled(self):
        """Calculate total meters drilled from all progress entries."""
        from django.db.models import Sum
        total = self.progress.aggregate(total=Sum('meters_drilled'))['total']
        return total or 0
    
    def get_shift_hours(self):
        """Calculate total shift duration in hours."""
        if self.start_time and self.end_time:
            from datetime import datetime, timedelta
            start = datetime.combine(self.date, self.start_time)
            end = datetime.combine(self.date, self.end_time)
            
            # Handle night shift that crosses midnight
            if end < start:
                end += timedelta(days=1)
            
            duration = end - start
            return duration.total_seconds() / 3600
        return 12  # Default 12 hours for standard shift


class DrillingProgress(models.Model):
    """
    Records drilling progress measurements for a shift.
    
    Tracks the depth measurements and drilling rate for each drilling run
    within a shift. Multiple progress records can be associated with one shift.
    
    Attributes:
        shift: The drill shift this progress belongs to
        hole_number: Hole identifier (e.g., BH-001, Hole-A)
        size: Drill bit size (PQ, HQ, NQ, etc.)
        start_depth: Starting depth in meters
        end_depth: Ending depth in meters
        meters_drilled: Total meters drilled (calculated or entered)
        core_loss: Core loss in meters
        core_gain: Core gain in meters
        recovery_percentage: Auto-calculated core recovery percentage
        penetration_rate: Drilling rate in meters per hour (auto-calculated)
        start_time: When drilling started for this segment
        end_time: When drilling ended for this segment
        remarks: Any observations or notes about this drilling segment
    """
    SIZE_CHOICES = [
        ('PQ', 'PQ (85mm)'),
        ('HQ', 'HQ (63.5mm)'),
        ('NQ', 'NQ (47.6mm)'),
        ('BQ', 'BQ (36.5mm)'),
        ('AQ', 'AQ (27mm)'),
    ]
    
    shift = models.ForeignKey(DrillShift, on_delete=models.CASCADE, related_name='progress')
    hole_number = models.CharField(max_length=50, blank=True, help_text="Hole identifier (e.g., BH-001)")
    size = models.CharField(max_length=10, choices=SIZE_CHOICES, default='HQ', help_text="Drill bit size")
    start_depth = models.DecimalField(max_digits=10, decimal_places=2)
    end_depth = models.DecimalField(max_digits=10, decimal_places=2)
    meters_drilled = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Core recovery fields
    core_loss = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Core loss in meters")
    core_gain = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Core gain in meters")
    recovery_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Auto-calculated")
    
    penetration_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Auto-calculated (m/hr)")
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)
    
    # Core tray image (optional)
    core_tray_image = models.ImageField(upload_to='core_trays/%Y/%m/%d/', blank=True, null=True, help_text="Photo of core tray (optional)")

    class Meta:
        ordering = ['start_depth']

    def save(self, *args, **kwargs):
        """Auto-calculate recovery percentage and penetration rate before saving."""
        # Auto-calc meters_drilled if not provided but depths are available
        try:
            if (self.meters_drilled is None or Decimal(self.meters_drilled) == 0) and \
               self.start_depth is not None and self.end_depth is not None:
                self.meters_drilled = Decimal(self.end_depth) - Decimal(self.start_depth)
        except Exception:
            # If any conversion fails, skip and let validation handle it
            pass
        # Calculate recovery percentage
        if self.meters_drilled and self.meters_drilled > 0:
            recovered_core = float(self.meters_drilled) - float(self.core_loss) + float(self.core_gain)
            self.recovery_percentage = (recovered_core / float(self.meters_drilled)) * 100
        
        # Calculate penetration rate
        if self.start_time and self.end_time and self.meters_drilled:
            from datetime import datetime, timedelta
            start = datetime.combine(datetime.today(), self.start_time)
            end = datetime.combine(datetime.today(), self.end_time)
            
            # Handle times crossing midnight
            if end < start:
                end += timedelta(days=1)
            
            duration_hours = (end - start).total_seconds() / 3600
            if duration_hours > 0:
                self.penetration_rate = float(self.meters_drilled) / duration_hours
        
        super().save(*args, **kwargs)

    def __str__(self):
        hole_info = f"{self.hole_number} - " if self.hole_number else ""
        return f"{hole_info}{self.start_depth} → {self.end_depth} ({self.meters_drilled} m)"


class ActivityLog(models.Model):
    """
    Logs activities and events that occurred during a shift.
    
    Tracks various activities like drilling operations, maintenance work,
    safety meetings, and other events with their duration and descriptions.
    
    Attributes:
        shift: The drill shift this activity belongs to
        timestamp: When the activity occurred
        activity_type: Type of activity (drilling/maintenance/safety/meeting/other)
        description: Detailed description of the activity
        duration_minutes: How long the activity took in minutes
        performed_by: User who performed or logged the activity
    """
    ACTIVITY_CHOICES = [
        ('drilling', 'Drilling'),
        ('maintenance', 'Maintenance'),
        ('safety', 'Safety'),
        ('meeting', 'Meeting'),
        ('hole_conditioning', 'Hole Conditioning'),
        ('trip_rods', 'Trip Rods'),
        ('mobilising', 'Mobilising'),
        ('other', 'Other'),
    ]

    shift = models.ForeignKey(DrillShift, on_delete=models.CASCADE, related_name='activities')
    timestamp = models.DateTimeField(default=timezone.now)
    activity_type = models.CharField(max_length=32, choices=ACTIVITY_CHOICES, default='other')
    description = models.TextField()
    duration_minutes = models.PositiveIntegerField(default=0, help_text="Duration in minutes (required)")
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.activity_type} @ {self.timestamp:%Y-%m-%d %H:%M}"


class MaterialUsed(models.Model):
    """
    Records materials and resources consumed during a shift.
    
    Tracks all materials used during drilling operations, including
    fuel, drilling fluids, cement, and other supplies.
    
    Attributes:
        shift: The drill shift where materials were used
        material_name: Name of the material
        quantity: Amount of material used
        unit: Unit of measurement (liters, kg, bags, etc.)
        remarks: Additional notes about material usage
    """
    shift = models.ForeignKey(DrillShift, on_delete=models.CASCADE, related_name='materials')
    material_name = models.CharField(max_length=128)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit = models.CharField(max_length=32, default='unit')
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ['material_name']

    def __str__(self):
        return f"{self.material_name}: {self.quantity} {self.unit}"


class Survey(models.Model):
    """
    Records downhole/camera survey data for drill holes.
    
    Tracks survey measurements taken during drilling operations including
    orientation, dip angle, and other survey parameters.
    
    Attributes:
        shift: The drill shift when survey was conducted
        progress: Related drilling progress entry
        survey_type: Type of survey (gyro, camera, ongoing, etc.)
        depth: Depth at which survey was taken
        dip_angle: Dip angle in degrees
        azimuth: Azimuth/direction in degrees
        findings: Survey results and observations
        surveyor_name: Name of person conducting survey
        survey_time: When survey was conducted
    """
    SURVEY_TYPE_CHOICES = [
        ('gyro', 'Gyro Survey'),
        ('camera', 'Camera Survey'),
        ('ongoing', 'Ongoing Survey'),
        ('magnetic', 'Magnetic Survey'),
        ('other', 'Other'),
    ]
    
    shift = models.ForeignKey(DrillShift, on_delete=models.CASCADE, related_name='surveys')
    progress = models.ForeignKey(DrillingProgress, on_delete=models.CASCADE, related_name='surveys', null=True, blank=True)
    survey_type = models.CharField(max_length=32, choices=SURVEY_TYPE_CHOICES, default='ongoing')
    depth = models.DecimalField(max_digits=10, decimal_places=2, help_text="Depth in meters")
    dip_angle = models.DecimalField(max_digits=5, decimal_places=2, help_text="Dip angle in degrees")
    azimuth = models.DecimalField(max_digits=6, decimal_places=2, help_text="Azimuth in degrees (0-360)")
    findings = models.TextField(blank=True, help_text="Survey results and observations")
    surveyor_name = models.CharField(max_length=255, blank=True)
    survey_time = models.DateTimeField(default=timezone.now)
    
    class Meta:
        ordering = ['depth']
    
    def __str__(self):
        return f"{self.get_survey_type_display()} at {self.depth}m - Dip: {self.dip_angle}°"


class Casing(models.Model):
    """
    Records casing installation data for drill holes.
    
    Tracks casing pipes installed during drilling operations including
    size, depth, length, and type of casing used.
    
    Attributes:
        shift: The drill shift when casing was installed
        casing_size: Diameter/size of the casing (e.g., 4", 6", 8")
        casing_type: Type of casing material (PVC, Steel, etc.)
        start_depth: Starting depth of casing installation in meters
        end_depth: Ending depth of casing installation in meters
        length: Total length of casing installed in meters
        remarks: Additional notes about casing installation
        installed_at: When casing was installed
    """
    CASING_SIZE_CHOICES = [
        ('2"', '2 inch'),
        ('3"', '3 inch'),
        ('4"', '4 inch'),
        ('6"', '6 inch'),
        ('8"', '8 inch'),
        ('10"', '10 inch'),
        ('12"', '12 inch'),
    ]
    
    CASING_TYPE_CHOICES = [
        ('pvc', 'PVC'),
        ('steel', 'Steel'),
        ('hdpe', 'HDPE'),
        ('fiberglass', 'Fiberglass'),
        ('other', 'Other'),
    ]
    
    shift = models.ForeignKey(DrillShift, on_delete=models.CASCADE, related_name='casings')
    casing_size = models.CharField(max_length=10, choices=CASING_SIZE_CHOICES, help_text="Casing diameter")
    casing_type = models.CharField(max_length=32, choices=CASING_TYPE_CHOICES, default='pvc', help_text="Casing material type")
    start_depth = models.DecimalField(max_digits=10, decimal_places=2, help_text="Starting depth in meters")
    end_depth = models.DecimalField(max_digits=10, decimal_places=2, help_text="Ending depth in meters")
    length = models.DecimalField(max_digits=10, decimal_places=2, help_text="Total length in meters")
    remarks = models.TextField(blank=True, help_text="Notes about casing installation")
    installed_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        ordering = ['start_depth']
    
    def __str__(self):
        return f"{self.casing_size} {self.get_casing_type_display()} - {self.start_depth}m to {self.end_depth}m"


class BOQReport(models.Model):
    """Period-based BOQ package prepared by the contractor and reviewed by the client."""

    STATUS_DRAFT = 'draft'
    STATUS_SUBMITTED = 'submitted'

    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SUBMITTED, 'Submitted to Client'),
    ]

    CLIENT_PENDING = 'pending'
    CLIENT_APPROVED = 'approved'
    CLIENT_REJECTED = 'rejected'

    CLIENT_STATUS_CHOICES = [
        (CLIENT_PENDING, 'Pending Client Review'),
        (CLIENT_APPROVED, 'Approved by Client'),
        (CLIENT_REJECTED, 'Rejected by Client'),
    ]

    title = models.CharField(max_length=255)
    client = models.ForeignKey('Client', on_delete=models.PROTECT, related_name='boq_reports')
    contractor_workspace = models.ForeignKey(
        Workspace,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='contractor_boq_reports',
        limit_choices_to={'workspace_type': Workspace.WORKSPACE_CONTRACTOR},
        help_text="Contractor company for this BOQ",
    )
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    client_status = models.CharField(max_length=16, choices=CLIENT_STATUS_CHOICES, default=CLIENT_PENDING)
    contractor_comments = models.TextField(blank=True)
    client_comments = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_boq_reports')
    submitted_to_client_at = models.DateTimeField(null=True, blank=True)
    client_reviewed_at = models.DateTimeField(null=True, blank=True)
    client_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_boq_reports'
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-period_end', '-created_at']

    def __str__(self):
        return f"{self.client.name} BOQ ({self.period_start} to {self.period_end})"

    def clean(self):
        if self.period_end < self.period_start:
            raise ValidationError({'period_end': 'Period end must be on or after the start date.'})

    def get_shifts_queryset(self):
        return DrillShift.objects.filter(
            client=self.client,
            date__range=[self.period_start, self.period_end],
            status=DrillShift.STATUS_APPROVED,
        ).select_related('client', 'created_by').prefetch_related('progress', 'materials')

    def get_total_meters(self):
        total = DrillingProgress.objects.filter(
            shift__in=self.get_shifts_queryset()
        ).aggregate(total=Sum('meters_drilled'))['total']
        return total or Decimal('0.00')

    def get_total_shifts(self):
        return self.get_shifts_queryset().count()

    def get_materials_summary(self):
        return MaterialUsed.objects.filter(
            shift__in=self.get_shifts_queryset()
        ).values('material_name', 'unit').annotate(
            total_quantity=Sum('quantity')
        ).order_by('material_name')

    def get_line_items_by_type(self):
        """Returns line items grouped by item_type as a dictionary."""
        items = self.line_items.all().order_by('item_type', 'item_name')
        return {
            'drill_size': [item for item in items if item.item_type == 'drill_size'],
            'equipment': [item for item in items if item.item_type == 'equipment'],
            'consumable': [item for item in items if item.item_type == 'consumable'],
        }

    def get_total_by_type(self):
        """Returns total cost for each item type as a dictionary."""
        items = self.line_items.all()
        totals = {
            'drill_size': Decimal('0.00'),
            'equipment': Decimal('0.00'),
            'consumable': Decimal('0.00'),
        }
        for item in items:
            totals[item.item_type] = totals.get(item.item_type, Decimal('0.00')) + (item.total_amount or Decimal('0.00'))
        return totals

    def get_additional_charges_total(self):
        """Returns effective additional charges that are approved by both sides."""
        total = self.additional_charges.filter(
            contractor_approved=True,
            client_approved=True,
            is_rejected=False,
        ).aggregate(total=Sum('amount'))['total']
        return total or Decimal('0.00')

    def get_grand_total(self):
        """Returns the sum of all BOQLineItem total_amount values plus approved additional charges."""
        total = self.line_items.aggregate(
            grand_total=Sum('total_amount')
        )['grand_total'] or Decimal('0.00')
        total += self.get_additional_charges_total()
        return total or Decimal('0.00')


class BOQLineItem(models.Model):
    """
    Individual line items in a BOQ, linked to approved presets.
    
    Stores drill sizes, equipment, and consumables charges with locked rates
    from the approved presets. Enables detailed breakdown in BOQ exports.
    """
    ITEM_TYPE_DRILL_SIZE = 'drill_size'
    ITEM_TYPE_EQUIPMENT = 'equipment'
    ITEM_TYPE_CONSUMABLE = 'consumable'
    ITEM_TYPE_ADDITIONAL_CHARGE = 'additional_charge'
    
    ITEM_TYPE_CHOICES = [
        (ITEM_TYPE_DRILL_SIZE, 'Drill Size'),
        (ITEM_TYPE_EQUIPMENT, 'Equipment'),
        (ITEM_TYPE_CONSUMABLE, 'Consumable'),
        (ITEM_TYPE_ADDITIONAL_CHARGE, 'Additional Charge'),
    ]
    
    boq_report = models.ForeignKey(BOQReport, on_delete=models.CASCADE, related_name='line_items')
    
    item_type = models.CharField(max_length=20, choices=ITEM_TYPE_CHOICES)
    item_name = models.CharField(max_length=255, help_text="Name of drill size, equipment, or consumable")
    quantity = models.DecimalField(max_digits=12, decimal_places=3, help_text="Quantity (meters, days, units, etc.)")
    unit = models.CharField(max_length=50, help_text="Unit of measurement (m, day, hr, unit, etc.)")
    locked_rate = models.DecimalField(max_digits=10, decimal_places=2, help_text="Rate locked from approved preset")
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, help_text="Quantity × Rate (auto-calculated)")
    
    # Link to the approved preset (if applicable)
    drill_size_preset = models.ForeignKey(
        'DrillSizePreset',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='boq_line_items'
    )
    equipment_preset = models.ForeignKey(
        'EquipmentPreset',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='boq_line_items'
    )
    consumable_preset = models.ForeignKey(
        'ConsumablePreset',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='boq_line_items'
    )
    additional_charge_preset = models.ForeignKey(
        'AdditionalChargePreset',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='boq_line_items'
    )
    
    notes = models.TextField(blank=True, help_text="Additional notes about this line item")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['item_type', 'item_name']
    
    def save(self, *args, **kwargs):
        """Auto-calculate total amount before saving."""
        if self.quantity and self.locked_rate:
            self.total_amount = self.quantity * self.locked_rate
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.item_name} - {self.quantity} {self.unit} @ ${self.locked_rate}"


class BOQAdditionalCharge(models.Model):
    """Variable extra charges that must be approved by both contractor and client."""

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    boq_report = models.ForeignKey(BOQReport, on_delete=models.CASCADE, related_name='additional_charges')
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=14, decimal_places=2, help_text='Use negative values for discounts / credits.')
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='proposed_additional_charges')

    contractor_approved = models.BooleanField(default=False)
    client_approved = models.BooleanField(default=False)
    is_rejected = models.BooleanField(default=False)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def status(self):
        if self.is_rejected:
            return self.STATUS_REJECTED
        if self.contractor_approved and self.client_approved:
            return self.STATUS_APPROVED
        return self.STATUS_PENDING

    @property
    def effective_amount(self):
        return self.amount if self.status == self.STATUS_APPROVED else Decimal('0.00')

    def get_status_display(self):
        return dict(self.STATUS_CHOICES).get(self.status, 'Unknown')

    def __str__(self):
        return f"{self.description} ({self.amount}) [{self.status}]"


class ApprovalHistory(models.Model):
    """
    Tracks the approval workflow history for drill shifts.
    
    Records each approval action taken on a shift, including who approved/rejected
    it, when, and any comments provided. Maintains a complete audit trail.
    
    Attributes:
        shift: The drill shift being approved
        approver: User who made the approval decision
        role: Role of the approver at time of approval
        decision: Approval decision (pending/approved/rejected)
        comments: Comments or feedback from the approver
        timestamp: When the approval action was taken
    """
    DECISION_PENDING = 'pending'
    DECISION_APPROVED = 'approved'
    DECISION_REJECTED = 'rejected'

    DECISION_CHOICES = [
        (DECISION_PENDING, 'Pending'),
        (DECISION_APPROVED, 'Approved'),
        (DECISION_REJECTED, 'Rejected'),
    ]

    shift = models.ForeignKey(DrillShift, on_delete=models.CASCADE, related_name='approvals')
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    role = models.CharField(max_length=64, blank=True)
    decision = models.CharField(max_length=16, choices=DECISION_CHOICES, default=DECISION_PENDING)
    comments = models.TextField(blank=True)
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.shift_id} - {self.decision} by {self.approver_id} @ {self.timestamp:%Y-%m-%d %H:%M}"


class Alert(models.Model):
    """
    System alerts for drilling operations requiring manager attention.
    
    Automatically generated when certain thresholds are breached:
    - Recovery below 70%
    - ROP drop > 30% vs previous shift
    - Excessive downtime (>4 hours)
    - Bit failure indicators
    
    Attributes:
        shift: Related drill shift that triggered the alert
        alert_type: Type of alert (recovery/rop_drop/downtime/bit_failure)
        severity: Alert severity level (low/medium/high/critical)
        title: Short alert title
        description: Detailed alert description
        value: Numerical value related to the alert (e.g., recovery %, ROP drop %)
        threshold: The threshold that was breached
        is_active: Whether alert is still active/unresolved
        is_acknowledged: Whether a manager has acknowledged the alert
        acknowledged_by: Manager who acknowledged the alert
        acknowledged_at: When the alert was acknowledged
        created_at: When the alert was created
    """
    ALERT_RECOVERY = 'recovery'
    ALERT_ROP_DROP = 'rop_drop'
    ALERT_DOWNTIME = 'downtime'
    ALERT_BIT_FAILURE = 'bit_failure'
    
    ALERT_TYPE_CHOICES = [
        (ALERT_RECOVERY, 'Low Core Recovery'),
        (ALERT_ROP_DROP, 'ROP Drop'),
        (ALERT_DOWNTIME, 'Excessive Downtime'),
        (ALERT_BIT_FAILURE, 'Bit Failure Warning'),
    ]
    
    SEVERITY_LOW = 'low'
    SEVERITY_MEDIUM = 'medium'
    SEVERITY_HIGH = 'high'
    SEVERITY_CRITICAL = 'critical'
    
    SEVERITY_CHOICES = [
        (SEVERITY_LOW, 'Low'),
        (SEVERITY_MEDIUM, 'Medium'),
        (SEVERITY_HIGH, 'High'),
        (SEVERITY_CRITICAL, 'Critical'),
    ]
    
    shift = models.ForeignKey(DrillShift, on_delete=models.CASCADE, related_name='alerts')
    alert_type = models.CharField(max_length=32, choices=ALERT_TYPE_CHOICES)
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default=SEVERITY_MEDIUM)
    title = models.CharField(max_length=255)
    description = models.TextField()
    value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Alert value (%, hours, etc)")
    threshold = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Threshold breached")
    is_active = models.BooleanField(default=True)
    is_acknowledged = models.BooleanField(default=False)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='acknowledged_alerts')
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['alert_type', 'is_active']),
            models.Index(fields=['severity', 'is_active']),
        ]
    
    def __str__(self):
        return f"{self.get_alert_type_display()} - {self.shift} ({self.get_severity_display()})"
    
    def acknowledge(self, user):
        """Mark alert as acknowledged by a manager."""
        self.is_acknowledged = True
        self.acknowledged_by = user
        self.acknowledged_at = timezone.now()
        self.save()


class DrillSizePreset(models.Model):
    """
    Preset rates for drill sizes (PQ, HQ, NQ, etc.).
    Contractors create presets and submit them to clients for approval.
    Approved presets auto-populate BOQ line items.
    """
    STATUS_DRAFT = 'draft'
    STATUS_SUBMITTED = 'submitted'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SUBMITTED, 'Submitted to Client'),
    ]

    CLIENT_PENDING = 'pending'
    CLIENT_APPROVED = 'approved'
    CLIENT_REJECTED = 'rejected'
    CLIENT_STATUS_CHOICES = [
        (CLIENT_PENDING, 'Pending Client Approval'),
        (CLIENT_APPROVED, 'Approved by Client'),
        (CLIENT_REJECTED, 'Rejected by Client'),
    ]

    contractor_workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='drill_size_presets',
        limit_choices_to={'workspace_type': Workspace.WORKSPACE_CONTRACTOR},
    )
    submitted_to_client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='drill_size_presets_submitted',
        help_text="Client this preset was submitted to for approval"
    )

    name = models.CharField(max_length=50, help_text="e.g., PQ, HQ, NQ, BQ")
    rate_per_meter = models.DecimalField(max_digits=10, decimal_places=2, help_text="Rate in currency per meter")
    
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    client_status = models.CharField(max_length=16, choices=CLIENT_STATUS_CHOICES, null=True, blank=True)
    
    submitted_to_client_at = models.DateTimeField(null=True, blank=True)
    client_approved_at = models.DateTimeField(null=True, blank=True)
    client_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approved_drill_size_presets'
    )
    client_comments = models.TextField(blank=True, help_text="Client feedback on the preset")
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_drill_size_presets')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = [('contractor_workspace', 'name', 'submitted_to_client')]

    def __str__(self):
        return f"{self.name} - {self.contractor_workspace.name} (${self.rate_per_meter}/m)"


class EquipmentPreset(models.Model):
    """
    Preset rates for equipment rental (Gyro, TLB, Orientation Tool, etc.).
    Contractors create presets and submit them to clients for approval.
    """
    STATUS_DRAFT = 'draft'
    STATUS_SUBMITTED = 'submitted'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SUBMITTED, 'Submitted to Client'),
    ]

    CLIENT_PENDING = 'pending'
    CLIENT_APPROVED = 'approved'
    CLIENT_REJECTED = 'rejected'
    CLIENT_STATUS_CHOICES = [
        (CLIENT_PENDING, 'Pending Client Approval'),
        (CLIENT_APPROVED, 'Approved by Client'),
        (CLIENT_REJECTED, 'Rejected by Client'),
    ]

    PERIOD_DAILY = 'daily'
    PERIOD_HOURLY = 'hourly'
    PERIOD_CHOICES = [
        (PERIOD_DAILY, 'Daily Rate'),
        (PERIOD_HOURLY, 'Hourly Rate'),
    ]

    contractor_workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='equipment_presets',
        limit_choices_to={'workspace_type': Workspace.WORKSPACE_CONTRACTOR},
    )
    submitted_to_client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='equipment_presets_submitted',
    )

    name = models.CharField(max_length=100, help_text="e.g., Gyro, TLB, Orientation Tool")
    rate = models.DecimalField(max_digits=10, decimal_places=2, help_text="Rate in currency")
    period = models.CharField(max_length=16, choices=PERIOD_CHOICES, default=PERIOD_DAILY)
    
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    client_status = models.CharField(max_length=16, choices=CLIENT_STATUS_CHOICES, null=True, blank=True)
    
    submitted_to_client_at = models.DateTimeField(null=True, blank=True)
    client_approved_at = models.DateTimeField(null=True, blank=True)
    client_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approved_equipment_presets'
    )
    client_comments = models.TextField(blank=True)
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_equipment_presets')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = [('contractor_workspace', 'name', 'submitted_to_client')]

    def __str__(self):
        return f"{self.name} - {self.get_period_display()} ${self.rate}"


class ConsumablePreset(models.Model):
    """
    Preset rates for consumables (Casing, Drilling Fluids, etc.).
    Contractors create presets and submit them to clients for approval.
    """
    STATUS_DRAFT = 'draft'
    STATUS_SUBMITTED = 'submitted'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SUBMITTED, 'Submitted to Client'),
    ]

    CLIENT_PENDING = 'pending'
    CLIENT_APPROVED = 'approved'
    CLIENT_REJECTED = 'rejected'
    CLIENT_STATUS_CHOICES = [
        (CLIENT_PENDING, 'Pending Client Approval'),
        (CLIENT_APPROVED, 'Approved by Client'),
        (CLIENT_REJECTED, 'Rejected by Client'),
    ]

    contractor_workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='consumable_presets',
        limit_choices_to={'workspace_type': Workspace.WORKSPACE_CONTRACTOR},
    )
    submitted_to_client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='consumable_presets_submitted',
    )

    name = models.CharField(max_length=100, help_text="e.g., Casing 2-inch, Drilling Fluid")
    rate = models.DecimalField(max_digits=10, decimal_places=2, help_text="Rate in currency")
    unit = models.CharField(max_length=50, help_text="e.g., per unit, per meter, per liter")
    
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    client_status = models.CharField(max_length=16, choices=CLIENT_STATUS_CHOICES, null=True, blank=True)
    
    submitted_to_client_at = models.DateTimeField(null=True, blank=True)
    client_approved_at = models.DateTimeField(null=True, blank=True)
    client_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approved_consumable_presets'
    )
    client_comments = models.TextField(blank=True)
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_consumable_presets')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = [('contractor_workspace', 'name', 'submitted_to_client')]

    def __str__(self):
        return f"{self.name} - ${self.rate}/{self.unit}"


class AdditionalChargePreset(models.Model):
    """
    Preset rates for additional charges and deductions.
    Contractors create charge presets (positive) and submit to clients for approval.
    Clients create deduction presets (negative) for their own use.
    """
    STATUS_DRAFT = 'draft'
    STATUS_SUBMITTED = 'submitted'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SUBMITTED, 'Submitted to Client'),
    ]

    CLIENT_PENDING = 'pending'
    CLIENT_APPROVED = 'approved'
    CLIENT_REJECTED = 'rejected'
    CLIENT_STATUS_CHOICES = [
        (CLIENT_PENDING, 'Pending Client Approval'),
        (CLIENT_APPROVED, 'Approved by Client'),
        (CLIENT_REJECTED, 'Rejected by Client'),
    ]

    CHARGE_TYPE_CHARGE = 'charge'
    CHARGE_TYPE_DEDUCTION = 'deduction'
    CHARGE_TYPE_CHOICES = [
        (CHARGE_TYPE_CHARGE, 'Charge (Positive)'),
        (CHARGE_TYPE_DEDUCTION, 'Deduction (Negative)'),
    ]

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='additional_charge_presets',
    )
    submitted_to_client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='additional_charge_presets_submitted',
    )

    name = models.CharField(max_length=100, help_text="e.g., Rig relocation fee, Delay penalty, Equipment damage")
    rate = models.DecimalField(max_digits=10, decimal_places=2, help_text="Rate in currency (positive for charges, negative for deductions)")
    unit = models.CharField(max_length=50, help_text="e.g., per unit, per trip, per day, per hour")
    charge_type = models.CharField(max_length=20, choices=CHARGE_TYPE_CHOICES, default=CHARGE_TYPE_CHARGE)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    client_status = models.CharField(max_length=16, choices=CLIENT_STATUS_CHOICES, null=True, blank=True)

    submitted_to_client_at = models.DateTimeField(null=True, blank=True)
    client_approved_at = models.DateTimeField(null=True, blank=True)
    client_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approved_additional_charge_presets'
    )
    client_comments = models.TextField(blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_additional_charge_presets')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['charge_type', 'name']
        unique_together = [('workspace', 'name', 'submitted_to_client')]

    def __str__(self):
        sign = "+" if self.charge_type == self.CHARGE_TYPE_CHARGE else "-"
        return f"{self.name} - {sign}${abs(self.rate)}/{self.unit}"

    @property
    def effective_rate(self):
        """Return the rate with correct sign based on charge type."""
        return self.rate if self.charge_type == self.CHARGE_TYPE_CHARGE else -abs(self.rate)


# ─────────────────────────────────────────────────────────────────────────────
# Geology / Lithology Models
# ─────────────────────────────────────────────────────────────────────────────

class DrillHole(models.Model):
    """
    Represents a single drill hole with its collar location and metadata.

    Each hole can have many depth-interval lithology logs attached to it.
    Coordinates are stored as WGS-84 decimal degrees (latitude/longitude) for
    Leaflet map display, with optional easting/northing for local grid systems.
    """
    hole_id = models.CharField(max_length=50, unique=True, help_text="Unique hole identifier, e.g. BH-001")
    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        related_name='drill_holes',
        null=True, blank=True,
    )
    project_name = models.CharField(max_length=255, blank=True, help_text="Project or site name")
    location_description = models.CharField(max_length=255, blank=True, help_text="Human-readable location description")

    # GPS / WGS-84 coordinates for Leaflet map
    latitude = models.DecimalField(
        max_digits=10, decimal_places=7,
        null=True, blank=True,
        help_text="Decimal degrees (WGS-84)",
    )
    longitude = models.DecimalField(
        max_digits=10, decimal_places=7,
        null=True, blank=True,
        help_text="Decimal degrees (WGS-84)",
    )

    # Optional local grid coordinates
    easting = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Local grid easting (m)")
    northing = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Local grid northing (m)")
    elevation = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text="Collar elevation above sea level (m)")

    # Hole geometry
    total_depth = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text="Total drilled depth (m)")
    dip = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Hole dip angle (degrees, negative = downward)")
    azimuth = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Hole azimuth (degrees, 0–360)")

    drilled_date = models.DateField(null=True, blank=True, help_text="Date drilling commenced")
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='drill_holes',
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['hole_id']
        indexes = [
            models.Index(fields=['client']),
        ]

    def __str__(self):
        return self.hole_id

    def get_max_logged_depth(self):
        """Return the deepest logged depth from lithology intervals."""
        agg = self.lithology_intervals.aggregate(max_depth=models.Max('depth_to'))
        return agg['max_depth'] or 0

    def has_coordinates(self):
        return self.latitude is not None and self.longitude is not None


class LithologyInterval(models.Model):
    """
    A single depth interval within a drill hole describing the rock type (lithology).

    Multiple intervals together form the complete lithology log / strip log for a hole.
    """
    LITHOLOGY_CHOICES = [
        ('topsoil', 'Topsoil'),
        ('clay', 'Clay'),
        ('sandy_clay', 'Sandy Clay'),
        ('sand', 'Sand'),
        ('gravel', 'Gravel'),
        ('sandstone', 'Sandstone'),
        ('siltstone', 'Siltstone'),
        ('shale', 'Shale'),
        ('mudstone', 'Mudstone'),
        ('limestone', 'Limestone'),
        ('dolomite', 'Dolomite'),
        ('marble', 'Marble'),
        ('quartzite', 'Quartzite'),
        ('granite', 'Granite'),
        ('granodiorite', 'Granodiorite'),
        ('diorite', 'Diorite'),
        ('gabbro', 'Gabbro'),
        ('basalt', 'Basalt'),
        ('andesite', 'Andesite'),
        ('rhyolite', 'Rhyolite'),
        ('schist', 'Schist'),
        ('gneiss', 'Gneiss'),
        ('pegmatite', 'Pegmatite'),
        ('breccia', 'Breccia'),
        ('conglomerate', 'Conglomerate'),
        ('coal', 'Coal'),
        ('ironstone', 'Ironstone'),
        ('calcrete', 'Calcrete'),
        ('ferricrete', 'Ferricrete'),
        ('weathered_rock', 'Weathered Rock'),
        ('other', 'Other'),
    ]

    # Standard geological colour codes used on strip logs
    LITHOLOGY_COLORS = {
        'topsoil': '#8B4513',
        'clay': '#DEB887',
        'sandy_clay': '#D2B48C',
        'sand': '#F5DEB3',
        'gravel': '#A9A9A9',
        'sandstone': '#F4A460',
        'siltstone': '#BC8F5F',
        'shale': '#708090',
        'mudstone': '#808080',
        'limestone': '#FFFACD',
        'dolomite': '#E6E6FA',
        'marble': '#F0F0F0',
        'quartzite': '#E0FFFF',
        'granite': '#FFC0CB',
        'granodiorite': '#FFB6C1',
        'diorite': '#D8BFD8',
        'gabbro': '#2F4F4F',
        'basalt': '#36454F',
        'andesite': '#778899',
        'rhyolite': '#DB7093',
        'schist': '#9ACD32',
        'gneiss': '#6B8E23',
        'pegmatite': '#FF69B4',
        'breccia': '#CD853F',
        'conglomerate': '#8B6914',
        'coal': '#1C1C1C',
        'ironstone': '#8B0000',
        'calcrete': '#FFF8DC',
        'ferricrete': '#B22222',
        'weathered_rock': '#BDB76B',
        'other': '#C0C0C0',
    }

    drill_hole = models.ForeignKey(DrillHole, on_delete=models.CASCADE, related_name='lithology_intervals')
    depth_from = models.DecimalField(max_digits=8, decimal_places=2, help_text="Start depth (m)")
    depth_to = models.DecimalField(max_digits=8, decimal_places=2, help_text="End depth (m)")
    lithology_code = models.CharField(max_length=30, choices=LITHOLOGY_CHOICES, default='other')
    description = models.TextField(blank=True, help_text="Detailed description of the rock / material")
    colour = models.CharField(max_length=7, blank=True, help_text="Hex colour override, e.g. #FF0000")
    hardness = models.CharField(
        max_length=20,
        blank=True,
        choices=[
            ('very_soft', 'Very Soft'),
            ('soft', 'Soft'),
            ('medium', 'Medium'),
            ('hard', 'Hard'),
            ('very_hard', 'Very Hard'),
        ],
        help_text="Rock hardness",
    )
    weathering = models.CharField(
        max_length=20,
        blank=True,
        choices=[
            ('fresh', 'Fresh'),
            ('slightly_weathered', 'Slightly Weathered'),
            ('moderately_weathered', 'Moderately Weathered'),
            ('highly_weathered', 'Highly Weathered'),
            ('completely_weathered', 'Completely Weathered'),
        ],
        help_text="Degree of weathering",
    )
    recovery_pct = models.DecimalField(
        max_digits=5, decimal_places=2,
        null=True, blank=True,
        help_text="Core recovery percentage for this interval",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['depth_from']
        unique_together = [('drill_hole', 'depth_from', 'depth_to')]

    def __str__(self):
        return f"{self.drill_hole.hole_id}: {self.depth_from}–{self.depth_to}m ({self.get_lithology_code_display()})"

    @property
    def interval_length(self):
        return float(self.depth_to) - float(self.depth_from)

    @property
    def display_colour(self):
        """Return the colour to use in the strip log (custom override or default)."""
        if self.colour:
            return self.colour
        return self.LITHOLOGY_COLORS.get(self.lithology_code, '#C0C0C0')
