from django.http import Http404
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated

from .models import ClientPage
from .serializers import ClientPageSerializer


class ClientPageDetailView(RetrieveAPIView):
    """GET /api/clients/<slug>/ — the page and its products, for allowed users.

    Users who are not allowed get a 404, not a 403, so the page's existence
    isn't confirmed to them.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ClientPageSerializer
    lookup_field = 'slug'
    queryset = ClientPage.objects.active()

    def get_object(self):
        page = super().get_object()
        if not page.allows(self.request.user):
            raise Http404
        return page
