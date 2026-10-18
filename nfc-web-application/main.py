from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Depends
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import json
# For actual database connection, uncomment and configure SQLAlchemy models
# from database import get_db, Wallet

app = FastAPI()
templates = Jinja2Templates(directory="templates")

class ConnectionManager:
    """
    Manages WebSocket connections for real-time broadcasting to display nodes.
    """
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

class ScanPayload(BaseModel):
    card_uid: str

@app.get("/kiosk")
async def serve_kiosk_page(request: Request):
    """
    Serves the Kiosk Dashboard HTML page.
    """
    return templates.TemplateResponse("kiosk.html", {"request": request})

@app.websocket("/ws/kiosk")
async def websocket_kiosk_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for display nodes (e.g., iPad).
    """
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.post("/api/kiosk/scan")
async def process_nfc_scan(payload: ScanPayload):
    """
    REST API endpoint to receive NFC UID from ESP32.
    Queries the database and broadcasts the balance.
    """
    # Mock database validation process
    # Replace with actual DB query: db.query(Wallet).filter(Wallet.card_uid == payload.card_uid).first()
    valid_uids = {"A1B2C3D4": 150.50, "04030201": 500.00}
    
    if payload.card_uid not in valid_uids:
        error_msg = json.dumps({
            "status": "error", 
            "message": "Card not registered"
        })
        await manager.broadcast(error_msg)
        raise HTTPException(status_code=404, detail="Card not registered")

    balance = valid_uids[payload.card_uid]
    
    success_msg = json.dumps({
        "status": "success",
        "card_uid": payload.card_uid,
        "balance": balance
    })
    
    await manager.broadcast(success_msg)
    return {"message": "Scan processed successfully"}