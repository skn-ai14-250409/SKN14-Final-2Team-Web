"""
ASGI config for django_app project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/
"""

import os
from pathlib import Path

from django.conf import settings
from django.core.asgi import get_asgi_application
from blacknoise import BlackNoise

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_app.settings')

application = get_asgi_application()

# blacknoise(asgi전용) 설정
application = BlackNoise(get_asgi_application())
application.add(settings.BASE_DIR / "static", "/static")