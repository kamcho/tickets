from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager


class MyUserManager(BaseUserManager):
    """Custom manager for MyUser model that uses email instead of username."""

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'Admin')

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)


class MyUser(AbstractUser):
    role_choice = (
        ('Receptionist','Receptionist'),
        ('Field Agent','Field Agent'),
        ('Admin','Admin')
    )
    username = None
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15)
    role = models.CharField(max_length=20,choices=role_choice)
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = MyUserManager()

class TicketCategory(models.Model):
    name = models.CharField(max_length=100)
    def __str__(self):
        return self.name

class Customer(models.Model):
    contact_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15)
    address = models.TextField(blank=True, null=True)
    location = models.CharField(max_length=500, blank=True, null=True, help_text="Google Maps link or location address")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.contact_name


class Ticket(models.Model):
    STATUS = [
        ('Open','Open'),
        ('In Progress','In Progress'),
        ('On Hold','On Hold'),
        ('Resolved','Resolved'),
        ('Closed','Closed'),
    ]

    PRIORITY = [
        ('High','High'),
        ('Medium','Medium'),
        ('Low','Low'),
    ]
    ticket_id = models.CharField(max_length=20)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets')
    subject = models.CharField(max_length=200, null=True, blank=True)
    description = models.TextField()
    category = models.ForeignKey(TicketCategory, on_delete=models.CASCADE)
    priority = models.CharField(max_length=20,choices=PRIORITY)
    status = models.CharField(max_length=20,choices=STATUS, default='Open')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def save(self, *args, **kwargs):
        if not self.ticket_id:
            import uuid
            self.ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.ticket_id

class TicketAssignment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    assigned_to = models.ForeignKey(MyUser, on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return self.ticket_id

class TicketComments(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    comment = models.TextField()
    commented_by = models.ForeignKey(MyUser, on_delete=models.CASCADE)
    commented_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return self.ticket_id

class TicketAttachments(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    attachment = models.FileField(upload_to='attachments')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return self.ticket_id


