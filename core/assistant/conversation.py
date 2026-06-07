"""Conversation persistence for web and WhatsApp."""
import json
import uuid

from core.models import AssistantConversation, AssistantMessage
from core.assistant.prompts import build_system_prompt
from core.assistant.tools import _normalize_phone, _resolve_customer
from core.text_utils import strip_non_bmp


def get_or_create_web_conversation(request):
    key = request.session.get('assistant_session_key')
    if not key:
        key = uuid.uuid4().hex
        request.session['assistant_session_key'] = key
    conv, _ = AssistantConversation.objects.get_or_create(
        channel=AssistantConversation.CHANNEL_WEB,
        session_key=key,
    )
    return conv


def get_or_create_whatsapp_conversation(phone, profile_name=''):
    digits = _normalize_phone(phone)
    conv, created = AssistantConversation.objects.get_or_create(
        channel=AssistantConversation.CHANNEL_WHATSAPP,
        session_key=digits,
        defaults={'whatsapp_phone': digits},
    )
    if created or not conv.whatsapp_phone:
        conv.whatsapp_phone = digits
        conv.save(update_fields=['whatsapp_phone', 'updated_at'])

    if not conv.customer_id:
        customer = _resolve_customer(phone=digits)
        if customer:
            conv.customer = customer
            conv.save(update_fields=['customer', 'updated_at'])
        # Do not auto-create customers here — OpenAI calls create_or_get_customer when appropriate.

    return conv


def append_message(conversation, role, content='', tool_name='', tool_call_id='', tool_calls_json=''):
    safe_content = strip_non_bmp(content or '')
    safe_tool_calls = strip_non_bmp(tool_calls_json or '')
    return AssistantMessage.objects.create(
        conversation=conversation,
        role=role,
        content=safe_content,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        tool_calls_json=safe_tool_calls,
    )


def build_openai_messages(conversation, channel):
    """Build message list for the LLM from stored history (last N user turns)."""
    from django.conf import settings

    max_turns = getattr(settings, 'ASSISTANT_MAX_HISTORY_TURNS', 8)
    all_rows = list(conversation.messages.order_by('created_at'))

    turns = []
    buf = []
    for row in all_rows:
        if row.role == AssistantMessage.ROLE_USER:
            if buf:
                turns.append(buf)
            buf = [row]
        else:
            if buf:
                buf.append(row)
            else:
                # Orphan assistant/tool rows before any user message — skip.
                continue
    if buf:
        turns.append(buf)

    rows = [row for turn in turns[-max_turns:] for row in turn]

    customer = conversation.customer if conversation.customer_id else None
    messages = [{'role': 'system', 'content': build_system_prompt(channel, customer=customer)}]
    for row in rows:
        if row.role == AssistantMessage.ROLE_USER:
            messages.append({'role': 'user', 'content': row.content})
        elif row.role == AssistantMessage.ROLE_ASSISTANT:
            entry = {'role': 'assistant', 'content': row.content or ''}
            if row.tool_calls_json:
                try:
                    entry['tool_calls'] = json.loads(row.tool_calls_json)
                except json.JSONDecodeError:
                    pass
            messages.append(entry)
        elif row.role == AssistantMessage.ROLE_TOOL:
            messages.append({
                'role': 'tool',
                'tool_call_id': row.tool_call_id,
                'content': row.content,
            })
    return messages


def save_conversation_category_ids(conversation, category_ids):
    """Persist category picks for this chat thread (web assistant)."""
    ids = []
    for x in category_ids or []:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    if ids:
        conversation.selected_category_ids = ids
        conversation.save(update_fields=['selected_category_ids', 'updated_at'])


def clear_conversation_category_ids(conversation):
    conversation.selected_category_ids = []
    conversation.save(update_fields=['selected_category_ids', 'updated_at'])


def link_conversation_customer(conversation, customer_id=None, phone=None):
    customer = None
    from django.contrib.auth import get_user_model
    User = get_user_model()
    if customer_id:
        customer = User.objects.filter(pk=customer_id, role='Customer').first()
    elif phone:
        customer = _resolve_customer(phone=phone)
    if customer:
        conversation.customer = customer
        conversation.save(update_fields=['customer', 'updated_at'])
    return customer
