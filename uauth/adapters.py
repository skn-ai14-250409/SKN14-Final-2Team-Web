from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.urls import reverse
from urllib.parse import urlencode
from django.utils.http import url_has_allowed_host_and_scheme


def _redir_with_next(next_url: str | None = None) -> str:
    base = reverse("account_login_redirect")
    if next_url:
        return f"{base}?{urlencode({'next': next_url})}"
    return base


class CustomAccountAdapter(DefaultAccountAdapter):
    def get_login_redirect_url(self, request):
        user = request.user
        provider = request.session.get("socialaccount_provider")

        needs_completion = (
            not hasattr(user, "detail")
            or not user.detail.gender
            or not user.detail.birth_year
        )

        if provider in ["google", "kakao"] and needs_completion:
            target = reverse("uauth:complete_profile")
        else:
            target = "/chat/"

        requested_next = (
            request.GET.get("next")
            or request.POST.get("next")
            or request.session.get("next")
        )
        final_target = (
            requested_next
            if requested_next and url_has_allowed_host_and_scheme(requested_next, allowed_hosts={request.get_host()}, require_https=request.is_secure())
            else target
        )
        return _redir_with_next(final_target)


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        request.session["socialaccount_provider"] = sociallogin.account.provider

    def get_login_redirect_url(self, request):
        user = request.user
        provider = request.session.get("socialaccount_provider")

        needs_completion = (
            not hasattr(user, "detail")
            or not user.detail.gender
            or not user.detail.birth_year
        )

        if provider in ["google", "kakao"] and needs_completion:
            target = reverse("uauth:complete_profile")
        else:
            target = reverse("home")

        requested_next = (
            request.GET.get("next")
            or request.POST.get("next")
            or request.session.get("next")
        )
        final_target = (
            requested_next
            if requested_next and url_has_allowed_host_and_scheme(requested_next, allowed_hosts={request.get_host()}, require_https=request.is_secure())
            else target
        )
        return _redir_with_next(final_target)

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        extra_data = sociallogin.account.extra_data
        if not user.email:
            user.email = extra_data.get("email", "")
            user.save()
        return user