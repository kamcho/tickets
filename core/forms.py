from django import forms
from django.contrib.auth import get_user_model
from core.form_utils import clean_kenya_mobile_phone
from .models import (
    Ticket, TicketComments, TicketAttachments, TicketCategory, MyUser,
    NetworkRouter, CustomerHomeRouter, Vendor,
)
from core.tenancy import is_platform_superadmin

User = get_user_model()

class VendorForm(forms.ModelForm):
    class Meta:
        model = Vendor
        fields = [
            'name', 'slug', 'is_active',
            'phone_primary', 'phone_secondary', 'email',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Acme Fiber Ltd'}),
            'slug': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'acme-fiber'}),
            'phone_primary': forms.TextInput(attrs={'class': 'form-input'}),
            'phone_secondary': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check'}),
        }

    def clean_slug(self):
        slug = (self.cleaned_data.get('slug') or '').strip().lower()
        if not slug:
            raise forms.ValidationError('Slug is required (lowercase, hyphens).')
        return slug


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

    grant_platform_superadmin = forms.BooleanField(
        required=False,
        label='Platform super-admin (all vendors)',
        help_text='Only for your platform team — not tenant Admins.',
        widget=forms.CheckboxInput(attrs={'class': 'form-check'}),
    )

    class Meta:
        model = MyUser
        fields = ['first_name', 'last_name', 'email', 'phone', 'role', 'vendor']
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

    def __init__(self, *args, acting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.acting_user = acting_user
        self.fields['role'].choices = [
            c for c in MyUser.role_choice if c[0] != 'Customer'
        ]
        if acting_user and is_platform_superadmin(acting_user):
            self.fields['vendor'].queryset = Vendor.objects.filter(is_active=True).order_by('name')
            self.fields['vendor'].required = False
            self.fields['vendor'].widget.attrs['class'] = 'form-input'
            self.fields['vendor'].help_text = (
                'Leave blank only when granting platform super-admin (all tenants).'
            )
        else:
            self.fields.pop('vendor', None)
            self.fields.pop('grant_platform_superadmin', None)

    def clean_phone(self):
        return clean_kenya_mobile_phone(self.cleaned_data.get('phone'))

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', 'Passwords do not match.')
        grant_sa = cleaned_data.get('grant_platform_superadmin')
        vendor = cleaned_data.get('vendor')
        if self.acting_user and is_platform_superadmin(self.acting_user):
            if grant_sa and vendor:
                self.add_error(
                    'vendor',
                    'Platform super-admins cannot be tied to a single vendor.',
                )
            if not grant_sa and not vendor:
                self.add_error(
                    'vendor',
                    'Pick a vendor for this user, or enable platform super-admin.',
                )
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

    def __init__(self, *args, can_assign=False, vendor=None, **kwargs):
        super().__init__(*args, **kwargs)
        cat_qs = TicketCategory.objects.order_by('name')
        if vendor:
            cat_qs = cat_qs.filter(vendor=vendor)
        self.fields['categories'].queryset = cat_qs
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
    def __init__(self, *args, vendor=None, **kwargs):
        self.vendor = vendor
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['contact_name'].initial = self.instance.display_name

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
        fields = ['phone', 'address', 'location']
        widgets = {
            'phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '07XX XXX XXX or 254 7XX XXX XXX',
                'inputmode': 'tel',
                'autocomplete': 'tel',
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
            phone=phone,
            password=password,
            address=self.cleaned_data.get('address') or '',
            location=self.cleaned_data.get('location') or '',
            vendor=self.vendor,
        )
        user.first_name = first
        user.last_name = last or '-'
        user.address = self.cleaned_data.get('address') or ''
        user.location = self.cleaned_data.get('location') or ''
        user.save()
        return user

class CustomerHomeRouterForm(forms.ModelForm):
    class Meta:
        model = CustomerHomeRouter
        fields = [
            'brand', 'model', 'serial_number', 'mac_address',
            'ssid', 'wifi_password', 'ownership', 'installed_at',
            'notes', 'is_active',
        ]
        widgets = {
            'brand': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'TP-Link / Tenda / D-Link…',
            }),
            'model': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Archer C6 / AC10…',
            }),
            'serial_number': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Serial on device sticker',
            }),
            'mac_address': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'AA:BB:CC:DD:EE:FF',
            }),
            'ssid': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Wi‑Fi name (optional)',
            }),
            'wifi_password': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Wi‑Fi password (staff only)',
                'autocomplete': 'off',
            }),
            'ownership': forms.Select(attrs={'class': 'form-input'}),
            'installed_at': forms.DateInput(attrs={
                'class': 'form-input',
                'type': 'date',
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 2,
                'placeholder': 'Where installed, spare unit, issues…',
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check'}),
        }

    def clean(self):
        cleaned = super().clean()
        brand = (cleaned.get('brand') or '').strip()
        model = (cleaned.get('model') or '').strip()
        serial = (cleaned.get('serial_number') or '').strip()
        if not brand and not model and not serial:
            raise forms.ValidationError(
                'Enter at least a brand, model, or serial number for this home router.',
            )
        return cleaned


class NetworkRouterForm(forms.ModelForm):
    class Meta:
        model = NetworkRouter
        fields = [
            'name', 'location', 'status', 'customers_served',
            'is_active', 'is_default', 'notes',
            'ip_address', 'api_host', 'api_user', 'api_password',
            'api_ssl', 'api_verify_ssl', 'api_port',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Tower A / HQ Core',
            }),
            'location': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Site / tower description',
            }),
            'status': forms.Select(attrs={'class': 'form-input'}),
            'customers_served': forms.NumberInput(attrs={
                'class': 'form-input',
                'min': 0,
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 2,
                'placeholder': 'Optional notes for NOC / billing…',
            }),
            'ip_address': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Optional display IP (e.g. 10.0.0.1)',
            }),
            'api_host': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'REST host — IP or hostname (e.g. router.vpn)',
            }),
            'api_user': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'billing',
                'autocomplete': 'off',
            }),
            'api_password': forms.PasswordInput(attrs={
                'class': 'form-input',
                'placeholder': 'RouterOS API password',
                'autocomplete': 'new-password',
            }, render_value=True),
            'api_port': forms.NumberInput(attrs={
                'class': 'form-input',
                'placeholder': 'Blank = 443 HTTPS / 80 HTTP',
                'min': 1,
                'max': 65535,
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check'}),
            'api_ssl': forms.CheckboxInput(attrs={'class': 'form-check'}),
            'api_verify_ssl': forms.CheckboxInput(attrs={'class': 'form-check'}),
        }

    def clean(self):
        cleaned = super().clean()
        api_host = (cleaned.get('api_host') or '').strip()
        ip_address = cleaned.get('ip_address')
        if not api_host and not ip_address:
            self.add_error(
                'api_host',
                'Provide API host or a display IP so the app can reach this router.',
            )
        api_user = (cleaned.get('api_user') or '').strip()
        api_password = (cleaned.get('api_password') or '').strip()
        if (api_user and not api_password) or (api_password and not api_user):
            self.add_error(
                'api_password' if api_user else 'api_user',
                'API username and password must both be set, or both left blank.',
            )
        return cleaned


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
