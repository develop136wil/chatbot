# 1. 베이스 이미지 (Python 3.10)
FROM python:3.10-slim

# 2. 시스템 패키지 설치 (Redis 서버 필수)
RUN apt-get update && apt-get install -y \
    redis-server \
    && rm -rf /var/lib/apt/lists/*

# 3. 보안을 위한 사용자 설정
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

# 4. 작업 디렉토리 설정
WORKDIR /app

# 5. 라이브러리 설치
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. 소스 코드 복사
COPY --chown=user . .

# 7. 포트 개방
EXPOSE 7860

# 8. [핵심 수정] bash로 스크립트 강제 실행!
CMD ["bash", "start.sh"]