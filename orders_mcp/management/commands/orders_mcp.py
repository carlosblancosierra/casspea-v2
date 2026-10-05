"""Run the orders MCP server over stdio.

    python manage.py orders_mcp

For an MCP client on a machine that can reach the database directly (a local
copy, or a shell on the server). The client starts this process and talks
JSON-RPC over stdin/stdout, one message per line. Remote clients should use
the HTTP endpoint at /api/mcp/ instead.
"""
import json
import sys

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from orders_mcp.protocol import PARSE_ERROR, handle_message


class Command(BaseCommand):
    help = 'Serve the read-only orders MCP tools over stdio.'

    def handle(self, *args, **options):
        # stdout is the protocol channel; anything else printed there would
        # corrupt it, so diagnostics go to stderr.
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                reply = {'jsonrpc': '2.0', 'id': None,
                         'error': {'code': PARSE_ERROR, 'message': 'Invalid JSON.'}}
            else:
                # A long-lived process outlives the database connection's
                # max age; refresh it between messages like a request would.
                close_old_connections()
                if isinstance(message, list):
                    reply = [r for r in (handle_message(m) for m in message) if r is not None] or None
                else:
                    reply = handle_message(message)
            if reply is not None:
                sys.stdout.write(json.dumps(reply, default=str) + '\n')
                sys.stdout.flush()
