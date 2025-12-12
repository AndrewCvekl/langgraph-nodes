# Technical Notes

## Subgraph Integration and Interrupt Handling

### The Challenge

When a subgraph contains interrupts, we need to ensure that state updates (like `assistant_messages`) are visible **before** the interrupt is shown to the user.

### The Problem We Encountered

**Initial Approach (Didn't Work):**
```python
def run_lyrics_subgraph(state, config):
    result = lyrics_subgraph.invoke(state, config)
    return result
```

When wrapping a subgraph in a function and invoking it, the function doesn't return until all interrupts are resolved. So state updates from nodes inside the subgraph aren't visible in the parent graph's result until the entire subgraph completes.

**Result:** User sees the interrupt prompt without seeing the context message first.

### The Solution

Add the compiled subgraph **directly** as a node (not wrapped in a function):

```python
# Add subgraph directly (not wrapped in a function)
builder.add_node("run_lyrics_subgraph", lyrics_subgraph)
```

When you add a compiled subgraph directly, LangGraph treats each node within the subgraph as part of the parent graph's execution flow. State updates from each internal node are committed and visible in results at each step.

**Result:** State updates (including `assistant_messages`) from `lyrics_catalogue_lookup` are visible before `lyrics_interrupt_listen_confirm` triggers.

### Implementation Status

- **Email Subgraph**: Still uses wrapper function (should be updated for consistency)
- **Lyrics Subgraph**: Now added directly as a node ✅
- **Payment Subgraph**: TBD - needs to be embedded within lyrics flow

### State Flow Example

```
User: "Song with lyrics purple haze"

[Graph: route_intent] → routes to run_lyrics_subgraph
[Subgraph: lyrics_init_extract] → extracts query
[Subgraph: lyrics_genius_search] → finds matches
[Subgraph: lyrics_catalogue_lookup] → adds message to assistant_messages
  └─ State commit happens here!
[Subgraph: lyrics_interrupt_listen_confirm] → interrupt triggers
  └─ Parent sees assistant_messages and prints them BEFORE interrupt

User sees:
  "I think you're thinking of 'Purple Haze'..."
  [Interrupt]: "Do you want to have a listen?"
```

### Key Takeaway

For subgraphs with interrupts where you want to show messages before the interrupt:
- ✅ Add the compiled subgraph directly as a node
- ❌ Don't wrap it in a function that calls `.invoke()`

### Exception: When You Need Custom Logic

If you need custom logic between subgraph completion and parent graph continuation (like checking payment state), you'll need to use a wrapper function. In that case, ensure all informational messages happen BEFORE the subgraph is invoked, not within it.

### Main.py Enhancement

Also added logic to print `assistant_messages` before showing each interrupt:

```python
while "__interrupt__" in result:
    # Print messages BEFORE showing interrupt
    messages = result.get("assistant_messages", [])
    if messages:
        print_assistant_messages(messages)
    
    # Then handle interrupt
    resume_value = handle_interrupt(result["__interrupt__"])
    result = graph.invoke(Command(resume=resume_value), config)
```

This ensures messages are shown even if there are issues with state propagation.

