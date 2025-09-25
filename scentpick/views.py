# --- Python 표준 라이브러리 ---
import os
import uuid
import json
import re
import random
import imghdr
from datetime import datetime
from zoneinfo import ZoneInfo

# --- 외부 라이브러리 ---
import requests
import boto3

# --- Django 기본 ---
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q, Count, Max  # yyh : Count, Max 추가
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt

# --- 프로젝트 내부 (app) ---
from .models import (
    Perfume,
    Favorite,
    FeedbackEvent,
    NoteImage,
    Conversation,
    Message,
    RecRun,
    RecCandidate,
)
from uauth.models import UserDetail
from uauth.utils import process_profile_image, upload_to_s3_and_get_url

from .utils.note_translations import get_korean_note_name, get_english_note_name

# S3 클라이언트 전역 설정
s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    region_name=settings.AWS_S3_REGION_NAME,
)

def home(request):
    return render(request, "scentpick/home.html")

def login_view(request):
    return render(request, "scentpick/login.html")

def register(request):
    return render(request, "scentpick/register.html")

@login_required
def chat(request):
    """
    Chat 페이지: conversations DB에서 대화 목록과 메시지들을 읽어서 표시
    """
    # 전체 대화 목록 (프론트에서 스크롤로 제한)
    recent_conversations = Conversation.objects.filter(
        user=request.user
    ).order_by('-updated_at')
    
    # 현재 선택된 대화 ID (세션 또는 GET 파라미터에서)
    current_conversation_id = request.GET.get('conversation_id') or request.session.get('conversation_id')
    current_conversation = None
    messages = []
    
    if current_conversation_id:
        try:
            current_conversation = Conversation.objects.get(
                id=current_conversation_id, 
                user=request.user
            )
            # 해당 대화의 메시지들 가져오기 (추천 데이터 포함)
            messages_raw = current_conversation.messages.order_by('created_at')
            messages = []
            
            for m in messages_raw:
                message_data = {
                    'role': m.role,
                    'content': m.content,
                    'created_at': m.created_at,
                    'chat_image': getattr(m, 'chat_image', None),  # 안전한 이미지 URL 접근
                    'perfume_list': []
                }
                
                # assistant 메시지인 경우 관련된 추천 데이터 찾기
                if m.role == 'assistant':
                    rec_runs = RecRun.objects.filter(
                        conversation=current_conversation,
                        request_msg__created_at__lte=m.created_at
                    ).order_by('-created_at')
                    
                    if rec_runs.exists():
                        latest_run = rec_runs.first()
                        candidates = latest_run.candidates.select_related('perfume').order_by('rank')
                        
                        perfume_list = []
                        for candidate in candidates:
                            perfume_list.append({
                                'id': candidate.perfume.id,
                                'brand': candidate.perfume.brand,
                                'name': candidate.perfume.name,
                                'rank': candidate.rank,
                                'score': candidate.score
                            })
                        
                        if perfume_list:
                            message_data['perfume_list'] = perfume_list
                
                messages.append(message_data)
            
            # 세션에 저장
            request.session['conversation_id'] = current_conversation.id
        except Conversation.DoesNotExist:
            current_conversation_id = None
            messages = []
    
    return render(request, "scentpick/chat.html", {
        "recent_conversations": recent_conversations,
        "current_conversation": current_conversation,
        "current_conversation_id": current_conversation_id,
        "chat_messages": json.dumps(messages, default=str, ensure_ascii=False),  # JSON으로 직렬화
        "SERVICE_TOKEN": SERVICE_TOKEN,
    })

@login_required
def perfumes(request):
    q = (request.GET.get("q") or "").strip()
    brand_sel = request.GET.getlist("brand")
    size_sel = request.GET.getlist("size")
    gender_sel = request.GET.getlist("gender")
    conc_sel = request.GET.getlist("conc")
    accord_sel = request.GET.getlist("accord")

    qs = Perfume.objects.all()

    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(brand__icontains=q)
            | Q(description__icontains=q)
            | Q(main_accords__icontains=q)
            | Q(top_notes__icontains=q)
            | Q(middle_notes__icontains=q)
            | Q(base_notes__icontains=q)
        )

    if brand_sel:
        qs = qs.filter(brand__in=brand_sel)

    if size_sel:
        size_q = Q()
        for s in size_sel:
            try:
                s_int = int(s)
                size_q |= Q(sizes__contains=s_int)
            except ValueError:
                pass
        if size_q:
            qs = qs.filter(size_q)

    if gender_sel:
        gq = Q()
        for g in gender_sel:
            gq |= Q(gender__iexact=g)
        if gq:
            qs = qs.filter(gq)

    if conc_sel:
        cq = Q()
        for c in conc_sel:
            cq |= Q(concentration__icontains=c)
        if cq:
            qs = qs.filter(cq)

    if accord_sel:
        aq = Q()
        for a in accord_sel:
            aq |= Q(main_accords__icontains=a)
        if aq:
            qs = qs.filter(aq)

    qs = qs.order_by("brand", "name")

    paginator = Paginator(qs, 24)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    current = page_obj.number
    total = paginator.num_pages
    page_range_custom = []

    if total <= 10:
        page_range_custom = list(range(1, total + 1))
    else:
        if current <= 6:
            page_range_custom = list(range(1, 7)) + ["...", total]
        elif current >= total - 5:
            page_range_custom = [1, "..."] + list(range(total - 5, total + 1))
        else:
            page_range_custom = [1, "..."] + list(range(current - 2, current + 3)) + ["...", total]

    for p in page_obj.object_list:
        raw = p.main_accords or ""
        if isinstance(raw, list):
            toks = [str(t).strip() for t in raw]
        elif isinstance(raw, str):
            if "," in raw:
                toks = [t.strip() for t in raw.split(",")]
            else:
                toks = [t.strip() for t in raw.split()]
        else:
            toks = []
        p.accord_list = [t for t in toks if t][:6]
        p.image_url = f"https://scentpick-images.s3.ap-northeast-2.amazonaws.com/perfumes/{p.id}.jpg"

    brands = Perfume.objects.values_list("brand", flat=True).distinct().order_by("brand")
    concentrations = (
        Perfume.objects.exclude(concentration="")
        .values_list("concentration", flat=True)
        .distinct()
        .order_by("concentration")
    )
    genders = (
        Perfume.objects.exclude(gender="")
        .values_list("gender", flat=True)
        .distinct()
        .order_by("gender")
    )

    raw_accords = Perfume.objects.exclude(main_accords="").values_list("main_accords", flat=True)
    accord_set = set()
    for raw in raw_accords:
        if not raw:
            continue
        if isinstance(raw, list):
            parts = [str(p).strip() for p in raw if p]
        else:
            cleaned = str(raw).strip("[]").replace("'", "").replace('"', "")
            parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        for p in parts:
            if p and p not in ["/", "-", "_"]:
                accord_set.add(p)
    accords = sorted(accord_set)

    base_qd = request.GET.copy()
    base_qd.pop("page", True)
    base_qs = base_qd.urlencode()

    ctx = {
        "page_obj": page_obj,
        "page_range_custom": page_range_custom,
        "brands": brands,
        "concentrations": concentrations,
        "genders": genders,
        "accords": accords,
        "selected": {
            "q": q,
            "brand": brand_sel,
            "gender": gender_sel,
            "conc": conc_sel,
            "accord": accord_sel,
        },
        "base_qs": base_qs,
    }

    if request.GET.get("ajax") == "1":
        return render(request, "scentpick/perfumes_grid.html", ctx)
    
    return render(request, "scentpick/perfumes.html", ctx)

@login_required
def offlines(request):
    return render(request, "scentpick/offlines.html", {"KAKAO_JS_KEY": settings.KAKAO_JS_KEY})

@login_required
def profile_edit(request):
    user: User = request.user
    detail: UserDetail = user.detail
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        gender = request.POST.get("gender")
        birth_year = request.POST.get("birth_year")
        file = request.FILES.get("profile_image")

        errors = []
        if not email:
            errors.append("이메일을 입력하세요")

        if birth_year:
            try:
                by = int(birth_year)
                if by < 1900 or by > 2100:
                    errors.append("올바른 출생연도를 입력하세요")
            except ValueError:
                errors.append("올바른 출생연도를 입력하세요")

        if errors:
            return render(request, "scentpick/profile_edit.html", {
                "errors": errors,
                "form_data": request.POST,
                "detail": detail,
            })

        user.email = email
        user.save()
        if gender:
            detail.gender = gender
        if birth_year:
            detail.birth_year = int(birth_year)

        if file:
            try:
                ctype = getattr(file, "content_type", "").lower()
                allowed_ct = {"image/jpeg", "image/png", "image/gif"}
                if ctype not in allowed_ct:
                    file.seek(0)
                    kind = (imghdr.what(file) or "").lower()
                    if kind == "jpg":
                        kind = "jpeg"
                    if kind not in {"jpeg", "png", "gif"}:
                        raise ValueError("이미지 형식은 JPG/PNG/GIF 만 지원합니다")

                crop = {
                    "x": request.POST.get("crop_x"),
                    "y": request.POST.get("crop_y"),
                    "size": request.POST.get("crop_size"),
                    "scale": request.POST.get("crop_scale"),
                }
                file.seek(0)
                image_bytes = process_profile_image(file, crop=crop)
                url = upload_to_s3_and_get_url(user.id, image_bytes, ext="jpg")
                detail.profile_image_url = url
            except Exception as e:
                messages.warning(request, f"프로필 이미지 처리 오류: {e}")

        detail.save()
        messages.success(request, "회원정보가 저장되었습니다")
        return redirect("scentpick:mypage")

    return render(request, "scentpick/profile_edit.html", {"detail": detail})

@login_required
def password_change_view(request):
    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "비밀번호가 변경되었습니다.")
            return redirect('scentpick:mypage')
    else:
        form = PasswordChangeForm(user=request.user)
    return render(request, 'scentpick/password_change.html', { 'form': form })


# --- S3 퍼블릭 이미지 베이스 ---
S3_BASE = "https://scentpick-images.s3.ap-northeast-2.amazonaws.com"


# =======================
# 날씨/추천 유틸
# =======================
WMO_KO = {
    0: "맑음", 1: "대체로 맑음", 2: "부분 흐림", 3: "흐림",
    45: "안개", 48: "짙은 안개",
    51: "약한 이슬비", 53: "보통 이슬비", 55: "강한 이슬비",
    61: "약한 비", 63: "보통 비", 65: "강한 비",
    71: "약한 눈", 73: "보통 눈", 75: "강한 눈",
    80: "약한 소나기", 81: "소나기", 82: "강한 소나기",
    95: "뇌우", 96: "뇌우(약한 우박)", 99: "뇌우(강한 우박)",
}

def wind_text(speed_ms):
    if speed_ms is None:
        return "바람 -"
    try:
        s = float(speed_ms)
    except Exception:
        return "바람 -"
    if s < 2:   return "바람 약함"
    if s < 6:   return "바람 보통"
    if s < 10:  return "바람 강함"
    return "바람 매우 강함"

def emoji_by_code(code):
    if code in (0, 1):         return "☀️"
    if code == 2:              return "⛅"
    if code == 3:              return "☁️"
    if code in (45, 48):       return "🌫️"
    if code in (51, 53, 55):   return "🌦️"
    if code in (61, 63, 65, 80, 81, 82): return "🌧️"
    if code in (71, 73, 75):   return "🌨️"
    if code in (95, 96, 99):   return "⛈️"
    return "🌤️"

def tip_and_accords_by_code(code):
    if code in (0, 1, 2):  # 맑음
        return ("상쾌하고 시원한 시트러스 계열이나 아쿠아틱 노트가 어울려요!",
                ["시트러스", "아쿠아틱", "그린", "프레시", "허벌"])
    if code in (61, 63, 65, 80, 81, 82):  # 비/소나기
        return ("비 오는 날엔 우디/머스크 같은 포근한 향이 좋아요.",
                ["우디", "머스크", "앰버", "스파이시", "파우더리"])
    if code in (3, 45, 48):  # 흐림/안개
        return ("흐리거나 안개 낀 날엔 파우더리/머스크로 잔잔하게.",
                ["파우더리", "머스크", "알데하이드", "아이리스"])
    if code in (71, 73, 75):  # 눈
        return ("눈 오는 날엔 바닐라/앰버 계열로 따뜻하게!",
                ["바닐라", "앰버", "스위트", "구르망", "스파이시", "레진"])
    if code in (95, 96, 99):  # 뇌우
        return ("뇌우에는 스파이시/레진 계열로 존재감 있게.",
                ["스파이시", "레진", "가죽", "우디", "앰버"])
    return ("오늘 기분에 맞는 향을 가볍게 시향해 보세요 :)", ["플로랄", "프루티", "그린", "머스크"])

def fetch_weather_simple(city="Seoul", lat=None, lon=None):
    # 1) 위경도 직접 받은 경우
    if lat is not None and lon is not None:
        pass  # 그대로 사용
    else:
        # city 이름 기반 지오코딩
        g = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "ko", "format": "json"},
            timeout=5,
        )
        g.raise_for_status()
        gj = g.json()
        if gj.get("results"):
            lat = gj["results"][0]["latitude"]
            lon = gj["results"][0]["longitude"]
        else:
            lat, lon = 37.5665, 126.9780  # 서울 기본

    # 2) 현재 날씨 조회
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "timezone": "Asia/Seoul",
        },
        timeout=5,
    )
    r.raise_for_status()
    cur = r.json().get("current") or {}

    code = cur.get("weather_code")
    desc = WMO_KO.get(code, "알 수 없음")
    temp = cur.get("temperature_2m")
    humi = cur.get("relative_humidity_2m")
    wind = cur.get("wind_speed_10m")

    line1 = f"{desc}, {round(temp)}°C" if temp is not None else f"{desc}, -°C"
    line2 = f"습도 {humi}%," if humi is not None else "습도 -%,"
    line2 += f" {wind_text(wind)}"

    return line1, line2, code


# =======================
# DB 조회 / 이미지 URL 부여
# =======================
def query_perfumes_by_accords(accords, limit=8, gender=None):
    from django.db.models import Q
    
    # 어코드 조건 구성
    accord_q = Q()
    for a in accords:
        accord_q |= Q(main_accords__contains=[a])
    
    # 성별 조건 추가
    def apply_gender_filter(base_query):
        if gender and gender in ['Male', 'Female']:
            # Male이나 Female이 요청되면 해당 성별 + Unisex 포함
            return base_query.filter(Q(gender=gender) | Q(gender='Unisex'))
        elif gender == 'Unisex':
            # Unisex만 요청되면 Unisex만
            return base_query.filter(gender='Unisex')
        else:
            # gender가 None이면 성별 필터링 없음
            return base_query
    
    try:
        # JSONField 방식으로 시도
        base_qs = Perfume.objects.filter(accord_q)
        qs = apply_gender_filter(base_qs)[:limit]
        
        if qs.exists():
            return list(qs)
    except Exception:
        pass  # TextField(JSON 문자열) fallback
    
    # TextField fallback
    accord_q = Q()
    for a in accords:
        accord_q |= Q(main_accords__icontains=f'"{a}"')
    
    base_qs = Perfume.objects.filter(accord_q)
    qs = apply_gender_filter(base_qs)[:limit]
    
    return list(qs)

def attach_image_urls(perfumes_iter):
    """scentpick-images/perfumes/{id}.jpg 규칙으로 image_url 속성 부여"""
    for p in perfumes_iter:
        p.image_url = f"{S3_BASE}/perfumes/{p.id}.jpg"


# =======================
# 계절 추천 유틸
# =======================
def seasonal_accords_and_tip(month: int):
    if month in (3, 4, 5):  # 봄
        return ("봄 맞춤 추천 Top 3",
                "포근한 날씨엔 플로랄/그린/시트러스가 잘 어울려요.",
                ["플로랄", "그린", "시트러스", "프루티"])
    if month in (6, 7, 8):  # 여름
        return ("여름 맞춤 추천 Top 3",
                "더운 날에는 아쿠아틱/시트러스로 시원하게!",
                ["아쿠아틱", "시트러스", "프레시", "허벌"])
    if month in (9, 10, 11):  # 가을
        return ("가을 맞춤 추천 Top 3",
                "선선해진 날씨에는 우디/스파이시가 딱 좋아요.",
                ["우디", "스파이시", "앰버", "머스크"])
    # 겨울: 12, 1, 2
    return ("겨울 맞춤 추천 Top 3",
            "차가운 공기엔 바닐라/앰버/레진 계열로 따뜻하게.",
            ["바닐라", "앰버", "레진", "스위트", "가죽"])

def get_seasonal_picks(limit=3):
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    season_title, season_tip, target_accords = seasonal_accords_and_tip(now.month)
    picks = query_perfumes_by_accords(target_accords, limit=limit)
    attach_image_urls(picks)
    return season_title, season_tip, picks


# =======================
# 월드컵 유틸
# =======================
GENDER_MAP_KO2EN = {
    "남성": "Male",
    "여성": "Female",
    "남녀공용": "Unisex",
}

def parse_day_night_value(val, key):  # key: "day" or "night"
    """day_night_score가 dict 또는 'day(47.1) / night(25.9)' 문자열 둘 다 처리"""
    if val is None:
        return 0.0
    if isinstance(val, dict):
        try:
            return float(val.get(key, 0) or 0)
        except Exception:
            return 0.0
    s = str(val)
    m = re.search(rf"{key}\s*\(([\d.]+)\)", s, re.IGNORECASE)
    return float(m.group(1)) if m else 0.0

def filter_worldcup_candidates(gender_ko: str, accord_ko: str, time_pref: str, need=8):
    """
    성별/메인어코드/낮밤 선택으로 Perfume 후보 8개 뽑기
    - 성별: 남성→Male+Unisex, 여성→Female+Unisex, 남녀공용→Unisex
    - 메인어코드: JSONField or TEXT(JSON문자열) 모두 대응
    - 낮/밤: 점수 높은 순으로 정렬 후 상위 need개
    """
    # 성별 매핑
    g_en = GENDER_MAP_KO2EN.get(gender_ko, None) or "Unisex"
    if g_en == "Male":
        g_filter = ["Male", "Unisex"]
    elif g_en == "Female":
        g_filter = ["Female", "Unisex"]
    else:
        g_filter = ["Unisex"]

    # 메인어코드 조건
    q = Q(gender__in=g_filter)
    try:
        q &= Q(main_accords__contains=[accord_ko])
        base = Perfume.objects.filter(q)[:200]
        if not base:
            raise ValueError
    except Exception:
        # TEXT 저장 fallback (JSON 문자열)
        q &= (Q(main_accords__icontains=f'"{accord_ko}"') | Q(main_accords__icontains=accord_ko))
        base = Perfume.objects.filter(q)[:200]

    # 낮/밤 점수로 정렬
    key = "day" if time_pref == "day" else "night"
    lst = list(base)
    lst.sort(key=lambda p: parse_day_night_value(getattr(p, "day_night_score", None), key), reverse=True)

    # 상위 need개 (여유분에서 랜덤 샘플)
    top = lst[:max(need, 12)]
    if len(top) > need:
        top = random.sample(top, need)

    # 이미지 URL 부착
    attach_image_urls(top)

    # ★ description 포함해서 프런트에 넘김
    items = [{
        "id": p.id,
        "name": p.name,
        "brand": p.brand,
        "detail_url": getattr(p, "detail_url", ""),
        "image_url": getattr(p, "image_url", ""),
        "description": (p.description or ""),
    } for p in top]

    return items


# =======================
# 추천 페이지 뷰 (메인)
# =======================
@login_required
def recommend(request):
    lat = request.GET.get("lat")
    lon = request.GET.get("lon")
    city = request.GET.get("city", "Seoul")

    # 템플릿 라디오 옵션
    ACCORD_OPTIONS = ["플로랄", "우디", "시트러스", "스파이시", "파우더리", "스위트"]

    # 월드컵 필터 값(그대로 유지)
    g = request.GET.get("g", "")   # "남성" | "여성" | "남녀공용"
    a = request.GET.get("a", "")   # "플로랄" | ...
    t = request.GET.get("t", "")   # "day" | "night"

    try:
       # ① 날씨 정보
        if lat and lon:
            line1, line2, code = fetch_weather_simple(lat=float(lat), lon=float(lon))
        else:
            line1, line2, code = fetch_weather_simple(city=city)
        tip, target_accords = tip_and_accords_by_code(code)
        emoji = emoji_by_code(code)

        # 사용자 성별 정보 가져오기 (users 테이블에서)
        user_gender = None
        if request.user.is_authenticated:
            try:
                user_gender = request.user.detail.gender
            except:
                user_gender = None

        # ② 날씨 기반 추천: 풀 60개 중 랜덤 3개
        weather_perfumes = fetch_random_by_accords(target_accords, pool=60, k=3, gender=user_gender)
        exclude_ids = {p.id for p in weather_perfumes}

        # ③ 계절 기반 추천: 당일 계절 어코드로 풀 60개 중 랜덤 3개 (위와 중복 안 나오게)
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        season_title, season_tip, season_accords = seasonal_accords_and_tip(now.month)
        seasonal_perfumes = fetch_random_by_accords(season_accords, pool=60, k=3, exclude_ids=exclude_ids, gender=user_gender)
        context = {
            # 날씨 박스
            "weather_line1": line1,
            "weather_line2": line2,
            "weather_emoji": emoji,
            "weather_tip": tip,
            # 추천 리스트
            "perfumes": weather_perfumes,            # 날씨 기반 Top3 (매 리디렉션마다 랜덤)
            "season_title": season_title,
            "season_tip": season_tip,
            "seasonal_perfumes": seasonal_perfumes,  # 계절 기반 Top3 (매 리디렉션마다 랜덤)
            # 라디오 옵션
            "accord_options": ACCORD_OPTIONS,
        }

    except requests.RequestException:
        # 날씨 API 실패 시: 날씨 박스만 기본값, 계절 추천은 랜덤으로 계속
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        season_title, season_tip, season_accords = seasonal_accords_and_tip(now.month)
        seasonal_perfumes = fetch_random_by_accords(season_accords, pool=60, k=3)

        context = {
            "weather_line1": "데이터 없음, -°C",
            "weather_line2": "습도 -%, 바람 -",
            "weather_emoji": "🌤️",
            "weather_tip": "오늘 기분에 맞는 향을 가볍게 시향해 보세요 :)",
            "perfumes": [],                           # 날씨 추천 없음
            "season_title": season_title,
            "season_tip": season_tip,
            "seasonal_perfumes": seasonal_perfumes,  # 계절 랜덤 Top3
            "accord_options": ACCORD_OPTIONS,
        }

    # ④ 월드컵 후보 (필터 있으면 8강 생성)
    worldcup = []
    if g and a and t in ("day", "night"):
        worldcup = filter_worldcup_candidates(g, a, t, need=8)

    context.update({
        "wc_selected_gender": g,
        "wc_selected_accord": a,
        "wc_selected_time": t,
        "worldcup_candidates": worldcup,
        "worldcup_candidates_json": json.dumps(worldcup, ensure_ascii=False),
    })

    return render(request, "scentpick/recommend.html", context)


def _sample_random(seq, k):
    """seq에서 k개 랜덤 샘플 (부족하면 있는 만큼)"""
    seq = list(seq) if seq is not None else []
    if len(seq) <= k:
        return seq
    return random.sample(seq, k)

def fetch_random_by_accords(accords, pool=60, k=3, exclude_ids=None, gender=None):
    """
    어코드로 pool개 풀을 긁어온 뒤 k개 랜덤 뽑기.
    exclude_ids에 있는 id는 제외(중복 회피용).
    gender: 'Male', 'Female', 'Unisex' 중 하나.
    """
    # 풀 데이터 조회 시 성별 필터링 포함
    pool_list = query_perfumes_by_accords(accords, limit=pool, gender=gender)
    
    # 중복 제외 처리
    if exclude_ids:
        pool_list = [p for p in pool_list if getattr(p, "id", None) not in exclude_ids]
    
    # 랜덤 추출
    picked = _sample_random(pool_list, k)
    
    # 이미지 URL 붙이기
    attach_image_urls(picked)
    
    return picked

# FastAPI 설정
FASTAPI_CHAT_URL = os.environ.get("FASTAPI_CHAT_URL")
SERVICE_TOKEN = os.environ.get("SERVICE_TOKEN")


@login_required 
@require_POST
def chat_submit_api(request):
    """
    사용자가 메세지 전송 시 user_id와 query만 fastapi로 전송하고,
    chatbot.py로 fastapi에서 conversations db를 작성해서 django가 db를 읽어서 띄워주는 방식
    """
    try:
        # JSON 요청 처리
        if request.content_type == 'application/json':
            body = json.loads(request.body.decode("utf-8"))
            content = (body.get("content") or body.get("query") or "").strip()
            conversation_id = body.get("conversation_id")
        else:
            # Form 데이터 처리 (기존 호환성)
            content = request.POST.get("content", "").strip()
            conversation_id = request.POST.get("conversation_id") or request.session.get("conversation_id")
            
        if not content:
            return JsonResponse({"error": "내용이 비었습니다."}, status=400)

        # FastAPI로 user_id와 query만 전송
        payload = {
            "user_id": request.user.id,
            "query": content
        }
        
        if conversation_id:
            try:
                payload["conversation_id"] = int(conversation_id)
            except ValueError:
                pass  # 잘못된 conversation_id는 무시

        headers = {
            "X-Service-Token": SERVICE_TOKEN,
            "Content-Type": "application/json",
        }
        
        # FastAPI 호출
        r = requests.post(FASTAPI_CHAT_URL, json=payload, headers=headers, timeout=60)
        r.raise_for_status()
        data = r.json()

        # 세션에 conversation_id 업데이트 (다음 메시지에서 사용)
        if data.get("conversation_id"):
            request.session["conversation_id"] = data["conversation_id"]

        # FastAPI가 conversations DB를 작성했으므로 응답만 반환 + 추천 향수 리스트 포함
        response_data = {
            "conversation_id": data.get("conversation_id"),
            "final_answer": data.get("final_answer", "응답을 받지 못했습니다."),
            "perfume_list": data.get("perfume_list", []),
            "success": True
        }
        print("💾 Django API Response:", response_data)  # 서버 콘솔에 출력
        return JsonResponse(response_data)
        
    except requests.HTTPError as e:
        return JsonResponse({"error": f"FastAPI 오류: {e.response.text}"}, status=502)
    except Exception as e:
        return JsonResponse({"error": f"서버 오류: {str(e)}"}, status=500)


@login_required
@require_POST
def chat_stream_api(request):
    """
    스트리밍 채팅 API - Server-Sent Events 방식으로 실시간 응답 (멀티모달 지원)
    """
    try:
        # JSON 요청 처리
        if request.content_type == 'application/json':
            body = json.loads(request.body.decode("utf-8"))
            content = (body.get("content") or body.get("query") or "").strip()
            conversation_id = body.get("conversation_id")
            image_file = None
        else:
            # FormData 요청 처리 (이미지 + 텍스트)
            content = request.POST.get("content", "").strip()
            conversation_id = request.POST.get("conversation_id") or request.session.get("conversation_id")
            image_file = request.FILES.get("image")

         # 텍스트도 없고 이미지도 없으면 에러
        if not content and not image_file:
            def error_generator():
                yield f"data: {json.dumps({'error': '내용이 비었습니다.'})}\n\n"
            return StreamingHttpResponse(error_generator(), content_type='text/event-stream')

        # 이미지만 있을 경우 기본 query 채워주기
        if not content and image_file:
            content = "이미지 기반 추천 요청"

        # FastAPI로 스트리밍 요청 준비
        payload = {
            "user_id": request.user.id,
            "query": content,
            "stream": True  # 스트리밍 요청임을 표시
        }

        # 이미지 첨부 시 S3 업로드 (체계적인 경로 구조)
        uploaded_image_url = None
        if image_file:
            # 체계적인 경로: chat_images/user_id/conversation_id/message_id_timestamp_filename
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            # conversation_id가 있으면 사용, 없으면 'new'로 임시 처리
            conv_path = str(conversation_id) if conversation_id else 'new'
            filename = f"chat_images/{request.user.id}/{conv_path}/{timestamp}_{image_file.name}"

            s3_client.upload_fileobj(
                image_file,
                settings.AWS_STORAGE_BUCKET_NAME,
                filename,
                ExtraArgs={"ContentType": image_file.content_type},
            )
            uploaded_image_url = f"https://{settings.AWS_STORAGE_BUCKET_NAME}.s3.{settings.AWS_S3_REGION_NAME}.amazonaws.com/{filename}"
            payload["image_url"] = uploaded_image_url

        if conversation_id:
            try:
                payload["conversation_id"] = int(conversation_id)
            except ValueError:
                pass

        headers = {
            "X-Service-Token": SERVICE_TOKEN,
            "Content-Type": "application/json",
            "Accept": "text/event-stream"  # SSE 요청
        }

        def stream_generator():
            final_conversation_id = None
            try:
                # FastAPI 서버가 없을 때 임시 mock 응답
                if not FASTAPI_CHAT_URL:
                    mock_response = f"안녕하세요! '{content}'에 대한 응답입니다. 현재 FastAPI 서버가 연결되지 않아 임시 응답을 제공합니다."
                    import time
                    for chunk in mock_response.split():
                        yield f"data: {json.dumps({'content': chunk + ' '})}\n\n"
                        time.sleep(0.1)  # 스트리밍 효과
                    yield f"data: {json.dumps({'done': True, 'conversation_id': conversation_id or 1, 'perfume_list': []})}\n\n"
                    return

                # FastAPI로 스트리밍 요청
                response = requests.post(
                    FASTAPI_CHAT_URL + "/stream" if not FASTAPI_CHAT_URL.endswith("/stream") else FASTAPI_CHAT_URL,
                    json=payload,
                    headers=headers,
                    stream=True,
                    timeout=120
                )
                response.raise_for_status()

                # 스트리밍 응답 처리
                for line in response.iter_lines(decode_unicode=True):
                    if line:
                        # FastAPI에서 오는 SSE 데이터를 그대로 전달
                        if line.startswith("data: "):
                            try:
                                # conversation_id 추출 시도
                                data = json.loads(line[6:])
                                if data.get('conversation_id'):
                                    # conversation_id가 있으면 세션과 변수에 저장
                                    request.session["conversation_id"] = data["conversation_id"]
                                    final_conversation_id = data['conversation_id']
                            except:
                                pass
                            yield f"{line}\n\n"
                        else:
                            # 일반 텍스트라면 SSE 형식으로 감싸기
                            yield f"data: {json.dumps({'content': line})}\n\n"

                # 스트림 종료 신호
                yield f"data: {json.dumps({'done': True})}\n\n"

                # 스트리밍 완료 후 이미지 URL 업데이트
                if uploaded_image_url and final_conversation_id:
                    try:
                        # 해당 conversation의 가장 최근 user 메시지 찾기
                        conv = Conversation.objects.get(id=final_conversation_id, user=request.user)
                        user_message = conv.messages.filter(role='user').order_by('-created_at').first()
                        if user_message:
                            user_message.chat_image = uploaded_image_url
                            user_message.save()
                            print(f"✅ Image URL saved to message {user_message.id}: {uploaded_image_url}")
                    except Exception as e:
                        print(f"❌ Failed to save image URL: {e}")

            except requests.RequestException as e:
                # FastAPI 서버가 없을 때 mock 응답
                print(f"FastAPI 연결 실패, mock 응답 사용: {e}")
                mock_response = f"안녕하세요! '{content}'에 대한 응답입니다. FastAPI 서버 연결에 실패하여 임시 응답을 제공합니다."
                import time
                for chunk in mock_response.split():
                    yield f"data: {json.dumps({'content': chunk + ' '})}\n\n"
                    time.sleep(0.1)
                yield f"data: {json.dumps({'done': True, 'conversation_id': conversation_id or 1, 'perfume_list': []})}\n\n"

            except Exception as e:
                yield f"data: {json.dumps({'error': f'서버 오류: {str(e)}'})}\n\n"

        response = StreamingHttpResponse(stream_generator(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Headers'] = 'Cache-Control'
        response['X-Accel-Buffering'] = 'no'   # Nginx 버퍼링 비활성화
        return response

    except Exception as e:
        # Fast API 실패 시 업로드 취소
        s3_client.delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=filename)

        def error_generator():
            yield f"data: {json.dumps({'error': f'서버 오류: {str(e)}'})}\n\n"
        return StreamingHttpResponse(error_generator(), content_type='text/event-stream')

def get_note_image_url(note_name):
    """노트명으로 이미지 URL 가져오기 - 개선된 버전"""
    try:
        # 한국어면 영어로 변환
        english_name = get_english_note_name(note_name)
        
        # 1. 정확한 이름으로 검색
        note_image = NoteImage.objects.filter(note_name__iexact=english_name).first()
        if note_image:
            return note_image.image_url
        
        # 2. 부분 매칭으로 검색 (대소문자 무시)
        note_image = NoteImage.objects.filter(note_name__icontains=english_name).first()
        if note_image:
            return note_image.image_url
        
        # 3. 공백으로 분리해서 각 단어로 검색
        if ' ' in english_name:
            for word in english_name.split():
                if len(word) > 2:  # 2글자 이상인 단어만
                    note_image = NoteImage.objects.filter(note_name__icontains=word).first()
                    if note_image:
                        return note_image.image_url
        
        # 4. 역방향 검색 - DB의 노트명이 한국어 노트명을 포함하는지
        notes_containing = NoteImage.objects.filter(note_name__icontains=note_name).first()
        if notes_containing:
            return notes_containing.image_url
        return None
        
    except Exception as e:
        return None


def product_detail(request, perfume_id):
    # DB 테스트 (개발용 - 나중에 제거)
    #test_note_images()
    
    perfume = get_object_or_404(Perfume, id=perfume_id)
    image_url = f"https://scentpick-images.s3.ap-northeast-2.amazonaws.com/perfumes/{perfume.id}.jpg"
    
    # 사용자의 즐겨찾기/피드백 상태 확인
    is_favorite = False
    feedback_status = None
    
    if request.user.is_authenticated:
        # 즐겨찾기 상태 확인
        is_favorite = Favorite.objects.filter(
            user=request.user,
            perfume=perfume
        ).exists()
        
        # 피드백 상태 확인
        feedback = FeedbackEvent.objects.filter(
            user=request.user,
            perfume=perfume,
            action__in=['like', 'dislike']
        ).first()
        
        if feedback:
            feedback_status = feedback.action
    
    def safe_process_json_field(field_data):
        if not field_data:
            return []
        
        try:
            # Case 1: 이미 Python 리스트인 경우
            if isinstance(field_data, list):
                return field_data
            
            # Case 2: JSON 문자열인 경우 (예: '["레몬", "자몽"]')
            if isinstance(field_data, str):
                import json
                try:
                    parsed = json.loads(field_data)
                    if isinstance(parsed, list):
                        return parsed
                except:
                    # Case 3: JSON 파싱 실패시 공백으로 분리 (예: '레몬 자몽')
                    return field_data.split()
            
            return []
        except Exception as e:
            print(f"Error processing field: {field_data}, Error: {e}")
            return []
    
    main_accords = safe_process_json_field(perfume.main_accords)
    top_notes = safe_process_json_field(perfume.top_notes)
    middle_notes = safe_process_json_field(perfume.middle_notes)
    base_notes = safe_process_json_field(perfume.base_notes)
    
    # 노트에 이미지 URL과 한국어 이름 추가
    def enhance_notes(notes_list):
        enhanced_notes = []
        for note in notes_list:
            enhanced_notes.append({
                'name': note,
                'korean_name': note,  # 이미 한국어이므로 그대로 사용
                'image_url': get_note_image_url(note)  # 한국어→영어 변환 후 이미지 검색
            })
        return enhanced_notes
    
    enhanced_top_notes = enhance_notes(top_notes)
    enhanced_middle_notes = enhance_notes(middle_notes)
    enhanced_base_notes = enhance_notes(base_notes)
    
    # 이전/다음 향수 가져오기
    prev_perfume = Perfume.objects.filter(id__lt=perfume_id).order_by('-id').first()
    next_perfume = Perfume.objects.filter(id__gt=perfume_id).order_by('id').first()

    context = {
        'perfume': perfume,
        'image_url': image_url,
        'main_accords': main_accords,
        'top_notes': enhanced_top_notes,
        'middle_notes': enhanced_middle_notes,
        'base_notes': enhanced_base_notes,
        'sizes': perfume.sizes,
        'gender': perfume.gender,
        'prev_perfume': prev_perfume,
        'next_perfume': next_perfume,
        'detail_url': perfume.detail_url,  # bysuco 링크 추가
        'notes_score': perfume.notes_score,  # 노트 점수 추가
        'season_score': perfume.season_score,  # 계절 점수 추가
        'day_night_score': perfume.day_night_score,  # 낮/밤 점수 추가
        'is_favorite': is_favorite,  # 즐겨찾기 상태
        'feedback_status': feedback_status,  # 피드백 상태 ('like', 'dislike', None)
    }
    return render(request, 'scentpick/product_detail.html', context)

@require_POST
def toggle_favorite(request):
    """즐겨찾기 토글 -  (디버깅 추가)"""
    try:
        data = json.loads(request.body)
        perfume_id = data.get('perfume_id')
        
        if not perfume_id:
            return JsonResponse({
                'status': 'error',
                'message': '향수 ID가 필요합니다.'
            }, status=400)
        
        perfume = get_object_or_404(Perfume, id=perfume_id)
        
        # admin 사용자 사용
        request.user = User.objects.get(username=request.user.username)
        
        # DB에서 즐겨찾기 확인
        favorite = Favorite.objects.filter(
            user=request.user,
            perfume=perfume
        ).first()
        
        if favorite:
            # 즐겨찾기에서 제거
            favorite.delete()
            is_favorite = False
            message = f'{perfume.name}이(가) 즐겨찾기에서 제거되었습니다.'
        else:
            # 즐겨찾기에 추가
            new_favorite = Favorite.objects.create(
                user=request.user,
                perfume=perfume
            )
            is_favorite = True
            message = f'{perfume.name}이(가) 즐겨찾기에 추가되었습니다.'
        
        # 현재 즐겨찾기 개수 확인
        total_favorites = Favorite.objects.filter(user=request.user).count()
        
        return JsonResponse({
            'status': 'success',
            'success': True,
            'is_favorite': is_favorite,
            'message': message,
            'debug_total_favorites': total_favorites  # 디버깅 정보
        })
        
    except User.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'admin 사용자를 찾을 수 없습니다.'
        }, status=500)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'오류가 발생했습니다: {str(e)}'
        }, status=500)

@require_POST
def toggle_like_dislike(request):
    """좋아요/싫어요 토글"""
    try:
        data = json.loads(request.body)
        perfume_id = data.get('perfume_id')
        action = data.get('action')  # 'like' 또는 'dislike'
        
        if not perfume_id or action not in ['like', 'dislike']:
            return JsonResponse({
                'status': 'error',
                'message': '유효하지 않은 요청입니다.'
            }, status=400)
        
        perfume = get_object_or_404(Perfume, id=perfume_id)
        
        # admin 사용자 사용
        request.user = User.objects.get(username=request.user.username)
        
        # 기존 피드백 이벤트 확인
        existing_feedback = FeedbackEvent.objects.filter(
            user=request.user,
            perfume=perfume,
            action__in=['like', 'dislike']
        ).first()
        
        if existing_feedback:
            if existing_feedback.action == action:
                # 같은 액션이면 삭제 (토글 off)
                existing_feedback.delete()
                current_action = None
                message = f'{perfume.name}의 {action}가 취소되었습니다.'
            else:
                # 다른 액션이면 업데이트 (좋아요 ↔ 싫어요)
                existing_feedback.action = action
                existing_feedback.save()
                current_action = action
                if action == 'like':
                    message = f'{perfume.name}에 좋아요를 눌렀습니다!'
                else:
                    message = f'{perfume.name}에 싫어요를 눌렀습니다.'
        else:
            # 새로운 피드백 이벤트 생성
            new_feedback = FeedbackEvent.objects.create(
                user=request.user,
                perfume=perfume,
                action=action,
                source='detail',
                context={'page': 'product_detail', 'user': 'admin'}
            )
            current_action = action
            if action == 'like':
                message = f'{perfume.name}에 좋아요를 눌렀습니다!'
            else:
                message = f'{perfume.name}에 싫어요를 눌렀습니다.'
        
        # 현재 피드백 상태 확인
        total_likes = FeedbackEvent.objects.filter(user=request.user, action='like').count()
        total_dislikes = FeedbackEvent.objects.filter(user=request.user, action='dislike').count()
        
        return JsonResponse({
            'status': 'success',
            'success': True,
            'current_action': current_action,
            'message': message,
            'debug_likes': total_likes,
            'debug_dislikes': total_dislikes
        })
        
    except User.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'admin 사용자를 찾을 수 없습니다.'
        }, status=500)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'오류가 발생했습니다: {str(e)}'
        }, status=500)


@login_required 
def mypage(request):
    """마이페이지"""
    try:
        request.user = User.objects.get(username=request.user.username)

        # --- 정렬 파라미터 ---
        sort_by  = (request.GET.get('sort_by')  or 'date').strip()   # date|brand|name|count
        sort_dir = (request.GET.get('sort_dir') or 'desc').strip()   # asc|desc
        desc = (sort_dir == 'desc')

        # =========================[ 추천 내역 집계 ]=========================
        brand = (request.GET.get('brand') or '').strip()
        name = (request.GET.get('name') or '').strip()
        date_from = (request.GET.get('date_from') or '').strip()
        date_to   = (request.GET.get('date_to') or '').strip()

        rec_qs = RecCandidate.objects.filter(run_rec__user=request.user)

        if brand:
            rec_qs = rec_qs.filter(perfume__brand__icontains=brand)
        if name:
            rec_qs = rec_qs.filter(perfume__name__icontains=name)
        if date_from:
            rec_qs = rec_qs.filter(run_rec__created_at__date__gte=date_from)
        if date_to:
            rec_qs = rec_qs.filter(run_rec__created_at__date__lte=date_to)

        rec_agg = (
            rec_qs.values('perfume_id', 'perfume__brand', 'perfume__name')
                 .annotate(
                     rec_count=Count('id'),
                     last_date=Max('run_rec__created_at'),
                 )
        )

        # --- 정렬 결정 ---
        order = []
        if sort_by == 'brand':
            order = ['-perfume__brand', '-perfume__name'] if desc else ['perfume__brand', 'perfume__name']
        elif sort_by == 'name':
            order = ['-perfume__name'] if desc else ['perfume__name']
        elif sort_by == 'count':
            # 같은 횟수면 최신순 보조 정렬
            order = ['-rec_count', '-last_date'] if desc else ['rec_count', '-last_date']
        else:  # 'date' 기본
            order = ['-last_date'] if desc else ['last_date']

        rec_agg = rec_agg.order_by(*order)

        # 페이지네이션(5개)
        rec_paginator = Paginator(rec_agg, 5)
        rec_page = rec_paginator.get_page(request.GET.get('page') or 1)
        # ===============================================================

        # 이하 즐겨찾기/피드백 기존 코드 그대로...
        favorite_perfumes = Perfume.objects.filter(
            favorited_by__user=request.user
        ).order_by('-favorited_by__created_at')

        liked_feedback = FeedbackEvent.objects.filter(
            user=request.user, action='like'
        ).select_related('perfume').order_by('-created_at')

        disliked_feedback = FeedbackEvent.objects.filter(
            user=request.user, action='dislike'
        ).select_related('perfume').order_by('-created_at')

        for perfume in favorite_perfumes:
            perfume.image_url = f"https://scentpick-images.s3.ap-northeast-2.amazonaws.com/perfumes/{perfume.id}.jpg"
        for feedback in liked_feedback:
            feedback.perfume.image_url = f"https://scentpick-images.s3.ap-northeast-2.amazonaws.com/perfumes/{feedback.perfume.id}.jpg"
        for feedback in disliked_feedback:
            feedback.perfume.image_url = f"https://scentpick-images.s3.ap-northeast-2.amazonaws.com/perfumes/{feedback.perfume.id}.jpg"

        context = {
            'rec_page': rec_page,
            'f_brand': brand, 'f_name': name, 'f_date_from': date_from, 'f_date_to': date_to,
            'favorite_perfumes': favorite_perfumes,
            'favorites_count': favorite_perfumes.count(),
            'liked_perfumes': liked_feedback,
            'likes_count': liked_feedback.count(),
            'disliked_perfumes': disliked_feedback,
            'dislikes_count': disliked_feedback.count(),
            # ★ 템플릿에 현재 정렬 상태 전달 (화살표 표시용)
            'sort_by': sort_by,
            'sort_dir': sort_dir,
        }

    except User.DoesNotExist:
        context = {
            'rec_page': None,
            'f_brand': '', 'f_name': '', 'f_date_from': '', 'f_date_to': '',
            'favorite_perfumes': Perfume.objects.none(),
            'favorites_count': 0,
            'liked_perfumes': [], 'likes_count': 0,
            'disliked_perfumes': [], 'dislikes_count': 0,
            'sort_by': 'date', 'sort_dir': 'desc',
            'error': 'admin 사용자를 찾을 수 없습니다.',
        }

    return render(request, "scentpick/mypage.html", context)

@login_required
@require_GET
def conversations_api(request):
    """
    대화 목록 API - AJAX로 대화 목록 로드
    """
    items = []
    qs = Conversation.objects.filter(user=request.user).order_by('-updated_at')[:100]
    for c in qs:
        title = c.title
        if not title:
            # Fallback: derive from first user message
            try:
                first_user = c.messages.filter(role='user').order_by('created_at').first()
                if first_user and first_user.content:
                    title = first_user.content[:15]
            except Exception:
                pass
        if not title:
            title = f"대화 {c.id}"
        items.append({
            'id': c.id,
            'title': title,
            'updated_at': c.updated_at.isoformat(),
        })
    return JsonResponse({'items': items})


@login_required
@require_POST
def chat_new_api(request):
    """
    새 대화 시작 API - 세션 초기화
    """
    # 세션에서 현재 대화 ID 제거
    request.session['conversation_id'] = None
    return JsonResponse({'ok': True, 'message': '새 대화가 시작되었습니다.'})


@login_required
@require_POST
def delete_feedback_api(request):
    """피드백 삭제 API"""
    try:
        data = json.loads(request.body)
        feedback_id = data.get('feedback_id')
        
        if not feedback_id:
            return JsonResponse({
                'status': 'error',
                'message': '피드백 ID가 필요합니다.'
            }, status=400)
        
        # 피드백 이벤트 삭제
        feedback = get_object_or_404(FeedbackEvent, id=feedback_id, user=request.user)
        feedback.delete()
        
        return JsonResponse({
            'status': 'success',
            'message': '피드백이 삭제되었습니다.'
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'오류가 발생했습니다: {str(e)}'
        }, status=500)


@login_required
@require_POST  
def update_feedback_api(request):
    """피드백 업데이트 API"""
    try:
        data = json.loads(request.body)
        feedback_id = data.get('feedback_id')
        action = data.get('action')
        
        if not feedback_id or action not in ['like', 'dislike']:
            return JsonResponse({
                'status': 'error',
                'message': '유효하지 않은 요청입니다.'
            }, status=400)
        
        # 피드백 이벤트 업데이트
        feedback = get_object_or_404(FeedbackEvent, id=feedback_id, user=request.user)
        feedback.action = action
        feedback.save()
        
        return JsonResponse({
            'status': 'success',
            'message': f'피드백이 {action}로 업데이트되었습니다.'
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'오류가 발생했습니다: {str(e)}'
        }, status=500)
@login_required
@require_GET
def conversations_api(request):
    """
    대화 목록 API - AJAX로 대화 목록 로드
    """
    items = []
    qs = Conversation.objects.filter(user=request.user).order_by('-updated_at')[:100]
    for c in qs:
        title = c.title
        if not title:
            # Fallback: derive from first user message
            try:
                first_user = c.messages.filter(role='user').order_by('created_at').first()
                if first_user and first_user.content:
                    title = first_user.content[:15]
            except Exception:
                pass
        if not title:
            title = f"대화 {c.id}"
        items.append({
            'id': c.id,
            'title': title,
            'updated_at': c.updated_at.isoformat(),
        })
    return JsonResponse({'items': items})

@login_required
@require_GET
def conversation_messages_api(request, conv_id: int):
    """
    특정 대화의 메시지 목록 API - AJAX로 메시지 로드 (추천 데이터 포함)
    """
    conv = get_object_or_404(Conversation, id=conv_id, user=request.user)
    msgs = conv.messages.order_by('created_at')
    data = []
    
    for m in msgs:
        message_data = {
            'role': m.role,
            'content': m.content,
            'created_at': m.created_at.isoformat(),
            'chat_image': getattr(m, 'chat_image', None),  # 안전한 이미지 URL 접근
        }
        
        # assistant 메시지인 경우 관련된 추천 데이터 찾기
        if m.role == 'assistant':
            # 이 메시지와 연관된 RecRun 찾기
            rec_runs = RecRun.objects.filter(
                conversation=conv,
                request_msg__created_at__lte=m.created_at
            ).order_by('-created_at')
            
            if rec_runs.exists():
                latest_run = rec_runs.first()
                # 추천 후보들 가져오기
                candidates = latest_run.candidates.select_related('perfume').order_by('rank')
                
                perfume_list = []
                for candidate in candidates:
                    perfume_list.append({
                        'id': candidate.perfume.id,
                        'brand': candidate.perfume.brand,
                        'name': candidate.perfume.name,
                        'rank': candidate.rank,
                        'score': candidate.score
                    })
                
                if perfume_list:
                    message_data['perfume_list'] = perfume_list
        
        data.append(message_data)
    
    return JsonResponse({'conversation_id': conv.id, 'title': conv.title, 'items': data})

@login_required
@require_POST
def chat_new_api(request):
    """
    새 대화 시작 API - 세션 초기화
    """
    # 세션에서 현재 대화 ID 제거
    request.session['conversation_id'] = None
    return JsonResponse({'ok': True, 'message': '새 대화가 시작되었습니다.'})