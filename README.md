# Listener Projection BPP

FastAPI service that listens to a WebSocket and queries ClickHouse database with a clean, modular architecture.

## 📁 Project Structure

```
listener-projection-bpp/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application factory
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py        # API endpoints
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py        # Configuration management
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py       # Pydantic models
│   └── services/
│       ├── __init__.py
│       ├── clickhouse.py    # ClickHouse service
│       └── websocket.py     # WebSocket listener service
├── main.py                  # Application entry point
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## 🎯 Features

- 🔌 **WebSocket Listener**: Connects to `ws://********/ws/******`
- 🗄️ **ClickHouse Integration**: Async database queries
- 🏗️ **Modular Architecture**: Clean separation of concerns
- 🔄 **Auto-Reconnect**: Automatic WebSocket reconnection
- 📡 **Real-time Processing**: Process and forward data in real-time
- 🎨 **Modern FastAPI**: Using latest FastAPI patterns
- 💾 **Data Caching**: In-memory caching with TTL for WebSocket data
- 📊 **Real-time Monitoring**: Beautiful web-based dashboard for live data monitoring
- 📈 **Cache Statistics**: Track message counts, cache hits, and performance metrics
- 🔍 **Data Search**: Search and filter cached data

## 🚀 Quick Start (Recommended)

### Option 1: Test with Local WebSocket Simulator (Easiest)

**Windows (Command Prompt):**
```cmd
start_local_monitoring.bat
```

**Windows (PowerShell):**
```powershell
.\start_local_monitoring.ps1
```

This will:
- ✅ Start FastAPI Listener on port 8000
- ✅ Start WebSocket Simulator on port 8001
- ✅ Open interactive test client
- ✅ Launch monitor dashboard in browser
- ✅ Ready to send test polygon queries

**Then in the test client window, enter:**
```
119.3 -8.6 119.5 -8.6 119.5 -8.4 119.3 -8.4 119.3 -8.6
```

See [QUICKSTART.md](QUICKSTART.md) for more test polygons and details.

### Option 2: Use Startup Scripts (For production setup)

**Windows (Command Prompt):**
```cmd
run.bat
```

**Windows (PowerShell):**
```powershell
.\run.ps1
```

**Linux/Mac:**
```bash
chmod +x run.sh
./run.sh
```

### Option 2: Manual Setup

1. **Create a virtual environment:**
```bash
python -m venv venv
```

2. **Activate the virtual environment:**
```bash
# Windows (Command Prompt)
venv\Scripts\activate.bat

# Windows (PowerShell)
.\venv\Scripts\Activate.ps1

# Linux/Mac
source venv/bin/activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

4. **Configure environment variables:**
```bash
# Copy the example environment file
copy .env.example .env

# Edit .env with your configuration
```

5. **Run the application:**
```bash
python main.py
```

## Configuration

Edit the `.env` file with your settings:

```env
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=9000
CLICKHOUSE_DATABASE=default
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=

WEBSOCKET_URL=ws://202.10.32.106:1880/ws/projection_bpp

HOST=0.0.0.0
PORT=8000
```

## 🎮 Usage

### Using Startup Scripts (with venv)

**Windows:**
```cmd
run.bat
```
or
```powershell
.\run.ps1
```

**Linux/Mac:**
```bash
./run.sh
```

### Manual Execution (after activating venv)

**Run the service:**
```bash
python main.py
```

**Or use uvicorn directly with auto-reload:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The service will start on `http://localhost:8000` and automatically connect to the WebSocket!

### 📊 Real-Time Monitoring Dashboard

Access the beautiful monitoring dashboard at:
```
http://localhost:8000/monitor
```

Features:
- 🔴/🟢 Live connection status indicator
- 📨 Real-time message counter
- 💾 Cache size and statistics
- 📋 Live message feed with auto-scroll
- 📊 Cache performance metrics
- 🔄 Auto-refresh every 5 seconds
- 🗑️ Clear cache button

See [MONITORING.md](MONITORING.md) for detailed documentation on monitoring and caching features.

## API Endpoints

### GET `/`
Service information and available endpoints.

**Response:**
```json
{
  "service": "Projection BPP Listener",
  "version": "1.0.0",
  "status": "running",
  "websocket_url": "ws://202.10.32.106:1880/ws/projection_bpp",
  "endpoints": {
    "health": "/health",
    "query": "/query",
    "websocket": "/ws",
    "monitor_ui": "/monitor",
    "cache_stats": "/cache/stats",
    "cache_recent": "/cache/recent",
    "cache_clear": "/cache/clear"
  }
}
```

### GET `/health`
Check service health and ClickHouse connection status.

**Response:**
```json
{
  "status": "ok",
  "clickhouse": "connected",
  "timestamp": "2025-10-17T10:30:00"
}
```

### GET `/monitor`
Access the real-time monitoring dashboard (web UI).

### POST `/query`
Execute a custom ClickHouse query.

**Request:**
```json
{
  "query": "SELECT * FROM your_table LIMIT 10"
}
```

**Response:**
```json
{
  "success": true,
  "rows": 10,
  "data": [...]
}
```

### GET `/cache/stats`
Get cache statistics.

**Response:**
```json
{
  "total_messages": 1500,
  "current_size": 1000,
  "valid_items": 980,
  "max_size": 1000,
  "ttl_seconds": 3600,
  "cache_hits": 0,
  "cache_misses": 0,
  "last_updated": "2025-10-17T10:30:00"
}
```

### GET `/cache/recent?limit=100`
Get recent cached data.

**Query Parameters:**
- `limit` (optional): Number of items to return (default: 100)

**Response:**
```json
{
  "data": [...],
  "stats": {...}
}
```

### POST `/cache/clear`
Clear all cached data.

**Response:**
```json
{
  "message": "Cache cleared successfully"
}
```

### WebSocket `/ws`
Connect to receive real-time data from the service.

```javascript
const ws = new WebSocket('ws://localhost:8000/ws');

ws.onopen = () => {
  console.log('Connected!');
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === 'initial_data') {
    console.log('Initial cache data:', data.data);
  } else if (data.type === 'polygon_update') {
    console.log('New update:', data.data);
    console.log('Cache stats:', data.cache_stats);
  }
};
```

## How It Works

1. **Startup**: The service connects to the external WebSocket at `ws://202.10.32.106:1880/ws/projection_bpp`
2. **Listen**: Continuously listens for messages from the WebSocket
3. **Process**: When a message arrives:
   - Parses the message (JSON format)
   - Queries ClickHouse database
   - Sends results to connected clients via `/ws` endpoint
4. **Auto-reconnect**: If the WebSocket connection drops, it automatically reconnects after 5 seconds

## Customization

### Modify ClickHouse Query

Edit the `process_websocket_message()` function in `main.py`:

```python
async def process_websocket_message(data: dict):
    # Your custom query logic here
    query = """
        SELECT column1, column2, column3
        FROM your_table
        WHERE condition = 'value'
        ORDER BY timestamp DESC
        LIMIT 100
    """
    result = await query_clickhouse(query)
    # Process result...
```

### Add Message Processing Logic

You can add custom logic to process incoming WebSocket messages based on their content:

```python
async def process_websocket_message(data: dict):
    message_type = data.get("type")
    
    if message_type == "request_data":
        query = "SELECT * FROM data_table"
    elif message_type == "request_status":
        query = "SELECT * FROM status_table"
    else:
        query = "SELECT * FROM default_table"
    
    result = await query_clickhouse(query)
    # Process result...
```

## Development

### API Documentation

Once the service is running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 🐛 Troubleshooting

### PowerShell Execution Policy Error
If you get "cannot be loaded because running scripts is disabled", run:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
Then try running `.\run.ps1` again, or use `run.bat` instead.

### Virtual Environment Issues
- Make sure Python 3.8+ is installed
- Delete `venv` folder and recreate: `python -m venv venv`
- Use `run.bat` on Windows if PowerShell has issues

### WebSocket Connection Issues
- Verify the WebSocket URL is accessible: `ws://202.10.32.106:1880/ws/projection_bpp`
- Check firewall settings
- The service will automatically retry connection every 5 seconds

### ClickHouse Connection Issues
- Verify ClickHouse is running
- Check host, port, and credentials in `.env`
- Use `/health` endpoint to check connection status: http://localhost:8000/health

### Import Errors
Make sure you're running from the project root and the virtual environment is activated:
```bash
cd c:\spasi\listener-projection-bpp
venv\Scripts\activate.bat
python main.py
```

## License

MIT
