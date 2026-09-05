"""Staff-facing marketing management - rate parity, experiences and referral
commissions. Kept apart from apps.marketing.views, which serves the public,
unauthenticated villa pages - see that module's docstring for why.
"""

from django.shortcuts import render
from django.urls import reverse
from django.views.generic import View

from apps.organizations.mixins import ManagerRequiredMixin
from apps.organizations.scoping import scoped_villas


class MarketingOverviewView(ManagerRequiredMixin, View):
    """Landing page for the Marketing section - one villa's mini-website
    status per row, so a manager with several villas can turn each on or
    off from a single screen instead of hunting through each villa's own
    activities page.
    """

    template_name = "marketing/overview.html"

    def get(self, request):
        villas, _membership = scoped_villas(request)
        rows = []
        for villa in villas:
            website_path = reverse(
                "marketing:villa_page",
                args=[villa.organization.slug, villa.slug],
            )
            rows.append({
                "villa": villa,
                "website_url": request.build_absolute_uri(website_path),
                "website_missing_requirements": villa.website_missing_requirements(),
            })
        return render(request, self.template_name, {"villa_rows": rows})
