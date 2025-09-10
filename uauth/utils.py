import io
import os
from typing import Optional, Dict

from django.conf import settings


def _ensure_pillow():
    try:
        from PIL import Image, ImageOps, ImageSequence  # noqa: F401
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Pillow (PIL) is required for image processing.") from e


def _open_image(file_obj):
    from PIL import Image, ImageOps, ImageSequence
    file_obj.seek(0)
    img = Image.open(file_obj)
    if getattr(img, "is_animated", False):
        frame0 = ImageSequence.Iterator(img).__next__()
        img = frame0.convert("RGBA")
    return img


def _to_square(img):
    w, h = img.size
    if w == h:
        return img
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def _apply_crop(img, crop: Optional[Dict[str, float]]):
    """Apply square crop sent from client.

    Frontend sends x, y, size computed in ORIGINAL image coordinates
    (it divides the preview offsets by scale before submit).
    Therefore, we MUST NOT resize by scale here. We crop directly
    using (x, y, size) on the original image space.
    """
    if not crop:
        return _to_square(img)
    try:
        x = float(crop.get("x"))
        y = float(crop.get("y"))
        size = float(crop.get("size"))
        # scale is ignored for crop, kept for backward compatibility
        _ = float(crop.get("scale", 1.0))
    except Exception:
        return _to_square(img)

    # Clamp to image bounds in original space
    w, h = img.size
    x = max(0.0, x)
    y = max(0.0, y)
    size = max(1.0, size)
    if x + size > w:
        x = max(0.0, w - size)
    if y + size > h:
        y = max(0.0, h - size)
    return img.crop((int(x), int(y), int(x + size), int(y + size)))


def _to_rgb(img):
    from PIL import Image
    if img.mode in ("RGB",):
        return img
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def process_profile_image(file_obj, crop: Optional[Dict[str, float]] = None, size: int = 512) -> bytes:
    _ensure_pillow()
    from PIL import Image

    file_obj.seek(0, os.SEEK_END)
    file_size = file_obj.tell()
    if file_size > 5 * 1024 * 1024:
        raise ValueError("이미지 최대 5MB까지 가능합니다.")
    file_obj.seek(0)

    img = _open_image(file_obj)
    img = _apply_crop(img, crop)
    img = img.resize((size, size), Image.LANCZOS)
    img = _to_rgb(img)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    buf.seek(0)
    return buf.read()


def upload_to_s3_and_get_url(user_id: int, image_bytes: bytes, ext: str = "jpg") -> str:
    import base64
    bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None)
    region = getattr(settings, "AWS_S3_REGION_NAME", None)
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")

    if not (bucket and region and access_key and secret_key):
        raise RuntimeError("S3 설정을 확인하세요 (.env / settings)")

    try:
        import boto3
    except Exception as e:
        raise RuntimeError("boto3 패키지 필요: pip install boto3") from e

    s3 = boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )
    key = f"profiles/{user_id}.{ext}"
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=image_bytes,
        ContentType="image/jpeg" if ext.lower() in ("jpg", "jpeg") else "image/png",
        ACL="public-read",
        CacheControl="public, max-age=31536000",
    )
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"