"""Nationality choices for `Guest.nationality`.

ISO 3166-1 alpha-2 codes, since that's what the field stores (required for the
STM police report - see Guest's docstring). Not the full ~250-country ISO
list - just the nationalities that actually show up booking Bali villas today,
so the dropdown stays short enough to scan rather than needing a search box.
Indonesian is listed first since it's the most common answer and the one that
turns the STM reminder off (see PoliceReport - a report is only needed for
foreign guests).

A guest from a country not on this list is simply left blank on file and can
be filled in later - see the Add Reservation form's soft handling of a blank
nationality (CLAUDE.md rule 2: nothing here should claim more than it knows).
"""

from django.utils.translation import gettext_lazy as _

NATIONALITY_CHOICES = [
    ("ID", _("Indonesian")),
    ("AU", _("Australian")),
    ("US", _("American")),
    ("GB", _("British")),
    ("DE", _("German")),
    ("FR", _("French")),
    ("NL", _("Dutch")),
    ("RU", _("Russian")),
    ("JP", _("Japanese")),
    ("KR", _("South Korean")),
    ("SG", _("Singaporean")),
    ("MY", _("Malaysian")),
    ("CN", _("Chinese")),
    ("HK", _("Hong Kong")),
    ("TW", _("Taiwanese")),
    ("IN", _("Indian")),
    ("PH", _("Filipino")),
    ("TH", _("Thai")),
    ("VN", _("Vietnamese")),
    ("CA", _("Canadian")),
    ("ES", _("Spanish")),
    ("IT", _("Italian")),
    ("PT", _("Portuguese")),
    ("SE", _("Swedish")),
    ("NO", _("Norwegian")),
    ("DK", _("Danish")),
    ("FI", _("Finnish")),
    ("CH", _("Swiss")),
    ("AT", _("Austrian")),
    ("BE", _("Belgian")),
    ("IE", _("Irish")),
    ("PL", _("Polish")),
    ("BR", _("Brazilian")),
    ("MX", _("Mexican")),
    ("AR", _("Argentinian")),
    ("ZA", _("South African")),
    ("NZ", _("New Zealander")),
    ("AE", _("Emirati")),
    ("SA", _("Saudi Arabian")),
    ("IL", _("Israeli")),
    ("TR", _("Turkish")),
    ("UA", _("Ukrainian")),
]
