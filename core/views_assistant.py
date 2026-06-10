"""Web chat and WhatsApp webhook views for the AI assistant."""

import json

import logging



from django.conf import settings

from django.http import HttpResponse, JsonResponse, StreamingHttpResponse

from django.shortcuts import render

from django.views.decorators.csrf import csrf_exempt

from django.views.decorators.http import require_GET, require_POST



from core.assistant.agent import iter_assistant_turn, run_assistant_turn

from core.assistant.conversation import (
    get_or_create_web_conversation,
    get_or_create_whatsapp_conversation,
    save_conversation_category_ids,
)

from core.assistant.sidebar import build_sidebar_payload

from core.assistant.whatsapp import (

    extract_inbound_messages,

    send_whatsapp_text,

    verify_webhook_token,

    whatsapp_configured,

)

from core.category_utils import categories_payload
from django.urls import reverse



logger = logging.getLogger(__name__)





def _parse_category_ids(raw):

    ids = []

    if not raw:

        return ids

    for x in raw:

        try:

            ids.append(int(x))

        except (TypeError, ValueError):

            continue

    return ids





def _parse_chat_body(request):

    try:

        body = json.loads(request.body.decode('utf-8') or '{}')

    except json.JSONDecodeError:

        return None, [], JsonResponse({'error': 'Invalid JSON.'}, status=400)



    message = (body.get('message') or '').strip()

    if not message:

        return None, [], JsonResponse({'error': 'Message is required.'}, status=400)

    if len(message) > 4000:

        return None, [], JsonResponse({'error': 'Message too long.'}, status=400)

    category_ids = _parse_category_ids(body.get('category_ids'))

    return message, category_ids, None





def assistant_page(request):

    """Web chat for customers — links conversation to logged-in portal user if present."""

    conv = get_or_create_web_conversation(request)

    # If a customer is signed in to the portal, attach them to this conversation
    # so the AI knows who they are without asking for their phone number.
    if (
        request.user.is_authenticated
        and getattr(request.user, 'role', None) == 'Customer'
        and not conv.customer_id
    ):
        conv.customer = request.user
        conv.save(update_fields=['customer', 'updated_at'])

    history = [

        {'role': m.role, 'content': m.content}

        for m in conv.messages.filter(role__in=['user', 'assistant']).order_by('created_at')[:50]

        if m.content

    ]

    sidebar = build_sidebar_payload(conv, request=request)
    portal_tickets_base = request.build_absolute_uri(reverse('portal_ticket_list'))

    return render(request, 'core/assistant.html', {

        'chat_history': history,

        'assistant_enabled': bool(getattr(settings, 'OPENAI_API_KEY', '')),

        'whatsapp_enabled': whatsapp_configured(),

        'whatsapp_display': getattr(settings, 'WHATSAPP_DISPLAY_NUMBER', ''),

        'sidebar_json': json.dumps(sidebar),

        'categories_json': json.dumps(categories_payload()),

        'portal_tickets_base': portal_tickets_base,

    })





@require_GET

def category_suggest_api(request):

    """Suggest complaint categories from description text."""

    description = request.GET.get('description', '')

    return JsonResponse({'categories': categories_payload(description)})





@require_POST

def assistant_chat_api(request):

    """JSON API: POST { \"message\": \"...\" } -> { \"reply\": \"...\" }"""

    message, category_ids, err = _parse_chat_body(request)

    if err:

        return err



    conv = get_or_create_web_conversation(request)
    if category_ids:
        save_conversation_category_ids(conv, category_ids)

    reply = run_assistant_turn(
        conv, message, channel='web', selected_category_ids=category_ids or None,
        request=request,
    )

    return JsonResponse({'reply': reply})





@require_POST

def assistant_chat_stream_api(request):

    """NDJSON stream — progress steps then final reply."""

    message, category_ids, err = _parse_chat_body(request)

    if err:

        return err



    conv = get_or_create_web_conversation(request)
    if category_ids:
        save_conversation_category_ids(conv, category_ids)

    def event_stream():
        try:
            for event in iter_assistant_turn(
                conv,
                message,
                channel='web',
                selected_category_ids=category_ids or None,
                request=request,
            ):

                yield json.dumps(event) + '\n'

        except Exception:

            logger.exception('Assistant stream failed')

            yield json.dumps({

                'event': 'error',

                'message': 'Something went wrong. Please try again.',

            }) + '\n'

            yield json.dumps({

                'event': 'done',

                'reply': 'Sorry, something went wrong on our side. Please try again.',

            }) + '\n'



    response = StreamingHttpResponse(event_stream(), content_type='application/x-ndjson')

    response['Cache-Control'] = 'no-cache'

    response['X-Accel-Buffering'] = 'no'

    return response





@csrf_exempt

def whatsapp_webhook(request):

    """Meta webhook — GET verify, POST inbound messages."""

    if request.method == 'GET':

        mode = request.GET.get('hub.mode')

        token = request.GET.get('hub.verify_token')

        challenge = request.GET.get('hub.challenge')

        result = verify_webhook_token(mode, token, challenge)

        if result is not None:

            return HttpResponse(result, content_type='text/plain')

        return HttpResponse('Forbidden', status=403)



    if request.method != 'POST':

        return HttpResponse('Method Not Allowed', status=405)



    try:

        payload = json.loads(request.body.decode('utf-8') or '{}')

    except json.JSONDecodeError:

        return HttpResponse('Bad Request', status=400)



    for inbound in extract_inbound_messages(payload):

        text = (inbound.get('text') or '').strip()

        if not text:

            continue

        try:

            conv = get_or_create_whatsapp_conversation(

                inbound['from_phone'],

                profile_name=inbound.get('profile_name', ''),

            )

            reply = run_assistant_turn(conv, text, channel='whatsapp')

            send_whatsapp_text(inbound['from_phone'], reply)

        except Exception:

            logger.exception('WhatsApp message handling failed')

            send_whatsapp_text(

                inbound['from_phone'],

                'Sorry, something went wrong. Please try again or contact Metrolinks support.',

            )



    return HttpResponse('OK', status=200)

