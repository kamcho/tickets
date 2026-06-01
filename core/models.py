from django.db import models
from django.contrib.auth.models import AbstractUser

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

class TicketCategory(models.Model):
    name = models.CharField(max_length=100)
    def __str__(self):
        return self.name

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


