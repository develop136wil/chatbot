
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
api_key = os.getenv("GEMINI_API_KEYS", "").split(",")[0].strip()
if not api_key:
    print("No API key found")
    exit(1)

client = genai.Client(api_key=api_key)
print("Listing models...")
try:
    for m in client.models.list(config={'page_size': 100}):
        if 'embed' in m.name.lower():
            print(f"Model: {m.name}")
except Exception as e:
    print(f"Error listing models: {e}")
