"""Admin-only endpoint to manage the Summer Break clearance boxes from the UI.

Lets a staff user run the same work as the ``load_summer_break_boxes`` management
command (create/update the boxes, publish them, hide them) from the frontend
admin panel instead of shelling into the server.
"""
from io import StringIO

import structlog
from django.core.management import call_command
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from users.authentication import CustomJWTAuthentication
from .models import Product, ProductCategory

logger = structlog.get_logger(__name__)

CATEGORY_SLUG = "summer-break-boxes"
SIZES = [9, 15, 24, 48]

# Map the frontend action to the management-command keyword options.
ACTIONS = {
    "load": {},
    "publish": {"publish": True},
    "deactivate": {"deactivate": True},
}


class SummerBreakBoxesAdminView(APIView):
    """GET the current state of the boxes; POST to create/publish/hide them."""

    permission_classes = [IsAdminUser]
    authentication_classes = [CustomJWTAuthentication, SessionAuthentication]

    def _status(self):
        category = ProductCategory.objects.filter(slug=CATEGORY_SLUG).first()
        boxes = []
        for units in SIZES:
            slug = f"summer-break-{units}-bonbons"
            product = Product.objects.filter(slug=slug).first()
            boxes.append({
                "units": units,
                "slug": slug,
                "exists": bool(product),
                "active": product.active if product else False,
                "sold_out": product.sold_out if product else False,
                "price": str(product.base_price) if product else None,
                "compare_at_price": str(product.compare_at_price) if product and product.compare_at_price else None,
                "stripe_price_id": product.stripe_price_id if product else None,
            })
        return {
            "category": {
                "exists": bool(category),
                # "published" == visible in the shop grid (category active).
                "published": category.active if category else False,
                "slug": CATEGORY_SLUG,
            },
            "boxes": boxes,
            "landing_path": "/landing/summer-break",
        }

    def get(self, request, *args, **kwargs):
        return Response(self._status(), status=200)

    def post(self, request, *args, **kwargs):
        action = (request.data.get("action") or "load").strip()
        dry_run = bool(request.data.get("dry_run", False))

        if action not in ACTIONS:
            return Response(
                {"error": f"Unknown action '{action}'. Use one of: {', '.join(ACTIONS)}."},
                status=400,
            )

        options = dict(ACTIONS[action])
        options["dry_run"] = dry_run

        out = StringIO()
        try:
            call_command("load_summer_break_boxes", stdout=out, stderr=out, **options)
        except Exception as exc:  # surface the failure to the admin instead of a 500
            logger.error("summer_break_admin_action_failed", action=action, error=str(exc), exc_info=True)
            return Response(
                {"ok": False, "action": action, "error": str(exc), "output": out.getvalue()},
                status=400,
            )

        logger.info("summer_break_admin_action", action=action, dry_run=dry_run)
        return Response(
            {"ok": True, "action": action, "dry_run": dry_run, "output": out.getvalue(), "status": self._status()},
            status=200,
        )
