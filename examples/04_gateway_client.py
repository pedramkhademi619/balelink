"""Use the HTTP gateway from any language - here, Python with httpx.

BALELINK_API_KEY=secret balelink serve        # in another terminal
python examples/04_gateway_client.py
"""

import httpx

BASE = "http://127.0.0.1:8787"
HEADERS = {"X-Api-Key": "secret"}

with httpx.Client(base_url=BASE, headers=HEADERS) as http:
    http.post("/sessions", json={"name": "me", "webhook_url": "http://127.0.0.1:9000/hook"})
    http.post("/sessions/me/login/code", json={"phone": input("Phone: ")}).raise_for_status()
    r = http.post("/sessions/me/login/verify", json={"code": input("Code: ")})
    print(r.json())
    http.post("/sessions/me/messages", json={"to": "09121234567", "text": "hello"})
