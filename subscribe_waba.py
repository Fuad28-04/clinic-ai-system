"""
one-time setup script.
tells meta: "forward messages from this whatsapp business account to my app".
run it once after issuing a new access token.
"""

import os
import sys
import httpx
from dotenv import load_dotenv

load_dotenv()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WABA_ID = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID")

# fail early with a clear message instead of a confusing API error later
if not WHATSAPP_TOKEN:
    sys.exit("WHATSAPP_TOKEN is missing from .env")
if not WABA_ID:
    sys.exit("WHATSAPP_BUSINESS_ACCOUNT_ID is missing from .env")

url = f"https://graph.facebook.com/v21.0/{WABA_ID}/subscribed_apps"
headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

print("Subscribing app to WABA...")
response = httpx.post(url, headers=headers, timeout=30)
print(f"Status: {response.status_code}")
print(f"Response: {response.text}")

# read it back so we can confirm the app actually shows up
print("\nChecking current subscriptions...")
check = httpx.get(url, headers=headers, timeout=30)
print(f"Status: {check.status_code}")
print(f"Response: {check.text}")