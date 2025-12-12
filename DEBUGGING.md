# Debugging Guide

## Logging

The application now includes comprehensive logging to help debug issues.

### Log Levels

By default, logging is set to `INFO` level. You can see:
- User input
- Graph node execution
- Routing decisions
- Agent selections
- Errors and exceptions

### Viewing Logs

When you run the application, logs will be printed to the console alongside the chat:

```bash
python -m app.main
```

Example log output:
```
2025-01-12 10:30:45 - app.main - INFO - User input: show me my account details
2025-01-12 10:30:45 - app.main - INFO - Invoking graph with 1 new message(s)
2025-01-12 10:30:45 - app.graphs.app_graph - INFO - [ingest_user_message] Processing 1 message(s)
2025-01-12 10:30:45 - app.graphs.app_graph - INFO - [route_intent] Route decision: normal
2025-01-12 10:30:45 - app.graphs.app_graph - INFO - [normal_conversation] Using customer agent
```

### Adjusting Log Level

To see more detailed logs (DEBUG level), edit `app/main.py`:

```python
# Change this line:
logging.basicConfig(level=logging.INFO, ...)

# To:
logging.basicConfig(level=logging.DEBUG, ...)
```

To reduce logging (only errors), use:

```python
logging.basicConfig(level=logging.ERROR, ...)
```

### Disabling Logs

To disable all logging output:

```python
logging.basicConfig(level=logging.CRITICAL, ...)
```

Or comment out the logging configuration entirely:

```python
# logging.basicConfig(...)
```

## Common Issues and Debugging

### Issue: Bot gets stuck after completing a flow

**Symptoms:** After email update or lyrics search completes, the next user input hangs.

**Debug steps:**
1. Check the logs for the last node executed
2. Look for error messages in the logs
3. Verify the state is being properly saved by the checkpointer

**Logs to look for:**
```
[run_email_update_subgraph] Completed, status: done
[ingest_user_message] Processing X message(s)
[route_intent] Route decision: normal
```

If you don't see the route decision, the issue is likely in the routing logic.

### Issue: Agent gives wrong responses

**Debug steps:**
1. Check which agent was selected:
   ```
   [normal_conversation] Using customer agent
   ```
2. Verify the routing decision was correct
3. Check if the LLM response contains errors

### Issue: Interrupts not working

**Debug steps:**
1. Check if the interrupt is being triggered:
   ```
   app.main - INFO - Graph interrupted, waiting for user input
   ```
2. Verify the checkpointer is working
3. Ensure you're using the same `thread_id` when resuming

## Saving Logs to File

To save logs to a file for later analysis:

```bash
python -m app.main 2>&1 | tee app.log
```

This will display logs in the terminal AND save them to `app.log`.

To save only logs (not user interaction):

```bash
python -m app.main > /dev/null 2> app.log
```

## Analyzing Logs

Use grep to filter logs:

```bash
# Show only errors
cat app.log | grep ERROR

# Show routing decisions
cat app.log | grep "Route decision"

# Show agent selections
cat app.log | grep "Using.*agent"

# Show interrupt points
cat app.log | grep "interrupted"
```

## Performance Profiling

To measure execution time of different nodes, the logs include timestamps. Compare consecutive timestamps to see where delays occur:

```
2025-01-12 10:30:45 - [ingest_user_message] ...
2025-01-12 10:30:46 - [route_intent] ...        # 1 second
2025-01-12 10:30:52 - [normal_conversation] ... # 6 seconds (LLM call)
```

## Reporting Issues

When reporting issues, please include:

1. **The logs** from the session where the issue occurred
2. **The exact user input** that caused the issue
3. **Expected behavior** vs. actual behavior
4. **The last successful operation** before the issue

Example bug report:
```
Issue: Bot stuck after email update

Steps to reproduce:
1. "update my email"
2. Confirm with "Yes"
3. Enter code "123456"
4. Enter new email "test@example.com"
5. Type "show my account" <- HANGS HERE

Logs:
[paste relevant log lines]

Expected: Should show account details
Actual: No response, appears to hang
```

