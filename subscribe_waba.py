"""
one-time helper script.
this tells meta: "hey, forward messages from this whatsapp business account to my app"
run it once, then delete it (or keep it, doesn't matter)
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WABA_ID = "1391902689110766"   # whatsapp business account id from the meta dashboard

url = f"https://graph.facebook.com/v21.0/{WABA_ID}/subscribed_apps"
headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

print("Subscribing app to WABA...")
response = httpx.post(url, headers=headers, timeout=30)
print(f"Status: {response.status_code}")
print(f"Response: {response.text}")

# also check what's currently subscribed, so we can confirm it worked
print("\nChecking current subscriptions...")
check = httpx.get(url, headers=headers, timeout=30)
print(f"Status: {check.status_code}")
print(f"Response: {check.text}")