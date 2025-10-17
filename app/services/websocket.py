"""WebSocket listener service."""

import asyncio
import json
from typing import Optional, Callable
from datetime import datetime
import websockets
from fastapi import WebSocket

from app.core.config import settings
from app.services.clickhouse import clickhouse_service
from app.services.cache import data_cache


class WebSocketListener:
    """Service for listening to external WebSocket and processing messages."""
    
    def __init__(self):
        """Initialize WebSocket listener."""
        self.url = settings.WEBSOCKET_URL
        self.reconnect_delay = settings.WEBSOCKET_RECONNECT_DELAY
        self.client_connection: Optional[WebSocket] = None
        self.is_running = False
        self.connected_clients: list[WebSocket] = []
        self.listener_task: Optional[asyncio.Task] = None
        self.is_active = settings.WEBSOCKET_AUTO_START  # Control flag
        self._websocket_connection = None
    
    def set_client_connection(self, websocket: Optional[WebSocket]):
        """Set the client WebSocket connection."""
        self.client_connection = websocket
    
    def add_client(self, websocket: WebSocket):
        """Add a client WebSocket connection."""
        if websocket not in self.connected_clients:
            self.connected_clients.append(websocket)
    
    def remove_client(self, websocket: WebSocket):
        """Remove a client WebSocket connection."""
        if websocket in self.connected_clients:
            self.connected_clients.remove(websocket)
    
    async def broadcast_to_clients(self, data: dict):
        """Broadcast data to all connected clients."""
        disconnected_clients = []
        for client in self.connected_clients:
            try:
                await client.send_json(data)
            except Exception as e:
                print(f"Error sending to client: {e}")
                disconnected_clients.append(client)
        
        # Remove disconnected clients
        for client in disconnected_clients:
            self.remove_client(client)
    
    async def listen(self):
        """Start listening to the external WebSocket with auto-reconnect."""
        self.is_running = True
        
        # Main reconnection loop - only loops if connection fails
        while self.is_running and self.is_active:
            try:
                print(f"🔌 Connecting to WebSocket: {self.url}")
                async with websockets.connect(self.url) as websocket:
                    self._websocket_connection = websocket
                    print(f"✓ Connected to WebSocket: {self.url}")
                    
                    # Listen to messages - this loop stays here as long as connection is alive
                    async for message in websocket:
                        # Quick check if listener was stopped
                        if not self.is_active or not self.is_running:
                            print("⏸️ Stopping WebSocket listener...")
                            return
                        
                        print(f"📩 Received message: {message[:100]}...")
                        await self.process_message(message)
                    
                    # Connection closed normally by server
                    print("⚠️ WebSocket connection closed by server")
                        
            except websockets.exceptions.WebSocketException as e:
                print(f"❌ WebSocket connection error: {e}")
                if self.is_active and self.is_running:
                    print(f"🔄 Reconnecting in {self.reconnect_delay} seconds...")
                    await asyncio.sleep(self.reconnect_delay)
                else:
                    print("⏸️ Not reconnecting - listener was stopped")
                    return
                    
            except Exception as e:
                print(f"❌ Unexpected error: {e}")
                if self.is_active and self.is_running:
                    print(f"🔄 Reconnecting in {self.reconnect_delay} seconds...")
                    await asyncio.sleep(self.reconnect_delay)
                else:
                    print("⏸️ Not reconnecting - listener was stopped")
                    return
                    
            finally:
                self._websocket_connection = None
        
        print("🛑 WebSocket listener stopped")
    
    async def process_message(self, message: str):
        """
        Process incoming WebSocket message.
        
        Args:
            message: Raw message from WebSocket
        """
        try:
            # Try to parse as JSON
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                print(f"⚠️ Non-JSON message received")
                data = {"raw_message": message}
            
            # Store in cache with query result
            query_result = None
            cache_status = "new"
            
            # Check if we have this data cached already
            cached_items = data_cache.search("data", data)
            
            if cached_items:
                # Found in cache - check if recent enough
                latest_cached = cached_items[-1]  # Most recent
                cached_time = datetime.fromisoformat(latest_cached["timestamp"])
                time_diff = datetime.now() - cached_time
                
                # If cached within TTL, use it
                if time_diff.total_seconds() < data_cache.ttl_seconds:
                    print("✓ Data found in cache - using cached result")
                    cache_status = "hit"
                    query_result = latest_cached.get("metadata", {}).get("query_result")
                else:
                    print("🔄 Cached data expired - querying ClickHouse...")
                    cache_status = "expired"
            else:
                print("🔄 New data - querying ClickHouse...")
                cache_status = "miss"
            
            # Query ClickHouse if not in cache or expired
            if query_result is None:
                # Execute ClickHouse query
                # query_result = await self.query_clickhouse(data)
                # test data
                query_result = [
                    {'id': 1, 'value': 'example'},
                    {'id': 2, 'value': 'sample'}
                ]
            
            # Store in cache with query result
            data_cache.add(data, metadata={
                "source": "polygon_websocket",
                "received_at": datetime.now().isoformat(),
                "query_result": query_result,
                "cache_status": cache_status
            })
            
            # Broadcast to connected UI clients
            broadcast_data = {
                "type": "polygon_update",
                "timestamp": datetime.now().isoformat(),
                "data": data,
                "query_result": query_result,
                "cache_status": cache_status,
                "cache_stats": data_cache.get_stats()
            }
            await self.broadcast_to_clients(broadcast_data)
            
            if query_result:
                print(f"✓ Processed message (cache: {cache_status})")
            
        except Exception as e:
            print(f"❌ Error processing message: {e}")
            import traceback
            traceback.print_exc()
    
    async def query_and_send(self, data: dict) -> Optional[list]:
        """
        Query ClickHouse and send results to connected clients.
        
        Args:
            data: Parsed message data
            
        Returns:
            Query results or None
        """
        try:
            # Example query - modify based on your use case
            query = """
                SELECT * FROM your_table
                ORDER BY timestamp DESC
                LIMIT 10
            """
            
            # Execute query in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, clickhouse_service.execute_query, query)
            
            if result and self.client_connection:
                # Prepare response
                response_data = {
                    "timestamp": datetime.now().isoformat(),
                    "received_data": data,
                    "query_result": result
                }
                
                # Send to connected client
                await self.client_connection.send_json(response_data)
            
            return result
            
        except Exception as e:
            print(f"❌ Error in query_and_send: {e}")
            return None
    
    async def query_clickhouse(self, data: dict) -> Optional[list]:
        """
        Query ClickHouse based on polygon data.
        
        Args:
            data: Polygon data
            
        Returns:
            Query results or None
        """
        try:
            # Example query - customize based on your schema
            # Extract relevant fields from polygon data
            query = """
                SELECT * FROM your_table
                WHERE 1=1
                ORDER BY timestamp DESC
                LIMIT 10
            """
            
            # You can customize the query based on polygon data
            # For example, if polygon has coordinates:
            # if 'coordinates' in data:
            #     coords = data['coordinates']
            #     query = f"""
            #         SELECT * FROM your_table
            #         WHERE point_in_polygon(latitude, longitude, {coords})
            #         ORDER BY timestamp DESC
            #         LIMIT 100
            #     """
            
            # Run blocking ClickHouse query in thread pool to avoid blocking async loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, clickhouse_service.execute_query, query)
            return result if result else []
            
        except Exception as e:
            print(f"❌ Error querying ClickHouse: {e}")
            return None
    
    def start_listener(self) -> dict:
        """
        Start the WebSocket listener.
        
        Returns:
            Status dictionary
        """
        if self.is_active:
            return {
                "status": "already_active",
                "message": "WebSocket listener is already running",
                "is_active": True
            }
        
        # Set flags to active
        self.is_active = True
        self.is_running = False  # Will be set to True by listen()
        
        # Create new listener task if not exists or completed
        if self.listener_task is None or self.listener_task.done():
            self.listener_task = asyncio.create_task(self.listen())
            print("▶️ WebSocket listener STARTED (task created)")
        else:
            print("▶️ WebSocket listener STARTED (task already running)")
        
        return {
            "status": "started",
            "message": "WebSocket listener started successfully",
            "is_active": True,
            "url": self.url
        }
    
    def stop_listener(self) -> dict:
        """
        Stop the WebSocket listener.
        
        Returns:
            Status dictionary
        """
        if not self.is_active:
            return {
                "status": "already_inactive",
                "message": "WebSocket listener is already stopped",
                "is_active": False
            }
        
        # Set flags to inactive
        self.is_active = False
        self.is_running = False
        
        # Close WebSocket connection if exists
        if self._websocket_connection:
            try:
                asyncio.create_task(self._websocket_connection.close())
            except Exception as e:
                print(f"⚠️ Error closing WebSocket connection: {e}")
        
        print("⏸️ WebSocket listener STOPPED")
        
        return {
            "status": "stopped",
            "message": "WebSocket listener stopped successfully",
            "is_active": False
        }
    
    def get_status(self) -> dict:
        """
        Get current status of WebSocket listener.
        
        Returns:
            Status dictionary
        """
        task_status = "none"
        if self.listener_task:
            if self.listener_task.done():
                task_status = "completed"
            elif self.listener_task.cancelled():
                task_status = "cancelled"
            else:
                task_status = "running"
        
        return {
            "is_active": self.is_active,
            "is_running": self.is_running,
            "task_status": task_status,
            "connected_clients": len(self.connected_clients),
            "websocket_url": self.url,
            "auto_start": settings.WEBSOCKET_AUTO_START,
            "connection_status": "connected" if self._websocket_connection else "disconnected"
        }
    
    def stop(self):
        """Stop the WebSocket listener."""
        self.is_running = False
        self.is_active = False


# Singleton instance
websocket_listener = WebSocketListener()
