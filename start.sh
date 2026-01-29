#!/bin/bash

# 1. Redis 서버 실행
echo "🚀 Starting Redis Server..."
redis-server --save "" --appendonly no &
sleep 2

# 2. Worker (오뚝이 모드: 죽으면 5초 뒤 부활)
# (괄호) 안에 넣고 무한루프(while true)를 돌리면 죽어도 다시 살아남!
(
  while true; do
    echo "🚀 Starting Chatbot Worker 1..."
    python -u worker.py
    echo "⚠️ Worker 1 crashed! Restarting in 5 seconds..."
    sleep 5
  done
) &

# 요리사 2명 쓰고 싶으면 이렇게 하나 더 추가
(
  while true; do
    echo "🚀 Starting Chatbot Worker 2..."
    python -u worker.py
    echo "⚠️ Worker 2 crashed! Restarting in 5 seconds..."
    sleep 5
  done
) &

# 3. FastAPI 서버 실행
# (이게 죽으면 컨테이너 전체가 죽고, 그건 Hugging Face가 살려줌)
echo "🚀 Starting FastAPI Server..."
uvicorn main:app --host 0.0.0.0 --port 7860