from django.test import TestCase, override_settings
from django.urls import reverse

from django.contrib.auth import authenticate

from core.auth_utils import get_user_by_login_identifier
from core.phone_utils import normalize_kenya_phone
from .models import MyUser


class EmailOrPhoneLoginTests(TestCase):
    def setUp(self):
        self.user = MyUser(
            email='login.test@metrolinks.co.ke',
            first_name='Login',
            last_name='Test',
            role='Field Agent',
            phone='254711222333',
        )
        self.user.set_password('testpass123')
        self.user.save()

    def test_resolve_by_email(self):
        self.assertEqual(
            get_user_by_login_identifier('login.test@metrolinks.co.ke'),
            self.user,
        )

    def test_resolve_by_local_phone(self):
        self.assertEqual(get_user_by_login_identifier('0711222333'), self.user)

    def test_authenticate_with_phone(self):
        user = authenticate(username='0711222333', password='testpass123')
        self.assertEqual(user, self.user)

    def test_authenticate_with_email(self):
        user = authenticate(username='login.test@metrolinks.co.ke', password='testpass123')
        self.assertEqual(user, self.user)


class KenyaPhoneNormalizationTests(TestCase):
    def test_local_zero_prefix(self):
        self.assertEqual(normalize_kenya_phone('0712345678'), '254712345678')

    def test_plus_and_spaces(self):
        self.assertEqual(normalize_kenya_phone('+254 712 345 678'), '254712345678')

    def test_nine_digit_mobile(self):
        self.assertEqual(normalize_kenya_phone('712345678'), '254712345678')

    def test_already_international(self):
        self.assertEqual(normalize_kenya_phone('254712345678'), '254712345678')

    def test_double_prefix_mistake(self):
        self.assertEqual(normalize_kenya_phone('2540712345678'), '254712345678')

    def test_invalid_rejected(self):
        self.assertEqual(normalize_kenya_phone('07'), '')
        self.assertEqual(normalize_kenya_phone('123'), '')

@override_settings(ALLOWED_HOSTS=['tickets.testserver', 'testserver', 'localhost', '127.0.0.1'])
class UserManagementTests(TestCase):
    def setUp(self):
        # Create different role users
        self.admin = MyUser(
            email="admin@metrolinks.co.ke",
            first_name="Admin",
            last_name="User",
            role="Admin",
            is_staff=True,
            is_superuser=True
        )
        self.admin.set_password("adminpassword123")
        self.admin.save()

        self.agent = MyUser(
            email="agent@metrolinks.co.ke",
            first_name="Agent",
            last_name="User",
            role="Field Agent"
        )
        self.agent.set_password("agentpassword123")
        self.agent.save()

        # Set default host for test client to route through django-hosts
        self.client.defaults['HTTP_HOST'] = 'tickets.testserver'

    def test_anonymous_user_redirected(self):
        """Verify anonymous user is redirected to login page."""
        response = self.client.get(reverse('user_list'))
        self.assertRedirects(response, '/login/?next=/users/')

        response = self.client.get(reverse('user_create'))
        self.assertRedirects(response, '/login/?next=/users/create/')

    def test_non_admin_role_denied(self):
        """Verify field agents (non-admin role) are redirected to homepage with access denied."""
        self.client.login(email="agent@metrolinks.co.ke", username="agent@metrolinks.co.ke", password="agentpassword123")
        
        response = self.client.get(reverse('user_list'))
        self.assertRedirects(response, '/')
        
        response = self.client.get(reverse('user_create'))
        self.assertRedirects(response, '/')

    def test_admin_role_access(self):
        """Verify admin role can access both user list and creation view successfully."""
        self.client.login(email="admin@metrolinks.co.ke", username="admin@metrolinks.co.ke", password="adminpassword123")
        
        response = self.client.get(reverse('user_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/user_list.html')
        
        response = self.client.get(reverse('user_create'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/user_form.html')

    def test_user_creation_success(self):
        """Verify user creation with valid data works, hashes password, and redirects."""
        self.client.login(email="admin@metrolinks.co.ke", username="admin@metrolinks.co.ke", password="adminpassword123")
        
        post_data = {
            'first_name': 'New',
            'last_name': 'Agent',
            'email': 'newagent@metrolinks.co.ke',
            'phone': '+254700000000',
            'role': 'Field Agent',
            'password': 'securepassword555',
            'confirm_password': 'securepassword555'
        }
        
        response = self.client.post(reverse('user_create'), post_data)
        self.assertRedirects(response, reverse('user_list'))
        
        # Verify user exists in database
        user_exists = MyUser.objects.filter(email='newagent@metrolinks.co.ke').exists()
        self.assertTrue(user_exists)
        
        # Verify password has been hashed correctly and is valid
        user = MyUser.objects.get(email='newagent@metrolinks.co.ke')
        self.assertTrue(user.check_password('securepassword555'))
        self.assertEqual(user.role, 'Field Agent')
        self.assertEqual(user.phone, '254700000000')
        self.assertFalse(user.is_staff)

    def test_admin_user_creation_elevated(self):
        """Verify creating an Admin role elevations is_staff and is_superuser to True."""
        self.client.login(email="admin@metrolinks.co.ke", username="admin@metrolinks.co.ke", password="adminpassword123")
        
        post_data = {
            'first_name': 'New',
            'last_name': 'Admin',
            'email': 'newadmin@metrolinks.co.ke',
            'phone': '+254711111111',
            'role': 'Admin',
            'password': 'secureadminpwd',
            'confirm_password': 'secureadminpwd'
        }
        
        response = self.client.post(reverse('user_create'), post_data)
        self.assertRedirects(response, reverse('user_list'))
        
        user = MyUser.objects.get(email='newadmin@metrolinks.co.ke')
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
