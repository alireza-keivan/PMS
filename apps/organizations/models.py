"""The tenant boundary.

One Organization is one client operator running 3-15 villas. Every piece of
client data hangs off it, and the sync tier is set here because it determines
how honest the UI has to be about what the data actually is.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class Organization(TimeStampedModel):
    class SyncTier(models.TextChoices):
        # Beds24 API: near-real-time, full guest details, pricing, messaging.
        PREMIUM = "premium", _("Connected accounts")
        # iCal feeds: one-way, refreshed every few hours by the OTA, dates only.
        BASIC = "basic", _("Calendar links only")

    class PlanTier(models.TextChoices):
        STARTER = "starter", _("Starter")
        GROWTH = "growth", _("Growth")
        PRO = "pro", _("Pro")

    # How many villas each plan allows. No billing behind this yet - an admin
    # sets the tier by hand until real subscription management exists - but
    # the limit itself is real and enforced, not just decorative. Sized to
    # the operator range this product targets - see CLAUDE.md.
    PLAN_VILLA_LIMITS = {
        PlanTier.STARTER: 5,
        PlanTier.GROWTH: 10,
        PlanTier.PRO: 15,
    }

    name = models.CharField(max_length=160)
    slug = models.SlugField(unique=True)
    sync_tier = models.CharField(
        max_length=10, choices=SyncTier.choices, default=SyncTier.BASIC
    )
    plan = models.CharField(max_length=10, choices=PlanTier.choices, default=PlanTier.STARTER)
    default_currency = models.CharField(
        max_length=3,
        default="IDR",
        help_text=_("Currency the owner wants reports displayed in."),
    )
    whatsapp_number = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def has_live_sync(self) -> bool:
        """Whether booking data is near-real-time and complete.

        Gate any UI that claims freshness or shows guest names, pricing or
        messages on this. On the basic tier those fields are simply absent, and
        presenting stale availability as live is the exact failure this product
        exists to prevent.
        """
        return self.sync_tier == self.SyncTier.PREMIUM

    @property
    def villa_limit(self) -> int:
        return self.PLAN_VILLA_LIMITS[self.plan]

    @property
    def can_add_villa(self) -> bool:
        """Half-finished villas don't count - somebody part-way through the
        add form has not used up one of their paid slots yet.
        """
        return self.villas.live().count() < self.villa_limit


class Membership(TimeStampedModel):
    """Which people can see which operator's data.

    Manager vs. Staff is a Django Group (see apps.organizations.permissions),
    not a field here - this model only ties a user to an organization and,
    for Staff, to the specific villas they're allowed to see.
    """

    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="memberships"
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    villas = models.ManyToManyField(
        "villas.Villa",
        blank=True,
        related_name="assigned_members",
        help_text=_("Staff only. Leave empty for access to every villa."),
    )

    class Meta:
        unique_together = [("user", "organization")]

    def __str__(self):
        return f"{self.user} @ {self.organization}"
