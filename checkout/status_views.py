from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema, OpenApiResponse

from checkout.store_status import store_status


class StoreStatusView(APIView):
    """Public endpoint the frontend polls to know whether the shop is open.

    Returns ``{open, deadline, reopen_label}`` so the UI can gate checkout and
    show the correct Summer Break messaging without hardcoding the date.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        summary="Store open/closed status",
        responses={200: OpenApiResponse(description="Store status")},
        tags=["checkout"],
    )
    def get(self, request, *args, **kwargs):
        return Response(store_status(), status=200)
