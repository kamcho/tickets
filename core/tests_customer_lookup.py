"""Tests for customer/ticket lookup by phone."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from core.customer_lookup import customers_for_contact, tickets_for_contact
from core.models import Ticket

User = get_user_model()


class PhoneTicketLookupTests(TestCase):
    def test_duplicate_phone_formats_share_tickets(self):
        """Legacy production rows: 07XXXXXXXX and 254XXXXXXXXX as separate unique phones."""
        staff = User(
            email='james@example.com',
            first_name='James',
            last_name='Maina',
            phone='0728507155',
            role='Customer',
            is_staff=False,
            is_active=True,
        )
        staff.set_password('0728507155')
        staff.save()

        assistant = User(
            email='wa_254728507155@customers.metrolinkssolutionltd.local',
            first_name='John',
            last_name='Maina',
            phone='254728507155',
            role='Customer',
            is_staff=False,
            is_active=True,
        )
        assistant.set_unusable_password()
        assistant.save()

        ticket = Ticket.objects.create(
            customer=staff,
            description='Internet down',
            priority='Medium',
            status='Open',
        )

        self.assertNotEqual(staff.id, assistant.id)

        by_local = customers_for_contact(phone='0728507155')
        self.assertEqual(by_local.count(), 2)

        _, tickets = tickets_for_contact(phone='+254728507155')
        self.assertEqual(tickets.count(), 1)
        self.assertEqual(tickets.first().ticket_id, ticket.ticket_id)

        _, tickets_by_id = tickets_for_contact(customer_id=assistant.id)
        self.assertEqual(tickets_by_id.count(), 1)
