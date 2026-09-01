"""Which villas the logged-in user may see, in the current organization.

Lives here rather than on any one feature app since bookings, compliance,
guests, and villas all need it - see apps.organizations.models.Membership.
"""

from apps.organizations.permissions import is_manager
from apps.villas.models import Villa


def scoped_villas(request):
    """Active villas the logged-in user may see. Staff scoped to specific
    villas (Membership.villas) only see those; an empty M2M for staff means
    unrestricted, per that field's own help text. Managers always see every
    active villa.
    """
    org = request.organization
    membership = request.user.memberships.get(organization=org)
    villas = Villa.objects.filter(organization=org).live()
    if not is_manager(request.user) and membership.villas.exists():
        villas = villas.filter(id__in=membership.villas.values_list("id", flat=True))
    return list(villas.order_by("name")), membership
