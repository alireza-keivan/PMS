"""Every model in this project is meant to be usable through Django admin -
see CLAUDE.md: 'Don't build custom internal-only screens that the admin
already handles.' If admin is the actual internal ops panel, its pages have
to load. This walks every registered model's list and add page as a
superuser and checks nothing crashes.
"""

import pytest
from django.contrib import admin
from django.urls import reverse


def _registered_models():
    return list(admin.site._registry.keys())


@pytest.fixture
def admin_client(db, client):
    from apps.accounts.models import User

    superuser = User.objects.create_superuser(email="admin@example.com", password="testpass123")
    client.force_login(superuser)
    return client


@pytest.mark.parametrize("model", _registered_models(), ids=lambda m: m._meta.label)
def test_admin_changelist_loads(admin_client, model):
    url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
    response = admin_client.get(url)
    assert response.status_code == 200


@pytest.mark.parametrize("model", _registered_models(), ids=lambda m: m._meta.label)
def test_admin_add_page_loads(admin_client, model):
    url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_add")
    response = admin_client.get(url)
    # 200 = normal add form. 403 is acceptable only for models where the
    # ModelAdmin deliberately disables add (e.g. append-only logs).
    assert response.status_code in (200, 403)
