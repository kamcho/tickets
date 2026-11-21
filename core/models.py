from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager

from core.phone_utils import normalize_kenya_phone


class MyUserManager(BaseUserManager):
    """Custom manager for MyUser model that uses email instead of username."""

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        phone = (extra_fields.get('phone') or '').strip()
        if phone:
            normalized = normalize_kenya_phone(phone)
            if not normalized:
                raise ValueError(
                    f'Phone number {phone!r} could not be normalized to 254XXXXXXXXX format. '
                    'Provide a valid Kenyan mobile (07…, 254…, +254…).'
                )
            extra_fields['phone'] = normalized
        extra_fields.setdefault('first_name', 'User')
        extra_fields.setdefault('last_name', '-')
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'Admin')
        extra_fields.setdefault('first_name', 'Admin')
        extra_fields.setdefault('last_name', 'User')

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        if not (extra_fields.get('phone') or '').strip():
            raise ValueError('Superuser must have a unique phone number.')

        return self.create_user(email, password, **extra_fields)


class MyUser(AbstractUser):
    role_choice = (
        ('Receptionist', 'Receptionist'),
        ('Field Agent', 'Field Agent'),
        ('Admin', 'Admin'),
        ('Customer', 'Customer'),
    )
    username = None
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15, unique=True)
    role = models.CharField(max_length=20, choices=role_choice)
    address = models.TextField(blank=True, default='')
    location = models.CharField(
        max_length=500, blank=True, default='',
        help_text='Google Maps link or location address',
    )
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name', 'phone']

    objects = MyUserManager()

    @property
    def display_name(self):
        name = f'{self.first_name} {self.last_name}'.strip()
        if name and name != '-':
            return name
        return self.email

    @property
    def is_customer(self):
        return self.role == 'Customer'

    def save(self, *args, **kwargs):
        if self.phone:
            normalized = normalize_kenya_phone(self.phone)
            if normalized:
                self.phone = normalized
            # If normalization fails, keep the current value rather than
            # wiping it — the form layer is responsible for rejecting invalid input.
        super().save(*args, **kwargs)


class TicketCategory(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Ticket(models.Model):
    STATUS = [
        ('Open', 'Open'),
        ('In Progress', 'In Progress'),
        ('On Hold', 'On Hold'),
        ('Resolved', 'Resolved'),
        ('Closed', 'Closed'),
    ]

    PRIORITY = [
        ('High', 'High'),
        ('Medium', 'Medium'),
        ('Low', 'Low'),
    ]
    ticket_id = models.CharField(max_length=20)
    customer = models.ForeignKey(
        MyUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_tickets',
        limit_choices_to={'role': 'Customer'},
    )
    description = models.TextField()
    categories = models.ManyToManyField(
        TicketCategory, related_name='tickets', blank=True,
    )
    priority = models.CharField(max_length=20, choices=PRIORITY)
    status = models.CharField(max_length=20, choices=STATUS, default='Open')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.ticket_id:
            import uuid
            self.ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.ticket_id

    @property
    def categories_display(self):
        names = list(self.categories.values_list('name', flat=True))
        return ', '.join(names) if names else '—'


class TicketAssignment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    assigned_to = models.ForeignKey(MyUser, on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.ticket.ticket_id


class TicketComments(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    comment = models.TextField()
    commented_by = models.ForeignKey(
        MyUser, on_delete=models.CASCADE, null=True, blank=True, related_name='ticket_comments',
    )
    commented_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.ticket.ticket_id

    @property
    def author_name(self):
        if self.commented_by_id:
            return self.commented_by.display_name
        return 'Unknown'

    @property
    def author_role_label(self):
        if self.commented_by_id:
            return self.commented_by.role or 'Staff'
        return 'Staff'


class TicketAttachments(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    attachment = models.FileField(upload_to='attachments')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.ticket.ticket_id


class AssistantConversation(models.Model):
    """One thread per web session or WhatsApp phone number."""
    CHANNEL_WEB = 'web'
    CHANNEL_WHATSAPP = 'whatsapp'
    CHANNEL_CHOICES = [
        (CHANNEL_WEB, 'Web'),
        (CHANNEL_WHATSAPP, 'WhatsApp'),
    ]

    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    session_key = models.CharField(max_length=128, db_index=True)
    customer = models.ForeignKey(
        MyUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assistant_conversations',
        limit_choices_to={'role': 'Customer'},
    )
    whatsapp_phone = models.CharField(max_length=32, blank=True, default='')
    selected_category_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['channel', 'session_key'], name='unique_assistant_session'),
        ]

    def __str__(self):
        return f'{self.channel}:{self.session_key[:24]}'


class AssistantMessage(models.Model):
    ROLE_USER = 'user'
    ROLE_ASSISTANT = 'assistant'
    ROLE_SYSTEM = 'system'
    ROLE_TOOL = 'tool'
    ROLE_CHOICES = [
        (ROLE_USER, 'User'),
        (ROLE_ASSISTANT, 'Assistant'),
        (ROLE_SYSTEM, 'System'),
        (ROLE_TOOL, 'Tool'),
    ]

    conversation = models.ForeignKey(
        AssistantConversation, on_delete=models.CASCADE, related_name='messages',
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField(blank=True, default='')
    tool_name = models.CharField(max_length=64, blank=True, default='')
    tool_call_id = models.CharField(max_length=64, blank=True, default='')
    tool_calls_json = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.role} @ {self.conversation_id}'


class NetworkRouter(models.Model):
    """Physical MikroTik (per site/tower) — API credentials live here (DB), not only .env."""

    STATUS_ONLINE = 'online'
    STATUS_UNREACHABLE = 'unreachable'
    STATUS_LOS = 'los'
    STATUS_UNKNOWN = 'unknown'
    STATUS_CHOICES = (
        (STATUS_ONLINE, 'Online'),
        (STATUS_UNREACHABLE, 'Unreachable'),
        (STATUS_LOS, 'LOS / Alignment issue'),
        (STATUS_UNKNOWN, 'Unknown'),
    )

    name = models.CharField(max_length=120)
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text='Optional display / management IP. Prefer api_host for REST.',
    )
    location = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_UNKNOWN, db_index=True,
    )
    customers_served = models.PositiveIntegerField(
        default=0,
        help_text='Approx. customers behind this router (manual or synced).',
    )
    notes = models.TextField(blank=True, default='')
    last_seen_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(
        default=False,
        help_text='Default tower for new PPPoE accounts (ISP infrastructure — not a customer home router).',
    )

    # RouterOS REST — one row per physical router
    api_host = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Hostname or IP for REST (e.g. 10.0.0.1 or router.vpn).',
    )
    api_user = models.CharField(max_length=64, blank=True, default='')
    api_password = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='RouterOS API password (stored in DB; restrict admin access).',
    )
    api_ssl = models.BooleanField(default=True, help_text='Use HTTPS for REST')
    api_verify_ssl = models.BooleanField(
        default=False,
        help_text='Verify TLS cert (False OK for private self-signed)',
    )
    api_port = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Blank = 443 (HTTPS) or 80 (HTTP)',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Network router'
        verbose_name_plural = 'Network routers'

    def __str__(self):
        return f'{self.name} ({self.get_status_display()})'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default and self.is_active:
            NetworkRouter.objects.filter(is_default=True).exclude(pk=self.pk).update(
                is_default=False,
            )

    @property
    def effective_api_host(self):
        return (self.api_host or (str(self.ip_address) if self.ip_address else '')).strip()

    def has_api_credentials(self):
        return bool(self.effective_api_host and self.api_user and self.api_password)


class CustomerHomeRouter(models.Model):
    """Normal CPE / home Wi‑Fi router issued to a customer (not a MikroTik tower)."""

    OWNERSHIP_COMPANY = 'company'
    OWNERSHIP_CUSTOMER = 'customer'
    OWNERSHIP_CHOICES = (
        (OWNERSHIP_COMPANY, 'Company-owned (issued)'),
        (OWNERSHIP_CUSTOMER, 'Customer-owned'),
    )

    customer = models.ForeignKey(
        MyUser,
        on_delete=models.CASCADE,
        related_name='home_routers',
        limit_choices_to={'role': 'Customer'},
    )
    brand = models.CharField(max_length=80, blank=True, default='')
    model = models.CharField(max_length=120, blank=True, default='')
    serial_number = models.CharField(max_length=120, blank=True, default='', db_index=True)
    mac_address = models.CharField(max_length=32, blank=True, default='')
    ssid = models.CharField(max_length=64, blank=True, default='', help_text='Wi‑Fi network name')
    wifi_password = models.CharField(
        max_length=128,
        blank=True,
        default='',
        help_text='Staff-only — Wi‑Fi password if recorded',
    )
    ownership = models.CharField(
        max_length=20,
        choices=OWNERSHIP_CHOICES,
        default=OWNERSHIP_COMPANY,
    )
    installed_at = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_active', '-installed_at', '-id']
        verbose_name = 'Customer home router'
        verbose_name_plural = 'Customer home routers'

    def __str__(self):
        label = ' '.join(p for p in (self.brand, self.model) if p).strip() or 'Home router'
        if self.serial_number:
            return f'{label} ({self.serial_number})'
        return label

    @property
    def display_name(self):
        return str(self)
