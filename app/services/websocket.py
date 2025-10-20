"""WebSocket listener service."""

import asyncio
import json
from pathlib import Path
import math
from typing import Optional, Callable, List, Dict, Any
from datetime import datetime, timedelta
import websockets
from fastapi import WebSocket
import numpy as np
import pandas as pd

from app.core.config import settings
from app.services.clickhouse import clickhouse_service
from app.services.cache import data_cache
from app.controllers.matching_controller import matching_controller

try:
    from src.matching import ScoringParams, build_candidates, assign_one_to_one
    from src.geo import make_transformer, to_xy, parse_time_s, knots_to_mps
    HAS_MATCHING = True
except ImportError:
    HAS_MATCHING = False
    
    
POLYGON_DEBUG_LISTEN=False
POLYGON_DEBUG_LISTEN_GEOM=[
        [
            [
                116.44933178566555,
                -0.8430916258939618
            ],
            [
                116.44933178566555,
                -2.826198539872806
            ],
            [
                118.69607870265867,
                -2.826198539872806
            ],
            [
                118.69607870265867,
                -0.8430916258939618
            ],
            [
                116.44933178566555,
                -0.8430916258939618
            ]
        ]
    ]

class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


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
        
        # Polling system properties
        self.ais_cache: Dict[str, Dict] = {}  # mmsi -> {data}
        self.arpa_cache: Dict[str, Dict] = {}  # target -> {data}
        self.last_ais_fetch: Optional[datetime] = None
        self.last_arpa_fetch: Optional[datetime] = None
        self.cache_ttl = getattr(settings, 'CACHE_TTL_S', 3600)
        
        # Projection and bbox for polling
        self.site_lat = getattr(settings, 'SITE_LAT', -1.279656)
        self.site_lon = getattr(settings, 'SITE_LON', 116.809655)
        self.filter_radius_km = getattr(settings, 'FILTER_RADIUS_KM', 60.0)
        self.projection = getattr(settings, 'PROJECTION', 'EPSG:32650')
        self.transformer = None
        self.bbox = None
        
        # Gating and scoring params
        self.gating_distance_m = getattr(settings, 'GATING_DISTANCE_M', 8000.0)
        self.time_gate_s = getattr(settings, 'TIME_GATE_S', 1800.0)
        self.match_threshold = getattr(settings, 'MATCH_THRESHOLD', 0.6)
        self.scoring_params = ScoringParams(
            pos_sigma_m=getattr(settings, 'POS_SIGMA_M', 500.0),
            spd_sigma_ms=getattr(settings, 'SPD_SIGMA_MS', 3.0),
            hdg_sigma_deg=getattr(settings, 'HDG_SIGMA_DEG', 40.0),
            time_sigma_s=getattr(settings, 'TIME_SIGMA_S', 60.0)
        ) if HAS_MATCHING else None
        self.demo_message_path = Path(__file__).parent.parent.parent / "data" / "demo_message.json"
    
    def load_demo_message(self) -> Optional[str]:
        try:
            if self.demo_message_path.exists():
                with open(self.demo_message_path, 'r') as f:
                    demo_data = json.load(f)
                    print(f"✓ Loaded demo message from {self.demo_message_path}")
                    return json.dumps(demo_data)
            else:
                print(f"⚠️ Demo message file not found at {self.demo_message_path}")
                return None
        except Exception as e:
            print(f"❌ Error loading demo message: {str(e)}")
            return None
    
    def calculate_azimuth(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate azimuth (bearing) from point 1 to point 2 in degrees."""
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        dlon_rad = math.radians(lon2 - lon1)
        
        y = math.sin(dlon_rad) * math.cos(lat2_rad)
        x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon_rad)
        
        azimuth_rad = math.atan2(y, x)
        azimuth_deg = math.degrees(azimuth_rad)
        
        # Normalize to 0-360
        return (azimuth_deg + 360) % 360
    
    def prune_cache(self, cache: Dict, ts_key: str):
        """Remove old entries from cache based on TTL."""
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=self.cache_ttl)
        
        keys_to_remove = []
        for key, record in cache.items():
            ts = record.get(ts_key)
            if ts:
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                if ts < cutoff:
                    keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del cache[key]
        
        if keys_to_remove:
            print(f"  Pruned {len(keys_to_remove)} old entries from cache")
    
    async def fetch_ais_incremental(self, since: datetime, bbox: Dict) -> List[Dict]:
        """Fetch AIS data since last fetch time within bbox."""
        try:
            query = f"""
                SELECT 
                    mmsi,
                    toFloat64(latitude) as lat,
                    toFloat64(longitude) as lon,
                    toFloat64(speed) as sog,
                    toFloat64(course) as cog,
                    toFloat64(heading) as heading,
                    ts,
                    ship_name,
                    ship_type
                FROM ais_data
                WHERE ts > %(since)s
                  AND latitude BETWEEN %(min_lat)s AND %(max_lat)s
                  AND longitude BETWEEN %(min_lon)s AND %(max_lon)s
                ORDER BY ts ASC
            """
            
            params = {
                'since': since,
                'min_lat': bbox['min_lat'],
                'max_lat': bbox['max_lat'],
                'min_lon': bbox['min_lon'],
                'max_lon': bbox['max_lon']
            }
            
            result = await clickhouse_service.execute_query(query, params)
            return result if result else []
        except Exception as e:
            print(f"❌ Error fetching incremental AIS: {e}")
            return []
    
    async def fetch_arpa_incremental(self, since: datetime, bbox: Dict) -> List[Dict]:
        """Fetch ARPA data since last fetch time within bbox."""
        try:
            query = f"""
                SELECT 
                    target_number as target,
                    toFloat64(latitude) as lat,
                    toFloat64(longitude) as lon,
                    toFloat64(speed) as speed,
                    toFloat64(course) as course,
                    recv_at,
                    source
                FROM arpa_data
                WHERE recv_at > %(since)s
                  AND latitude BETWEEN %(min_lat)s AND %(max_lat)s
                  AND longitude BETWEEN %(min_lon)s AND %(max_lon)s
                ORDER BY recv_at ASC
            """
            
            params = {
                'since': since,
                'min_lat': bbox['min_lat'],
                'max_lat': bbox['max_lat'],
                'min_lon': bbox['min_lon'],
                'max_lon': bbox['max_lon']
            }
            
            result = await clickhouse_service.execute_query(query, params)
            return result if result else []
        except Exception as e:
            print(f"❌ Error fetching incremental ARPA: {e}")
            return []
    
    def build_internal_frames(self) -> tuple:
        """Build DataFrames from cached data for matching."""
        try:
            # Build ARPA DataFrame
            arpa_records = []
            for target, record in self.arpa_cache.items():
                arpa_records.append({
                    'target': target,
                    'lat': record.get('lat'),
                    'lon': record.get('lon'),
                    'speed': record.get('speed', 0.0),
                    'course': record.get('course'),
                    'recv_at': record.get('recv_at'),
                    'source': record.get('source', 'unknown')
                })
            
            # Build AIS DataFrame
            ais_records = []
            for mmsi, record in self.ais_cache.items():
                ais_records.append({
                    'mmsi': mmsi,
                    'lat': record.get('lat'),
                    'lon': record.get('lon'),
                    'sog': record.get('sog', 0.0),
                    'cog': record.get('cog'),
                    'heading': record.get('heading'),
                    'heading_az': record.get('heading_az'),  # Calculated azimuth
                    'ts': record.get('ts'),
                    'ship_name': record.get('ship_name', ''),
                    'ship_type': record.get('ship_type', 0)
                })
            
            arpa_df = pd.DataFrame(arpa_records) if arpa_records else pd.DataFrame()
            ais_df = pd.DataFrame(ais_records) if ais_records else pd.DataFrame()
            
            return arpa_df, ais_df
        except Exception as e:
            print(f"❌ Error building DataFrames: {e}")
            return pd.DataFrame(), pd.DataFrame()
    
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
                if POLYGON_DEBUG_LISTEN:
                    print("📢 Polygon debug listen active - skipping actual WebSocket connection")
                    
                    while self.is_active and self.is_running:
                        print(f"📢 Polygon debug listen active - sending mock data")
                        mock_message = json.dumps({
                            "type": "FeatureCollection",
                            "features": [
                                {
                                    "type": "Feature",
                                    "properties": {
                                        "name": "Camera Position",
                                        "type": "camera",
                                        "bearing": 270,
                                        "zoom": 30,
                                        "camera_height_m": 30
                                    },
                                    "geometry": {
                                        "type": "Point",
                                        "coordinates": [
                                            116.809655,
                                            -1.279656
                                        ]
                                    }
                                },
                                {
                                    "type": "Feature",
                                    "properties": {
                                        "type": "visible_sea_area",
                                        "bearing": 45,
                                        "zoom": 10
                                    },
                                    "geometry": {
                                        "type": "Polygon",
                                        "coordinates": POLYGON_DEBUG_LISTEN_GEOM
                                    }
                                }
                            ]
                        })
                        await self.process_message(mock_message)
                        await asyncio.sleep(5)
                        # demo_message = self.load_demo_message()
                        # if demo_message:
                        #     print("📨 Processing demo message from demo_message.json")
                        #     await self.process_message(demo_message)
                        #     await asyncio.sleep(5)
                        # else:
                        #     print("Failed to load demo message, stopping listener")
                        #     break
                else:
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
    
    def extract_polygon_from_camera_fov(self, geojson_message: dict) -> Optional[List]:
        """
        Extract polygon from camera field-of-view GeoJSON message.
        
        Args:
            geojson_message: GeoJSON FeatureCollection from camera FOV WebSocket
            
        Returns:
            Polygon coordinates as list of [lon, lat] pairs, or None if not found
        """
        try:
            if geojson_message.get("type") == "FeatureCollection":
                features = geojson_message.get("features", [])
                print(f"📐 Parsing camera FOV GeoJSON with {len(features)} features")
                
                for feature in features:
                    # Look for the visible_sea_area feature
                    props = feature.get("properties", {})
                    if props.get("type") == "visible_sea_area":
                        geometry = feature.get("geometry", {})
                        if geometry.get("type") == "Polygon":
                            coordinates = geometry.get("coordinates")
                            if coordinates and len(coordinates) > 0:
                                # GeoJSON Polygon coordinates are [[[lon, lat], ...]]
                                # Extract the outer ring (first element)
                                polygon = coordinates[0]
                                print(f"✅ Extracted visible_sea_area polygon with {len(polygon)} points")
                                print(f"   Properties: bearing={props.get('bearing')}°, zoom={props.get('zoom')}x")
                                return polygon
                
                print("⚠️ No visible_sea_area feature found in camera FOV message")
            return None
        except Exception as e:
            print(f"❌ Error extracting polygon from camera FOV: {e}")
            return None
    
    async def process_message(self, message: str):
        """
        Process incoming WebSocket message from external source and send query results back.
        Also broadcasts to connected monitors via FastAPI /ws endpoint.
        
        Args:
            message: Raw message from external WebSocket
        """
        try:
            # Try to parse as JSON
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                print(f"⚠️ Non-JSON message received")
                data = {"raw_message": message}
            
            # Check if this is a camera FOV GeoJSON message
            if isinstance(data, dict) and data.get("type") == "FeatureCollection":
                print(f"📹 Detected camera FOV GeoJSON message")
                polygon = self.extract_polygon_from_camera_fov(data)
                if polygon:
                    polygon_geojson = [polygon]  # Wrap in one more array for GeoJSON format
                    
                    print(f"🎯 Calling matching controller with polygon...")
                    result = await matching_controller.process_matching(
                        polygon=polygon_geojson,
                        since_minutes=60,
                        ais_limit=1000,
                        arpa_limit=1000
                    )
                    
                    if result.get("success"):
                        # Extract the data from matching result
                        matching_data = result.get("data", {})
                        matched_pairs = matching_data.get("matched_pairs", [])
                        unmatched_ais = matching_data.get("unmatched_ais", [])
                        unmatched_arpa = matching_data.get("unmatched_arpa", [])
                        statistics = matching_data.get("statistics", {})
                        parameters = matching_data.get("parameters", {})
                        
                        print(f"✅ Matching completed: {statistics.get('matched', 0)} pairs, {statistics.get('unmatched_ais', 0)} unmatched AIS, {statistics.get('unmatched_arpa', 0)} unmatched ARPA")
                        
                        # Build response format matching frontend expectations
                        # Ensure arpa and ais records have 'lng' field (not 'lon')
                        for pair in matched_pairs:
                            if pair.get("ais") and "lon" in pair["ais"] and "lng" not in pair["ais"]:
                                pair["ais"]["lng"] = pair["ais"]["lon"]
                            if pair.get("arpa") and "lon" in pair["arpa"] and "lng" not in pair["arpa"]:
                                pair["arpa"]["lng"] = pair["arpa"]["lon"]
                        
                        for rec in unmatched_ais:
                            if "lon" in rec and "lng" not in rec:
                                rec["lng"] = rec["lon"]
                        
                        for rec in unmatched_arpa:
                            if "lon" in rec and "lng" not in rec:
                                rec["lng"] = rec["lon"]
                        
                        response_data = {
                            "type": "assignments_weighted",
                            "pairs": matched_pairs,
                            "unmatched_arpa": unmatched_arpa,
                            "unmatched_ais": unmatched_ais,
                            "message_listener": data,
                            "timestamp": datetime.now().isoformat(),
                        }
                        
                        # Send result back to external WebSocket
                        if self._websocket_connection:
                            try:
                                response_json = json.dumps(response_data, cls=DateTimeEncoder)
                                await self._websocket_connection.send(response_json)
                                print(f"📤 Sent matching result to external WebSocket")
                            except Exception as e:
                                print(f"⚠️ Failed to send response to external WebSocket: {e}")
                        
                        # Broadcast to connected clients
                        await self.broadcast_to_clients(response_data)
                        
                        return
                    else:
                        print(f"❌ Matching failed: {result.get('message')}")
                        return
                else:
                    print(f"⚠️ Could not extract polygon from camera FOV, skipping query")
                    return
            
            # For non-camera FOV messages, return early
            print(f"⚠️ Non-camera FOV message, ignoring")
            return
            
        except Exception as e:
            print(f"❌ Error processing message: {e}")
            import traceback
            traceback.print_exc()
            
    async def broadcast_to_clients(self, data: dict):
        """Broadcast data to all connected clients."""
        disconnected_clients = []
        for client in self.connected_clients:
            try:
                # Use DateTimeEncoder to handle datetime objects
                json_str = json.dumps(data, cls=DateTimeEncoder)
                await client.send_text(json_str)
            except Exception as e:
                print(f"Error sending to client: {e}")
                disconnected_clients.append(client)
        
        # Remove disconnected clients
        for client in disconnected_clients:
            self.remove_client(client)
    
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
            "url": self.url,
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
