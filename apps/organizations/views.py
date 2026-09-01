"""Team management: the screen a Manager uses to add and re-scope Staff.

Staff accounts are always created fresh from here, never linked from an
existing account - see EmailAlreadyInUse in apps.organizations.services for
why: Manager-vs-Staff is a Group on the User, global across every
organization they belong to, so reusing an email that already has an
account risks quietly making that person a Manager here too (or, the same
bug the other way round, a person who is legitimately a Manager of their own
business elsewhere would keep that global status if reused as "Staff" in a
second organization).
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView, ListView

from apps.organizations.forms import StaffCreateForm, StaffVillasForm
from apps.organizations.mixins import ManagerRequiredMixin
from apps.organizations.models import Membership
from apps.organizations.permissions import is_manager
from apps.organizations.services import EmailAlreadyInUse, create_staff_for, update_staff_villas
from apps.villas.models import Villa


class StaffListView(ManagerRequiredMixin, ListView):
    template_name = "organizations/staff_list.html"
    context_object_name = "memberships"

    def get_queryset(self):
        return (
            Membership.objects.filter(organization=self.request.organization)
            .select_related("user")
            .prefetch_related("villas")
            .order_by("user__full_name", "user__email")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for membership in context["memberships"]:
            membership.is_manager_member = is_manager(membership.user)
        return context


class StaffCreateView(ManagerRequiredMixin, FormView):
    template_name = "organizations/staff_form.html"
    form_class = StaffCreateForm
    success_url = reverse_lazy("organizations:staff_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["villa_queryset"] = Villa.objects.filter(organization=self.request.organization).live()
        return kwargs

    def form_valid(self, form):
        try:
            create_staff_for(
                self.request.organization,
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
                full_name=form.cleaned_data["full_name"],
                villas=form.cleaned_data["villas"],
            )
        except EmailAlreadyInUse:
            form.add_error(
                "email",
                _("Someone already has an account with this email. Use a different email for this staff member."),
            )
            return self.form_invalid(form)

        messages.success(self.request, _("Staff account created."))
        return super().form_valid(form)


class StaffVillasView(ManagerRequiredMixin, FormView):
    """Change which villas an existing staff member can see."""

    template_name = "organizations/staff_villas_form.html"
    form_class = StaffVillasForm
    success_url = reverse_lazy("organizations:staff_list")

    def dispatch(self, request, *args, **kwargs):
        self.membership = get_object_or_404(
            Membership, pk=kwargs["pk"], organization=request.organization
        )
        if is_manager(self.membership.user):
            # Managers see every villa already - there's nothing here to edit.
            return redirect("organizations:staff_list")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["villa_queryset"] = Villa.objects.filter(organization=self.request.organization).live()
        kwargs["initial"] = {"villas": self.membership.villas.all()}
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["membership"] = self.membership
        return context

    def form_valid(self, form):
        update_staff_villas(self.membership, form.cleaned_data["villas"])
        messages.success(self.request, _("Villa access updated."))
        return super().form_valid(form)
