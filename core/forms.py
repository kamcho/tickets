from django import forms
from django.contrib.auth import get_user_model
from core.form_utils import clean_kenya_mobile_phone
from .models import Ticket, TicketComments, TicketAttachments, TicketCategory, MyUser

User = get_user_model()

class UserCreateForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-input',
        'placeholder': '••••••••',
        'autocomplete': 'new-password'
    }))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-input',
        'placeholder': '••••••••',
        'autocomplete': 'new-password'
    }))

    class Meta:
        model = MyUser
        fields = ['first_name', 'last_name', 'email', 'phone', 'role']
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Jane'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Mwangi'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'jane@metrolinks.co.ke'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '+254 7XX XXX XXX'
            }),
            'role': forms.Select(attrs={
                'class': 'form-input'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].choices = [
            c for c in MyUser.role_choice if c[0] != 'Customer'
        ]

    def clean_phone(self):
        return clean_kenya_mobile_phone(self.cleaned_data.get('phone'))

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', 'Passwords do not match.')
        return cleaned_data

class CustomerChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.display_name} - {obj.phone}"

class AgentChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        name = f"{obj.first_name} {obj.last_name}".strip()
        if name:
            return f"{name} ({obj.email})"
        return obj.email


class TicketForm(forms.ModelForm):
    customer = CustomerChoiceField(
        queryset=MyUser.objects.none(),
        widget=forms.HiddenInput(),
        required=False,
    )
    assigned_to = AgentChoiceField(
        queryset=MyUser.objects.none(),
        widget=forms.HiddenInput(),
        required=False,
        label="Assign to agent",
    )

    class Meta:
        model = Ticket
        fields = ['customer', 'description', 'categories', 'priority']
        widgets = {
            'description': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 5,
                'placeholder': 'Provide detailed information about the issue, including steps to reproduce...',
                'id': 'ticket-description',
            }),
            'categories': forms.CheckboxSelectMultiple(),
            'priority': forms.Select(attrs={
                'class': 'form-input'
            }),
        }

    def __init__(self, *args, can_assign=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['categories'].queryset = TicketCategory.objects.order_by('name')
        self.fields['categories'].required = True
        self.fields['categories'].label = 'Complaint categories (select all that apply)'
        self.fields['categories'].help_text = 'Choose every category that matches the issue.'
        customer_id = self.data.get('customer') if self.data else self.initial.get('customer')
        if customer_id:
            self.fields['customer'].queryset = MyUser.objects.filter(
                pk=customer_id, role='Customer',
            )

        if not can_assign:
            del self.fields['assigned_to']
        else:
            agent_id = self.data.get('assigned_to') if self.data else self.initial.get('assigned_to')
            if agent_id:
                self.fields['assigned_to'].queryset = MyUser.objects.filter(
                    pk=agent_id, role='Field Agent'
                )

class CustomerForm(forms.ModelForm):
    contact_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'John Kamau',
        }),
        label='Full name',
    )
    portal_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Optional — enables client portal sign-in',
            'autocomplete': 'new-password',
        }),
        label='Portal password (optional)',
        help_text='Leave blank to use the phone number as the portal password.',
    )

    class Meta:
        model = MyUser
        fields = ['email', 'phone', 'address', 'location']
        widgets = {
            'email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'john@company.co.ke'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '+254 7XX XXX XXX'
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 2,
                'placeholder': 'Physical address or P.O. Box...'
            }),
            'location': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Paste Google Maps link or type location address...'
            }),
        }

    def clean_phone(self):
        return clean_kenya_mobile_phone(self.cleaned_data.get('phone'))

    def save(self, commit=True):
        from core.customer_accounts import (
            create_customer_user,
            default_customer_portal_password,
            split_contact_name,
        )

        if not commit:
            raise ValueError('CustomerForm requires commit=True')
        contact = self.cleaned_data['contact_name']
        portal_password = (self.cleaned_data.get('portal_password') or '').strip()
        phone = self.cleaned_data['phone']
        password = portal_password or default_customer_portal_password(phone)
        first, last = split_contact_name(contact)
        user = create_customer_user(
            contact_name=contact,
            email=self.cleaned_data['email'],
            phone=phone,
            password=password,
            address=self.cleaned_data.get('address') or '',
            location=self.cleaned_data.get('location') or '',
        )
        user.first_name = first
        user.last_name = last or '-'
        user.address = self.cleaned_data.get('address') or ''
        user.location = self.cleaned_data.get('location') or ''
        user.save()
        return user

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['contact_name'].initial = self.instance.display_name

class CommentForm(forms.ModelForm):
    class Meta:
        model = TicketComments
        fields = ['comment']
        widgets = {
            'comment': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 3,
                'placeholder': 'Type your update or comment here...'
            }),
        }

class AttachmentForm(forms.ModelForm):
    class Meta:
        model = TicketAttachments
        fields = ['attachment']
        widgets = {
            'attachment': forms.ClearableFileInput(attrs={
                'class': 'form-input'
            }),
        }


class ProfileForm(forms.ModelForm):
    def clean_phone(self):
        return clean_kenya_mobile_phone(
            self.cleaned_data.get('phone'),
            required=False,
        )

    class Meta:
        model = MyUser
        fields = ['first_name', 'last_name', 'phone', 'address', 'location']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '+254 7XX XXX XXX',
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 2,
                'placeholder': 'Optional address',
            }),
            'location': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Location or map link',
            }),
        }


class ProfilePasswordForm(forms.Form):
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'autocomplete': 'current-password',
        }),
        label='Current password',
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'autocomplete': 'new-password',
        }),
        label='New password',
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'autocomplete': 'new-password',
        }),
        label='Confirm new password',
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('new_password') != cleaned.get('confirm_password'):
            self.add_error('confirm_password', 'Passwords do not match.')
        return cleaned
