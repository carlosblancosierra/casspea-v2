from rest_framework.generics import ListAPIView
from flavours.models import Flavour
from flavours.serializers import FlavourSerializer


class FlavourListView(ListAPIView):
    """Flavours that can be picked into a box today.

    `?include=coming_soon` adds the ones whose category has not launched yet
    (e.g. the Christmas flavours before 1 December), for the pages that show
    them off. The default leaves them out, so every box builder, and anything
    else that reads this list to let a customer choose, cannot offer them.
    """
    serializer_class = FlavourSerializer

    def get_queryset(self):
        include = self.request.query_params.get('include', '')
        qs = (
            Flavour.objects.active()
            if 'coming_soon' in include.split(',')
            else Flavour.objects.purchasable()
        )
        return qs.select_related('category').prefetch_related('allergens')
