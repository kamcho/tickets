"""Tests for customer/ticket lookup by phone."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from core.assistant.tools import tool_get_customer_tickets
from core.customer_lookup import customers_for_contact, tickets_for_contact
from core.models import Ticket

User = get_user_model()


class SpacedPhoneTicketLookupTests(TestCase):
    def test_ticket_on_spaced_phone_not_lost_to_wrong_icontains_match(self):
        decoy = User(
            email='wa_254728507155@customers.metrolinkssolutionltd.local',
            first_name='John',
            last_name='Maina',
            phone='254728507155',
            role='Customer',
            is_staff=False,
            is_active=True,
        )
        decoy.set_unusable_password()
        decoy.save()

        owner = User(
            email='jamesmaina3020@gmail.com',
            first_name='John',
            last_name='Maina',
            phone='254711111111',
            role='Customer',
            is_staff=False,
            is_active=True,
        )
        owner.set_unusable_password()
        owner.save()
        User.objects.filter(pk=owner.pk).update(phone='254 728 507 155')
        owner.refresh_from_db()

        ticket = Ticket.objects.create(
            customer=owner,
            description='Must be attended as soon as possible',
            priority='Medium',
            status='Open',
        )
        ticket.ticket_id = 'TKT-CD247E50'
        ticket.save(update_fields=['ticket_id'])

        self.assertEqual(customers_for_contact(phone='254728507155').count(), 2)

        _, tickets = tickets_for_contact(phone='254728507155')
        self.assertEqual(tickets.count(), 1)
        self.assertEqual(tickets.first().ticket_id, 'TKT-CD247E50')

        result = tool_get_customer_tickets(phone='254728507155')
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['tickets'][0]['ticket_id'], 'TKT-CD247E50')


class DuplicatePhoneFormatTests(TestCase):
    def test_legacy_07_and_254_rows_share_tickets(self):
        staff = User(
            email='staff@example.com',
            first_name='James',
            last_name='Maina',
            phone='254728507155',
            role='Customer',
            is_staff=False,
            is_active=True,
        )
        staff.set_password('0728507155')
        staff.save()
        User.objects.filter(pk=staff.pk).update(phone='0728507155')

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

        _, tickets = tickets_for_contact(phone='+254728507155')
        self.assertEqual(tickets.count(), 1)
        self.assertEqual(tickets.first().pk, ticket.pk)

        _, tickets_by_id = tickets_for_contact(customer_id=assistant.id)
        self.assertEqual(tickets_by_id.count(), 1)
