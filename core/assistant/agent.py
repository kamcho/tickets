"""
OpenAI inference loop — shared by web and WhatsApp.

OpenAI infers intent and selects tools; Django executes them and emits progress events for the web UI.
"""
import json
import logging

import httpx
from django.conf import settings

from core.assistant.tools import TOOL_SCHEMAS, execute_tool
from core.assistant.conversation import append_message, build_openai_messages
from core.assistant.formatting import format_assistant_reply
from core.assistant.progress import (
    STEP_COMPOSE,
    STEP_THINKING,
    done_event,
    error_event,
    progress_event,
    tool_step_label,
)
from core.assistant.sidebar import sidebar_event, ticket_id_from_tool_result
from core.category_utils import (
    categories_payload,
    conversation_needs_category_picker,
)

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6

SIDEBAR_REFRESH_TOOLS = frozenset({
    'create_support_ticket',
    'get_customer_tickets',
    'lookup_ticket',
    'create_or_get_customer',
})


def _sidebar_snapshot(conversation, channel, current_ticket_id=None):
    if channel != 'web':
        return None
    payload = sidebar_event(conversation, current_ticket_id=current_ticket_id)
    return {k: v for k, v in payload.items() if k != 'event'}


def _finish_turn(conversation, reply, channel, current_ticket_id=None):
    sidebar = _sidebar_snapshot(conversation, channel, current_ticket_id)
    return done_event(reply, sidebar=sidebar)


def _openai_configured():
    return bool(getattr(settings, 'OPENAI_API_KEY', ''))


def _call_openai(messages):
    api_key = settings.OPENAI_API_KEY
    model = getattr(settings, 'OPENAI_MODEL', 'gpt-4o-mini')
    base_url = getattr(settings, 'OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')

    payload = {
        'model': model,
        'messages': messages,
        'tools': TOOL_SCHEMAS,
        'tool_choice': 'auto',
        'parallel_tool_calls': True,
        'temperature': 0.3,
    }
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            f'{base_url}/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def _extract_assistant_message(choice_message):
    msg = {
        'role': choice_message.get('role', 'assistant'),
        'content': choice_message.get('content') or '',
    }
    if choice_message.get('tool_calls'):
        msg['tool_calls'] = choice_message['tool_calls']
    return msg


def _finalize_reply(reply):
    return format_assistant_reply(reply)


def _persist_and_return(conversation, reply):
    reply = _finalize_reply(reply)
    append_message(conversation, 'assistant', reply)
    return reply


def _effective_category_ids(conversation, selected_category_ids):
    if selected_category_ids:
        return list(selected_category_ids)
    return list(conversation.selected_category_ids or [])


def iter_assistant_turn(conversation, user_text, channel='web', selected_category_ids=None):
    """
    Process one user message; yields progress events, then done_event(reply).
    """
    user_text = (user_text or '').strip()
    active_ticket_id = None

    if not user_text:
        reply = _finalize_reply('Please send a message so I can help you.')
        yield _finish_turn(conversation, reply, channel, active_ticket_id)
        return

    category_ids = _effective_category_ids(conversation, selected_category_ids)

    if channel == 'web' and conversation_needs_category_picker(conversation, user_text):
        yield {
            'event': 'category_picker',
            'description': user_text,
            'categories': categories_payload(user_text),
            'prompt': (
                'Before we continue, pick every category that fits this issue '
                '(suggested ones are pre-selected). Tap Continue once — '
                'we will not ask again for this chat.'
            ),
        }
        return

    append_message(conversation, 'user', user_text)
    conversation.save(update_fields=['updated_at'])

    if not _openai_configured():
        reply = (
            'The support assistant is not fully configured yet (missing OPENAI_API_KEY). '
            'Please contact Metrolinks support by phone or email, or ask your administrator '
            'to enable the AI assistant.'
        )
        yield progress_event(STEP_THINKING[0], STEP_THINKING[1], 'error')
        _persist_and_return(conversation, reply)
        yield _finish_turn(conversation, reply, channel, active_ticket_id)
        return

    messages = build_openai_messages(conversation, channel)
    think_id, think_label = STEP_THINKING

    for _round in range(MAX_TOOL_ROUNDS):
        yield progress_event(think_id, think_label, 'active')

        try:
            data = _call_openai(messages)
        except httpx.HTTPError:
            logger.exception('OpenAI API error')
            yield progress_event(think_id, think_label, 'error')
            reply = (
                'Sorry, I had trouble reaching the AI service. Please try again in a moment '
                'or contact Metrolinks support directly.'
            )
            _persist_and_return(conversation, reply)
            yield _finish_turn(conversation, reply, channel, active_ticket_id)
            return

        yield progress_event(think_id, think_label, 'done')

        choice = data['choices'][0]['message']
        assistant_msg = _extract_assistant_message(choice)
        tool_calls = assistant_msg.get('tool_calls') or []

        if not tool_calls:
            compose_id, compose_label = STEP_COMPOSE
            yield progress_event(compose_id, compose_label, 'active')
            reply = (assistant_msg.get('content') or '').strip() or (
                'How can I help you with your support request today?'
            )
            reply = _persist_and_return(conversation, reply)
            yield progress_event(compose_id, compose_label, 'done')
            yield _finish_turn(conversation, reply, channel, active_ticket_id)
            return

        messages.append(assistant_msg)
        append_message(
            conversation,
            'assistant',
            content=assistant_msg.get('content') or '',
            tool_calls_json=json.dumps(tool_calls) if tool_calls else '',
        )

        parsed_calls = []
        for tool_call in tool_calls:
            fn = tool_call.get('function', {})
            parsed_calls.append({
                'id': tool_call.get('id', ''),
                'name': fn.get('name', ''),
                'arguments': fn.get('arguments', '{}'),
            })

        for tc in parsed_calls:
            label = tool_step_label(tc['name'])
            yield progress_event(tc['name'], label, 'pending')

        for tc in parsed_calls:
            label = tool_step_label(tc['name'])
            yield progress_event(tc['name'], label, 'active')
            result = execute_tool(
                tc['name'],
                tc['arguments'],
                conversation=conversation,
                channel=channel,
                selected_category_ids=category_ids,
            )
            result_json = json.dumps(result)
            append_message(
                conversation,
                'tool',
                content=result_json,
                tool_name=tc['name'],
                tool_call_id=tc['id'],
            )
            messages.append({
                'role': 'tool',
                'tool_call_id': tc['id'],
                'content': result_json,
            })
            status = 'error' if result.get('error') else 'done'
            yield progress_event(tc['name'], label, status)

            tid = ticket_id_from_tool_result(tc['name'], result)
            if tid:
                active_ticket_id = tid
            if channel == 'web' and tc['name'] in SIDEBAR_REFRESH_TOOLS:
                snap = _sidebar_snapshot(conversation, channel, active_ticket_id)
                if snap:
                    yield {'event': 'sidebar', **snap}

    compose_id, compose_label = STEP_COMPOSE
    yield progress_event(compose_id, compose_label, 'active')
    reply = (
        'I need a bit more information to complete that request. '
        'Could you tell me more about your issue?'
    )
    _persist_and_return(conversation, reply)
    yield progress_event(compose_id, compose_label, 'done')
    yield _finish_turn(conversation, reply, channel, active_ticket_id)


def run_assistant_turn(conversation, user_text, channel='web', selected_category_ids=None):
    """Non-streaming wrapper (WhatsApp and legacy callers)."""
    reply = ''
    for event in iter_assistant_turn(
        conversation, user_text, channel=channel, selected_category_ids=selected_category_ids,
    ):
        if event.get('event') == 'done':
            reply = event.get('reply', '')
    return reply
