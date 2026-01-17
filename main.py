"""OAuth Relay Service for YouTube Analyzer.

A lightweight, privacy-focused relay service that enables OAuth callbacks
from anywhere without requiring users to expose their local machines.

Key features:
- Memory-only sessions (no persistent storage)
- Auto-expiring sessions (5 minutes)
- WebSocket real-time notifications
- HTTP polling fallback
- CORS enabled for cross-origin requests

This service is designed to be deployed on a public server with HTTPS
(e.g., via Coolify, Docker, or any containerized environment).

MIT License - Open source for transparency and user trust.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="OAuth Relay Service",
    description="Privacy-focused OAuth callback relay for YouTube Analyzer",
    version="1.0.0",
)

# Enable CORS for cross-origin requests from local apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for OAuth relay
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory sessions (no persistence)
sessions: dict[str, dict[str, Any]] = {}
SESSION_TIMEOUT = timedelta(minutes=5)

# WebSocket connections per session
ws_connections: dict[str, list[WebSocket]] = {}


def cleanup_expired_sessions() -> list[str]:
    """Remove expired sessions and return list of cleaned session IDs."""
    now = datetime.utcnow()
    expired = [
        sid
        for sid, data in sessions.items()
        if now - data["created_at"] > SESSION_TIMEOUT
    ]
    for sid in expired:
        sessions.pop(sid, None)
        ws_connections.pop(sid, None)
    return expired


def get_or_create_session(session_id: str) -> dict[str, Any]:
    """Get existing session or create a new one."""
    if session_id not in sessions:
        sessions[session_id] = {
            "created_at": datetime.utcnow(),
            "code": None,
            "error": None,
            "retrieved": False,
        }
    return sessions[session_id]


@app.get("/callback")
async def oauth_callback(
    session: str = Query(..., description="Session ID from local app"),
    code: str | None = Query(None, description="OAuth authorization code"),
    error: str | None = Query(None, description="OAuth error"),
    error_description: str | None = Query(None, description="Error description"),
    state: str | None = Query(None, description="OAuth state parameter"),
) -> HTMLResponse:
    """Receive OAuth callback from Google and transmit to local app.

    This endpoint is called by Google after the user completes the OAuth flow.
    The authorization code is stored temporarily and transmitted to the local
    app via WebSocket or HTTP polling.

    Args:
        session: Unique session ID to match with local app.
        code: OAuth authorization code (on success).
        error: OAuth error code (on failure).
        error_description: Human-readable error description.
        state: OAuth state parameter (for additional security if needed).

    Returns:
        HTML page confirming success or failure to the user.
    """
    cleanup_expired_sessions()

    session_data = get_or_create_session(session)

    if code:
        session_data["code"] = code
        # Notify WebSocket clients immediately
        if session in ws_connections:
            for ws in ws_connections[session]:
                try:
                    await ws.send_json({"code": code, "status": "success"})
                except Exception:
                    pass  # Client may have disconnected

        return HTMLResponse(
            """
            <!DOCTYPE html>
            <html><head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Authentification réussie</title>
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                       text-align: center; padding: 50px 20px; background: #f5f5f5; margin: 0; }
                .card { background: white; border-radius: 12px; padding: 40px; max-width: 400px;
                        margin: 0 auto; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
                h1 { color: #10b981; margin-bottom: 16px; font-size: 24px; }
                p { color: #6b7280; line-height: 1.6; }
                .icon { font-size: 48px; margin-bottom: 20px; }
            </style>
            </head>
            <body>
            <div class="card">
                <div class="icon">✅</div>
                <h1>Authentification réussie !</h1>
                <p>Vous pouvez fermer cette fenêtre et retourner à l'application YouTube Analyzer.</p>
            </div>
            </body></html>
            """,
            status_code=200,
        )

    if error:
        error_msg = error_description or error
        session_data["error"] = error_msg
        # Notify WebSocket clients of error
        if session in ws_connections:
            for ws in ws_connections[session]:
                try:
                    await ws.send_json({"error": error_msg, "status": "error"})
                except Exception:
                    pass

        return HTMLResponse(
            f"""
            <!DOCTYPE html>
            <html><head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Erreur d'authentification</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                       text-align: center; padding: 50px 20px; background: #f5f5f5; margin: 0; }}
                .card {{ background: white; border-radius: 12px; padding: 40px; max-width: 400px;
                        margin: 0 auto; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
                h1 {{ color: #ef4444; margin-bottom: 16px; font-size: 24px; }}
                p {{ color: #6b7280; line-height: 1.6; }}
                .error {{ background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px;
                         padding: 12px; margin-top: 16px; color: #dc2626; font-size: 14px; }}
                .icon {{ font-size: 48px; margin-bottom: 20px; }}
            </style>
            </head>
            <body>
            <div class="card">
                <div class="icon">❌</div>
                <h1>Erreur d'authentification</h1>
                <p>Une erreur s'est produite lors de l'authentification.</p>
                <div class="error">{error_msg}</div>
                <p style="margin-top: 20px;">Vous pouvez fermer cette fenêtre et réessayer dans l'application.</p>
            </div>
            </body></html>
            """,
            status_code=400,
        )

    # No code or error - this is the initial session registration from local app
    return HTMLResponse(
        """
        <!DOCTYPE html>
        <html><head>
        <meta charset="utf-8">
        <title>En attente...</title>
        <style>
            body { font-family: sans-serif; text-align: center; padding: 50px; }
        </style>
        </head>
        <body>
        <h1>Session enregistrée</h1>
        <p>En attente du callback OAuth...</p>
        </body></html>
        """,
        status_code=200,
    )


@app.get("/poll/{session_id}")
async def poll_session(session_id: str) -> dict[str, Any]:
    """HTTP polling endpoint for environments without WebSocket support.

    Local apps can poll this endpoint to check if the OAuth code has arrived.
    Once the code is retrieved, the session is automatically deleted for privacy.

    Args:
        session_id: The session ID to check.

    Returns:
        JSON with either:
        - {"status": "waiting"} if no code yet
        - {"code": "..."} on success
        - {"error": "..."} on OAuth error

    Raises:
        HTTPException: 404 if session not found or expired.
    """
    cleanup_expired_sessions()

    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    session_data = sessions[session_id]

    if session_data["code"]:
        code = session_data["code"]
        # Delete session after retrieval (privacy: no data retention)
        sessions.pop(session_id, None)
        ws_connections.pop(session_id, None)
        return {"code": code, "status": "success"}

    if session_data["error"]:
        error = session_data["error"]
        # Delete session after retrieval
        sessions.pop(session_id, None)
        ws_connections.pop(session_id, None)
        return {"error": error, "status": "error"}

    return {"status": "waiting"}


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for real-time OAuth code transmission.

    This is the preferred method for receiving the OAuth code, as it provides
    instant notification when the code arrives. Falls back to polling if
    WebSocket connection fails.

    The connection is kept alive with periodic pings until:
    - The OAuth code arrives
    - An error occurs
    - The session expires
    - The client disconnects

    Args:
        websocket: The WebSocket connection.
        session_id: The session ID to monitor.
    """
    await websocket.accept()

    # Track this connection
    if session_id not in ws_connections:
        ws_connections[session_id] = []
    ws_connections[session_id].append(websocket)

    # Initialize session if not exists
    get_or_create_session(session_id)

    try:
        # Send any existing code/error immediately (in case we reconnected)
        session_data = sessions.get(session_id, {})
        if session_data.get("code"):
            await websocket.send_json(
                {"code": session_data["code"], "status": "success"}
            )
            return
        if session_data.get("error"):
            await websocket.send_json(
                {"error": session_data["error"], "status": "error"}
            )
            return

        # Keep connection alive until code received or timeout
        while True:
            try:
                # Wait for client message (ping/pong) with timeout
                await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
            except asyncio.TimeoutError:
                # Send keepalive ping
                cleanup_expired_sessions()
                if session_id not in sessions:
                    await websocket.send_json(
                        {"error": "Session expired", "status": "expired"}
                    )
                    break
                await websocket.send_json({"status": "waiting"})

            # Check if session has code or error now
            session_data = sessions.get(session_id, {})
            if session_data.get("code"):
                await websocket.send_json(
                    {"code": session_data["code"], "status": "success"}
                )
                break
            if session_data.get("error"):
                await websocket.send_json(
                    {"error": session_data["error"], "status": "error"}
                )
                break

    except WebSocketDisconnect:
        pass  # Client disconnected normally
    except Exception:
        pass  # Handle any other errors gracefully
    finally:
        # Clean up this connection
        if session_id in ws_connections:
            ws_connections[session_id] = [
                ws for ws in ws_connections[session_id] if ws != websocket
            ]


@app.get("/health")
async def health_check() -> dict[str, Any]:
    """Health check endpoint for monitoring and load balancers.

    Returns:
        JSON with service status and basic metrics.
    """
    cleanup_expired_sessions()
    return {
        "status": "ok",
        "active_sessions": len(sessions),
        "active_websockets": sum(len(conns) for conns in ws_connections.values()),
    }


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint with service information."""
    return {
        "service": "OAuth Relay Service",
        "version": "1.0.0",
        "description": "Privacy-focused OAuth callback relay for YouTube Analyzer",
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
