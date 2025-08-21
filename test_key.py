from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

try:
    response = client.models.list()
    print("✅ API key works! Models available:")
    for m in response.data[:5]:  # show first 5 models
        print("-", m.id)
except Exception as e:
    print("❌ Error:", e)
