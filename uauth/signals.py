from allauth.account.signals import user_signed_up
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserDetail


@receiver(user_signed_up)
def create_user_detail_on_social_signup(request, user, sociallogin=None, **kwargs):
    detail, _ = UserDetail.objects.get_or_create(user=user)
    if sociallogin is not None:
        provider = sociallogin.account.provider
        extra = sociallogin.account.extra_data or {}

        if provider == "naver":
            detail.gender = extra.get("gender") or detail.gender
            if "birthyear" in extra:
                try:
                    detail.birth_year = int(extra.get("birthyear"))
                except Exception:
                    pass
            detail.name = extra.get("name") or detail.name or user.username

        elif provider == "kakao":
            kakao_account = extra.get("kakao_account", {})
            profile = kakao_account.get("profile", {})
            detail.name = profile.get("nickname") or detail.name or user.username

        elif provider == "google":
            detail.name = extra.get("name") or detail.name or user.username

        detail.save()


@receiver(post_save, sender=User)
def ensure_user_detail(sender, instance: User, created: bool, **kwargs):
    detail, _ = UserDetail.objects.get_or_create(user=instance)
    if not detail.name:
        full = " ".join(part for part in [instance.first_name, instance.last_name] if part).strip()
        if full:
            detail.name = full
            detail.save(update_fields=["name"])

