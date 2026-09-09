import random

from django.conf import settings
from django.db import models


class Experiment(models.Model):
    """
    One A/B test.

    Kept deliberately small: the interesting data is the join from an
    assignment's session to the order that session eventually paid for, and
    that join needs nothing more than a stable variant per visitor.
    """

    key = models.SlugField(
        max_length=64,
        unique=True,
        help_text="Referenced by the front end, e.g. 'box_builder'.",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    active = models.BooleanField(
        default=True,
        help_text=(
            "The kill switch. Turned off, no new assignments are made and every "
            "visitor falls back to the control variant — including visitors "
            "already assigned to another one."
        ),
    )

    variants = models.JSONField(
        default=dict,
        help_text=(
            'Variant name to relative weight, e.g. {"control": 50, "quick": 50}. '
            'One variant must be named "control": it is what everyone gets if '
            "anything at all goes wrong."
        ),
    )

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    CONTROL = 'control'

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return f'{self.key} ({"active" if self.active else "off"})'

    def pick_variant(self) -> str:
        """Weighted random choice. Falls back to control on any bad config."""
        weights = {
            name: float(weight)
            for name, weight in (self.variants or {}).items()
            if float(weight) > 0
        }
        if not weights:
            return self.CONTROL
        names = list(weights)
        return random.choices(names, weights=[weights[n] for n in names], k=1)[0]


class Assignment(models.Model):
    """
    Which variant one visitor saw.

    Keyed on the Django session, which is the same key carts use
    (carts.managers.CartManager._get_or_create_session_cart). That is what
    makes the purchase side of the funnel a database join rather than a
    client-side event a consent banner or an ad blocker could swallow.
    """

    experiment = models.ForeignKey(Experiment, related_name='assignments', on_delete=models.CASCADE)
    session_id = models.CharField(max_length=255, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    variant = models.CharField(max_length=64)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created']
        constraints = [
            # One variant per visitor per experiment. Without this a visitor
            # could be re-bucketed on a reload and appear in both arms.
            models.UniqueConstraint(
                fields=['experiment', 'session_id'], name='unique_assignment_per_session'
            )
        ]

    def __str__(self):
        return f'{self.experiment.key}={self.variant} ({self.session_id[:8]})'


class Event(models.Model):
    """
    A funnel step the server cannot observe on its own.

    Purchases are deliberately NOT recorded here — they are derived from the
    order tables, which cannot be lost in the redirect to Stripe.
    """

    ADD_TO_CART = 'builder_add_to_cart'

    assignment = models.ForeignKey(Assignment, related_name='events', on_delete=models.CASCADE)
    name = models.CharField(max_length=64)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created']
        indexes = [models.Index(fields=['assignment', 'name'])]

    def __str__(self):
        return f'{self.name} ({self.assignment_id})'
