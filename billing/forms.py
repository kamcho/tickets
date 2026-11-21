from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from billing.models import Expenditure, Plan
from core.phone_utils import normalize_kenya_phone

User = get_user_model()


class ExpenditureForm(forms.ModelForm):
    class Meta:
        model = Expenditure
        fields = ('title', 'description', 'amount', 'payment_method', 'occurred_at')
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Tower site rent',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 3,
                'placeholder': 'Optional notes',
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-input',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0.01',
            }),
            'payment_method': forms.Select(attrs={'class': 'form-input'}),
            'occurred_at': forms.DateTimeInput(attrs={
                'class': 'form-input',
                'type': 'datetime-local',
                'step': '60',
            }, format='%Y-%m-%dT%H:%M'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['occurred_at'].input_formats = [
            '%Y-%m-%dT%H:%M',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%d %H:%M',
            '%Y-%m-%d %H:%M:%S',
        ]
        self.fields['description'].required = False
        if not self.is_bound and not self.instance.pk:
            self.initial.setdefault(
                'occurred_at',
                timezone.localtime(timezone.now()).strftime('%Y-%m-%dT%H:%M'),
            )

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        try:
            amount = Decimal(amount).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError):
            raise forms.ValidationError('Enter a valid amount.')
        if amount <= 0:
            raise forms.ValidationError('Amount must be greater than zero.')
        return amount

    def clean_occurred_at(self):
        value = self.cleaned_data.get('occurred_at')
        if value and timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return value


class StkPushForm(forms.Form):
    phone = forms.CharField(
        max_length=20,
        label='Customer phone',
        help_text='07…, 254…, or +254… — STK prompt is sent here',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': '0712345678',
            'inputmode': 'tel',
        }),
    )
    amount = forms.DecimalField(
        min_value=Decimal('1'),
        max_digits=12,
        decimal_places=2,
        label='Amount (KES)',
        widget=forms.NumberInput(attrs={
            'class': 'form-input',
            'placeholder': '2500',
            'step': '1',
            'min': '1',
        }),
    )
    account_reference = forms.CharField(
        max_length=12,
        required=False,
        label='Account reference',
        help_text='Short label on the M-Pesa prompt (max 12 chars). Defaults to payment id.',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'METROLINKS',
        }),
    )
    description = forms.CharField(
        max_length=13,
        required=False,
        label='Description',
        help_text='Shown on the STK prompt (max 13 chars).',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Internet bill',
        }),
    )
    customer = forms.ModelChoiceField(
        queryset=User.objects.filter(role='Customer').order_by('first_name', 'last_name'),
        required=False,
        label='Link to customer (optional)',
        widget=forms.Select(attrs={'class': 'form-input'}),
    )

    def clean_phone(self):
        raw = self.cleaned_data['phone']
        normalized = normalize_kenya_phone(raw)
        if not normalized:
            raise forms.ValidationError(
                'Enter a valid Kenyan mobile (07…, 254…, or +254…).'
            )
        return normalized

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        try:
            amount = Decimal(amount).quantize(Decimal('1'))
        except (InvalidOperation, TypeError):
            raise forms.ValidationError('Enter a valid amount.')
        if amount < 1:
            raise forms.ValidationError('Amount must be at least KES 1.')
        return amount


class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = ('name', 'speed_mbps', 'price', 'mikrotik_profile', 'is_active')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input'}),
            'speed_mbps': forms.NumberInput(attrs={'class': 'form-input', 'min': 1}),
            'price': forms.NumberInput(attrs={'class': 'form-input', 'step': '1', 'min': '0'}),
            'mikrotik_profile': forms.TextInput(attrs={'class': 'form-input'}),
            'is_active': forms.CheckboxInput(),
        }


class StartSubscriptionForm(forms.Form):
    plan = forms.ModelChoiceField(
        queryset=Plan.objects.filter(is_active=True),
        label='Plan',
        widget=forms.Select(attrs={'class': 'form-input'}),
    )
    started_at = forms.DateTimeField(
        required=False,
        label='Start / paid at (optional)',
        help_text='Leave blank to use now. Expiry = this time + 1 calendar month (exact second).',
        input_formats=['%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
        widget=forms.DateTimeInput(attrs={
            'class': 'form-input',
            'type': 'datetime-local',
            'step': '1',
        }),
    )

    def clean_started_at(self):
        value = self.cleaned_data.get('started_at')
        if value and timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return value


class PullTransactionForm(forms.Form):
    mpesa_receipt = forms.CharField(
        max_length=64,
        label='M-Pesa receipt / code',
        help_text='From the customer SMS (e.g. QJL7XK2M3N). We ask Safaricom to confirm it.',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'QJL7XK2M3N',
            'autocomplete': 'off',
            'style': 'text-transform:uppercase',
        }),
    )
    phone = forms.CharField(
        max_length=20,
        required=False,
        label='Customer phone (optional)',
        help_text='Helps match the customer before Safaricom replies.',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': '0712345678',
            'inputmode': 'tel',
        }),
    )
    amount = forms.DecimalField(
        required=False,
        min_value=Decimal('1'),
        max_digits=12,
        decimal_places=2,
        label='Expected amount (optional)',
        help_text='Safaricom amount wins when the pull result arrives.',
        widget=forms.NumberInput(attrs={
            'class': 'form-input',
            'placeholder': '2000',
            'step': '1',
            'min': '1',
        }),
    )
    customer = forms.ModelChoiceField(
        queryset=User.objects.filter(role='Customer').order_by('first_name', 'last_name'),
        required=False,
        label='Link to customer (optional)',
        widget=forms.Select(attrs={'class': 'form-input'}),
    )
    notes = forms.CharField(
        max_length=120,
        required=False,
        label='Notes',
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Optional'}),
    )

    def clean_mpesa_receipt(self):
        return (self.cleaned_data['mpesa_receipt'] or '').strip().upper()

    def clean_phone(self):
        raw = (self.cleaned_data.get('phone') or '').strip()
        if not raw:
            return ''
        normalized = normalize_kenya_phone(raw)
        if not normalized:
            raise forms.ValidationError(
                'Enter a valid Kenyan mobile (07…, 254…, or +254…).'
            )
        return normalized


class ManualPaymentForm(forms.Form):
    METHOD_MPESA = 'mpesa'
    METHOD_CASH = 'cash'
    METHOD_CHOICES = (
        (METHOD_MPESA, 'M-Pesa code (customer paid paybill/till)'),
        (METHOD_CASH, 'Cash at office'),
    )

    method = forms.ChoiceField(
        choices=METHOD_CHOICES,
        label='Payment type',
        initial=METHOD_MPESA,
        widget=forms.Select(attrs={'class': 'form-input'}),
    )
    mpesa_receipt = forms.CharField(
        max_length=64,
        required=False,
        label='M-Pesa receipt / code',
        help_text='Required for M-Pesa. Optional for cash (auto-generated if blank).',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'QJL7XK2M3N',
            'autocomplete': 'off',
            'style': 'text-transform:uppercase',
        }),
    )
    phone = forms.CharField(
        max_length=20,
        label='Customer phone',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': '0712345678',
            'inputmode': 'tel',
        }),
    )
    amount = forms.DecimalField(
        min_value=Decimal('1'),
        max_digits=12,
        decimal_places=2,
        label='Amount (KES)',
        widget=forms.NumberInput(attrs={
            'class': 'form-input',
            'placeholder': '2000',
            'step': '1',
            'min': '1',
        }),
    )
    customer = forms.ModelChoiceField(
        queryset=User.objects.filter(role='Customer').order_by('first_name', 'last_name'),
        required=False,
        label='Link to customer',
        help_text='Strongly recommended so the subscription renews on the right account.',
        widget=forms.Select(attrs={'class': 'form-input'}),
    )
    notes = forms.CharField(
        max_length=120,
        required=False,
        label='Notes',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. Paid at front desk',
        }),
    )

    def clean_mpesa_receipt(self):
        return (self.cleaned_data.get('mpesa_receipt') or '').strip().upper()

    def clean_phone(self):
        raw = self.cleaned_data['phone']
        normalized = normalize_kenya_phone(raw)
        if not normalized:
            raise forms.ValidationError(
                'Enter a valid Kenyan mobile (07…, 254…, or +254…).'
            )
        return normalized

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        try:
            amount = Decimal(amount).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError):
            raise forms.ValidationError('Enter a valid amount.')
        if amount < 1:
            raise forms.ValidationError('Amount must be at least KES 1.')
        return amount

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get('method')
        receipt = cleaned.get('mpesa_receipt') or ''
        if method == self.METHOD_MPESA and not receipt:
            self.add_error('mpesa_receipt', 'Receipt code is required for M-Pesa.')
        return cleaned
