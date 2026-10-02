"""Streamable HTTP transport for the orders MCP server.

Stateless and JSON-only: every POST carries one JSON-RPC message (or a batch)
and gets the answer in the response body. No SSE stream and no session ids,
because no tool here is long-running or pushes updates.

Access needs the shared secret in MCP_API_TOKEN, sent either as
`Authorization: Bearer <token>` (Claude Code, Claude Desktop config, most
clients) or as the last path segment, /api/mcp/<token>/, for clients that can
only be given a URL. With MCP_API_TOKEN unset the endpoint is switched off.
"""
import hmac
import json

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .protocol import PARSE_ERROR, handle_message


def _authorised(request, path_token):
    expected = getattr(settings, 'MCP_API_TOKEN', '') or ''
    if not expected:
        return False
    supplied = path_token or ''
    header = request.headers.get('Authorization', '')
    if header.lower().startswith('bearer '):
        supplied = header[7:].strip()
    return hmac.compare_digest(supplied.encode(), expected.encode())


@csrf_exempt
def mcp_endpoint(request, path_token=None):
    if not getattr(settings, 'MCP_API_TOKEN', ''):
        return JsonResponse({'detail': 'MCP server is not enabled.'}, status=503)
    if not _authorised(request, path_token):
        response = JsonResponse({'detail': 'Invalid or missing token.'}, status=401)
        response['WWW-Authenticate'] = 'Bearer'
        return response
    if request.method != 'POST':
        response = HttpResponse(status=405)
        response['Allow'] = 'POST'
        return response

    try:
        payload = json.loads(request.body or b'')
    except ValueError:
        return JsonResponse(
            {'jsonrpc': '2.0', 'id': None, 'error': {'code': PARSE_ERROR, 'message': 'Invalid JSON.'}},
            status=400,
        )

    if isinstance(payload, list):
        replies = [r for r in (handle_message(m) for m in payload) if r is not None]
        if not replies:
            return HttpResponse(status=202)
        return JsonResponse(replies, safe=False)

    reply = handle_message(payload)
    if reply is None:
        return HttpResponse(status=202)
    return JsonResponse(reply)
