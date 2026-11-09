"""FastAPI entry point for the Customer Wallet and balance kiosk."""

import asyncio
import importlib.util
import re
from pathlib import Path
from uuid import UUID

import psycopg2
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import database


# Load the same token verifier used by Cashier, without importing the desktop app.
here = Path(__file__).resolve().parent
security_path = here.parent / "nfc-desktop" / "token_security.py"
spec = importlib.util.spec_from_file_location("foodcourt_token_security", security_path)
security = importlib.util.module_from_spec(spec)
spec.loader.exec_module(security)

app = FastAPI(title="Food Court Customer Portal")
templates = Jinja2Templates(directory=str(here / "templates"))


class ConnectionManager:
    """Track the browser screens that are waiting for a kiosk scan."""

    def __init__(self):
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, event: dict):
        # Take a snapshot because screens may disconnect during a send.
        for connection in tuple(self.active_connections):
            try:
                await asyncio.wait_for(connection.send_json(event), timeout=1)
            except (OSError, RuntimeError, WebSocketDisconnect, TimeoutError):
                self.disconnect(connection)


manager = ConnectionManager()


def wallet_page(request, *, wallet=None, transactions=(), error=None, status=200):
    # Signed wallet URLs and transaction details should not be cached or forwarded.
    return templates.TemplateResponse(
        request=request,
        name="wallet.html",
        context={
            "wallet": wallet, "transactions": transactions,
            "error": error, "message": error,
        },
        status_code=status,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@app.get("/wallet", response_class=HTMLResponse)
def check_wallet(request: Request, t: str = "", s: str = ""):
    """Show the balance and recent transactions for one signed card cycle."""
    invalid_link = "ลิงก์บัตรไม่ถูกต้อง กรุณาแตะบัตรใหม่"
    try:
        token = str(UUID(t))
        if not re.fullmatch(r"[0-9a-fA-F]{32}", s):
            return wallet_page(request, error=invalid_link, status=404)

        # Verify the signature before loading transaction details.
        wallet = database.get_wallet_by_token(token)
        if not wallet or not security.TokenSecurity.verify_url_token(
            bytes.fromhex(wallet["card_uid"].replace(":", "")), token, s
        ):
            return wallet_page(request, error=invalid_link, status=404)
        if wallet["status"] != "ACTIVE":
            return wallet_page(
                request, error="บัตรนี้สิ้นสุดรอบการใช้งานแล้ว", status=403
            )

        transactions = database.get_recent_transactions(limit=10, token_uuid=token)
    except ValueError:
        return wallet_page(request, error=invalid_link, status=404)
    except (psycopg2.Error, RuntimeError):
        return wallet_page(
            request, error="ยังเปิดข้อมูลบัตรไม่ได้ กรุณาติดต่อจุดบริการ", status=503
        )

    return wallet_page(request, wallet=wallet, transactions=transactions)


class CardScan(BaseModel):
    card_uid: str


@app.get("/kiosk", response_class=HTMLResponse)
def kiosk(request: Request):
    return templates.TemplateResponse(request=request, name="kiosk.html")


@app.websocket("/ws/kiosk")
async def kiosk_socket(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Keep the tablet subscribed until its browser disconnects.
        while (await websocket.receive())["type"] != "websocket.disconnect":
            pass
    finally:
        manager.disconnect(websocket)


@app.post("/api/kiosk/scan")
async def scan_card(scan: CardScan):
    # The ESP32 sends a UID. The database supplies the balance for the tablet.
    uid = scan.card_uid.strip().replace(":", "").upper()
    if not re.fullmatch(r"(?:[0-9A-F]{8}|[0-9A-F]{14})", uid):
        return JSONResponse({"status": "invalid"}, status_code=400)
    try:
        # Run the blocking database query outside the WebSocket event loop.
        balance = await run_in_threadpool(database.get_kiosk_balance, uid)
    except psycopg2.Error:
        await manager.broadcast({"status": "unavailable"})
        return JSONResponse({"status": "unavailable"}, status_code=503)

    if balance is None:
        event = {"status": "inactive"}
    else:
        event = {"status": "ok", "balance": format(balance, ".2f")}
    await manager.broadcast(event)
    return {"status": event["status"]}


if __name__ == "__main__":
    # Bind to the local network so phones, tablets and the ESP32 can connect.
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)