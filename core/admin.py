from django.contrib import admin
from .models import MyUser, TicketCategory, Customer, Ticket, TicketAssignment, TicketComments, TicketAttachments

admin.site.register(MyUser)
admin.site.register(TicketCategory)
admin.site.register(Customer)
admin.site.register(Ticket)
admin.site.register(TicketAssignment)
admin.site.register(TicketComments)
admin.site.register(TicketAttachments)
