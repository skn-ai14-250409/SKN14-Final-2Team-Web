from django.urls import path
from . import views

app_name = 'scentpick'

urlpatterns = [
    path('', views.home, name='home'),
    path('chat/', views.chat, name='chat'),
    path('recommend/', views.recommend, name='recommend'),
    path('perfumes/', views.perfumes, name='perfumes'),
    path('product/<slug:slug>/', views.product_detail, name='product_detail'),
    path('offlines/', views.offlines, name='offlines'),
    path('mypage/', views.mypage, name='mypage'),
    path('mypage/profile/', views.profile_edit, name='profile_edit'),
    path('mypage/password/', views.password_change_view, name='password_change'),
]