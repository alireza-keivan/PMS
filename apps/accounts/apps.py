from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    verbose_name = "Accounts"

    def ready(self):
        # Connects the sign-in / sign-out / failed-attempt log lines.
        from apps.accounts import signals  # noqa: F401
