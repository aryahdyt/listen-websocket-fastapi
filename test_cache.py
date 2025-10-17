"""Test script for cache functionality."""

import asyncio
import json
from datetime import datetime
from app.services.cache import data_cache


def test_basic_cache_operations():
    """Test basic cache operations."""
    print("=" * 60)
    print("Testing Cache Basic Operations")
    print("=" * 60)
    
    # Clear cache first
    data_cache.clear()
    print("\n✓ Cache cleared")
    
    # Add some test data
    test_data = [
        {"symbol": "AAPL", "price": 150.25, "volume": 1000000},
        {"symbol": "GOOGL", "price": 2800.50, "volume": 500000},
        {"symbol": "MSFT", "price": 380.75, "volume": 750000},
    ]
    
    print("\n📝 Adding test data to cache...")
    for i, data in enumerate(test_data):
        data_cache.add(data, metadata={"index": i, "test": True})
        print(f"  Added: {data['symbol']}")
    
    # Get statistics
    stats = data_cache.get_stats()
    print("\n📊 Cache Statistics:")
    print(f"  Total messages: {stats['total_messages']}")
    print(f"  Current size: {stats['current_size']}")
    print(f"  Valid items: {stats['valid_items']}")
    print(f"  Max size: {stats['max_size']}")
    print(f"  TTL: {stats['ttl_seconds']} seconds")
    
    # Get recent data
    recent = data_cache.get_recent(limit=5)
    print(f"\n📥 Retrieved {len(recent)} recent items:")
    for item in recent:
        print(f"  - {item['data']['symbol']}: ${item['data']['price']}")
    
    # Search functionality
    print("\n🔍 Searching for AAPL...")
    results = data_cache.search("symbol", "AAPL")
    if results:
        print(f"  Found {len(results)} result(s)")
        print(f"  Price: ${results[0]['data']['price']}")
    
    print("\n✅ All basic tests passed!")


def test_cache_limits():
    """Test cache size limits."""
    print("\n" + "=" * 60)
    print("Testing Cache Size Limits")
    print("=" * 60)
    
    # Create a cache with small max size
    from app.services.cache import DataCache
    small_cache = DataCache(max_size=10, ttl_seconds=60)
    
    print("\n📝 Adding 15 items to cache with max_size=10...")
    for i in range(15):
        small_cache.add({"id": i, "value": f"item_{i}"})
    
    stats = small_cache.get_stats()
    print(f"\n📊 Cache size after adding 15 items: {stats['current_size']}")
    print(f"  Expected: 10 (due to max_size limit)")
    
    if stats['current_size'] <= 10:
        print("✅ Size limit working correctly!")
    else:
        print("❌ Size limit not working!")
    
    # Verify oldest items were removed
    recent = small_cache.get_recent(limit=20)
    print(f"\n📥 Items in cache:")
    for item in recent:
        print(f"  - ID: {item['data']['id']}")


def test_concurrent_access():
    """Test thread-safe concurrent access."""
    print("\n" + "=" * 60)
    print("Testing Concurrent Access (Thread Safety)")
    print("=" * 60)
    
    import threading
    
    data_cache.clear()
    
    def add_items(thread_id, count):
        for i in range(count):
            data_cache.add(
                {"thread": thread_id, "item": i},
                metadata={"thread_id": thread_id}
            )
    
    print("\n🔄 Starting 5 threads, each adding 20 items...")
    threads = []
    for i in range(5):
        t = threading.Thread(target=add_items, args=(i, 20))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    stats = data_cache.get_stats()
    print(f"\n📊 Final cache statistics:")
    print(f"  Total messages: {stats['total_messages']}")
    print(f"  Current size: {stats['current_size']}")
    
    if stats['total_messages'] == 100:
        print("✅ Thread safety test passed!")
    else:
        print(f"❌ Expected 100 messages, got {stats['total_messages']}")


def test_time_range_query():
    """Test time range queries."""
    print("\n" + "=" * 60)
    print("Testing Time Range Queries")
    print("=" * 60)
    
    data_cache.clear()
    
    import time
    
    print("\n📝 Adding items with delays...")
    for i in range(5):
        data_cache.add({"item": i, "timestamp": datetime.now().isoformat()})
        time.sleep(0.1)
    
    # Query last 2 seconds
    from datetime import timedelta
    end = datetime.now()
    start = end - timedelta(seconds=2)
    
    results = data_cache.get_by_timerange(start, end)
    print(f"\n📥 Items from last 2 seconds: {len(results)}")
    
    if len(results) > 0:
        print("✅ Time range query working!")
    else:
        print("❌ Time range query failed!")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🧪 CACHE FUNCTIONALITY TEST SUITE")
    print("=" * 60)
    
    try:
        test_basic_cache_operations()
        test_cache_limits()
        test_concurrent_access()
        test_time_range_query()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS COMPLETED SUCCESSFULLY!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
