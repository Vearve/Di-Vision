from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import date
from decimal import Decimal
from core.models import BOQReport, BOQAdditionalCharge, Client, DrillShift, DrillingProgress, ActivityLog, MaterialUsed, ApprovalHistory
from accounts.models import UserProfile

User = get_user_model()

class ShiftListViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Create users with different roles
        cls.supervisor = User.objects.create_user(username='supervisor', password='test123')
        cls.supervisor.profile.role = UserProfile.ROLE_SUPERVISOR
        cls.supervisor.profile.save()
        
        cls.manager = User.objects.create_user(username='manager', password='test123')
        cls.manager.profile.role = UserProfile.ROLE_MANAGER
        cls.manager.profile.save()
        
        cls.client_user = User.objects.create_user(username='client', password='test123')
        cls.client_user.profile.role = UserProfile.ROLE_CLIENT
        cls.client_user.profile.save()
        
        # Create some test shifts
        cls.draft_shift = DrillShift.objects.create(
            created_by=cls.supervisor,
            date=date.today(),
            rig='Rig 1',
            status=DrillShift.STATUS_DRAFT
        )
        
        cls.submitted_shift = DrillShift.objects.create(
            created_by=cls.supervisor,
            date=date.today(),
            rig='Rig 2',
            status=DrillShift.STATUS_SUBMITTED
        )
        
        cls.approved_shift = DrillShift.objects.create(
            created_by=cls.supervisor,
            date=date.today(),
            rig='Rig 3',
            status=DrillShift.STATUS_APPROVED
        )

    def test_view_url_exists_at_desired_location(self):
        self.client.login(username='supervisor', password='test123')
        response = self.client.get('/shifts/')
        self.assertEqual(response.status_code, 200)

    def test_view_url_accessible_by_name(self):
        self.client.login(username='supervisor', password='test123')
        response = self.client.get(reverse('core:shift_list'))
        self.assertEqual(response.status_code, 200)

    def test_view_uses_correct_template(self):
        self.client.login(username='supervisor', password='test123')
        response = self.client.get(reverse('core:shift_list'))
        self.assertTemplateUsed(response, 'core/shift_list.html')

    def test_client_can_only_see_approved_shifts(self):
        self.client.login(username='client', password='test123')
        response = self.client.get(reverse('core:shift_list'))
        shifts = response.context['shifts']
        self.assertEqual(shifts.count(), 1)
        self.assertEqual(shifts.first(), self.approved_shift)

    def test_manager_can_see_submitted_and_approved_shifts(self):
        self.client.login(username='manager', password='test123')
        response = self.client.get(reverse('core:shift_list'))
        shifts = response.context['shifts']
        self.assertEqual(shifts.count(), 2)
        self.assertIn(self.submitted_shift, shifts)
        self.assertIn(self.approved_shift, shifts)

    def test_supervisor_can_see_own_drafts_and_others_submitted(self):
        self.client.login(username='supervisor', password='test123')
        response = self.client.get(reverse('core:shift_list'))
        shifts = response.context['shifts']
        self.assertEqual(shifts.count(), 3)
        

class ShiftCreateViewTest(TestCase):
    def setUp(self):
        self.supervisor = User.objects.create_user(username='supervisor', password='test123')
        self.supervisor.profile.role = UserProfile.ROLE_SUPERVISOR
        self.supervisor.profile.save()
        
        self.client_user = User.objects.create_user(username='client', password='test123')
        self.client_user.profile.role = UserProfile.ROLE_CLIENT
        self.client_user.profile.save()

    def test_only_supervisor_can_create_shift(self):
        # Test client cannot access create view
        self.client.login(username='client', password='test123')
        response = self.client.get(reverse('core:shift_create'))
        self.assertEqual(response.status_code, 403)

        # Test supervisor can access create view
        self.client.login(username='supervisor', password='test123')
        response = self.client.get(reverse('core:shift_create'))
        self.assertEqual(response.status_code, 200)

    def test_create_shift_with_formsets(self):
        self.client.login(username='supervisor', password='test123')
        data = {
            'date': '2025-11-03',
            'rig': 'Test Rig',
            'location': 'Test Location',
            'notes': 'Test notes',
            
            # Progress formset
            'progress-TOTAL_FORMS': '1',
            'progress-INITIAL_FORMS': '0',
            'progress-MIN_NUM_FORMS': '0',
            'progress-MAX_NUM_FORMS': '1000',
            'progress-0-start_depth': '10.00',
            'progress-0-end_depth': '15.50',
            'progress-0-meters_drilled': '5.50',
            'progress-0-penetration_rate': '2.75',
            
            # Activity formset
            'activity-TOTAL_FORMS': '1',
            'activity-INITIAL_FORMS': '0',
            'activity-MIN_NUM_FORMS': '0',
            'activity-MAX_NUM_FORMS': '1000',
            'activity-0-activity_type': 'drilling',
            'activity-0-description': 'Test drilling',
            'activity-0-duration_minutes': '120',
            
            # Material formset
            'material-TOTAL_FORMS': '1',
            'material-INITIAL_FORMS': '0',
            'material-MIN_NUM_FORMS': '0',
            'material-MAX_NUM_FORMS': '1000',
            'material-0-material_name': 'Diesel',
            'material-0-quantity': '100.00',
            'material-0-unit': 'liters',
        }
        
        response = self.client.post(reverse('core:shift_create'), data)
        self.assertEqual(response.status_code, 302)  # Redirect on success
        
        # Check if shift was created
        shift = DrillShift.objects.first()
        self.assertIsNotNone(shift)
        self.assertEqual(shift.rig, 'Test Rig')
        self.assertEqual(shift.created_by, self.supervisor)
        self.assertEqual(shift.status, DrillShift.STATUS_DRAFT)
        
        # Check related objects
        self.assertEqual(shift.progress.count(), 1)
        self.assertEqual(shift.activities.count(), 1)
        self.assertEqual(shift.materials.count(), 1)


class BOQAdditionalChargeTest(TestCase):
    def setUp(self):
        self.supervisor = User.objects.create_user(username='supervisor_bo', password='test123')
        self.supervisor.profile.role = UserProfile.ROLE_SUPERVISOR
        self.supervisor.profile.save()

        self.client_user = User.objects.create_user(username='client_bo', password='test123')
        self.client_user.profile.role = UserProfile.ROLE_CLIENT
        self.client_user.profile.save()

        self.client_company = Client.objects.create(name='Test Client', user=self.client_user)
        self.boq_report = BOQReport.objects.create(
            title='BOQ ACR Test',
            client=self.client_company,
            period_start=date.today(),
            period_end=date.today(),
            status=BOQReport.STATUS_DRAFT,
            client_status=BOQReport.CLIENT_PENDING,
            created_by=self.supervisor,
        )

    def test_contractor_proposes_and_client_approves_additional_charge(self):
        self.client.login(username='supervisor_bo', password='test123')
        resp = self.client.post(reverse('core:boq_add_additional_charge', args=[self.boq_report.pk]), {
            'description': 'Rig relocation fee',
            'amount': '500.00',
        })
        self.assertEqual(resp.status_code, 302)

        charge = BOQAdditionalCharge.objects.get(boq_report=self.boq_report)
        self.assertTrue(charge.contractor_approved)
        self.assertFalse(charge.client_approved)
        self.assertEqual(charge.status, BOQAdditionalCharge.STATUS_PENDING)

        self.client.logout()
        self.client.login(username='client_bo', password='test123')
        resp = self.client.post(reverse('core:boq_update_additional_charge', args=[self.boq_report.pk, charge.pk]), {
            'action': 'approve',
        })
        self.assertEqual(resp.status_code, 302)

        charge.refresh_from_db()
        self.assertTrue(charge.contractor_approved)
        self.assertTrue(charge.client_approved)
        self.assertEqual(charge.status, BOQAdditionalCharge.STATUS_APPROVED)

        total = self.boq_report.get_additional_charges_total()
        self.assertEqual(total, Decimal('500.00'))
        self.assertEqual(self.boq_report.get_grand_total(), Decimal('500.00'))


class CustomErrorPagesTest(TestCase):
    def test_404_page_renders_custom_template(self):
        # Login first so route access is not redirected by login_required wrappers.
        user = User.objects.create_user(username='test404', password='test123')
        user.profile.role = UserProfile.ROLE_SUPERVISOR
        user.profile.save()
        self.client.login(username='test404', password='test123')

        response = self.client.get('/this-url-should-not-exist-for-test-404/')
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Page Not Found', status_code=404)

    def test_shift_detail_missing_returns_404(self):
        user = User.objects.create_user(username='test_shift404', password='test123')
        user.profile.role = UserProfile.ROLE_SUPERVISOR
        user.profile.save()
        self.client.login(username='test_shift404', password='test123')

        response = self.client.get(reverse('core:shift_detail', args=[999999]))
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Page Not Found', status_code=404)

    def test_core_main_routes_return_200_for_supervisor(self):
        supervisor = User.objects.create_user(username='supervisor2', password='test123')
        supervisor.profile.role = UserProfile.ROLE_SUPERVISOR
        supervisor.profile.save()
        self.client.login(username='supervisor2', password='test123')

        # ensure core public routes are routed properly
        for url_name in ['core:home_dashboard', 'core:shift_list']:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200, msg=f"{url_name} should be accessible")
