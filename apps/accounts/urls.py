from django.contrib.auth import views as auth_views
from django.urls import path

from apps.accounts import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Shown once, right after a new account is created with Google.
    path("welcome/", views.OnboardingView.as_view(), name="onboarding"),
    # Left as it was: nothing links here yet and it still needs its own
    # templates and an email backend before it can work.
    path("password-reset/", auth_views.PasswordResetView.as_view(), name="password_reset"),
]
