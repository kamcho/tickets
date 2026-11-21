"""MikroTik RouterOS REST client (PPPoE) — per-router DB credentials, .env fallback."""
import logging
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class MikroTikError(Exception):
    """Router unreachable or rejected the request."""

    def __init__(self, message, *, status_code=None, unreachable=False):
        super().__init__(message)
        self.status_code = status_code
        self.unreachable = unreachable


@dataclass
class RouterConnection:
    """Resolved REST target for one physical MikroTik."""

    host: str
    user: str
    password: str
    ssl: bool = True
    verify_ssl: bool = False
    port: int | None = None
    name: str = 'default'
    router_id: int | None = None
    source: str = 'env'  # env | db

    @property
    def base_url(self):
        host = (self.host or '').strip().rstrip('/')
        if not host:
            raise MikroTikError('Router API host is empty', unreachable=True)
        if host.startswith('http://') or host.startswith('https://'):
            return host.rstrip('/')
        scheme = 'https' if self.ssl else 'http'
        port = self.port
        if port is None:
            port = 443 if self.ssl else 80
        default_port = 443 if self.ssl else 80
        if port != default_port:
            return f'{scheme}://{host}:{port}'
        return f'{scheme}://{host}'


def env_connection():
    """Legacy single-router config from .env (fallback / local)."""
    if not getattr(settings, 'MIKROTIK_ENABLED', False):
        return None
    host = (getattr(settings, 'MIKROTIK_HOST', '') or '').strip()
    user = (getattr(settings, 'MIKROTIK_USER', '') or '').strip()
    password = (getattr(settings, 'MIKROTIK_PASSWORD', '') or '').strip()
    if not (host and user and password):
        return None
    return RouterConnection(
        host=host,
        user=user,
        password=password,
        ssl=getattr(settings, 'MIKROTIK_SSL', True),
        verify_ssl=getattr(settings, 'MIKROTIK_VERIFY_SSL', False),
        port=getattr(settings, 'MIKROTIK_PORT', None),
        name='env-default',
        source='env',
    )


def connection_from_router(router):
    if not router or not router.has_api_credentials():
        return None
    return RouterConnection(
        host=router.effective_api_host,
        user=router.api_user,
        password=router.api_password,
        ssl=router.api_ssl,
        verify_ssl=router.api_verify_ssl,
        port=router.api_port,
        name=router.name,
        router_id=router.pk,
        source='db',
    )


def get_default_router(*, vendor=None):
    from core.models import NetworkRouter
    qs = NetworkRouter.objects.filter(is_active=True)
    if vendor is not None:
        qs = qs.filter(vendor=vendor)
    return qs.filter(is_default=True).first() or qs.order_by('id').first()


def resolve_connection(*, router=None, account=None):
    """
    Prefer account.router → explicit router → DB default → .env fallback.
    """
    if account is not None and getattr(account, 'router_id', None):
        conn = connection_from_router(account.router)
        if conn:
            return conn
    if router is not None:
        conn = connection_from_router(router)
        if conn:
            return conn
    default = get_default_router()
    if default:
        conn = connection_from_router(default)
        if conn:
            return conn
    return env_connection()


def mikrotik_configured(*, router=None, account=None):
    """True if we can resolve any usable router connection."""
    try:
        return resolve_connection(router=router, account=account) is not None
    except Exception:
        return False


def _client(conn: RouterConnection):
    timeout = getattr(settings, 'MIKROTIK_TIMEOUT', 8.0)
    return httpx.Client(
        base_url=conn.base_url,
        auth=(conn.user, conn.password),
        timeout=timeout,
        verify=conn.verify_ssl,
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
    )


def _request(method, path, *, conn=None, router=None, account=None, json=None, params=None):
    conn = conn or resolve_connection(router=router, account=account)
    if not conn:
        raise MikroTikError(
            'No MikroTik credentials (add NetworkRouter in admin or set MIKROTIK_* in .env)',
            unreachable=True,
        )
    try:
        with _client(conn) as client:
            resp = client.request(method, path, json=json, params=params)
    except httpx.HTTPError as exc:
        logger.exception('MikroTik HTTP error [%s] %s %s: %s', conn.name, method, path, exc)
        raise MikroTikError(f'MikroTik unreachable ({conn.name}): {exc}', unreachable=True) from exc

    if resp.status_code >= 400:
        detail = (resp.text or '')[:300]
        raise MikroTikError(
            f'MikroTik [{conn.name}] {method} {path} → {resp.status_code}: {detail}',
            status_code=resp.status_code,
            unreachable=resp.status_code in (502, 503, 504),
        )
    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        return {'raw': resp.text}


def health(*, router=None, account=None):
    data = _request('GET', '/rest/system/resource', router=router, account=account)
    if isinstance(data, list) and data:
        return data[0]
    return data or {}


def find_ppp_secret(username, *, router=None, account=None):
    data = _request(
        'GET', '/rest/ppp/secret',
        router=router, account=account, params={'name': username},
    )
    if isinstance(data, list):
        for row in data:
            if str(row.get('name') or '') == username:
                return row
        return data[0] if len(data) == 1 else None
    if isinstance(data, dict) and data.get('name') == username:
        return data
    return None


def ensure_ppp_secret(*, username, password, profile, comment='', disabled=False, router=None, account=None):
    existing = find_ppp_secret(username, router=router, account=account)
    payload = {
        'name': username,
        'service': 'pppoe',
        'profile': profile or 'default',
        'comment': (comment or '')[:128],
        'disabled': 'true' if disabled else 'false',
    }
    if password:
        payload['password'] = password

    if existing and existing.get('.id'):
        rid = existing['.id']
        _request(
            'PATCH', f'/rest/ppp/secret/{quote(str(rid), safe="")}',
            router=router, account=account, json=payload,
        )
        return find_ppp_secret(username, router=router, account=account) or {**existing, **payload}

    _request('PUT', '/rest/ppp/secret', router=router, account=account, json=payload)
    return find_ppp_secret(username, router=router, account=account) or payload


def set_ppp_disabled(username, disabled=True, *, router=None, account=None):
    secret = find_ppp_secret(username, router=router, account=account)
    if not secret or not secret.get('.id'):
        raise MikroTikError(f'PPP secret not found: {username}')
    rid = secret['.id']
    _request(
        'PATCH',
        f'/rest/ppp/secret/{quote(str(rid), safe="")}',
        router=router, account=account,
        json={'disabled': 'true' if disabled else 'false'},
    )
    return find_ppp_secret(username, router=router, account=account) or secret


def list_ppp_active(username, *, router=None, account=None):
    data = _request(
        'GET', '/rest/ppp/active',
        router=router, account=account, params={'name': username},
    )
    if isinstance(data, list):
        return [r for r in data if str(r.get('name') or '') == username] or data
    if isinstance(data, dict) and data:
        return [data]
    return []


def kick_ppp(username, *, router=None, account=None):
    actives = list_ppp_active(username, router=router, account=account)
    kicked = 0
    for row in actives:
        rid = row.get('.id')
        if not rid:
            continue
        try:
            _request(
                'DELETE', f'/rest/ppp/active/{quote(str(rid), safe="")}',
                router=router, account=account,
            )
            kicked += 1
        except MikroTikError:
            logger.exception('Failed to kick PPP active %s for %s', rid, username)
    return kicked


def delete_ppp_secret(username, *, router=None, account=None):
    secret = find_ppp_secret(username, router=router, account=account)
    if not secret or not secret.get('.id'):
        return False
    _request(
        'DELETE', f'/rest/ppp/secret/{quote(str(secret[".id"]), safe="")}',
        router=router, account=account,
    )
    return True
