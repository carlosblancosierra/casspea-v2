"""Super-admin endpoint to load client setups from the front-end admin.

GET  /api/clients/admin/setups/  -> every setup and what exists already
POST /api/clients/admin/setups/  {"setup": "<key>", "dry_run": bool, "new_code": bool}
"""
import structlog
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from users.authentication import CustomJWTAuthentication

from .loader import load_setup, setup_status
from .setups import SETUPS

logger = structlog.get_logger(__name__)


class IsSuperUser(BasePermission):
    message = 'Only super admins can load client setups.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser)


class ClientSetupAdminView(APIView):
    permission_classes = [IsSuperUser]
    authentication_classes = [CustomJWTAuthentication, SessionAuthentication]

    def get(self, request):
        return Response({'setups': [setup_status(s) for s in SETUPS.values()]})

    def post(self, request):
        key = (request.data.get('setup') or '').strip()
        setup = SETUPS.get(key)
        if not setup:
            return Response({'error': f"Unknown setup '{key}'."}, status=400)
        dry_run = bool(request.data.get('dry_run', False))
        new_code = bool(request.data.get('new_code', False))
        try:
            result = load_setup(setup, dry_run=dry_run, new_code=new_code)
        except Exception as exc:  # show the failure in the admin instead of a 500
            logger.error('client_setup_load_failed', setup=key, error=str(exc), exc_info=True)
            return Response({'ok': False, 'error': str(exc)}, status=400)
        logger.info('client_setup_loaded', setup=key, dry_run=dry_run, new_code=new_code,
                    user_id=request.user.id)
        return Response({'ok': True, **result, 'status': setup_status(setup)})
