from datetime import datetime
import json
import random

import requests
from zoneinfo import ZoneInfo
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render, redirect

from uauth.models import UserDetail
from uauth.utils import process_profile_image, upload_to_s3_and_get_url
from .models import Perfume


def home(request):
    return render(request, "scentpick/home.html")

def login_view(request):
    return render(request, "scentpick/login.html")

def register(request):
    return render(request, "scentpick/register.html")


def product_detail(request, slug):
    # TODO: slug로 DB 조회 후 컨텍스트 바인딩
    ctx = {
        "brand": "Chanel",
        "name": "블루 드 샤넬",
        "price": "₩165,000",
        "slug": slug,
    }
    return render(request, "scentpick/product_detail.html", ctx)

@login_required
def chat(request):
    return render(request, "scentpick/chat.html")

@login_required
def recommend(request):
    return render(request, "scentpick/recommend.html")

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
def mypage(request):
    return render(request, "scentpick/mypage.html")

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
                    import imghdr
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

def fetch_weather_simple(city="Seoul"):
    # 1) 지오코딩
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

    # 2) 현재 날씨
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
    city = request.GET.get("city", "Seoul")

    # 템플릿 라디오 옵션
    ACCORD_OPTIONS = ["플로랄", "우디", "시트러스", "스파이시", "파우더리", "스위트"]

    # 월드컵 필터 값(그대로 유지)
    g = request.GET.get("g", "")   # "남성" | "여성" | "남녀공용"
    a = request.GET.get("a", "")   # "플로랄" | ...
    t = request.GET.get("t", "")   # "day" | "night"

    try:
        # ① 날씨 정보
        line1, line2, code = fetch_weather_simple(city)
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