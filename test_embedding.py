
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
api_key = os.getenv("GEMINI_API_KEYS", "").split(",")[0].strip()
if not api_key:
    print("No API key found in GEMINI_API_KEYS")
    exit(1)

client = genai.Client(api_key=api_key)
print(f"Testing embedding with model: text-embedding-005")

try:
    result = client.models.embed_content(
        model='text-embedding-005',
        contents="Hello world",
        config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY")
    )
    print("✅ Embedding success!")
    # print(result)
except Exception as e:
    print(f"❌ Embedding failed: {e}")
    # Try 004 just to confirm it fails
    try:
        print("Testing fallback check on text-embedding-004...")
        client.models.embed_content(
            model='text-embedding-004',
            contents="Hello",
        )
        print("❓ text-embedding-004 unexpectedly worked?")
    except Exception as e2:
        print(f"Expected failure for 004: {e2}")

