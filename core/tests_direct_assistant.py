"""Tests for deterministic assistant ticket/phone replies."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from core.assistant.direct import try_direct_reply
from core.models import AssistantConversation, AssistantMessage, Ticket

User = get_user_model()


class DirectTicketReplyTests(TestCase):
    def setUp(self):
        self.customer = User(
            email='jamesmaina3020@gmail.com',
            first_name='John',
            last_name='Maina',
            phone='254728507155',
            role='Customer',
            is_staff=False,
            is_active=True,
        )
        self.customer.set_password('0728507155')
        self.customer.save()
        self.ticket = Ticket.objects.create(
            customer=self.customer,
            description='Must be attended as soon as possible',
            priority='Medium',
            status='Open',
        )
        self.ticket.ticket_id = 'TKT-CD247E50'
        self.ticket.save(update_fields=['ticket_id'])
        self.conversation = AssistantConversation.objects.create(
            channel=AssistantConversation.CHANNEL_WEB,
            session_key='test-session',
        )

    def test_phone_message_lists_tickets_without_openai(self):
        AssistantMessage.objects.create(
            conversation=self.conversation,
            role=AssistantMessage.ROLE_ASSISTANT,
            content='Could you please provide your phone number so I can check your tickets?',
        )
        reply, ticket_id = try_direct_reply(self.conversation, '+254728507155')
        self.assertIsNotNone(reply)
        self.assertIn('TKT-CD247E50', reply)
        self.assertIn('1 ticket', reply.lower())
        self.assertEqual(ticket_id, 'TKT-CD247E50')

    def test_spaced_phone_still_finds_customer(self):
        User.objects.filter(pk=self.customer.pk).update(phone='254 728 507 155')
        self.customer.refresh_from_db()
        reply, _ = try_direct_reply(self.conversation, '+254728507155')
        self.assertIsNotNone(reply)
        self.assertIn('TKT-CD247E50', reply)
