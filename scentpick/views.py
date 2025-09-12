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

# --- Django 기본 ---
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST, require_GET

# --- 프로젝트 내부 (app) ---
from .models import (
    Perfume,
    Favorite,
    FeedbackEvent,
    NoteImage,
    Conversation,
    Message,
)
from uauth.models import UserDetail
from uauth.utils import process_profile_image, upload_to_s3_and_get_url


def home(request):
    return render(request, "scentpick/home.html")

def login_view(request):
    return render(request, "scentpick/login.html")

def register(request):
    return render(request, "scentpick/register.html")

@login_required
def chat(request):
    if "thread_uuid" not in request.session:
        request.session["thread_uuid"] = str(uuid.uuid4())
    return render(request, "scentpick/chat.html", {
        "conversation_id": request.session.get("conversation_id"),
        "external_thread_id": request.session.get("thread_uuid"),
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
def query_perfumes_by_accords(accords, limit=8):
    # JSONField 가정
    q = Q()
    for a in accords:
        q |= Q(main_accords__contains=[a])
    try:
        qs = Perfume.objects.filter(q)[:limit]
        if qs.exists():
            return list(qs)
    except Exception:
        pass  # TextField(JSON 문자열) fallback

    q = Q()
    for a in accords:
        q |= Q(main_accords__icontains=f'"{a}"')
    return list(Perfume.objects.filter(q)[:limit])

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

        # ② 날씨 기반 추천: 풀 60개 중 랜덤 3개
        weather_perfumes = fetch_random_by_accords(target_accords, pool=60, k=3)
        exclude_ids = {p.id for p in weather_perfumes}

        # ③ 계절 기반 추천: 당일 계절 어코드로 풀 60개 중 랜덤 3개 (위와 중복 안 나오게)
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        season_title, season_tip, season_accords = seasonal_accords_and_tip(now.month)
        seasonal_perfumes = fetch_random_by_accords(season_accords, pool=60, k=3, exclude_ids=exclude_ids)

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

def fetch_random_by_accords(accords, pool=60, k=3, exclude_ids=None):
    """
    어코드로 pool개 풀을 긁어온 뒤 k개 랜덤 뽑기.
    exclude_ids에 있는 id는 제외(중복 회피용).
    """
    pool_list = query_perfumes_by_accords(accords, limit=pool)
    if exclude_ids:
        pool_list = [p for p in pool_list if getattr(p, "id", None) not in exclude_ids]
    picked = _sample_random(pool_list, k)
    attach_image_urls(picked)
    return picked


FASTAPI_CHAT_URL = os.environ.get("FASTAPI_CHAT_URL")  # e.g., http://<fastapi-host>:8000/chat.run
SERVICE_TOKEN = os.environ.get("SERVICE_TOKEN")


@login_required
def chat_submit(request):
    if request.method == "POST":
        user = request.user
        content = request.POST.get("content", "").strip()

        # 세션에서 thread_uuid 사용(없으면 생성)
        thread_uuid = request.session.get("thread_uuid")
        if not thread_uuid:
            thread_uuid = str(uuid.uuid4())
            request.session["thread_uuid"] = thread_uuid

        # 기존 대화 이어가기: 템플릿 hidden 또는 세션에서 가져옴
        conversation_id_raw = request.POST.get("conversation_id") or request.session.get("conversation_id")
        conversation_id = int(conversation_id_raw) if conversation_id_raw else None

        idem_key = str(uuid.uuid4())

        payload = {
            "user_id": user.id,
            "conversation_id": conversation_id,         # 있으면 그대로
            "external_thread_id": thread_uuid,          # ✅ 장고가 만든 UUID 고정 사용
            "title": None,
            "message": {
                "content": content,
                "idempotency_key": idem_key,
                "metadata": {"source": "django-web"},
            }
        }
        headers = {
            "X-Service-Token": SERVICE_TOKEN,
            "X-Idempotency-Key": idem_key,
            "Content-Type": "application/json",
        }

        r = requests.post(FASTAPI_CHAT_URL, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()

        # 세션에 최신 conversation_id / external_thread_id 저장(재시도/재진입 대비)
        request.session["conversation_id"] = data["conversation_id"]
        request.session["thread_uuid"] = data["external_thread_id"]

        return render(request, "scentpick/chat.html", {
            "conversation_id": data["conversation_id"],
            "external_thread_id": data["external_thread_id"],
            "final_answer": data["final_answer"],
            "appended": data["messages_appended"],
        })

    # GET이면 chat()로 돌려도 됨
    return redirect("scentpick:chat")

FASTAPI_CHAT_URL = os.environ.get("FASTAPI_CHAT_URL")  # 예: http://<fastapi-host>:8000/chatbot/chat.run
SERVICE_TOKEN    = os.environ.get("SERVICE_TOKEN")

@login_required
@require_POST
def chat_submit_api(request):
    try:
        body = json.loads(request.body.decode("utf-8"))
        content = (body.get("content") or "").strip()
        if not content:
            return JsonResponse({"error": "내용이 비었습니다."}, status=400)

        # 세션의 thread_uuid 보장(없으면 생성)
        thread_uuid = request.session.get("thread_uuid")
        if not thread_uuid:
            thread_uuid = str(uuid.uuid4())
            request.session["thread_uuid"] = thread_uuid

        # 대화 이어가기: 세션 또는 요청에서 conversation_id 사용
        conv_id = body.get("conversation_id") or request.session.get("conversation_id")
        conv_id = int(conv_id) if conv_id else None

        # 새로운 대화라면 제목 생성 (15글자)
        title = None
        if not conv_id:
            title = content[:15] if len(content) > 15 else content

        idem = str(uuid.uuid4())
        payload = {
            "user_id": request.user.id,
            "conversation_id": conv_id,
            "external_thread_id": thread_uuid,  # ✅ 장고가 만든 UUID 고정 사용
            "title": title,
            "query": content,  # FastAPI가 기대하는 필드명
            "message": {
                "content": content,
                "idempotency_key": idem,
                "metadata": {"source": "django-web"},
            },
        }
        headers = {
            "X-Service-Token": SERVICE_TOKEN,
            "X-Idempotency-Key": idem,
            "Content-Type": "application/json",
        }
        
        r = requests.post(FASTAPI_CHAT_URL, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()

        # FastAPI 응답 구조에 맞게 필드 추출
        final_answer = data.get("final_answer") or data.get("response") or data.get("answer") or "응답을 받지 못했습니다."
        
        # 기존 conversation이 있으면 사용, 없으면 새로 생성
        if conv_id:
            try:
                conversation = Conversation.objects.get(id=conv_id, user=request.user)
            except Conversation.DoesNotExist:
                conversation = None
        else:
            conversation = None
            
        # 새 conversation 생성
        if not conversation:
            conversation = Conversation.objects.create(
                user=request.user,
                title=title,
                external_thread_id=thread_uuid
            )
        
        # 사용자 메시지 저장
        user_message = Message.objects.create(
            conversation=conversation,
            role='user',
            content=content,
            idempotency_key=idem,
            metadata={"source": "django-web"}
        )
        
        # AI 응답 메시지 저장
        ai_message = Message.objects.create(
            conversation=conversation,
            role='assistant',
            content=final_answer,
            model='fastapi-bot'
        )

        # 세션 갱신(재요청/새로고침 대비)
        request.session["conversation_id"] = conversation.id
        request.session["thread_uuid"] = thread_uuid

        # 프론트에 필요한 최소 데이터만 반환
        return JsonResponse({
            "conversation_id": conversation.id,
            "external_thread_id": thread_uuid,
            "final_answer": final_answer,
            "messages_appended": data.get("messages_appended", []),
        })
    except requests.HTTPError as e:
        return JsonResponse({"error": f"FastAPI 오류: {e.response.text}"}, status=502)
    except Exception as e:
        return JsonResponse({"error": f"서버 오류: {e}"}, status=500)

# 노트 한국어 번역 딕셔너리
NOTE_TRANSLATIONS = {
    # Citrus Smells
    'Bergamot': '베르가못',
    'Bigarade': '비가라드',
    'Bitter Orange': '쓴오렌지',
    'Blood Orange': '블러드 오렌지',
    'Lemon': '레몬',
    'Lime': '라임',
    'Orange': '오렌지',
    'Grapefruit': '자몽',
    'Mandarin Orange': '만다린',
    'Tangerine': '탠저린',
    'Yuzu': '유자',
    'Neroli': '네롤리',
    'Petitgrain': '쁘띠그레인',
    'Citrus': '시트러스',
    'Lemongrass': '레몬그라스',
    
    # Fruits, Vegetables And Nuts
    'Apple': '사과',
    'Apricot': '살구',
    'Cherry': '체리',
    'Peach': '복숭아',
    'Pear': '배',
    'Plum': '자두',
    'Banana': '바나나',
    'Blackberry': '블랙베리',
    'Blueberry': '블루베리',
    'Raspberry': '라즈베리',
    'Strawberry': '딸기',
    'Black Currant': '블랙커런트',
    'Coconut': '코코넛',
    'Almond': '아몬드',
    'Walnut': '호두',
    'Hazelnut': '헤이즐넛',
    'Fig': '무화과',
    'Grape': '포도',
    'Watermelon': '수박',
    'Melon': '멜론',
    'Pineapple': '파인애플',
    'Mango': '망고',
    'Papaya': '파파야',
    'Passion Fruit': '패션프루트',
    'Kiwi': '키위',
    'Pomegranate': '석류',
    'Carrot': '당근',
    'Tomato': '토마토',
    
    # Flowers
    'Rose': '장미',
    'Jasmine': '자스민',
    'Lavender': '라벤더',
    'Lily': '백합',
    'Peony': '작약',
    'Gardenia': '치자꽃',
    'Tuberose': '튜베로즈',
    'Ylang-Ylang': '일랑일랑',
    'Carnation': '카네이션',
    'Violet': '제비꽃',
    'Iris': '아이리스',
    'Freesia': '프리지아',
    'Magnolia': '목련',
    'Lily of the Valley': '은방울꽃',
    'Geranium': '제라늄',
    'Narcissus': '수선화',
    'Orange Blossom': '오렌지 블라썸',
    'Lotus': '연꽃',
    'Mimosa': '미모사',
    'Honeysuckle': '인동꽃',
    'Wisteria': '등나무',
    'Hibiscus': '히비스커스',
    'Chamomile': '카모마일',
    'Marigold': '메리골드',
    'Sunflower': '해바라기',
    'Dahlia': '달리아',
    'Orchid': '난초',
    'Cherry Blossom': '벚꽃',
    'Plumeria': '플루메리아',
    'Lilac': '라일락',
    'Hyacinth': '히아신스',
    'Daffodil': '수선화',
    'Chrysanthemum': '국화',
    
    # Spices
    'Cinnamon': '계피',
    'Cardamom': '카다몬',
    'Clove': '정향',
    'Nutmeg': '육두구',
    'Black Pepper': '후추',
    'Pink Pepper': '핑크 페퍼',
    'Star Anise': '팔각',
    'Ginger': '생강',
    'Vanilla': '바닐라',
    'Saffron': '사프란',
    'Cumin': '커민',
    'Coriander': '고수',
    'Fennel': '회향',
    'Anise': '아니스',
    'Bay Leaf': '월계수',
    'Allspice': '올스파이스',
    'Turmeric': '강황',
    'Paprika': '파프리카',
    'Curry': '커리',
    
    # Woods
    'Sandalwood': '샌달우드',
    'Cedar': '시더',
    'Pine': '소나무',
    'Birch': '자작나무',
    'Oak': '참나무',
    'Bamboo': '대나무',
    'Driftwood': '유목',
    'Ebony': '흑단',
    'Mahogany': '마호가니',
    'Rosewood': '로즈우드',
    'Teak': '티크',
    'Cypress': '사이프러스',
    'Juniper': '주니퍼',
    'Fir': '전나무',
    'Spruce': '가문비나무',
    'Elm': '느릅나무',
    'Ash': '물푸레나무',
    'Maple': '단풍나무',
    'Cherry Wood': '체리우드',
    'Apple Wood': '사과나무',
    'Olive Wood': '올리브 나무',
    
    # Resins
    'Amber': '앰버',
    'Frankincense': '프랑킨센스',
    'Myrrh': '몰약',
    'Benzoin': '벤조인',
    'Labdanum': '라브다눔',
    'Opoponax': '오포포낙스',
    'Elemi': '엘레미',
    'Copal': '코팔',
    'Dragon Blood': '드래곤 블러드',
    'Styrax': '스티락스',
    
    # Musks and Animal notes
    'Musk': '머스크',
    'White Musk': '화이트 머스크',
    'Ambergris': '앰버그리스',
    'Civet': '시벳',
    'Castoreum': '카스토리움',
    'Ambroxan': '암브록산',
    'Iso E Super': '이소 E 슈퍼',
    
    # Green and Aromatic
    'Mint': '민트',
    'Basil': '바질',
    'Thyme': '타임',
    'Rosemary': '로즈마리',
    'Sage': '세이지',
    'Oregano': '오레가노',
    'Marjoram': '마조람',
    'Eucalyptus': '유칼립투스',
    'Tea Tree': '티트리',
    'Pine Needles': '솔잎',
    'Grass': '풀',
    'Moss': '이끼',
    'Fern': '고사리',
    'Leaves': '잎',
    'Green Notes': '그린 노트',
    'Seaweed': '해조류',
    'Algae': '조류',
    
    # Gourmand and Sweet
    'Chocolate': '초콜릿',
    'Coffee': '커피',
    'Caramel': '카라멜',
    'Honey': '꿀',
    'Sugar': '설탕',
    'Cream': '크림',
    'Milk': '우유',
    'Butter': '버터',
    'Bread': '빵',
    'Cookie': '쿠키',
    'Cake': '케이크',
    'Pie': '파이',
    'Jam': '잼',
    'Maple Syrup': '메이플 시럽',
    'Marshmallow': '마시멜로',
    'Cotton Candy': '솜사탕',
    'Liquorice': '감초',
    'Praline': '프랄린',
    'Nougat': '누가',
    'Toffee': '토피',
    'Fudge': '퍼지',
    
    # Alcoholic beverages
    'Wine': '와인',
    'Champagne': '샴페인',
    'Whiskey': '위스키',
    'Rum': '럼',
    'Brandy': '브랜디',
    'Gin': '진',
    'Vodka': '보드카',
    'Beer': '맥주',
    'Sake': '사케',
    'Cognac': '코냑',
    
    # Tea and Tobacco
    'Black Tea': '홍차',
    'Green Tea': '녹차',
    'White Tea': '백차',
    'Oolong Tea': '우롱차',
    'Earl Grey': '얼그레이',
    'Jasmine Tea': '자스민차',
    'Chai': '차이',
    'Tobacco': '담배',
    'Pipe Tobacco': '파이프 담배',
    'Cigarette': '담배',
    'Cuban Tobacco': '쿠바 담배',
    
    # Marine and Aquatic
    'Sea Water': '바닷물',
    'Ocean Breeze': '바다 바람',
    'Salt': '소금',
    'Seashells': '조개껍질',
    'Coral': '산호',
    'Driftwood': '유목',
    'Kelp': '다시마',
    'Plankton': '플랑크톤',
    'Rain': '비',
    'Water': '물',
    'Ice': '얼음',
    'Snow': '눈',
    'Fog': '안개',
    'Ozone': '오존',
    
    # Leather and Animalic
    'Leather': '가죽',
    'Suede': '스웨이드',
    'Fur': '모피',
    'Skin': '피부',
    'Hair': '머리카락',
    'Sweat': '땀',
    'Body Odor': '체취',
    
    # Metallic and Mineral
    'Metal': '금속',
    'Iron': '철',
    'Steel': '강철',
    'Copper': '구리',
    'Silver': '은',
    'Gold': '금',
    'Tin': '주석',
    'Lead': '납',
    'Stone': '돌',
    'Flint': '부싯돌',
    'Concrete': '콘크리트',
    'Dust': '먼지',
    'Sand': '모래',
    'Clay': '점토',
    'Chalk': '분필',
    'Gunpowder': '화약',
    'Sulfur': '황',
    'Tar': '타르',
    'Gasoline': '휘발유',
    'Rubber': '고무',
    'Plastic': '플라스틱',
    
    # 추가된 항목들
    'Earthy': '얼디',
    'Warm': '웜',
    'Spicy': '스파이시',
    'Aromatic': '아로마틱',
    'Peach': '피치',
    'May': '5월의',
    'Pear': '페어',
    'Sambac': '삼박',
    'Tahitian': '타히티안',
    'Australian': '호주산',
    'Liquorice': '리코리스',
    'Yellow': '옐로우',
    'Floral': '플로랄',
    'Tree': '트리',
    'Seed': '씨드',
    'Leaf': '리프',
    'Madagascar': '마다가스카르',
    'Coumarin': '쿠마린',
    'Calabrian': '칼라브리안',
    'Petitgrain': '페티그레인',
    'Ginger': '진저',
    'Cardamom': '카다멈',
    'Solar': '솔라',
    'Dry Flower': '드라이플라워',
    'Absolute': '앱솔루트',
    'Driftwood': '드리프트우드',
    'Musk': '머스',
    'Oud': '오드',
    'Yuzu': '유주',
    'Grape': '그레이프',
    'Fruit': '프룻',
    'Osmanthus': '오스만투스',
    'Hedione': '헤디온',
    'Pink': '핑크',
    'Watery': '워터리',
    'Wild': '와일드',
    'Flower': '플라워',
    'Tropical': '트로피칼',
}

def get_korean_note_name(english_name):
    """영어 노트명을 한국어로 번역"""
    return NOTE_TRANSLATIONS.get(english_name, english_name)

# 한국어 → 영어 역번역 딕셔너리
KOREAN_TO_ENGLISH = {
    '베르가못': 'Bergamot',
    '비가라드': 'Bigarade',
    '쓴오렌지': 'Bitter Orange',
    '블러드오렌지': 'Blood Orange',
    '레몬': 'Lemon',
    '라임': 'Lime',
    '오렌지': 'Orange',
    '자몽': 'Grapefruit',
    '만다린': 'Mandarin Orange',
    '탠저린': 'Tangerine',
    '유자': 'Yuzu',
    '네롤리': 'Neroli',
    '쁘띠그레인': 'Petitgrain',
    '시트러스': 'Citrus',
    '레몬그라스': 'Lemongrass',
    
    # 과일
    '사과': 'Apple',
    '살구': 'Apricot',
    '체리': 'Cherry',
    '복숭아': 'Peach',
    '배': 'Pear',
    '자두': 'Plum',
    '바나나': 'Banana',
    '블랙베리': 'Blackberry',
    '블루베리': 'Blueberry',
    '라즈베리': 'Raspberry',
    '딸기': 'Strawberry',
    '블랙커런트': 'Black Currant',
    '커런트': 'Black Currant',
    '코코넛': 'Coconut',
    '아몬드': 'Almond',
    '호두': 'Walnut',
    '헤이즐넛': 'Hazelnut',
    '무화과': 'Fig',
    '포도': 'Grape',
    '수박': 'Watermelon',
    '멜론': 'Melon',
    '파인애플': 'Pineapple',
    '망고': 'Mango',
    '파파야': 'Papaya',
    '패션프루트': 'Passion Fruit',
    '키위': 'Kiwi',
    '석류': 'Pomegranate',
    '당근': 'Carrot',
    '토마토': 'Tomato',
    '리치': 'Lychee',
    
    # 꽃
    '장미': 'Rose',
    '로즈': 'Rose',
    '자스민': 'Jasmine',
    '라벤더': 'Lavender',
    '백합': 'Lily',
    '작약': 'Peony',
    '피오니': 'Peony',
    '치자꽃': 'Gardenia',
    '튜베로즈': 'Tuberose',
    '일랑일랑': 'Ylang-Ylang',
    '카네이션': 'Carnation',
    '제비꽃': 'Violet',
    '바이올렛': 'Violet',
    '아이리스': 'Iris',
    '프리지아': 'Freesia',
    '목련': 'Magnolia',
    '매그놀리아': 'Magnolia',
    '은방울꽃': 'Lily of the Valley',
    '제라늄': 'Geranium',
    '수선화': 'Narcissus',
    '오렌지블라썸': 'Orange Blossom',
    '연꽃': 'Lotus',
    '미모사': 'Mimosa',
    '인동꽃': 'Honeysuckle',
    '등나무': 'Wisteria',
    '히비스커스': 'Hibiscus',
    '카모마일': 'Chamomile',
    '메리골드': 'Marigold',
    '해바라기': 'Sunflower',
    '달리아': 'Dahlia',
    '난초': 'Orchid',
    '벚꽃': 'Cherry Blossom',
    '플루메리아': 'Plumeria',
    '라일락': 'Lilac',
    '히아신스': 'Hyacinth',
    '국화': 'Chrysanthemum',
    
    # 스파이스
    '계피': 'Cinnamon',
    '카다몬': 'Cardamom',
    '정향': 'Clove',
    '육두구': 'Nutmeg',
    '후추': 'Black Pepper',
    '핑크페퍼': 'Pink Pepper',
    '핑크': 'Pink Pepper',
    '페퍼': 'Pepper',
    '팔각': 'Star Anise',
    '생강': 'Ginger',
    '바닐라': 'Vanilla',
    '사프란': 'Saffron',
    '커민': 'Cumin',
    '고수': 'Coriander',
    '코리안더': 'Coriander',
    '회향': 'Fennel',
    '아니스': 'Anise',
    '월계수': 'Bay Leaf',
    '올스파이스': 'Allspice',
    '강황': 'Turmeric',
    '파프리카': 'Paprika',
    '커리': 'Curry',
    
    # 우드
    '샌달우드': 'Sandalwood',
    '시더': 'Cedar',
    '소나무': 'Pine',
    '자작나무': 'Birch',
    '참나무': 'Oak',
    '대나무': 'Bamboo',
    '유목': 'Driftwood',
    '흑단': 'Ebony',
    '마호가니': 'Mahogany',
    '로즈우드': 'Rosewood',
    '팰리샌더': 'Rosewood',
    '티크': 'Teak',
    '사이프러스': 'Cypress',
    '시프레': 'Cypress',
    '주니퍼': 'Juniper',
    '전나무': 'Fir',
    '가문비나무': 'Spruce',
    '느릅나무': 'Elm',
    '물푸레나무': 'Ash',
    '단풍나무': 'Maple',
    '체리우드': 'Cherry Wood',
    '사과나무': 'Apple Wood',
    '올리브나무': 'Olive Wood',
    '우디': 'Woody',
    '노트': 'Notes',
    
    # 레진
    '앰버': 'Amber',
    '프랑킨센스': 'Frankincense',
    '몰약': 'Myrrh',
    '벤조인': 'Benzoin',
    '라브다눔': 'Labdanum',
    '오포포낙스': 'Opoponax',
    '엘레미': 'Elemi',
    '코팔': 'Copal',
    '드래곤블러드': 'Dragon Blood',
    '스티락스': 'Styrax',
    
    # 머스크
    '머스크': 'Musk',
    '화이트머스크': 'White Musk',
    '화이트': 'White',
    '앰버그리스': 'Ambergris',
    '시벳': 'Civet',
    '카스토리움': 'Castoreum',
    '암브록산': 'Ambroxan',
    '이소이수퍼': 'Iso E Super',
    
    # 그린/아로마틱
    '민트': 'Mint',
    '바질': 'Basil',
    '타임': 'Thyme',
    '로즈마리': 'Rosemary',
    '세이지': 'Sage',
    '오레가노': 'Oregano',
    '마조람': 'Marjoram',
    '유칼립투스': 'Eucalyptus',
    '티트리': 'Tea Tree',
    '솔잎': 'Pine Needles',
    '풀': 'Grass',
    '이끼': 'Moss',
    '모스': 'Moss',
    '고사리': 'Fern',
    '잎': 'Leaves',
    '그린노트': 'Green Notes',
    '해조류': 'Seaweed',
    '조류': 'Algae',
    
    # 구르망/스위트
    '초콜릿': 'Chocolate',
    '커피': 'Coffee',
    '카라멜': 'Caramel',
    '꿀': 'Honey',
    '허니': 'Honey',
    '설탕': 'Sugar',
    '크림': 'Cream',
    '우유': 'Milk',
    '버터': 'Butter',
    '빵': 'Bread',
    '쿠키': 'Cookie',
    '케이크': 'Cake',
    '파이': 'Pie',
    '잼': 'Jam',
    '메이플시럽': 'Maple Syrup',
    '마시멜로': 'Marshmallow',
    '솜사탕': 'Cotton Candy',
    '감초': 'Liquorice',
    '프랄린': 'Praline',
    '누가': 'Nougat',
    '토피': 'Toffee',
    '퍼지': 'Fudge',
    
    # 음료
    '와인': 'Wine',
    '샴페인': 'Champagne',
    '위스키': 'Whiskey',
    '럼': 'Rum',
    '브랜디': 'Brandy',
    '진': 'Gin',
    '보드카': 'Vodka',
    '맥주': 'Beer',
    '사케': 'Sake',
    '코냑': 'Cognac',
    
    # 차/담배
    '홍차': 'Black Tea',
    '녹차': 'Green Tea',
    '백차': 'White Tea',
    '우롱차': 'Oolong Tea',
    '얼그레이': 'Earl Grey',
    '자스민차': 'Jasmine Tea',
    '차이': 'Chai',
    '담배': 'Tobacco',
    '파이프담배': 'Pipe Tobacco',
    '쿠바담배': 'Cuban Tobacco',
    
    # 해양/아쿠아틱
    '바닷물': 'Sea Water',
    '바다바람': 'Ocean Breeze',
    '소금': 'Salt',
    '조개껍질': 'Seashells',
    '산호': 'Coral',
    '다시마': 'Kelp',
    '플랑크톤': 'Plankton',
    '비': 'Rain',
    '물': 'Water',
    '얼음': 'Ice',
    '눈': 'Snow',
    '안개': 'Fog',
    '오존': 'Ozone',
    
    # 가죽/애니멀릭
    '가죽': 'Leather',
    '레더': 'Leather',
    '스웨이드': 'Suede',
    '모피': 'Fur',
    '피부': 'Skin',
    '머리카락': 'Hair',
    '땀': 'Sweat',
    '체취': 'Body Odor',
    
    # 기타 자주 나오는 노트들
    '페출리': 'Patchouli',
    '파츌리': 'Patchouli',
    '페출': 'Patchouli',
    '베티버': 'Vetiver',
    '카시스': 'Black Currant',
    '블랙': 'Black',
    '다마스크': 'Damask',
    '불가리안': 'Bulgarian',
    '터키쉬': 'Turkish',
    '스파이스': 'Spice',
    '루트': 'Root',
    '시앗': 'Seed',
    '씨앗': 'Seed',
    '알데하이드': 'Aldehyde',
    '부들레아': 'Buddleia',
    '월': 'Month',
    '5월의': 'May',
    '페탈': 'Petal',
    '워': 'Water',
}

def get_english_note_name(korean_name):
    """한국어 노트명을 영어로 역번역"""
    return KOREAN_TO_ENGLISH.get(korean_name, korean_name)

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
        
        # admin 사용자의 즐겨찾기한 향수들 가져오기
        favorite_perfumes = Perfume.objects.filter(
            favorited_by__user=request.user
        ).order_by('-favorited_by__created_at')
        
        # admin 사용자의 좋아요한 향수들 가져오기
        liked_perfumes = Perfume.objects.filter(
            feedback_events__user=request.user,
            feedback_events__action='like'
        ).distinct().order_by('-feedback_events__created_at')
        
        # admin 사용자의 싫어요한 향수들 가져오기
        disliked_perfumes = Perfume.objects.filter(
            feedback_events__user=request.user,
            feedback_events__action='dislike'
        ).distinct().order_by('-feedback_events__created_at')
        
        favorites_count = favorite_perfumes.count()
        likes_count = liked_perfumes.count()
        dislikes_count = disliked_perfumes.count()
        
        context = {
            'favorite_perfumes': favorite_perfumes,
            'favorites_count': favorites_count,
            'liked_perfumes': liked_perfumes,
            'likes_count': likes_count,
            'disliked_perfumes': disliked_perfumes,
            'dislikes_count': dislikes_count
        }
        
    except User.DoesNotExist:
        context = {
            'favorite_perfumes': Perfume.objects.none(),
            'favorites_count': 0,
            'liked_perfumes': Perfume.objects.none(),
            'likes_count': 0,
            'disliked_perfumes': Perfume.objects.none(),
            'dislikes_count': 0,
            'error': 'admin 사용자를 찾을 수 없습니다.'
        }
    
    return render(request, "scentpick/mypage.html", context)

@login_required
@require_GET
def conversations_api(request):
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
    conv = get_object_or_404(Conversation, id=conv_id, user=request.user)
    msgs = conv.messages.order_by('created_at')
    data = []
    for m in msgs:
        data.append({
            'role': m.role,
            'content': m.content,
            'created_at': m.created_at.isoformat(),
        })
    return JsonResponse({'conversation_id': conv.id, 'items': data})

@login_required
@require_POST
def chat_new_api(request):
    # Reset conversation and start a fresh thread for new chat
    request.session['conversation_id'] = None
    new_uuid = str(uuid.uuid4())
    request.session['thread_uuid'] = new_uuid
    return JsonResponse({'ok': True, 'external_thread_id': new_uuid})
