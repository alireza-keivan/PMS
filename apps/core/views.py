"""Shared views used by more than one app.

ComingSoonView exists so the sidebar can show the product's full, final shape
now - every section a user will eventually have - without each app needing
its own throwaway placeholder view before the real one is built.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class ComingSoonView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/coming_soon.html"
