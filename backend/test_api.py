import requests
import json
import time
import os

BASE_URL = "http://127.0.0.1:8002/api"

print("1. Creating new session...")
res = requests.get(f"{BASE_URL}/session/new")
session_id = res.json()["session_id"]
print(f"Session ID: {session_id}")

print("\n2. Checking existing documents (should be empty for new session)...")
res = requests.get(f"{BASE_URL}/documents", params={"session_id": session_id})
print(f"Documents: {res.json()}")

print("\n3. Uploading ml.pdf...")
pdf_path = "/Users/k/Downloads/Samvaad_Final_APP/backend/uploads/ml.pdf"
with open(pdf_path, 'rb') as f:
    res = requests.post(
        f"{BASE_URL}/documents/upload",
        data={"session_id": session_id},
        files={"files": ("ml.pdf", f, "application/pdf")}
    )
print(f"Upload Response: {res.json()}")

print("\n4. Triggering Memory Test - asking a personal fact")
res = requests.post(f"{BASE_URL}/chat", json={
    "session_id": session_id,
    "prompt": "Hi, my name is John and I love data science. What is Machine Learning according to the document?"
})
print(f"Text query response preview: {res.json()['response'][:100]}...")

print("\nWaiting 2 seconds for background memory update to finish...")
time.sleep(2)

print("\n5. Checking if memory was updated...")
res = requests.get(f"{BASE_URL}/memory/{session_id}")
print(f"Memory: {res.json()}")

print("\n6. Asking a visual query to test image retrieval...")
res = requests.post(f"{BASE_URL}/chat", json={
    "session_id": session_id,
    "prompt": "Can you explain the architecture diagram or any figures shown in the document?"
})
chat_data = res.json()
print(f"Visual query response preview: {chat_data['response'][:100]}...")
print(f"Image Sources Found: {len(chat_data.get('image_sources', []))}")
for img in chat_data.get('image_sources', []):
    print(f" - Image ID: {img['img_id']}, Score: {img['score']}")

