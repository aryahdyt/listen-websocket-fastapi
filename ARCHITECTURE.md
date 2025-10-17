# Architecture Overview

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        External Data Source                         │
│                                                                     │
│   Polygon WebSocket (ws://202.10.32.106:1880/ws/projection_bpp)   │
└─────────────────────────┬───────────────────────────────────────────┘
                          │
                          │ Real-time data stream
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    WebSocket Listener Service                       │
│                   (app/services/websocket.py)                       │
│                                                                     │
│  • Connects to external WebSocket                                  │
│  • Auto-reconnect on failure                                       │
│  • Parse JSON messages                                             │
│  • Process incoming data                                           │
└─────────────┬───────────────────────┬───────────────────────────────┘
              │                       │
              │                       │
              ▼                       ▼
┌─────────────────────────┐  ┌──────────────────────────┐
│   Data Cache Service    │  │  ClickHouse Database     │
│  (app/services/cache.py)│  │ (app/services/clickhouse)│
│                         │  │                          │
│  • In-memory storage    │  │  • Query execution       │
│  • TTL management       │  │  • Data persistence      │
│  • Thread-safe ops      │  │  • Analytics             │
│  • Size limits          │  │                          │
│  • Statistics tracking  │  │                          │
└─────────────┬───────────┘  └──────────┬───────────────┘
              │                         │
              │                         │
              └─────────┬───────────────┘
                        │
                        ▼
              ┌─────────────────────┐
              │   Broadcast Engine  │
              │   (WebSocket sends) │
              └─────────┬───────────┘
                        │
                        │ Real-time updates
                        │
        ┌───────────────┼───────────────┐
        │               │               │
        ▼               ▼               ▼
┌───────────────┐ ┌──────────┐ ┌─────────────┐
│   Monitor UI  │ │ REST API │ │   Custom    │
│   /monitor    │ │ Endpoints│ │  WebSocket  │
│               │ │          │ │   Clients   │
│ • Dashboard   │ │ /cache/* │ │             │
│ • Live feed   │ │ /query   │ │ • Python    │
│ • Statistics  │ │ /health  │ │ • JavaScript│
│ • Controls    │ │          │ │ • Any lang  │
└───────────────┘ └──────────┘ └─────────────┘
```

## Data Flow

### 1. Incoming Data Flow
```
Polygon WebSocket
    ↓
WebSocket Listener
    ↓
Parse JSON
    ↓
├─→ Cache (store with metadata)
│
└─→ ClickHouse Query (optional)
    ↓
Combine results
    ↓
Broadcast to clients
```

### 2. Cache Operations Flow
```
Add Data
    ↓
Check size limit
    ↓
Remove oldest if full
    ↓
Store with timestamp
    ↓
Update statistics
    ↓
Return
```

### 3. Client Connection Flow
```
Client connects to /ws
    ↓
Accept connection
    ↓
Add to client list
    ↓
Send initial data (50 recent items)
    ↓
Listen for new updates
    ↓
Broadcast on new data
    ↓
On disconnect: remove from list
```

## Component Responsibilities

### WebSocket Listener (`websocket.py`)
- ✓ Connect to external WebSocket
- ✓ Handle reconnection
- ✓ Parse messages
- ✓ Manage client connections
- ✓ Broadcast updates

### Data Cache (`cache.py`)
- ✓ Store data in memory
- ✓ Enforce TTL
- ✓ Maintain size limits
- ✓ Track statistics
- ✓ Thread-safe operations

### API Routes (`routes.py`)
- ✓ HTTP endpoints
- ✓ WebSocket endpoint
- ✓ Monitoring UI
- ✓ Cache management

### ClickHouse Service (`clickhouse.py`)
- ✓ Database connection
- ✓ Query execution
- ✓ Connection testing

## Technology Stack

### Backend
- **FastAPI**: Web framework
- **Uvicorn**: ASGI server
- **websockets**: WebSocket library
- **clickhouse-driver**: Database driver
- **Pydantic**: Data validation

### Frontend (Monitor UI)
- **HTML5**: Structure
- **CSS3**: Styling (gradient, animations)
- **JavaScript (Vanilla)**: Interactivity
- **WebSocket API**: Real-time updates

### Data Storage
- **In-Memory Cache**: Fast access, TTL support
- **ClickHouse**: Optional persistent storage

## Scalability Considerations

### Current Architecture
- ✓ Single instance
- ✓ In-memory cache
- ✓ Multiple WebSocket clients
- ✓ Async operations

### Potential Improvements
- ○ Redis for shared cache
- ○ Load balancer for multiple instances
- ○ Message queue (RabbitMQ/Kafka)
- ○ Horizontal scaling
- ○ Database connection pooling

## Security Layers

### Current
- ✓ CORS enabled
- ✓ Input validation (Pydantic)
- ✓ WebSocket connection management

### Recommendations
- ○ Authentication (JWT/OAuth)
- ○ Rate limiting
- ○ HTTPS/WSS
- ○ API key validation
- ○ Input sanitization

## Monitoring Points

### Application Metrics
1. Cache statistics
2. WebSocket connection status
3. Message processing rate
4. Client connection count

### System Metrics
1. Memory usage
2. CPU utilization
3. Network bandwidth
4. Response times

## Error Handling

```
Error Occurs
    ↓
Log error message
    ↓
Attempt recovery
    ↓
├─→ WebSocket: Reconnect after delay
├─→ Cache: Continue with partial data
├─→ Database: Return error response
└─→ Client: Close connection gracefully
```

## Performance Characteristics

### Cache Operations
- **Add**: O(1)
- **Get Recent**: O(n) where n = limit
- **Search**: O(n) where n = cache size
- **Stats**: O(n) for valid items count

### Memory Usage
- **Per Item**: ~1KB (depends on data)
- **1000 Items**: ~1MB + overhead
- **Max (default)**: ~50MB

### Latency
- **Cache Access**: <1ms
- **WebSocket Broadcast**: <10ms
- **Database Query**: 10-100ms (varies)

---

This architecture provides:
- ✅ Real-time data processing
- ✅ Efficient caching
- ✅ Multiple client support
- ✅ Easy monitoring
- ✅ Scalable design
