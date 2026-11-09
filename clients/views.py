from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .access import has_unlocked, unlock
from .models import ClientPage
from .serializers import ClientPageLockedSerializer, ClientPageSerializer


class ClientPageDetailView(APIView):
    """GET /api/clients/<slug>/

    Unlocked (this session entered the code, or staff): the page and its
    products. Locked: only the name, logo and colour for the code screen.
    Unknown or inactive page: 404.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug):
        page = get_object_or_404(ClientPage.objects.active(), slug=slug)
        if has_unlocked(request, page):
            return Response(ClientPageSerializer(page, context={'request': request}).data)
        return Response(ClientPageLockedSerializer(page, context={'request': request}).data)


class UnlockThrottle(AnonRateThrottle):
    # Slows down guessing: a handful of tries a minute per IP.
    scope = 'client_page_unlock'
    rate = '10/min'


class ClientPageUnlockView(APIView):
    """POST /api/clients/<slug>/unlock/ {"code": "..."}

    Right code: unlocks the page for this session and returns it.
    Wrong code: 400. Too many tries: 429.
    """
    permission_classes = [AllowAny]
    # No session auth here, so a signed-in admin isn't asked for a CSRF token.
    authentication_classes = []
    throttle_classes = [UnlockThrottle]

    def post(self, request, slug):
        page = get_object_or_404(ClientPage.objects.active(), slug=slug)
        if not page.check_access_code(request.data.get('code', '')):
            return Response(
                {'code': 'That code is not right.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        unlock(request, page)
        return Response(ClientPageSerializer(page, context={'request': request}).data)
