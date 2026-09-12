"""
quick test: can we send a whatsapp message at all?
this skips the whole webhook/AI part and just tries to send one message directly.
if this works, sending is fine and the problem is elsewhere.
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

# put your own whatsapp number here, with country code, no + sign
MY_NUMBER = "8801644173346"

url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
headers = {
    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
    "Content-Type": "application/json",
}
payload = {
    "messaging_product": "whatsapp",
    "to": MY_NUMBER,
    "type": "text",
    "text": {"body": "Test message from Clinic AI backend"},
}

print(f"Phone Number ID being used: {WHATSAPP_PHONE_NUMBER_ID}")
print(f"Token starts with: {WHATSAPP_TOKEN[:15] if WHATSAPP_TOKEN else 'NONE - not loaded!'}...")
print(f"Sending to: {MY_NUMBER}\n")

response = httpx.post(url, headers=headers, json=payload, timeout=30)
print(f"Status: {response.status_code}")
print(f"Response: {response.text}")