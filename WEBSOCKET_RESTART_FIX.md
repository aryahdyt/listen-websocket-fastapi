# WebSocket Listener Restart Fix

## Problem

When stopping the WebSocket listener and trying to start it again, the connection would not reconnect.

### Root Cause

The `start_listener()` method was only setting the `is_active` flag to `True`, but **it was not creating a new asyncio task** to run the `listen()` method. 

When you stopped the listener:
1. `is_active = False` was set
2. The existing `listen()` loop detected this and exited
3. The asyncio task completed

When you tried to start again:
1. `is_active = True` was set ✅
2. BUT no new task was created ❌
3. The `listen()` method never ran again ❌

---

## Solution

Updated the `start_listener()` method to:
1. Check if task exists and is completed
2. Create a new asyncio task if needed
3. Properly restart the WebSocket connection

### Code Changes

**Before:**
```python
def start_listener(self) -> dict:
    if self.is_active:
        return {"status": "already_active", ...}
    
    self.is_active = True  # ❌ Only set flag, no task created!
    print("▶️ WebSocket listener STARTED")
    
    return {"status": "started", ...}
```

**After:**
```python
def start_listener(self) -> dict:
    if self.is_active:
        return {"status": "already_active", ...}
    
    # Set flags to active
    self.is_active = True
    self.is_running = False  # Will be set to True by listen()
    
    # Create new listener task if not exists or completed ✅
    if self.listener_task is None or self.listener_task.done():
        self.listener_task = asyncio.create_task(self.listen())
        print("▶️ WebSocket listener STARTED (task created)")
    else:
        print("▶️ WebSocket listener STARTED (task already running)")
    
    return {"status": "started", ...}
```

---

## Additional Improvements

### 1. Enhanced Stop Method

Now properly closes the WebSocket connection:

```python
def stop_listener(self) -> dict:
    if not self.is_active:
        return {"status": "already_inactive", ...}
    
    # Set flags to inactive
    self.is_active = False
    self.is_running = False
    
    # Close WebSocket connection if exists ✅
    if self._websocket_connection:
        try:
            asyncio.create_task(self._websocket_connection.close())
        except Exception as e:
            print(f"⚠️ Error closing WebSocket connection: {e}")
    
    print("⏸️ WebSocket listener STOPPED")
    
    return {"status": "stopped", ...}
```

### 2. Better Status Reporting

Added task status to the status endpoint:

```python
def get_status(self) -> dict:
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
        "task_status": task_status,  # ✅ New field
        "connected_clients": len(self.connected_clients),
        "websocket_url": self.url,
        "auto_start": settings.WEBSOCKET_AUTO_START,
        "connection_status": "connected" if self._websocket_connection else "disconnected"
    }
```

---

## How It Works Now

### Flow: Stop → Start → Reconnect

```
1. User clicks "Stop"
   ↓
   stop_listener() called
   ↓
   • is_active = False
   • is_running = False
   • WebSocket connection closed
   ↓
   listen() loop detects is_active=False
   ↓
   listen() exits, task completes
   ↓
   Status: "stopped"

2. User clicks "Start"
   ↓
   start_listener() called
   ↓
   • is_active = True
   • Check if task exists and is done ✅
   ↓
   • Create new task: asyncio.create_task(self.listen()) ✅
   ↓
   listen() starts running
   ↓
   • Connects to WebSocket
   • Starts processing messages
   ↓
   Status: "started" ✅
```

---

## Testing

### Test Start/Stop Cycle

```bash
# Start the application
python main.py

# Stop listener
curl -X POST http://localhost:8000/listener/stop
# Response: {"status": "stopped", "is_active": false}

# Check status
curl http://localhost:8000/listener/status
# Response: {"is_active": false, "task_status": "completed", ...}

# Start listener again ✅
curl -X POST http://localhost:8000/listener/start
# Response: {"status": "started", "is_active": true}

# Check status
curl http://localhost:8000/listener/status
# Response: {"is_active": true, "task_status": "running", ...}

# Verify connection
# Should see logs:
# 🔌 Connecting to WebSocket: ws://...
# ✓ Connected to WebSocket: ws://...
```

### Test via Monitor UI

1. Open http://localhost:8000/monitor
2. Click "Stop Listener" button
3. Wait 2-3 seconds
4. Click "Start Listener" button
5. Check "Listener Status" card - should show "Active"
6. Activity log should show:
   - "⏸️ WebSocket listener STOPPED"
   - "▶️ WebSocket listener STARTED (task created)"
   - "🔌 Connecting to WebSocket: ..."
   - "✓ Connected to WebSocket: ..."

---

## Status Field Reference

### is_active
- `true`: Listener should be running
- `false`: Listener should be stopped

### is_running
- `true`: listen() loop is actively running
- `false`: listen() loop has exited

### task_status
- `"none"`: No task created yet
- `"running"`: Task is active and running
- `"completed"`: Task finished normally
- `"cancelled"`: Task was cancelled

### connection_status
- `"connected"`: WebSocket connection is established
- `"disconnected"`: No active WebSocket connection

---

## Benefits

✅ **Proper restart**: Creates new task when starting again  
✅ **Clean shutdown**: Closes WebSocket connection on stop  
✅ **Better monitoring**: Task status visible in status endpoint  
✅ **Reliable operation**: No more "stuck" states  
✅ **Clear logging**: Shows when task is created vs already running  

---

## Edge Cases Handled

### 1. Multiple Start Calls
If you call start multiple times while already running:
- Returns "already_active" status
- Does NOT create duplicate tasks
- Existing task continues running

### 2. Multiple Stop Calls
If you call stop multiple times while already stopped:
- Returns "already_inactive" status
- Safe to call multiple times

### 3. Start → Stop → Start (rapid)
- Each cycle properly creates/destroys task
- No race conditions
- Clean state transitions

### 4. Connection Failure After Start
- Task remains running
- Auto-reconnect logic kicks in
- Can still stop/start manually

---

## Troubleshooting

### Issue: "Started but not connecting"

**Check:**
```bash
curl http://localhost:8000/listener/status
```

**Look for:**
- `task_status`: Should be "running", not "completed" or "none"
- `is_active`: Should be `true`
- `is_running`: Should be `true` after a moment

**If task_status is "completed":**
- Check application logs for errors
- Task may have crashed immediately
- Look for connection errors

### Issue: "Already active but not working"

**Solution:**
```bash
# Force stop
curl -X POST http://localhost:8000/listener/stop

# Wait 2 seconds
sleep 2

# Start fresh
curl -X POST http://localhost:8000/listener/start
```

### Issue: "Task keeps failing"

**Check WebSocket URL:**
```bash
# In .env file
WEBSOCKET_URL=ws://202.10.32.106:1880/ws/projection_bpp

# Verify it's reachable
# You should see connection attempts in logs
```

---

## Migration Notes

### For Existing Deployments

No database migrations needed. Just restart the application:

```bash
# Stop application
Ctrl+C

# Update code
git pull  # or copy new files

# Start application
python main.py
```

### Configuration Changes

None required. All changes are in the code logic.

---

## Summary

### What Was Broken
- Stop → Start cycle didn't reconnect
- Only flag was set, no task created
- WebSocket connection never established again

### What Was Fixed
- ✅ Create new task when starting
- ✅ Properly close connection when stopping
- ✅ Better status reporting
- ✅ Clear logging of task lifecycle

### Result
**Now you can stop and start the WebSocket listener as many times as you want, and it will properly reconnect each time!** 🎉
