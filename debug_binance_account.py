from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error

BASE_URL = "https://api.binance.com"
PATH = "/api/v3/account"

api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")

if not api_key or not api_secret:
    raise RuntimeError("Faltan BINANCE_API_KEY o BINANCE_API_SECRET")

params = {
    "recvWindow": "5000",
    "timestamp": str(int(time.time() * 1000)),
}

query_string = urllib.parse.urlencode(params, safe=".")
signature = hmac.new(
    api_secret.encode("utf-8"),
    query_string.encode("utf-8"),
    hashlib.sha256,
).hexdigest()

body = f"{query_string}&signature={signature}".encode("utf-8")

request = urllib.request.Request(
    url=f"{BASE_URL}{PATH}",
    data=body,
    method="GET",
    headers={
        "X-MBX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded",
    },
)

print("=== REQUEST ===")
print("METHOD: GET")
print("URL:", f"{BASE_URL}{PATH}")
print("BODY:", body.decode("utf-8"))
print("HEADERS:", {"X-MBX-APIKEY": api_key[:4] + "..." + api_key[-4:]})

try:
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read().decode("utf-8")
        print("\n=== RESPONSE ===")
        print("STATUS:", response.status)
        print(raw)
except urllib.error.HTTPError as exc:
    error_body = exc.read().decode("utf-8", errors="replace")
    print("\n=== RESPONSE ===")
    print("STATUS:", exc.code)
    print(error_body)
except Exception as exc:
    print("\n=== ERROR ===")
    print(repr(exc))