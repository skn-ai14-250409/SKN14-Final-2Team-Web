from django.urls import path
from django.views.generic import TemplateView
from . import views
from django.shortcuts import redirect
import json
from django.http import JsonResponse
from django.contrib.auth.models import User

app_name = "uauth"


def logout_redirect(request):
    return redirect('account_logout')


def check_username(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        username = data.get('username')
        available = not User.objects.filter(username=username).exists()
        return JsonResponse({'available': available})
    return JsonResponse({'available': False})


urlpatterns = [
    path("profile/completion/", views.complete_profile, name="complete_profile"),
    path("login/", views.login_view, name="login"),
    path("register/", views.register, name="register"),
    path("check-username/", check_username, name="check_username"),
    path("login/redirect/",
         TemplateView.as_view(template_name="account/login_redirect.html"),
         name="login_redirect"),
    path("logout/", logout_redirect, name="logout"),
    path("mypage/", views.mypage, name="mypage"),
]