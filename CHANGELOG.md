# Changelog

## 2025-01-12 - Logging and Debugging Improvements

### Changes Made

#### 1. Added Comprehensive Logging

**Files Modified:**
- `app/main.py` - Added logging to CLI loop
- `app/graphs/app_graph.py` - Added logging to all graph nodes

**What was added:**
- User input logging
- Graph invocation tracking
- Node execution logging (ingest, route, normal_conversation, subgraphs)
- Routing decisions logging
- Agent selection logging (music vs customer)
- Error logging with stack traces
- State update tracking

**Example log output:**
```
2025-01-12 10:30:45 - app.main - INFO - User input: show me my account details
2025-01-12 10:30:45 - app.graphs.app_graph - INFO - [ingest_user_message] Processing 1 message(s)
2025-01-12 10:30:45 - app.graphs.app_graph - INFO - [route_intent] Route decision: normal
2025-01-12 10:30:45 - app.graphs.app_graph - INFO - [normal_conversation] Using customer agent
```

#### 2. Fixed State Management

**Issue:** After completing a subgraph (like email update), the next user input would hang or not process correctly.

**Root Cause:** The chat loop was trying to accumulate messages across turns, but LangGraph's checkpointer already handles this.

**Fix:** Simplified the state management to only pass new messages on each invoke, letting the checkpointer handle state persistence.

**Before:**
```python
# Accumulated messages across turns (incorrect)
messages = current_state.get("messages", []) + [HumanMessage(content=user_input)]
result = graph.invoke({"messages": messages, "user_id": user_id}, config)
```

**After:**
```python
# Only pass new message, checkpointer handles history
input_state = {"messages": [HumanMessage(content=user_input)], "user_id": user_id}
result = graph.invoke(input_state, config)
```

#### 3. Replaced SqliteSaver with MemorySaver

**Reason:** `SqliteSaver` isn't available in the installed LangGraph version.

**Impact:** State is now stored in memory only (lost when app restarts). For production, install `langgraph-checkpoint-sqlite` separately.

#### 4. Fixed Type Annotations

Changed `config: dict` to `config: RunnableConfig` in subgraph nodes to resolve warnings.

### How to Use Logging

#### Enable verbose logging:
```bash
# Logs will appear in terminal while you chat
python -m app.main
```

#### Save logs to file:
```bash
python -m app.main 2>&1 | tee session.log
```

#### Adjust log level:
Edit `app/main.py`:
```python
# For more details (DEBUG)
logging.basicConfig(level=logging.DEBUG, ...)

# For less output (WARNING/ERROR only)
logging.basicConfig(level=logging.WARNING, ...)
```

#### Filter logs:
```bash
# Only show routing decisions
python -m app.main 2>&1 | grep "Route decision"

# Only show errors
python -m app.main 2>&1 | grep ERROR
```

### Known Issues

1. **Pydantic V1 warning** - Harmless warning about Python 3.14 compatibility. Doesn't affect functionality.

2. **MemorySaver limitation** - State is lost when app restarts. For persistence across sessions, install `langgraph-checkpoint-sqlite`.

### Next Steps

When reporting issues, please include:
1. The full log output from your session
2. The exact user inputs that caused the problem
3. Any error messages

See `DEBUGGING.md` for more details on troubleshooting.

