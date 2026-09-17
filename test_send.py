"""
quick check: can we send a whatsapp message at all?
skips the webhook and the AI entirely - just fires one message straight at the API.
if this works, sending is fine and any problem is somewhere else.
"""

import os
import sys
import httpx
from dotenv import load_dotenv

load_dotenv()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

# whichever number you want the test message to land on,
# with country code and no + sign, e.g. 8801XXXXXXXXX
TEST_RECIPIENT = os.getenv("TEST_RECIPIENT")

if not WHATSAPP_TOKEN:
    sys.exit("WHATSAPP_TOKEN is missing from .env")
if not WHATSAPP_PHONE_NUMBER_ID:
    sys.exit("WHATSAPP_PHONE_NUMBER_ID is missing from .env")
if not TEST_RECIPIENT:
    sys.exit("TEST_RECIPIENT is missing from .env (your own number, country code, no +)")

url = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
headers = {
    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
    "Content-Type": "application/json",
}
payload = {
    "messaging_product": "whatsapp",
    "to": TEST_RECIPIENT,
    "type": "text",
    "text": {"body": "Test message from Clinic AI backend"},
}

print(f"Phone Number ID: {WHATSAPP_PHONE_NUMBER_ID}")
print(f"Token starts with: {WHATSAPP_TOKEN[:12]}...")
print(f"Sending to: {TEST_RECIPIENT}\n")

response = httpx.post(url, headers=headers, json=payload, timeout=30)
print(f"Status: {response.status_code}")
print(f"Response: {response.text}")