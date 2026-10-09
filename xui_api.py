"""
XUI Panel API interactions - Multi-server support
"""
import requests
import json
import logging
import time
from datetime import datetime, timedelta
import uuid
from config import USE_ONE_MONTH_MODE
from database import get_server, get_active_servers

logger = logging.getLogger(__name__)

# Session timeout in seconds (30 minutes)
SESSION_TIMEOUT = 1800

# Per-server session state
# Structure: { server_id: { 'session': requests.Session, 'authenticated': bool, 'last_login': float, 'config': dict } }
_server_sessions = {}


def _get_server_config(server_id):
    """Fetch server config from DB."""
    srv = get_server(server_id)
    if not srv:
        logger.error(f"Server not found: {server_id}")
        return None
    return srv


def _get_session(server_id, force_refresh=False):
    """
    Get or create a requests.Session for the given server.
    Returns (session, server_config) or (None, None) on failure.
    """
    global _server_sessions

    srv = _get_server_config(server_id)
    if not srv:
        return None, None

    state = _server_sessions.get(server_id)
    if state is None or force_refresh:
        state = {
            'session': requests.Session(),
            'authenticated': False,
            'last_login': 0,
            'config': srv,
        }
        state['session'].trust_env = False
        _server_sessions[server_id] = state
    else:
        # Refresh config in case it changed
        state['config'] = srv

    return state['session'], state['config']


def login_to_xui(server_id, force=False):
    """Login to a specific XUI server."""
    session, srv = _get_session(server_id)
    if not session or not srv:
        return False

    state = _server_sessions[server_id]
    current_time = time.time()

    # Already logged in and session fresh
    if state['authenticated'] and (current_time - state['last_login']) < SESSION_TIMEOUT and not force:
        return True

    url = f"{srv['url']}/login"
    data = {"username": srv['username'], "password": srv['password']}

    try:
        response = session.post(url, json=data, timeout=20)
        if response.ok:
            state['authenticated'] = True
            state['last_login'] = current_time
            logger.info(f"Logged in to server '{server_id}'")
            return True
        else:
            state['authenticated'] = False
            logger.error(f"Login failed for '{server_id}' status={response.status_code}")
            return False
    except Exception as e:
        state['authenticated'] = False
        logger.error(f"Login exception for '{server_id}': {e}")
        return False


def ensure_authenticated(server_id):
    """Ensure session is authenticated for the given server."""
    state = _server_sessions.get(server_id)
    if state and state.get('authenticated'):
        return True
    return login_to_xui(server_id)


def get_client_status(server_id, email):
    """Get status of a client on a specific server."""
    if not ensure_authenticated(server_id):
        return None

    session, srv = _get_session(server_id)
    if not session or not srv:
        return None

    response = session.get(f"{srv['url']}/panel/api/inbounds/getClientTraffics/{email}")
    if response.status_code == 401:
        if login_to_xui(server_id, force=True):
            response = session.get(f"{srv['url']}/panel/api/inbounds/getClientTraffics/{email}")
        else:
            return None

    if not response.ok:
        return None

    try:
        data = response.json().get('obj', {})
        if not data:
            return None

        total_bytes = data.get('total', 0)
        used_bytes = data.get('up', 0) + data.get('down', 0)
        remaining_bytes = max(0, total_bytes - used_bytes)
        remaining_gb = round(remaining_bytes / (1024 ** 3), 2)

        expiry_time = data.get('expiryTime', 0) / 1000
        remaining_seconds = max(0, expiry_time - time.time())

        remaining_days = int(remaining_seconds // 86400)
        remaining_hours = int((remaining_seconds % 86400) // 3600)

        if remaining_days > 0:
            remaining_time_display = f"{remaining_days} روز"
            if remaining_hours > 0:
                remaining_time_display += f" و {remaining_hours} ساعت"
        else:
            remaining_time_display = f"{remaining_hours} ساعت"

        return {
            'email': email,
            'server_id': server_id,
            'remaining_gb': remaining_gb,
            'remaining_days': remaining_days,
            'remaining_hours': remaining_hours,
            'remaining_time_display': remaining_time_display,
            'total_gb': round(total_bytes / (1024 ** 3), 2),
            'expiry_time_ms': int(data.get('expiryTime', 0)),
            'expiry_date': datetime.fromtimestamp(expiry_time).strftime('%Y-%m-%d'),
            'is_active': data.get('enable', False),
            'subId': data.get('subId', None)
        }
    except Exception as e:
        logger.error(f"Error parsing client status on '{server_id}': {e}")
        return None


def create_client(server_id, email, total_gb, expiry_time_ms):
    """Create a new client on a specific server."""
    if not ensure_authenticated(server_id):
        return None, f"Failed to login to server '{server_id}'"

    session, srv = _get_session(server_id)
    if not session or not srv:
        return None, "Server not found"

    client_id = str(uuid.uuid4())
    total_gb = int(total_gb)
    if USE_ONE_MONTH_MODE:
        expiry_time_ms = int((datetime.now() + timedelta(days=30)).timestamp() * 1000)

    settings = {
        "clients": [{
            "id": client_id,
            "flow": "",
            "email": email,
            "limitIp": 0,
            "totalGB": total_gb,
            "expiryTime": expiry_time_ms,
            "enable": True,
            "tgId": "",
            "subId": str(uuid.uuid4())[:16],
            "reset": 0
        }]
    }

    payload = {
        "id": srv['inbound_id'],
        "settings": json.dumps(settings, ensure_ascii=False)
    }

    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    try:
        response = session.post(
            f"{srv['url']}/panel/api/inbounds/addClient",
            headers=headers, json=payload, timeout=20
        )
        if response.status_code == 401:
            if login_to_xui(server_id, force=True):
                response = session.post(
                    f"{srv['url']}/panel/api/inbounds/addClient",
                    headers=headers, json=payload, timeout=20
                )

        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            return None, data.get("msg", "Error adding client")

        return client_id, None
    except Exception as e:
        logger.error(f"Error creating client on '{server_id}': {e}")
        return None, str(e)


def extend_client(server_id, email, client_id, additional_gb, new_expiry_time_ms=None):
    """Extend an existing client on a specific server."""
    if not ensure_authenticated(server_id):
        return False, f"Failed to login to server '{server_id}'"

    session, srv = _get_session(server_id)
    if not session or not srv:
        return False, "Server not found"

    client_status = get_client_status(server_id, email)
    if not client_status:
        return False, "Could not find client information"

    current_total_gb = client_status['total_gb']
    new_total_gb = current_total_gb + additional_gb
    total_bytes = int(new_total_gb * (1024 ** 3))

    if USE_ONE_MONTH_MODE:
        current_expiry = datetime.fromtimestamp((client_status.get('expiry_time_ms')) / 1000)
        expiry_time_ms = int((current_expiry + timedelta(days=30)).timestamp() * 1000)
    else:
        expiry_time_ms = int(new_expiry_time_ms)

    settings = {
        "clients": [{
            "id": client_id,
            "flow": "",
            "email": email,
            "limitIp": 0,
            "totalGB": total_bytes,
            "expiryTime": expiry_time_ms,
            "enable": True,
            "tgId": "",
            "subId": client_id[:16],
            "reset": 0
        }]
    }

    payload = {
        "id": srv['inbound_id'],
        "settings": json.dumps(settings, ensure_ascii=False)
    }

    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    try:
        response = session.post(
            f"{srv['url']}/panel/api/inbounds/updateClient/{client_id}",
            headers=headers, json=payload, timeout=20
        )
        if response.status_code == 401:
            if login_to_xui(server_id, force=True):
                response = session.post(
                    f"{srv['url']}/panel/api/inbounds/updateClient/{client_id}",
                    headers=headers, json=payload, timeout=20
                )

        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            return False, f"Error updating client: {data.get('msg', 'Unknown error')}"

        return True, None
    except Exception as e:
        logger.error(f"Error extending client on '{server_id}': {e}")
        return False, str(e)


def get_all_clients(server_id):
    """Get all clients from a specific server."""
    if not ensure_authenticated(server_id):
        return None

    session, srv = _get_session(server_id)
    if not session or not srv:
        return None

    try:
        response = session.get(f"{srv['url']}/panel/api/inbounds/list")

        if response.status_code == 401:
            if login_to_xui(server_id, force=True):
                response = session.get(f"{srv['url']}/panel/api/inbounds/list")
            else:
                return None

        if not response.ok:
            logger.error(f"Failed to get inbounds list from '{server_id}': {response.status_code}")
            return None

        data = response.json()
        if not data.get("success"):
            logger.error(f"API error on '{server_id}': {data.get('msg', 'Unknown error')}")
            return None

        all_clients = []
        inbounds = data.get("obj", [])

        for inbound in inbounds:
            if str(inbound.get("id")) == str(srv['inbound_id']):
                settings = json.loads(inbound.get("settings", "{}"))
                clients = settings.get("clients", [])

                for client in clients:
                    client["inboundId"] = inbound.get("id")
                    client["server_id"] = server_id
                    client["server_name"] = srv.get('name', server_id)

                    if client.get("email"):
                        traffic_info = get_client_status(server_id, client.get("email"))
                        if traffic_info:
                            client.update({
                                "remaining_gb": traffic_info.get("remaining_gb"),
                                "total_gb": traffic_info.get("total_gb"),
                                "expiry_date": traffic_info.get("expiry_date"),
                                "remaining_time_display": traffic_info.get("remaining_time_display"),
                                "is_active": traffic_info.get("is_active")
                            })

                all_clients.extend(clients)

        return all_clients
    except Exception as e:
        logger.error(f"Error getting all clients from '{server_id}': {e}")
        return None


def get_all_clients_multi_server():
    """Get clients from ALL active servers."""
    results = []
    for server_id, name in get_active_servers():
        clients = get_all_clients(server_id)
        if clients:
            for c in clients:
                c['server_id'] = server_id
                c['server_name'] = name
            results.extend(clients)
    return results


def delete_client(server_id, client_id):
    """Delete a client from a specific server."""
    if not ensure_authenticated(server_id):
        return False, f"Failed to login to server '{server_id}'"

    session, srv = _get_session(server_id)
    if not session or not srv:
        return False, "Server not found"

    try:
        response = session.post(
            f"{srv['url']}/panel/api/inbounds/{srv['inbound_id']}/delClient/{client_id}"
        )
        if response.status_code == 401:
            if login_to_xui(server_id, force=True):
                response = session.post(
                    f"{srv['url']}/panel/api/inbounds/{srv['inbound_id']}/delClient/{client_id}"
                )
            else:
                return False, "Authentication failed"

        if not response.ok:
            return False, f"API request failed: {response.status_code}"

        data = response.json()
        if not data.get("success"):
            return False, f"API error: {data.get('msg', 'Unknown error')}"

        return True, None
    except Exception as e:
        logger.error(f"Error deleting client from '{server_id}': {e}")
        return False, str(e)


# ============================================================
# BACKWARD COMPATIBILITY WRAPPERS (single default server)
# ============================================================
def _default_server_id():
    """Return the first active server ID."""
    servers = get_active_servers()
    return servers[0][0] if servers else None


def _legacy_get_client_status(email):
    sid = _default_server_id()
    return get_client_status(sid, email) if sid else None

def _legacy_create_client(email, total_gb, expiry_time_ms):
    sid = _default_server_id()
    return create_client(sid, email, total_gb, expiry_time_ms) if sid else (None, "No server configured")

def _legacy_extend_client(email, client_id, additional_gb, new_expiry_time_ms=None):
    sid = _default_server_id()
    return extend_client(sid, email, client_id, additional_gb, new_expiry_time_ms) if sid else (False, "No server configured")

def _legacy_get_all_clients():
    return get_all_clients_multi_server()

def _legacy_delete_client(client_id):
    """Delete a client - must search all servers to find it."""
    # Try to find the server_id from DB by client_id
    from database import DB_FILE
    import sqlite3
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT server_id FROM configs WHERE client_id = ?', (client_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row[0]:
        return delete_client(row[0], client_id)
    # Fallback: try all active servers
    for sid, _ in get_active_servers():
        ok, err = delete_client(sid, client_id)
        if ok:
            return True, None
    return False, "Client not found on any server"


# Export legacy names for callers that haven't been migrated
ensure_authenticated_legacy = lambda: True  # no-op; not used by multi-server code