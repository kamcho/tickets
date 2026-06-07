from django import forms
from django.contrib.auth.password_validation import validate_password

from core.form_utils import clean_kenya_mobile_phone
from core.models import Ticket, TicketCategory





class CustomerPortalLoginForm(forms.Form):

    phone_or_email = forms.CharField(
        label='Phone or email',
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': '07XX XXX XXX or your@email.com',
            'autocomplete': 'username',
        }),
    )

    password = forms.CharField(widget=forms.PasswordInput(attrs={

        'class': 'form-input',

        'placeholder': 'Your password',

        'autocomplete': 'current-password',

    }))





class CustomerPortalRegisterForm(forms.Form):

    contact_name = forms.CharField(max_length=100, widget=forms.TextInput(attrs={

        'class': 'form-input',

        'placeholder': 'Full name',

    }))

    email = forms.EmailField(widget=forms.EmailInput(attrs={

        'class': 'form-input',

        'placeholder': 'your@email.com',

    }))

    phone = forms.CharField(max_length=15, widget=forms.TextInput(attrs={

        'class': 'form-input',

        'placeholder': '+254 7XX XXX XXX',

    }))

    password = forms.CharField(widget=forms.PasswordInput(attrs={

        'class': 'form-input',

        'placeholder': 'Create a password',

        'autocomplete': 'new-password',

    }))

    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={

        'class': 'form-input',

        'placeholder': 'Confirm password',

        'autocomplete': 'new-password',

    }))



    def clean_phone(self):
        return clean_kenya_mobile_phone(self.cleaned_data.get('phone'))

    def clean(self):

        cleaned = super().clean()

        p1 = cleaned.get('password')

        p2 = cleaned.get('confirm_password')

        if p1 and p2 and p1 != p2:

            self.add_error('confirm_password', 'Passwords do not match.')

        if p1:

            validate_password(p1)

        return cleaned





class CustomerPortalActivateForm(forms.Form):

    """First-time setup for existing customers (email + phone on file)."""

    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-input'}))

    phone = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-input'}))

    password = forms.CharField(widget=forms.PasswordInput(attrs={

        'class': 'form-input',

        'autocomplete': 'new-password',

    }))

    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={

        'class': 'form-input',

        'autocomplete': 'new-password',

    }))

    def clean_phone(self):
        return clean_kenya_mobile_phone(self.cleaned_data.get('phone'))

    def clean(self):

        cleaned = super().clean()

        if cleaned.get('password') != cleaned.get('confirm_password'):

            self.add_error('confirm_password', 'Passwords do not match.')

        if cleaned.get('password'):

            validate_password(cleaned['password'])

        return cleaned





class CustomerPortalTicketLookupForm(forms.Form):

    ticket_id = forms.CharField(widget=forms.TextInput(attrs={

        'class': 'form-input',

        'placeholder': 'TKT-XXXXXXXX',

    }))

    phone = forms.CharField(widget=forms.TextInput(attrs={

        'class': 'form-input',

        'placeholder': 'Phone number on the ticket',

    }))

    def clean_phone(self):
        return clean_kenya_mobile_phone(self.cleaned_data.get('phone'))





class CustomerTicketForm(forms.ModelForm):

    class Meta:

        model = Ticket

        fields = ['description', 'categories', 'priority']

        widgets = {

            'description': forms.Textarea(attrs={

                'class': 'form-input',

                'rows': 5,

                'placeholder': 'Describe your issue in detail...',

                'id': 'complaint-description',

            }),

            'categories': forms.CheckboxSelectMultiple(),

            'priority': forms.Select(attrs={'class': 'form-input'}),

        }



    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.fields['categories'].queryset = TicketCategory.objects.order_by('name')

        self.fields['categories'].required = True

        self.fields['categories'].label = 'What best describes your complaint?'

        self.fields['categories'].help_text = 'Select all categories that apply — suggestions update as you type.'


