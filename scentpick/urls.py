from django.urls import path
from . import views

app_name = 'scentpick'

urlpatterns = [
    path('', views.home, name='home'),
    path('chat/', views.chat, name='chat'),
    path('recommend/', views.recommend, name='recommend'),
    path('perfumes/', views.perfumes, name='perfumes'),
    path('perfume/<int:perfume_id>/', views.product_detail, name='product_detail'),
    path('scentpick/api/toggle-favorite/', views.toggle_favorite, name='toggle_favorite'),
    path('scentpick/api/toggle-like-dislike/', views.toggle_like_dislike, name='toggle_like_dislike'),
    path('offlines/', views.offlines, name='offlines'),
    path('mypage/', views.mypage, name='mypage'),
    path('mypage/profile/', views.profile_edit, name='profile_edit'),
    path('mypage/password/', views.password_change_view, name='password_change'),
    path("api/chat", views.chat_submit_api, name="chat_submit_api"),
]