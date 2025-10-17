"""API routes."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse
from datetime import datetime

from app.models.schemas import QueryRequest, QueryResponse, HealthResponse
from app.services.clickhouse import clickhouse_service
from app.services.websocket import websocket_listener
from app.services.cache import data_cache
from app.core.config import settings

router = APIRouter()


@router.get("/")
async def root():
    """Root endpoint - service information."""
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "websocket_url": settings.WEBSOCKET_URL,
        "endpoints": {
            "health": "/health",
            "query": "/query",
            "websocket": "/ws",
            "monitor_ui": "/monitor",
            "cache_stats": "/cache/stats",
            "cache_recent": "/cache/recent",
            "cache_clear": "/cache/clear",
            "listener_status": "/listener/status",
            "listener_start": "/listener/start",
            "listener_stop": "/listener/stop"
        }
    }


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    clickhouse_status = "connected" if clickhouse_service.test_connection() else "disconnected"
    
    # Check Redis status from cache backend
    cache_stats = data_cache.get_stats()
    redis_status = "connected" if cache_stats.get("backend") == "redis" else "disconnected"
    
    return HealthResponse(
        status="ok",
        clickhouse=clickhouse_status,
        redis=redis_status,
        timestamp=datetime.now()
    )

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for clients to connect and receive data."""
    await websocket.accept()
    websocket_listener.add_client(websocket)
    print("✓ Client connected to WebSocket")
    
    try:
        # Send initial cache data
        recent_data = data_cache.get_recent(limit=50)
        await websocket.send_json({
            "type": "initial_data",
            "data": recent_data,
            "cache_stats": data_cache.get_stats(),
            "timestamp": datetime.now().isoformat()
        })
        
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_text()
            await websocket.send_json({
                "status": "received",
                "message": data,
                "timestamp": datetime.now().isoformat()
            })
    except WebSocketDisconnect:
        print("✗ Client disconnected from WebSocket")
        websocket_listener.remove_client(websocket)


@router.get("/cache/stats")
async def get_cache_stats():
    """Get cache statistics."""
    return data_cache.get_stats()


@router.get("/cache/recent")
async def get_recent_cached_data(limit: int = 100):
    """Get recent cached data."""
    return {
        "data": data_cache.get_recent(limit=limit),
        "stats": data_cache.get_stats()
    }


@router.post("/cache/clear")
async def clear_cache():
    """Clear all cached data."""
    data_cache.clear()
    return {"message": "Cache cleared successfully"}


@router.get("/listener/status")
async def get_listener_status():
    """Get WebSocket listener status."""
    return websocket_listener.get_status()


@router.post("/listener/start")
async def start_listener():
    """Start WebSocket listener."""
    return websocket_listener.start_listener()


@router.post("/listener/stop")
async def stop_listener():
    """Stop WebSocket listener."""
    return websocket_listener.stop_listener()


@router.get("/monitor", response_class=HTMLResponse)
async def monitoring_dashboard():
    """Real-time monitoring dashboard UI."""
    try:
        with open("static/monitor.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="""
        <html>
        <body>
        <h1>Monitor Dashboard Not Found</h1>
        <p>The monitoring dashboard HTML file is missing. Please ensure static/monitor.html exists.</p>
        <p><a href="/docs">View API Documentation</a> to use REST endpoints directly.</p>
        </body>
        </html>
        """, status_code=404)
