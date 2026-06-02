from django import forms
from .models import Ticket, TicketComments, TicketAttachments, TicketCategory, MyUser, Customer

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

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', 'Passwords do not match.')
        return cleaned_data

class TicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ['customer', 'subject', 'description', 'category', 'priority']
        widgets = {
            'customer': forms.Select(attrs={
                'class': 'form-input'
            }),
            'subject': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Summarize the issue briefly...'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-input',
                'rows': 5,
                'placeholder': 'Provide detailed information about the issue, including steps to reproduce...'
            }),
            'category': forms.Select(attrs={
                'class': 'form-input'
            }),
            'priority': forms.Select(attrs={
                'class': 'form-input'
            }),
        }

class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['contact_name', 'email', 'phone', 'address', 'location']
        widgets = {
            'contact_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'John Kamau'
            }),
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
