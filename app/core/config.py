"""Application configuration."""

import os
from typing import Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Application settings."""
    
    # Application
    APP_NAME: str = "Projection BPP Listener"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    
    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # ClickHouse
    CLICKHOUSE_HOST: str = os.getenv("CLICKHOUSE_HOST", "localhost")
    CLICKHOUSE_PORT: int = int(os.getenv("CLICKHOUSE_PORT", "9000"))
    CLICKHOUSE_DATABASE: str = os.getenv("CLICKHOUSE_DATABASE", "default")
    CLICKHOUSE_USER: str = os.getenv("CLICKHOUSE_USER", "default")
    CLICKHOUSE_PASSWORD: str = os.getenv("CLICKHOUSE_PASSWORD", "")
    
    # Redis
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")
    REDIS_TTL: int = int(os.getenv("REDIS_TTL", "3600"))
    REDIS_PREFIX: str = os.getenv("REDIS_PREFIX", "projection_bpp_cache_")
    
    # WebSocket
    WEBSOCKET_URL: str = os.getenv("WEBSOCKET_URL", "ws://202.10.32.106:1880/ws/projection_bpp")
    WEBSOCKET_RECONNECT_DELAY: int = int(os.getenv("WEBSOCKET_RECONNECT_DELAY", "5"))
    WEBSOCKET_AUTO_START: bool = os.getenv("WEBSOCKET_AUTO_START", "True").lower() == "true"
    
    # Polling System Configuration
    ENABLE_POLLING: bool = os.getenv("ENABLE_POLLING", "True").lower() == "true"
    POLL_INTERVAL_S: float = float(os.getenv("POLL_INTERVAL_S", "1.0"))
    BOOTSTRAP_MINUTES: int = int(os.getenv("BOOTSTRAP_MINUTES", "60"))
    CACHE_TTL_S: int = int(os.getenv("CACHE_TTL_S", "3600"))
    
    # Site Location (for bbox calculation)
    SITE_LAT: float = float(os.getenv("SITE_LAT", "-1.279656"))
    SITE_LON: float = float(os.getenv("SITE_LON", "116.809655"))
    FILTER_RADIUS_KM: float = float(os.getenv("FILTER_RADIUS_KM", "60.0"))
    
    # Projection
    PROJECTION: str = os.getenv("PROJECTION", "EPSG:32650")
    
    # Matching Parameters
    GATING_DISTANCE_M: float = float(os.getenv("GATING_DISTANCE_M", "8000.0"))
    TIME_GATE_S: float = float(os.getenv("TIME_GATE_S", "1800.0"))
    MATCH_THRESHOLD: float = float(os.getenv("MATCH_THRESHOLD", "0.6"))
    
    # Scoring Parameters
    POS_SIGMA_M: float = float(os.getenv("POS_SIGMA_M", "500.0"))
    SPD_SIGMA_MS: float = float(os.getenv("SPD_SIGMA_MS", "3.0"))
    HDG_SIGMA_DEG: float = float(os.getenv("HDG_SIGMA_DEG", "40.0"))
    TIME_SIGMA_S: float = float(os.getenv("TIME_SIGMA_S", "60.0"))
    
    class Config:
        """Pydantic config."""
        case_sensitive = True
        env_file = ".env"


settings = Settings()