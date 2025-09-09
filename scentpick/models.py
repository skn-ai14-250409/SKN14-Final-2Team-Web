from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator

USER_MODEL = settings.AUTH_USER_MODEL  # 기본값: auth.User

# Django 모델에서 기본값은 null=False (즉, NOT NULL)

# -----------------------------
# Perfume & static resources
# -----------------------------
class Perfume(models.Model):
    """
    향수 테이블 (perfumes)
    """
    id = models.BigAutoField(primary_key=True)
    brand = models.CharField(max_length=50)                         # text NN
    name = models.CharField(max_length=50)                          # text NN

    # 단일 ml 컬럼 삭제(size_ml) → JSON 리스트로 sizes 추가
    # 예: [30, 50, 100]
    sizes = models.JSONField(default=list, help_text="용량(ml) 리스트", null=True)

    detail_url = models.CharField(max_length=500, blank=True, null=True)
    description = models.TextField()
    concentration = models.CharField(max_length=30)

    # 마케팅/사용 대상을 위한 성별
    gender = models.CharField(
        max_length=10,  # Male, Female, Unisex 등
        default="Unisex",
        help_text="마케팅/사용 대상으로 설정한 성별(Male/Female/Unisex)"
    )

    # 노트 / 어코드 JSON 리스트 필드
    main_accords = models.JSONField() 
    top_notes = models.JSONField(blank=True, null=True)  
    middle_notes = models.JSONField(blank=True, null=True)
    base_notes = models.JSONField(blank=True, null=True)

    # 점수/추천 지표는 구조화 가능한 JSON dict로 관리
    notes_score = models.JSONField(blank=True, null=True)           # {"rose": 100.0, "jasmine": 87.5, ...}
    season_score = models.JSONField(blank=True, null=True)          # {"winter": 14.2, "summer": 22.5, ...}
    day_night_score = models.JSONField(blank=True, null=True)       # {"day": 47.1, "night": 25.9}

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "perfumes"
        indexes = [
            models.Index(fields=["brand"]),
            models.Index(fields=["name"]),
            models.Index(fields=["updated_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "name"],
                name="uq_perfume_brand_name",
            ),
        ]

    def __str__(self):
        return f"{self.brand} {self.name}"


class NoteImage(models.Model):
    """
    노트별 이미지 (note_images)
    """
    id = models.BigAutoField(primary_key=True)
    category = models.CharField(max_length=50, blank=True, null=True)
    note_name = models.CharField(max_length=50, blank=True, null=True)
    image_url = models.CharField(max_length=500, blank=True, null=True)

    class Meta:
        db_table = "note_images"

    def __str__(self):
        return self.note_name or f"Image#{self.pk}"


# -----------------------------
# Conversations & messages
# -----------------------------
class Conversation(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        USER_MODEL, on_delete=models.CASCADE, related_name="conversations"
    )
    title = models.CharField(max_length=40, blank=True, null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "conversations"
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["updated_at"]),
        ]

    def __str__(self):
        return f"Conv#{self.pk}"


class Message(models.Model):
    class Role(models.TextChoices):
        SYSTEM = "system", "system" # 값(DB 저장용), 라벨(표시용)
        USER = "user", "user"
        ASSISTANT = "assistant", "assistant"
        TOOL = "tool", "tool"  # user/assistant/tool

    id = models.BigAutoField(primary_key=True)
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    model = models.CharField(max_length=120, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "messages"
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self):
        return f"{self.role}@{self.conversation_id}"


# -----------------------------
# Favorites
# -----------------------------
class Favorite(models.Model):
    user = models.ForeignKey(
        USER_MODEL, on_delete=models.CASCADE, related_name="favorites"
    )
    perfume = models.ForeignKey(
        Perfume, on_delete=models.CASCADE, related_name="favorited_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "favorites"
        constraints = [
            models.UniqueConstraint(fields=["user", "perfume"], name="uq_favorite_user_perfume"),
        ]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["perfume"]),
        ]

    def __str__(self):
        return f"{self.user_id} - {self.perfume_id}"


# -----------------------------
# Recommendation logging
# -----------------------------
class RecRun(models.Model):
    """
    추천 근거 로깅 (rec_runs)
    한 번의 추천 수행(run)에 대한 메타 정보
    """
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        USER_MODEL, on_delete=models.CASCADE, related_name="rec_runs"
    )
    conversation = models.ForeignKey(
        Conversation, on_delete=models.SET_NULL, null=True, blank=True, related_name="rec_runs"
    )
    request_msg = models.ForeignKey(
        Message, on_delete=models.SET_NULL, null=True, blank=True, related_name="as_request_of_rec_runs"
    )

    query_text = models.TextField                                   # 사용자 원문 질의
    parsed_slots = models.JSONField(blank=True, null=True)          # 파싱된 슬롯
    agent = models.CharField(max_length=120, blank=True, null=True) # 사용한 추천 agent명
    model_version = models.CharField(max_length=120, blank=True, null=True)  # 모델/인덱스 버전

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rec_runs"
        indexes = [
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"RecRun#{self.pk} by {self.user_id}"


class RecCandidate(models.Model):
    """
    특정 run에서 추천된 각 후보와 근거 (rec_candidates)
    """
    id = models.BigAutoField(primary_key=True)
    run_rec = models.ForeignKey(
        RecRun, on_delete=models.CASCADE, related_name="candidates"
    )
    perfume = models.ForeignKey(
        Perfume, on_delete=models.CASCADE, related_name="rec_candidates"
    )

    rank = models.IntegerField(validators=[MinValueValidator(1)])   # 정렬 순위(1부터)
    score = models.FloatField(default=0.0)                          # 최종 랭킹 점수

    reason_summary = models.TextField(blank=True, null=True)        # 짧은 추천 이유 문장
    reason_detail = models.JSONField(blank=True, null=True)         # 구조화된 근거
    retrieved_from = models.CharField(
        max_length=120, blank=True, null=True,
        help_text="후보를 가져온 소스/전략 라벨 (e.g., dense, bm25, rule)"
    )

    class Meta:
        db_table = "rec_candidates"
        indexes = [
            models.Index(fields=["run_rec", "rank"]),
            models.Index(fields=["perfume"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["run_rec", "perfume"], name="uq_rec_candidate_run_perfume"),
        ]

    def __str__(self):
        return f"Run#{self.run_rec_id} → P#{self.perfume_id} (rank={self.rank})"


class FeedbackEvent(models.Model):
    """
    사용자 좋아요/싫어요 등 피드백 이력 (feedback_events)
    """
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        USER_MODEL, on_delete=models.CASCADE, related_name="feedback_events"
    )
    perfume = models.ForeignKey(
        Perfume, on_delete=models.CASCADE, related_name="feedback_events"
    )
    rec_candidate = models.ForeignKey(
        RecCandidate, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="feedback_events",
        help_text="특정 추천 리스트에서 나온 후보와 연결 (없을 수도 있음)"
    )

    source = models.CharField(max_length=120)                       # 이벤트 발생 맥락 (e.g., list, detail, popup)
    action = models.CharField(max_length=50)                        # e.g., like, dislike, dismiss, view
    context = models.JSONField(blank=True, null=True)               # 부가 정보(날씨, 월, 세션정보 등)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "feedback_events"
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["perfume"]),
            models.Index(fields=["rec_candidate"]),
            models.Index(fields=["action"]),
        ]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.user_id} {self.action} P#{self.perfume_id}"