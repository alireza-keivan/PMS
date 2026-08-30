"""Language-switch link helper.

i18n_patterns gives English pages no prefix and Indonesian pages a /id/
prefix, and the prefix always wins over the language cookie - see
apps.organizations.middleware for the tenant-scoping equivalent of this kind
of per-request resolution. That means a plain request.get_full_path() as the
switcher's "next" value resubmits whatever prefix the browser is already on:
clicking EN while on /id/villas/ sets the cookie to "en" but redirects back to
that same /id/ URL, which is still Indonesian regardless of the cookie.
translate_url() rewrites the path's prefix instead of carrying it over.
"""

from django import template
from django.urls import translate_url

register = template.Library()


@register.simple_tag(takes_context=True)
def language_url(context, language_code):
    request = context["request"]
    return translate_url(request.get_full_path(), language_code)
