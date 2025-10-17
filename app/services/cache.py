"""Caching service for WebSocket data using Redis."""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from collections import deque
import threading
import json
import redis
from app.core.config import settings


class DataCache:
    """Redis-backed cache for WebSocket data with in-memory fallback."""
    
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        """
        Initialize data cache with Redis backend.
        
        Args:
            max_size: Maximum number of items to store (for fallback cache)
            ttl_seconds: Time to live for cached items in seconds
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.ttl = timedelta(seconds=ttl_seconds)
        
        # Redis configuration
        self._redis_prefix = settings.REDIS_PREFIX
        self._redis_key = f"{self._redis_prefix}websocket:messages"
        
        # Redis client
        self._redis_client: Optional[redis.Redis] = None
        self._redis_available = False
        
        # Fallback in-memory cache (only used if Redis is unavailable)
        self._fallback_cache: deque = deque(maxlen=max_size)
        
        # Statistics
        self._stats = {
            "total_messages": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "last_updated": None,
            "using_redis": False
        }
        self._lock = threading.Lock()
        
        # Initialize Redis connection
        self._init_redis()
    
    def add(self, data: Any, metadata: Optional[Dict] = None) -> None:
        """
        Add data to cache (Redis or in-memory fallback).
        
        Args:
            data: Data to cache
            metadata: Optional metadata about the data
        """
        with self._lock:
            timestamp = datetime.now()
            cache_item = {
                "timestamp": timestamp.isoformat(),
                "data": data,
                "metadata": metadata or {}
            }
            
            # Try Redis first
            if self._check_redis():
                try:
                    # Use sorted set with timestamp as score for time-based queries
                    score = timestamp.timestamp()
                    member = json.dumps(cache_item)
                    
                    # Add to Redis sorted set with prefix
                    self._redis_client.zadd(self._redis_key, {member: score})
                    
                    # Trim to max size (keep most recent)
                    count = self._redis_client.zcard(self._redis_key)
                    if count > self.max_size:
                        remove_count = count - self.max_size
                        self._redis_client.zremrangebyrank(self._redis_key, 0, remove_count - 1)
                    
                    # Set expiration on the entire key
                    self._redis_client.expire(self._redis_key, self.ttl_seconds)
                    
                    self._stats["total_messages"] += 1
                    self._stats["last_updated"] = timestamp
                    return
                except Exception as e:
                    print(f"⚠️ Redis add failed, falling back to memory: {e}")
                    self._redis_available = False
            
            # Fallback to in-memory cache
            cache_item["timestamp"] = timestamp  # Keep datetime object for in-memory
            self._fallback_cache.append(cache_item)
            self._stats["total_messages"] += 1
            self._stats["last_updated"] = timestamp
    
    def get_recent(self, limit: int = 100) -> List[Dict]:
        """
        Get most recent cached items from Redis or fallback cache.
        
        Args:
            limit: Maximum number of items to return
            
        Returns:
            List of recent cache items with serialized timestamps
        """
        with self._lock:
            # Try Redis first
            if self._check_redis():
                try:
                    # Get most recent items from sorted set (highest scores)
                    items = self._redis_client.zrevrange(self._redis_key, 0, limit - 1)
                    
                    result = []
                    now = datetime.now()
                    for item in items:
                        try:
                            cache_item = json.loads(item)
                            # Check if expired
                            item_time = datetime.fromisoformat(cache_item["timestamp"])
                            if now - item_time <= self.ttl:
                                result.append(cache_item)
                        except Exception as e:
                            print(f"⚠️ Error parsing cache item: {e}")
                            continue
                    
                    self._stats["cache_hits"] += 1
                    return result
                except Exception as e:
                    print(f"⚠️ Redis get_recent failed, falling back to memory: {e}")
                    self._redis_available = False
            
            # Fallback to in-memory cache
            now = datetime.now()
            valid_items = [
                item for item in self._fallback_cache
                if now - item["timestamp"] <= self.ttl
            ]
            
            recent = list(valid_items)[-limit:]
            return [
                {
                    "timestamp": item["timestamp"].isoformat(),
                    "data": item["data"],
                    "metadata": item["metadata"]
                }
                for item in recent
            ]
    
    def get_by_timerange(self, start: datetime, end: datetime) -> List[Dict]:
        """
        Get cached items within a time range from Redis or fallback cache.
        
        Args:
            start: Start datetime
            end: End datetime
            
        Returns:
            List of cache items in the time range
        """
        with self._lock:
            # Try Redis first
            if self._check_redis():
                try:
                    start_score = start.timestamp()
                    end_score = end.timestamp()
                    
                    # Get items in score range
                    items = self._redis_client.zrangebyscore(
                        self._redis_key,
                        start_score,
                        end_score
                    )
                    
                    result = []
                    for item in items:
                        try:
                            cache_item = json.loads(item)
                            result.append(cache_item)
                        except Exception as e:
                            print(f"⚠️ Error parsing cache item: {e}")
                            continue
                    
                    return result
                except Exception as e:
                    print(f"⚠️ Redis get_by_timerange failed, falling back to memory: {e}")
                    self._redis_available = False
            
            # Fallback to in-memory cache
            return [
                {
                    "timestamp": item["timestamp"].isoformat(),
                    "data": item["data"],
                    "metadata": item["metadata"]
                }
                for item in self._fallback_cache
                if start <= item["timestamp"] <= end
            ]
    
    def search(self, key: str, value: Any) -> List[Dict]:
        """
        Search cache for items matching criteria (from Redis or fallback cache).
        
        Args:
            key: Key to search in data
            value: Value to match
            
        Returns:
            List of matching cache items
        """
        with self._lock:
            # Try Redis first
            if self._check_redis():
                try:
                    # Get all items and filter
                    items = self._redis_client.zrange(self._redis_key, 0, -1)
                    
                    results = []
                    for item in items:
                        try:
                            cache_item = json.loads(item)
                            data = cache_item["data"]
                            if isinstance(data, dict) and data.get(key) == value:
                                results.append(cache_item)
                        except Exception:
                            continue
                    
                    return results
                except Exception as e:
                    print(f"⚠️ Redis search failed, falling back to memory: {e}")
                    self._redis_available = False
            
            # Fallback to in-memory cache
            results = []
            for item in self._fallback_cache:
                data = item["data"]
                if isinstance(data, dict) and data.get(key) == value:
                    results.append({
                        "timestamp": item["timestamp"].isoformat(),
                        "data": item["data"],
                        "metadata": item["metadata"]
                    })
            return results
    
    def search_exact_data(self, data: Any) -> List[Dict]:
        """
        Search cache for items with exact data match (from Redis or fallback cache).
        
        Args:
            data: Exact data to match
            
        Returns:
            List of matching cache items
        """
        with self._lock:
            # Try Redis first
            if self._check_redis():
                try:
                    # Get all items and filter
                    items = self._redis_client.zrange(self._redis_key, 0, -1)
                    
                    results = []
                    for item in items:
                        try:
                            cache_item = json.loads(item)
                            if cache_item["data"] == data:
                                results.append(cache_item)
                        except Exception:
                            continue
                    
                    return results
                except Exception as e:
                    print(f"⚠️ Redis search_exact_data failed, falling back to memory: {e}")
                    self._redis_available = False
            
            # Fallback to in-memory cache
            results = []
            for item in self._fallback_cache:
                if item["data"] == data:
                    results.append({
                        "timestamp": item["timestamp"].isoformat(),
                        "data": item["data"],
                        "metadata": item["metadata"]
                    })
            return results
    
    def get_stats(self) -> Dict:
        """
        Get cache statistics from Redis or fallback cache.
        
        Returns:
            Dictionary with cache statistics (datetime serialized)
        """
        with self._lock:
            # Try Redis first
            if self._check_redis():
                try:
                    # Get count from Redis
                    total_items = self._redis_client.zcard(self._redis_key)
                    
                    # Count valid (non-expired) items
                    now = datetime.now()
                    cutoff_score = (now - self.ttl).timestamp()
                    valid_count = self._redis_client.zcount(self._redis_key, cutoff_score, "+inf")
                    
                    stats = {
                        **self._stats,
                        "current_size": total_items,
                        "valid_items": valid_count,
                        "max_size": self.max_size,
                        "ttl_seconds": self.ttl_seconds,
                        "backend": "redis",
                        "redis_key": self._redis_key
                    }
                    
                    if stats["last_updated"]:
                        stats["last_updated"] = stats["last_updated"].isoformat()
                    
                    return stats
                except Exception as e:
                    print(f"⚠️ Redis get_stats failed, falling back to memory: {e}")
                    self._redis_available = False
            
            # Fallback to in-memory cache
            now = datetime.now()
            valid_count = sum(
                1 for item in self._fallback_cache
                if now - item["timestamp"] <= self.ttl
            )
            
            stats = {
                **self._stats,
                "current_size": len(self._fallback_cache),
                "valid_items": valid_count,
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds,
                "backend": "memory"
            }
            
            if stats["last_updated"]:
                stats["last_updated"] = stats["last_updated"].isoformat()
                
            return stats
    
    def clear(self) -> None:
        """Clear all cached data from Redis and fallback cache."""
        with self._lock:
            # Clear Redis
            if self._check_redis():
                try:
                    self._redis_client.delete(self._redis_key)
                    print("✓ Redis cache cleared")
                except Exception as e:
                    print(f"⚠️ Redis clear failed: {e}")
                    self._redis_available = False
            
            # Clear in-memory fallback
            self._fallback_cache.clear()
            
            # Reset stats
            using_redis = self._stats.get("using_redis", False)
            self._stats = {
                "total_messages": 0,
                "cache_hits": 0,
                "cache_misses": 0,
                "last_updated": None,
                "using_redis": using_redis
            }
    
    def cleanup_expired(self) -> int:
        """
        Remove expired items from Redis and fallback cache.
        
        Returns:
            Number of items removed
        """
        with self._lock:
            removed_count = 0
            
            # Clean up Redis
            if self._check_redis():
                try:
                    now = datetime.now()
                    cutoff_score = (now - self.ttl).timestamp()
                    
                    # Remove items older than TTL
                    removed_count = self._redis_client.zremrangebyscore(
                        self._redis_key,
                        "-inf",
                        cutoff_score
                    )
                    
                    if removed_count > 0:
                        print(f"✓ Cleaned up {removed_count} expired items from Redis")
                    
                    return removed_count
                except Exception as e:
                    print(f"⚠️ Redis cleanup failed: {e}")
                    self._redis_available = False
            
            # Clean up in-memory fallback
            now = datetime.now()
            original_size = len(self._fallback_cache)
            
            self._fallback_cache = deque(
                (item for item in self._fallback_cache if now - item["timestamp"] <= self.ttl),
                maxlen=self.max_size
            )
            
            return original_size - len(self._fallback_cache)
    
    def _init_redis(self) -> None:
        """Initialize Redis connection with configured prefix."""
        try:
            # Create Redis connection
            self._redis_client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None,
                decode_responses=False,  # We handle JSON encoding
                socket_connect_timeout=5,
                socket_timeout=5
            )
            
            # Test connection
            self._redis_client.ping()
            self._redis_available = True
            self._stats["using_redis"] = True
            
            print(f"✓ DataCache: Redis connection established")
            print(f"  → Key prefix: {self._redis_prefix}")
            print(f"  → Full key: {self._redis_key}")
            
        except Exception as e:
            print(f"⚠️ DataCache: Redis unavailable, using in-memory fallback: {e}")
            self._redis_client = None
            self._redis_available = False
            self._stats["using_redis"] = False
    
    def _check_redis(self) -> bool:
        """
        Check if Redis is available and reconnect if needed.
        
        Returns:
            True if Redis is available, False otherwise
        """
        if self._redis_available and self._redis_client:
            try:
                # Quick ping to check connection
                self._redis_client.ping()
                return True
            except Exception:
                print("⚠️ Redis connection lost, attempting reconnect...")
                self._redis_available = False
        
        # Try to reconnect if not available
        if not self._redis_available:
            try:
                self._init_redis()
                return self._redis_available
            except Exception:
                return False
        
        return False
    
    def close(self) -> None:
        """Close Redis connection."""
        if self._redis_client:
            try:
                self._redis_client.close()
                print("✓ Redis cache connection closed")
            except Exception as e:
                print(f"⚠️ Error closing Redis connection: {e}")
            finally:
                self._redis_client = None
                self._redis_available = False


# Singleton instance
data_cache = DataCache(max_size=1000, ttl_seconds=3600)
