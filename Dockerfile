FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 빌드 및 런타임에 필요한 OS 패키지 설치
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       libpq-dev \
       default-libmysqlclient-dev \
       libjpeg-dev \
       zlib1g-dev \
       libssl-dev \
       pkg-config \
    && pip install --upgrade pip

# requirements 먼저 복사해서 설치 (캐시 활용 최적화)
COPY requirements.txt .
RUN pip install -r requirements.txt

# 불필요한 빌드 툴 제거 + 캐시 정리
RUN apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

# 프로젝트 소스 복사
COPY . .

EXPOSE 8000
CMD ["gunicorn", "-c", "gunicorn.conf.py"]