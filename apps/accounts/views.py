"""Signing in, and the welcome step that follows a brand new account.

Login stays a plain Django view. allauth handles the Google round trip and
nothing else, so this page - and every reverse("accounts:login") already in the
codebase - keeps working exactly as before.
"""

import logging

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import FormView

from apps.accounts.forms import OnboardingForm
from apps.organizations.services import create_organization_for

logger = logging.getLogger(__name__)


class LoginView(auth_views.LoginView):
    """The email + password form, plus a Google button when it is configured."""

    # Somebody already signed in who lands here (a stale bookmark, the browser
    # back button) should go to their dashboard, not be asked to sign in again.
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Hide the button rather than show one that can only fail: without
        # credentials in the environment, Google sign-in is not set up here.
        context["google_enabled"] = bool(settings.GOOGLE_OAUTH_CLIENT_ID)
        return context


class OnboardingView(LoginRequiredMixin, FormView):
    """The first screen a new account sees: name your business.

    Reached by redirect from OnboardingMiddleware, so it has to be able to send
    people away again - anyone who already belongs to a business has no reason
    to be here.
    """

    template_name = "accounts/onboarding.html"
    form_class = OnboardingForm
    success_url = reverse_lazy(settings.LOGIN_REDIRECT_URL)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)  # LoginRequiredMixin handles it
        # Belonging to a business is the test, not request.organization: a
        # member of a switched-off business must not be able to create a
        # second one by walking onto this URL.
        if request.user.memberships.exists():
            return redirect(settings.LOGIN_REDIRECT_URL)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        create_organization_for(self.request.user, form.cleaned_data["name"])
        return super().form_valid(form)
