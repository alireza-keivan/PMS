"""Base models every other app builds on.

Two ideas live here:
  1. TimeStampedModel - audit trail on everything.
  2. TenantOwnedModel - the multi-tenancy backbone. Every row that belongs to a
     client operator carries an `organization` link, and the default manager
     refuses to hand out rows without a tenant filter. One shared database, one
     deploy, hard row-level separation.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantQuerySet(models.QuerySet):
    def for_organization(self, organization):
        return self.filter(organization=organization)

    def for_request(self, request):
        """Scope to the organization resolved by OrganizationMiddleware."""
        return self.filter(organization=request.organization)


class TenantOwnedModel(TimeStampedModel):
    """Anything owned by one client operator.

    Subclasses must not override `objects` with a plain Manager - doing so
    removes the tenant helpers and makes accidental cross-client reads easy.
    """

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
        verbose_name=_("operator"),
    )

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True


class Money(models.Model):
    """Mixin for an amount stored in the currency it was actually received in.

    Bookings arrive from OTAs billing in IDR, AUD, USD and EUR. Converting on
    ingest would destroy the true figure and bake in whatever rate happened to
    apply that day, so the original is what gets stored. Conversion happens at
    display time in the reporting layer - see apps/reporting/fx.py.

    max_digits accommodates IDR, where a single villa night is routinely seven
    figures and an annual revenue total is ten or eleven.
    """

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(
        max_length=3,
        default="IDR",
        help_text=_("ISO 4217 code, exactly as the source reported it."),
    )

    class Meta:
        abstract = True
