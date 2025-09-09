from django.shortcuts import render

def login_view(request):
    return render(request, "uauth/login.html")

def register(request):
    return render(request, "uauth/register.html")