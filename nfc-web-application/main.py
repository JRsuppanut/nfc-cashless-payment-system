"""
Main entry point for the FastAPI Web Application.
Provides endpoints for the Customer Portal.
"""

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import List

import database

# Initialize the FastAPI application
app = FastAPI(title="Food Court Customer Portal")

# Configure the directory for Jinja2 HTML templates
templates = Jinja2Templates(directory="templates")

# ==========================================
# WebSocket Connection Manager (เพิ่มส่วนนี้)
# ==========================================
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass

# ต้องประกาศตัวแปร manager "หลังจาก" สร้าง Class ด้านบนเสร็จแล้ว
manager = ConnectionManager()

# ==========================================
# API Endpoints
# ==========================================
@app.get("/wallet", response_class=HTMLResponse)
async def check_wallet(request: Request, t: str = None, s: str = None):
    """
    Handle requests from NFC smartphone scans.
    Expected URL format: http://<domain>/wallet?t=<token_uuid>&s=<hmac_signature>
    """
    # 1. Validate URL parameters
    if not t:
        return templates.TemplateResponse(
            request=request,
            name="wallet.html", 
            context={
                "error": "INVALID_URL", 
                "message": "Missing Token UUID parameter."
            }
        )

    # 2. Fetch wallet data from the database
    wallet = database.get_wallet_by_token(t)
    
    if not wallet:
        return templates.TemplateResponse(
            request=request,
            name="wallet.html", 
            context={
                "error": "NOT_FOUND", 
                "message": "Wallet not found or is not registered in the system."
            }
        )

    # 3. Fetch transaction history specific to this token session only
    transactions = database.get_recent_transactions(limit=10, token_uuid=t)

    # 4. Render the HTML template with the retrieved data
    return templates.TemplateResponse(
        request=request,
        name="wallet.html",
        context={
            "error": None,
            "wallet": wallet,
            "transactions": transactions
        }
    )

if __name__ == "__main__":
    # Start the ASGI server
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)