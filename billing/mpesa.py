"""Safaricom Daraja STK Push client."""
import base64
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import httpx
from django.conf import settings

from core.phone_utils import normalize_kenya_phone

logger = logging.getLogger(__name__)


class MpesaError(Exception):
    """Raised when Daraja rejects a request or credentials are missing."""


def mpesa_configured():
    return bool(
        getattr(settings, 'MPESA_CONSUMER_KEY', '')
        and getattr(settings, 'MPESA_CONSUMER_SECRET', '')
        and getattr(settings, 'MPESA_SHORTCODE', '')
        and getattr(settings, 'MPESA_PASSKEY', '')
        and getattr(settings, 'MPESA_CALLBACK_URL', '')
    )


def transaction_status_configured():
    """Credentials needed to pull/verify an off-app M-Pesa receipt."""
    return bool(
        getattr(settings, 'MPESA_CONSUMER_KEY', '')
        and getattr(settings, 'MPESA_CONSUMER_SECRET', '')
        and getattr(settings, 'MPESA_SHORTCODE', '')
        and getattr(settings, 'MPESA_INITIATOR_NAME', '')
        and getattr(settings, 'MPESA_SECURITY_CREDENTIAL', '')
        and getattr(settings, 'MPESA_TRANSACTION_RESULT_URL', '')
        and getattr(settings, 'MPESA_TRANSACTION_TIMEOUT_URL', '')
    )


def _base_url():
    env = (getattr(settings, 'MPESA_ENVIRONMENT', 'sandbox') or 'sandbox').lower()
    if env == 'production':
        return 'https://api.safaricom.co.ke'
    return 'https://sandbox.safaricom.co.ke'


def get_access_token():
    if not mpesa_configured():
        raise MpesaError(
            'M-Pesa is not configured. Set MPESA_CONSUMER_KEY, '
            'MPESA_CONSUMER_SECRET, MPESA_SHORTCODE, MPESA_PASSKEY, '
            'and MPESA_CALLBACK_URL in .env'
        )
    key = settings.MPESA_CONSUMER_KEY
    secret = settings.MPESA_CONSUMER_SECRET
    url = f'{_base_url()}/oauth/v1/generate?grant_type=client_credentials'
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, auth=(key, secret))
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.exception('M-Pesa OAuth failed: %s', exc)
        raise MpesaError(f'M-Pesa auth failed: {exc}') from exc

    token = data.get('access_token')
    if not token:
        raise MpesaError(f'M-Pesa auth returned no token: {data}')
    return token


def _stk_password(timestamp):
    shortcode = str(settings.MPESA_SHORTCODE)
    passkey = settings.MPESA_PASSKEY
    raw = f'{shortcode}{passkey}{timestamp}'
    return base64.b64encode(raw.encode('utf-8')).decode('utf-8')


def _amount_int(amount):
    """Daraja STK expects integer shillings."""
    value = Decimal(str(amount)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    if value < 1:
        raise MpesaError('Amount must be at least KES 1')
    return int(value)


def initiate_stk_push(phone, amount, account_reference, description=''):
    """
    Send Lipa Na M-Pesa Online (STK Push).

    Returns the raw Daraja JSON response on HTTP success.
    Raises MpesaError on configuration / HTTP / API errors.
    """
    normalized = normalize_kenya_phone(phone)
    if not normalized:
        raise MpesaError(f'Invalid Kenyan mobile number: {phone!r}')

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    shortcode = str(settings.MPESA_SHORTCODE)
    party_b = str(getattr(settings, 'MPESA_PARTY_B', '') or shortcode)
    transaction_type = getattr(
        settings,
        'MPESA_TRANSACTION_TYPE',
        'CustomerPayBillOnline',
    )
    callback_url = settings.MPESA_CALLBACK_URL
    account_reference = (account_reference or 'METROLINKS')[:12]
    description = (description or 'Payment')[:13]
    amount_int = _amount_int(amount)

    payload = {
        'BusinessShortCode': shortcode,
        'Password': _stk_password(timestamp),
        'Timestamp': timestamp,
        'TransactionType': transaction_type,
        'Amount': amount_int,
        'PartyA': normalized,
        'PartyB': party_b,
        'PhoneNumber': normalized,
        'CallBackURL': callback_url,
        'AccountReference': account_reference,
        'TransactionDesc': description,
    }

    token = get_access_token()
    url = f'{_base_url()}/mpesa/stkpush/v1/processrequest'
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }

    logger.info(
        'STK Push start phone=%s amount=%s ref=%s',
        normalized, amount_int, account_reference,
    )
    try:
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            data = resp.json() if resp.content else {}
    except httpx.HTTPError as exc:
        logger.exception('STK Push HTTP error: %s', exc)
        raise MpesaError(f'STK Push request failed: {exc}') from exc

    # Daraja returns 200 with error fields sometimes; also non-200 JSON errors
    if resp.status_code >= 400:
        err = data.get('errorMessage') or data.get('ResponseDescription') or str(data)
        raise MpesaError(f'STK Push rejected ({resp.status_code}): {err}')

    if data.get('ResponseCode') not in ('0', 0, None) and 'CheckoutRequestID' not in data:
        # Some error payloads use errorCode without CheckoutRequestID
        if data.get('errorCode') or data.get('errorMessage'):
            raise MpesaError(
                data.get('errorMessage') or data.get('errorCode') or str(data)
            )

    if not data.get('CheckoutRequestID'):
        raise MpesaError(f'STK Push did not return CheckoutRequestID: {data}')

    logger.info(
        'STK Push accepted CheckoutRequestID=%s MerchantRequestID=%s',
        data.get('CheckoutRequestID'),
        data.get('MerchantRequestID'),
    )
    return {
        'phone': normalized,
        'amount': amount_int,
        'response': data,
    }


def parse_stk_callback(body):
    """
    Parse Daraja STK callback JSON into a flat dict.

    Returns keys: merchant_request_id, checkout_request_id, result_code,
    result_desc, amount, mpesa_receipt_number, phone, transaction_date.
    """
    body = body or {}
    stk = (body.get('Body') or {}).get('stkCallback') or {}
    result_code = stk.get('ResultCode')
    result_desc = stk.get('ResultDesc') or ''
    meta = {}
    for item in ((stk.get('CallbackMetadata') or {}).get('Item') or []):
        name = item.get('Name')
        if name:
            meta[name] = item.get('Value')

    phone_raw = meta.get('PhoneNumber')
    phone = normalize_kenya_phone(str(phone_raw)) if phone_raw else ''

    return {
        'merchant_request_id': stk.get('MerchantRequestID') or '',
        'checkout_request_id': stk.get('CheckoutRequestID') or '',
        'result_code': result_code,
        'result_desc': result_desc,
        'amount': meta.get('Amount'),
        'mpesa_receipt_number': str(meta.get('MpesaReceiptNumber') or ''),
        'phone': phone,
        'transaction_date': meta.get('TransactionDate'),
        'raw': body,
    }


def query_transaction_status(transaction_id, *, remarks='Payment verify', occasion='Verify'):
    """
    Ask Daraja for the status of a completed M-Pesa transaction (receipt code).

    Async: Safaricom POSTs the outcome to MPESA_TRANSACTION_RESULT_URL.
    Returns the immediate acknowledgement JSON (ConversationID, etc.).
    """
    if not transaction_status_configured():
        raise MpesaError(
            'Pull transaction is not configured. Set MPESA_INITIATOR_NAME, '
            'MPESA_SECURITY_CREDENTIAL, and result/timeout URLs (or use Manual record).'
        )

    receipt = (transaction_id or '').strip().upper()
    if not receipt:
        raise MpesaError('M-Pesa receipt / transaction ID is required')

    shortcode = str(settings.MPESA_SHORTCODE)
    identifier_type = str(getattr(settings, 'MPESA_IDENTIFIER_TYPE', '4') or '4')
    payload = {
        'Initiator': settings.MPESA_INITIATOR_NAME,
        'SecurityCredential': settings.MPESA_SECURITY_CREDENTIAL,
        'CommandID': 'TransactionStatusQuery',
        'TransactionID': receipt,
        'PartyA': shortcode,
        'IdentifierType': identifier_type,
        'ResultURL': settings.MPESA_TRANSACTION_RESULT_URL,
        'QueueTimeoutURL': settings.MPESA_TRANSACTION_TIMEOUT_URL,
        'Remarks': (remarks or 'OK')[:100],
        'Occasion': (occasion or 'OK')[:100],
    }

    token = get_access_token()
    url = f'{_base_url()}/mpesa/transactionstatus/v1/query'
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }

    logger.info('Transaction status query receipt=%s', receipt)
    try:
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            data = resp.json() if resp.content else {}
    except httpx.HTTPError as exc:
        logger.exception('Transaction status HTTP error: %s', exc)
        raise MpesaError(f'Transaction status request failed: {exc}') from exc

    if resp.status_code >= 400:
        err = data.get('errorMessage') or data.get('ResponseDescription') or str(data)
        raise MpesaError(f'Transaction status rejected ({resp.status_code}): {err}')

    # Accepted responses usually have ResponseCode "0"
    code = data.get('ResponseCode')
    if code not in ('0', 0, None) and not data.get('ConversationID'):
        if data.get('errorCode') or data.get('errorMessage'):
            raise MpesaError(
                data.get('errorMessage') or data.get('errorCode') or str(data)
            )
        raise MpesaError(f'Transaction status not accepted: {data}')

    logger.info(
        'Transaction status accepted ConversationID=%s OriginatorConversationID=%s',
        data.get('ConversationID'),
        data.get('OriginatorConversationID'),
    )
    return data


def _result_params_map(result):
    params = {}
    for item in ((result.get('ResultParameters') or {}).get('ResultParameter') or []):
        key = item.get('Key')
        if key:
            params[key] = item.get('Value')
    return params


def _phone_from_party_name(value):
    """DebitPartyName is often like '2547XXXX - JOHN DOE'."""
    if not value:
        return ''
    head = str(value).split('-', 1)[0].strip()
    return normalize_kenya_phone(head) or ''


def parse_transaction_status_result(body):
    """
    Parse Daraja Transaction Status ResultURL payload into a flat dict.
    """
    body = body or {}
    result = body.get('Result') or {}
    params = _result_params_map(result)

    amount = (
        params.get('Amount')
        or params.get('TransactionAmount')
        or params.get('TransAmount')
    )
    receipt = (
        params.get('ReceiptNo')
        or params.get('TransactionReceipt')
        or params.get('MpesaReceiptNumber')
        or result.get('TransactionID')
        or ''
    )
    phone = _phone_from_party_name(
        params.get('DebitPartyName') or params.get('DebitPartyPublicName')
    )
    status_text = str(
        params.get('TransactionStatus')
        or params.get('ResultDesc')
        or ''
    ).strip()

    return {
        'originator_conversation_id': result.get('OriginatorConversationID') or '',
        'conversation_id': result.get('ConversationID') or '',
        'transaction_id': str(result.get('TransactionID') or receipt or ''),
        'result_code': result.get('ResultCode'),
        'result_desc': result.get('ResultDesc') or '',
        'amount': amount,
        'mpesa_receipt_number': str(receipt or '').strip().upper(),
        'phone': phone,
        'transaction_status': status_text,
        'params': params,
        'raw': body,
    }
