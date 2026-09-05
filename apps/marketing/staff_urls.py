"""Staff-facing marketing management - rate parity, experiences and referral
commissions. Deliberately a separate module from apps.marketing.urls, which
serves the public, unauthenticated villa pages: mixing session-authenticated
and public views in one urls module makes it too easy for a future edit to
put an internal view on a public path by mistake.
"""

from django.urls import path

from apps.marketing.staff_views import MarketingOverviewView

app_name = "marketing_admin"

urlpatterns = [
    path("", MarketingOverviewView.as_view(), name="overview"),
]
