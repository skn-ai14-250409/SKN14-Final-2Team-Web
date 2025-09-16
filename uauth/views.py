# uauth/views.py
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate
from django.contrib.auth.models import User
from django.contrib import messages
from .models import UserDetail
from .utils import process_profile_image, upload_to_s3_and_get_url
import imghdr
from django.utils.http import url_has_allowed_host_and_scheme

@login_required
def complete_profile(request):
    detail = request.user.detail
    if request.method == "POST":
        detail.gender = request.POST.get("gender")
        detail.birth_year = request.POST.get("birth_year")

        # 프로필 이미지 처리 (선택 입력)
        file = request.FILES.get("profile_image")
        if file:
            try:
                # content_type 우선 검사, 미지원/없음이면 imghdr 보조 검사
                ctype = getattr(file, "content_type", "").lower()
                allowed_ct = {"image/jpeg", "image/png", "image/gif"}
                if ctype not in allowed_ct:
                    file.seek(0)
                    kind = (imghdr.what(file) or "").lower()
                    if kind == "jpg":
                        kind = "jpeg"
                    if kind not in {"jpeg", "png", "gif"}:
                        raise ValueError("지원 형식은 JPG/PNG/GIF 입니다.")

                crop = {
                    "x": request.POST.get("crop_x"),
                    "y": request.POST.get("crop_y"),
                    "size": request.POST.get("crop_size"),
                    "scale": request.POST.get("crop_scale"),
                }
                file.seek(0)
                image_bytes = process_profile_image(file, crop=crop)
                url = upload_to_s3_and_get_url(request.user.id, image_bytes, ext="jpg")
                detail.profile_image_url = url
            except Exception as e:
                return render(request, "uauth/complete_profile.html", {"detail": detail, "error": str(e)})

        detail.save()
        return redirect("/chat/")  # 저장 후 메인 페이지로 이동
    return render(request, "uauth/complete_profile.html", {"detail": detail})

def login_view(request):
    next_url = request.GET.get("next") or request.POST.get("next", "")
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        
        if username and password:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                    return redirect(next_url)
                messages.success(request, "로그인되었습니다.")
                return redirect("/")  # 메인 페이지로 리디렉션
            else:
                return render(request, "uauth/login.html", {
                    "error": "아이디 또는 비밀번호가 올바르지 않습니다.",
                    "form_data": request.POST
                })
        else:
            return render(request, "uauth/login.html", {
                "error": "아이디와 비밀번호를 모두 입력하세요.",
                "form_data": request.POST
            })
    
    return render(request, "uauth/login.html", {"next": next_url})

def register(request):
    if request.method == "POST":
        # 폼 데이터 받기
        username = request.POST.get("username")
        password1 = request.POST.get("password1")
        password2 = request.POST.get("password2")
        name = request.POST.get("name")
        email = request.POST.get("email")
        birth_year = request.POST.get("birth_year")
        gender = request.POST.get("gender")
        file = request.FILES.get("profile_image")
        
        # 유효성 검사
        errors = []
        
        if not username:
            errors.append("아이디를 입력하세요.")
        elif User.objects.filter(username=username).exists():
            errors.append("이미 존재하는 아이디입니다.")
            
        if not password1:
            errors.append("비밀번호를 입력하세요.")
        elif len(password1) < 8:
            errors.append("비밀번호는 8자 이상이어야 합니다.")
            
        if password1 != password2:
            errors.append("비밀번호가 일치하지 않습니다.")
            
        if not name:
            errors.append("이름을 입력하세요.")
            
        if not email:
            errors.append("이메일을 입력하세요.")
            
        if not birth_year:
            errors.append("출생연도를 입력하세요.")
        else:
            try:
                birth_year = int(birth_year)
                if birth_year < 1900 or birth_year > 2100:
                    errors.append("올바른 출생연도를 입력하세요.")
            except ValueError:
                errors.append("올바른 출생연도를 입력하세요.")
                
        if not gender:
            errors.append("성별을 선택하세요.")
            
        # 오류가 있으면 다시 폼 표시
        if errors:
            return render(request, "uauth/register.html", {
                "errors": errors,
                "form_data": request.POST
            })

        # 사용자 생성만 try로 감싸 안정성 향상
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password1
            )
        except Exception:
            messages.error(request, "회원가입 중 오류가 발생했습니다.")
            return render(request, "uauth/register.html", {"error": "회원가입 중 오류가 발생했습니다.", "form_data": request.POST})

        # UserDetail 생성 (여기서 예외 발생 가능성 낮음)
        detail, _ = UserDetail.objects.get_or_create(user=user)
        detail.name = name
        detail.gender = gender
        detail.birth_year = birth_year
        detail.save()

        # 프로필 이미지 처리 (실패해도 가입은 진행)
        if file:
            try:
                # 우선 content_type으로 판별, 실패시 imghdr 보조 사용
                ctype = getattr(file, "content_type", "").lower()
                allowed_ct = {"image/jpeg", "image/png", "image/gif"}
                if ctype not in allowed_ct:
                    # 일부 브라우저가 제공하지 않는 경우 대비
                    file.seek(0)
                    kind = (imghdr.what(file) or "").lower()
                    if kind == "jpg":
                        kind = "jpeg"
                    if kind not in {"jpeg", "png", "gif"}:
                        raise ValueError("지원 형식은 JPG/PNG/GIF 입니다.")

                crop = {
                    "x": request.POST.get("crop_x"),
                    "y": request.POST.get("crop_y"),
                    "size": request.POST.get("crop_size"),
                    "scale": request.POST.get("crop_scale"),
                }
                # 파일 포인터 초기화 후 처리
                file.seek(0)
                image_bytes = process_profile_image(file, crop=crop)
                url = upload_to_s3_and_get_url(user.id, image_bytes, ext="jpg")
                detail.profile_image_url = url
                detail.save()
            except Exception as e:
                messages.warning(request, f"프로필 이미지 처리 중 오류: {e}")

        # 자동 로그인 (실패 시 로그인 페이지 유도)
        auth_user = authenticate(username=username, password=password1)
        if auth_user:
            login(request, auth_user)
            messages.success(request, "회원가입이 완료되었습니다.")
            return redirect("/chat/")
        messages.info(request, "가입 완료. 로그인 후 이용해주세요.")
        return redirect("/accounts/login/")
    
    return render(request, "uauth/register.html")

def mypage(request):
    return render(request, "uauth/mypage.html")
