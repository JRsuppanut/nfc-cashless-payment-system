"""
Main entry point for the FastAPI Web Application.
Provides endpoints for the Customer Portal.
"""

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import database

# Initialize the FastAPI application
app = FastAPI(title="Food Court Customer Portal")

# Configure the directory for Jinja2 HTML templates
templates = Jinja2Templates(directory="templates")

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
        
    # 3. Security Check Placeholder
    # In a production environment, the HMAC signature (s) should be verified here 
    # using the TokenSecurity logic to prevent URL guessing.

    # 4. Fetch transaction history specific to this card
    card_uid = wallet["card_uid"]
    transactions = database.get_recent_transactions(limit=10, card_uid=card_uid)

    # 5. Render the HTML template with the retrieved data
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