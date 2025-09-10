from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator


class UserDetail(models.Model):
    """
    Per-user profile info extending Django auth_user via 1:1.
    Stored in table named "users" for backward compatibility.
    Primary key equals auth_user.id.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column="id",
        related_name="detail",
    )

    name = models.CharField(max_length=60, blank=True, null=True)
    gender = models.CharField(max_length=10, blank=True, null=True)
    birth_year = models.IntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1900), MaxValueValidator(2100)],
    )

    profile_image_url = models.URLField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "users"
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["gender"]),
            models.Index(fields=["created_at"]),
        ]
        verbose_name = "User Detail"
        verbose_name_plural = "User Details"

    def __str__(self):
        base = self.name or (self.user.email or self.user.username)
        return f"{base} (#{self.pk})"

    @property
    def avatar_url(self) -> str:
        base = "https://scentpick-images.s3.ap-northeast-2.amazonaws.com/profiles/default.jpg"
        if self.profile_image_url:
            try:
                ts = int(self.updated_at.timestamp()) if self.updated_at else 0
            except Exception:
                ts = 0
            sep = '&' if '?' in self.profile_image_url else '?'
            return f"{self.profile_image_url}{sep}v={ts}"
        return base