from django.shortcuts import render

def home(request):
    return render(request, "scentpick/home.html")

def login_view(request):
    return render(request, "scentpick/login.html")

def register(request):
    return render(request, "scentpick/register.html")

def chat(request):
    return render(request, "scentpick/chat.html")

def recommend(request):
    return render(request, "scentpick/recommend.html")

def perfumes(request):
    return render(request, "scentpick/perfumes.html")

def product_detail(request, slug):
    # TODO: slug로 DB 조회 후 컨텍스트 바인딩
    ctx = {
        "brand": "Chanel",
        "name": "블루 드 샤넬",
        "price": "₩165,000",
        "slug": slug,
    }
    return render(request, "scentpick/product_detail.html", ctx)

def offlines(request):
    return render(request, "scentpick/offlines.html")

def mypage(request):
    return render(request, "scentpick/mypage.html")