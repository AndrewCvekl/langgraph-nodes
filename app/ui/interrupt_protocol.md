# Interrupt Protocol

This document defines the contract between the LangGraph backend and UI clients for handling interrupts (human-in-the-loop interactions).

## Overview

Interrupts allow the graph to pause execution and wait for user input. When an interrupt occurs:

1. The graph state is saved to the checkpointer
2. The interrupt payload is returned to the caller in `result["__interrupt__"]`
3. The UI displays appropriate modal/prompt based on the payload type
4. User provides input
5. Caller resumes with `Command(resume=value)`
6. Graph continues from where it left off

## Interrupt Payloads

All interrupt payloads are JSON-serializable dictionaries.

### Confirm Modal

Used for Yes/No decisions.

```python
interrupt({
    "type": "confirm",
    "title": "Send Verification Code",
    "text": "Send verification code to the phone number on file?",
    "choices": ["Yes", "No"]
})
```

**Fields:**
- `type`: `"confirm"` (required)
- `title`: Modal title (required)
- `text`: Descriptive text/question (required)
- `choices`: List of choice strings (required, typically `["Yes", "No"]`)

**Resume Values:**
- `"Yes"` - User confirmed
- `"No"` - User declined

### Input Modal

Used for free-text input.

```python
interrupt({
    "type": "input",
    "title": "Enter Verification Code",
    "text": "Please enter the 6-digit code sent to your phone.",
    "placeholder": "123456"
})
```

**Fields:**
- `type`: `"input"` (required)
- `title`: Modal title (required)
- `text`: Descriptive text/instructions (required)
- `placeholder`: Example or hint text (optional)

**Resume Values:**
- String: The user's input

## Resume Protocol

To resume after an interrupt:

```python
from langgraph.types import Command

# Resume with user's response
result = graph.invoke(
    Command(resume=user_response),
    config={"configurable": {"thread_id": thread_id}}
)
```

**Important:** Always use the same `thread_id` when resuming.

## Implementation Rules

### Backend Rules

1. **One interrupt per node**: Each node should call `interrupt()` at most once.

2. **Interrupt first**: If a node calls `interrupt()`, it should be the first operation in the node (any code before it will re-run on resume).

3. **No try/except around interrupt**: Never wrap `interrupt()` in try/except blocks.

4. **JSON-serializable payloads**: All values in the interrupt payload must be JSON-serializable.

5. **Use Command for routing**: After processing the resume value, use `Command(goto=...)` for routing decisions.

### Frontend Rules

1. **Check for interrupts**: After each `invoke()` call, check if `"__interrupt__"` exists in the result.

2. **Handle interrupt list**: The `__interrupt__` value is a list. Process the first interrupt.

3. **Preserve thread_id**: Always resume with the same thread_id used in the original invoke.

4. **Type-based rendering**: Use the `type` field to determine how to render the modal.

## Example Flow

### Email Update Flow

```
User: "I want to update my email"

Graph → interrupt(confirm: "Send verification code?")
UI → Shows Yes/No modal
User → Clicks "Yes"
Resume → Command(resume="Yes")

Graph → Sends code
Graph → interrupt(input: "Enter code")
UI → Shows text input modal
User → Enters "123456"
Resume → Command(resume="123456")

Graph → Verifies code
Graph → interrupt(input: "Enter new email")
UI → Shows text input modal
User → Enters "new@email.com"
Resume → Command(resume="new@email.com")

Graph → Updates database
Graph → Returns success message
```

### Lyrics Search with Purchase

```
User: "What song goes 'Is this the real life'"

Graph → Searches Genius, finds match
Graph → interrupt(confirm: "Want to listen?")
User → "Yes"
Resume → Command(resume="Yes")

Graph → Fetches YouTube video
Graph → Returns embed + interrupt(confirm: "Buy for $0.99?")
User → "Yes"
Resume → Command(resume="Yes")

Graph → interrupt(confirm: "Confirm purchase?")
User → "Yes"
Resume → Command(resume="Yes")

Graph → Processes payment, creates invoice
Graph → Returns receipt
```

## Error Handling

If the user closes the modal or the session times out:

- Resume with `"No"` for confirm modals
- Resume with `""` for input modals

The graph should handle these gracefully (e.g., cancel the current flow).

## UI Component Suggestions

### Confirm Modal
```
┌─────────────────────────────────────┐
│  [Title]                            │
│                                     │
│  [Text description]                 │
│                                     │
│  ┌─────────┐    ┌─────────┐        │
│  │   Yes   │    │   No    │        │
│  └─────────┘    └─────────┘        │
└─────────────────────────────────────┘
```

### Input Modal
```
┌─────────────────────────────────────┐
│  [Title]                            │
│                                     │
│  [Text description]                 │
│                                     │
│  ┌─────────────────────────────┐   │
│  │ [placeholder]               │   │
│  └─────────────────────────────┘   │
│                                     │
│  ┌─────────┐    ┌─────────┐        │
│  │ Submit  │    │ Cancel  │        │
│  └─────────┘    └─────────┘        │
└─────────────────────────────────────┘
```

## Testing

The CLI demo (`app/main.py`) simulates modal interactions via stdin prompts. Use it as a reference implementation for the interrupt handling protocol.

