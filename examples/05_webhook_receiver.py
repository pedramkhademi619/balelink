"""Receive gateway webhooks and verify their signature.

pip install fastapi uvicorn
uvicorn examples.05_webhook_receiver:app --port 9000   # or rename the file
"""

import hmac

from fastapi import FastAPI, HTTPException, Request

from balelink.gateway.webhook import SIGNATURE_HEADER, sign

SECRET = "the-secret-you-gave-the-gateway"
app = FastAPI()


@app.post("/hook")
async def hook(request: Request):
    body = await request.body()
    given = request.headers.get(SIGNATURE_HEADER, "")
    if not hmac.compare_digest(given, sign(SECRET, body)):
        raise HTTPException(401, "bad signature")
    event = await request.json()
    msg = event["payload"]
    if event["event"] == "message":
        print(event["session"], msg["sender_id"], msg["kind"], msg["text"] or msg["caption"])
    return {"ok": True}
