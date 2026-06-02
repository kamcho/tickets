from django.test import TestCase, override_settings
from django.urls import reverse
from .models import MyUser

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
