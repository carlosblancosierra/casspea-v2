"""The small slice of the Model Context Protocol this server needs.

MCP is JSON-RPC 2.0. A tools-only server has to answer `initialize`, `ping`,
`tools/list` and `tools/call`, and accept notifications without replying. That
is little enough to implement directly, which keeps the official SDK (async,
Starlette) out of a synchronous Django/gunicorn deployment.

`handle_message` is transport-agnostic: the HTTP view and the stdio
management command both feed it parsed JSON and send back whatever it returns.
"""
import json
import logging

from .tools import TOOLS, ToolError

logger = logging.getLogger(__name__)

SERVER_INFO = {'name': 'casspea-orders', 'version': '1.0.0'}
SUPPORTED_VERSIONS = ('2025-06-18', '2025-03-26', '2024-11-05')
LATEST_VERSION = SUPPORTED_VERSIONS[0]

INSTRUCTIONS = (
    'Read-only access to CassPea orders. Use get_shipping_queue for what to post '
    'today, get_upcoming_shipments for the week ahead, get_production_totals for '
    'how many of each flavour to make, get_order for one order in full, and '
    'list_orders / get_customer_orders to search. Dates are YYYY-MM-DD, money is '
    'GBP. "shipping_date" is the day the box is posted, not the delivery day.'
)

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _result(msg_id, result):
    return {'jsonrpc': '2.0', 'id': msg_id, 'result': result}


def _error(msg_id, code, message):
    return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': code, 'message': message}}


def _tool_text(payload, is_error=False):
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, default=str)
    return {'content': [{'type': 'text', 'text': text}], 'isError': is_error}


def list_tools():
    return [
        {
            'name': name,
            'description': description,
            'inputSchema': schema,
            'annotations': {'readOnlyHint': True, 'openWorldHint': False},
        }
        for name, (_, description, schema) in TOOLS.items()
    ]


def call_tool(name, arguments):
    if name not in TOOLS:
        return None
    func, _, schema = TOOLS[name]
    arguments = arguments or {}
    if not isinstance(arguments, dict):
        return _tool_text("Arguments must be an object.", is_error=True)

    allowed = set(schema.get('properties', {}))
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        return _tool_text(f"Unknown argument(s): {', '.join(unknown)}.", is_error=True)
    missing = [key for key in schema.get('required', []) if arguments.get(key) in (None, '')]
    if missing:
        return _tool_text(f"Missing required argument(s): {', '.join(missing)}.", is_error=True)

    try:
        return _tool_text(func(**arguments))
    except (ToolError, ValueError, TypeError) as exc:
        return _tool_text(str(exc), is_error=True)


def handle_message(message):
    """Answer one JSON-RPC message. Returns None for notifications."""
    if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
        return _error(None, INVALID_REQUEST, 'Expected a JSON-RPC 2.0 object.')

    method = message.get('method')
    msg_id = message.get('id')
    params = message.get('params') or {}
    is_notification = 'id' not in message

    if not isinstance(method, str):
        # A response from the client (we never send requests) or garbage.
        return None if is_notification else _error(msg_id, INVALID_REQUEST, 'Missing method.')
    if is_notification:
        return None

    if method == 'initialize':
        requested = params.get('protocolVersion')
        return _result(msg_id, {
            'protocolVersion': requested if requested in SUPPORTED_VERSIONS else LATEST_VERSION,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': SERVER_INFO,
            'instructions': INSTRUCTIONS,
        })
    if method == 'ping':
        return _result(msg_id, {})
    if method == 'tools/list':
        return _result(msg_id, {'tools': list_tools()})
    if method == 'tools/call':
        name = params.get('name')
        try:
            outcome = call_tool(name, params.get('arguments'))
        except Exception:
            logger.exception('MCP tool %s failed', name)
            return _result(msg_id, _tool_text(f'Tool {name} failed unexpectedly.', is_error=True))
        if outcome is None:
            return _error(msg_id, INVALID_PARAMS, f'Unknown tool: {name}')
        return _result(msg_id, outcome)

    return _error(msg_id, METHOD_NOT_FOUND, f'Method not found: {method}')
