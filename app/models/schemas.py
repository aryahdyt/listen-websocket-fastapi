"""Pydantic schemas for request/response models."""

from typing import Any, List, Optional, Dict
from datetime import datetime
from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Request model for executing ClickHouse queries."""
    query: str = Field(..., description="SQL query to execute")
    

class QueryResponse(BaseModel):
    """Response model for query results."""
    success: bool
    rows: int
    data: List[Any]
    timestamp: datetime = Field(default_factory=datetime.now)


class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str
    clickhouse: str
    redis: str = "unknown"
    timestamp: datetime = Field(default_factory=datetime.now)


class MessageData(BaseModel):
    """Model for processed WebSocket messages."""
    timestamp: datetime
    received_data: dict
    query_result: Optional[List[Any]] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class CacheStats(BaseModel):
    """Model for cache statistics."""
    total_messages: int
    current_size: int
    valid_items: int
    max_size: int
    ttl_seconds: float
    cache_hits: int = 0
    cache_misses: int = 0
    last_updated: Optional[datetime] = None


class CachedItem(BaseModel):
    """Model for cached data item."""
    timestamp: datetime
    data: Any
    metadata: Dict = Field(default_factory=dict)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

