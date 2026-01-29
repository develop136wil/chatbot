# Vercel 배포용 환경 변수 설정

# Vercel Environment Variables 설정 필요:
# GEMINI_API_KEYS=your_keys_here
# SUPABASE_URL=your_supabase_url  
# SUPABASE_KEY=your_supabase_key
# GROQ_API_KEY=your_groq_key
# REDIS_HOST=your_redis_cloud_url

# Worker 인스턴스용 (별도):
# NOTION_KEY=your_notion_key (Worker에서만 필요)

# Vercel.json 구조:
{
  "version": 2,
  "builds": [{"src": "main.py", "use": "@vercel/python"}],
  "routes": [{"src": "main.py", "dest": "/"}],
  "env": {
    "GEMINI_API_KEYS": "@gemini_keys",
    "SUPABASE_URL": "@supabase_url", 
    "SUPABASE_KEY": "@supabase_key",
    "GROQ_API_KEY": "@groq_key",
    "REDIS_HOST": "@redis_host"
  }
}