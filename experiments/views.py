from collections import defaultdict
from decimal import Decimal

from django.db import IntegrityError
from rest_framework import permissions, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from orders.models import Order
from users.authentication import CustomJWTAuthentication

from .models import Assignment, Event, Experiment
from .serializers import AssignRequestSerializer, EventRequestSerializer
from .utils import is_bot


def _session_key(request) -> str:
    """The same key carts are stored against, creating it if this is a first visit."""
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


class AssignVariantView(APIView):
    """
    POST /api/experiments/assign/  {"experiment": "box_builder"}

    Returns the variant this visitor should see, creating a sticky assignment
    on first request. Every failure path returns control: an experiment that
    cannot answer must never stop someone buying chocolate.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = [CustomJWTAuthentication, SessionAuthentication]

    def post(self, request):
        serializer = AssignRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key = serializer.validated_data['experiment']

        experiment = Experiment.objects.filter(key=key, active=True).first()
        if experiment is None or is_bot(request):
            return Response({'variant': Experiment.CONTROL})

        session_id = _session_key(request)
        user = request.user if request.user.is_authenticated else None

        try:
            assignment, _ = Assignment.objects.get_or_create(
                experiment=experiment,
                session_id=session_id,
                defaults={'variant': experiment.pick_variant(), 'user': user},
            )
        except IntegrityError:
            # Two tabs opening at once raced us to the unique constraint. The
            # row that won is the answer.
            assignment = Assignment.objects.get(experiment=experiment, session_id=session_id)

        # Someone who logs in mid-visit keeps their variant; we just learn who
        # they are, which lets the results join reach their user-owned cart.
        if user is not None and assignment.user_id != user.id:
            assignment.user = user
            assignment.save(update_fields=['user'])

        return Response({'variant': assignment.variant})


class RecordEventView(APIView):
    """
    POST /api/experiments/event/  {"experiment": "box_builder", "name": "..."}

    Silently does nothing when the caller has no assignment — an unassigned
    visitor is not part of the experiment and inventing a row for them would
    only pollute the numbers.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes = [CustomJWTAuthentication, SessionAuthentication]

    def post(self, request):
        serializer = EventRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session_id = request.session.session_key
        if not session_id:
            return Response(status=status.HTTP_204_NO_CONTENT)

        assignment = Assignment.objects.filter(
            experiment__key=serializer.validated_data['experiment'],
            session_id=session_id,
        ).first()
        if assignment is None:
            return Response(status=status.HTTP_204_NO_CONTENT)

        Event.objects.create(assignment=assignment, name=serializer.validated_data['name'])
        return Response(status=status.HTTP_201_CREATED)


class ExperimentResultsView(APIView):
    """
    GET /api/experiments/<key>/results/

    Purchases are joined, not reported: assignment.session_id -> cart.session_id
    -> checkout session -> order. Nothing here depends on the browser having
    survived the round trip to Stripe.
    """

    permission_classes = [permissions.IsAdminUser]
    authentication_classes = [CustomJWTAuthentication, SessionAuthentication]

    def get(self, request, key):
        experiment = Experiment.objects.filter(key=key).first()
        if experiment is None:
            return Response({'detail': 'Experiment not found'}, status=status.HTTP_404_NOT_FOUND)

        assignments = list(
            experiment.assignments.values('id', 'variant', 'session_id', 'user_id')
        )

        by_session = {a['session_id']: a['variant'] for a in assignments}
        by_user = {a['user_id']: a['variant'] for a in assignments if a['user_id']}

        stats = {
            variant: {'variant': variant, 'visitors': 0, 'add_to_carts': 0, 'orders': 0, 'revenue': Decimal('0.00')}
            for variant in set(list(experiment.variants or {}) + [Experiment.CONTROL])
        }

        def bucket(variant):
            return stats.setdefault(
                variant,
                {'variant': variant, 'visitors': 0, 'add_to_carts': 0, 'orders': 0, 'revenue': Decimal('0.00')},
            )

        for assignment in assignments:
            bucket(assignment['variant'])['visitors'] += 1

        # Counted per visitor, not per click: someone adding three boxes is one
        # person who got as far as the cart.
        adders = (
            Event.objects
            .filter(assignment__experiment=experiment, name=Event.ADD_TO_CART)
            .values_list('assignment__variant', 'assignment_id')
            .distinct()
        )
        seen = defaultdict(set)
        for variant, assignment_id in adders:
            seen[variant].add(assignment_id)
        for variant, ids in seen.items():
            bucket(variant)['add_to_carts'] = len(ids)

        paid_orders = (
            Order.objects
            .filter(checkout_session__payment_status='paid')
            .select_related('checkout_session__cart', 'checkout_session__shipping_option')
            .prefetch_related('checkout_session__cart__items__product', 'checkout_session__cart__discount')
        )
        for order in paid_orders:
            cart = order.checkout_session.cart
            variant = by_session.get(cart.session_id) or by_user.get(cart.user_id)
            if variant is None:
                continue
            row = bucket(variant)
            row['orders'] += 1
            row['revenue'] += Decimal(order.checkout_session.total_with_shipping)

        results = []
        for row in sorted(stats.values(), key=lambda r: r['variant']):
            visitors = row['visitors']
            results.append({
                **row,
                'revenue': str(row['revenue'].quantize(Decimal('0.01'))),
                'add_to_cart_rate': round(row['add_to_carts'] / visitors, 4) if visitors else None,
                'order_rate': round(row['orders'] / visitors, 4) if visitors else None,
                'revenue_per_visitor': str(
                    (row['revenue'] / visitors).quantize(Decimal('0.01'))
                ) if visitors else None,
            })

        return Response({
            'key': experiment.key,
            'name': experiment.name,
            'active': experiment.active,
            'variants': results,
        })
