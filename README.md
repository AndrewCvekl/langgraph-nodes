# Music Store Customer Support Bot

A customer support chatbot for a music store built with LangGraph, featuring human-in-the-loop interactions, subgraphs, and LangSmith integration.

## Features

- **Music Catalogue Queries**: Search for albums, tracks, and artists
- **Customer Account Info**: View account details and purchase history
- **Email Update with Phone Verification**: Secure email updates using SMS verification codes
- **Lyrics Search**: Identify songs by lyrics, listen on YouTube, and purchase

## Architecture

The application uses a modular LangGraph architecture:

```
Main App Graph
├── Router (intent classification)
├── Normal Conversation (music/customer agents)
├── Email Update Subgraph (10 nodes with interrupts)
├── Lyrics Search Subgraph (10 nodes with interrupts)
└── Payment Subgraph (8 nodes with interrupts)
```

### Key Design Decisions

- **StateGraph over MessageGraph**: Uses modern LangGraph v1 patterns
- **Command-based routing**: Nodes return `Command(goto=...)` for explicit control flow
- **Parameterized SQL**: All database queries use SQLAlchemy `text()` with parameters (no SQL injection)
- **Interrupt protocol**: Structured payloads for UI modals (see `app/ui/interrupt_protocol.md`)
- **Idempotent payments**: Payment intent IDs ensure charges aren't duplicated

## Setup

### Prerequisites

- Python 3.11–3.13
- OpenAI API key
- (Optional) LangSmith API key for tracing

### Installation

```bash
# Clone/navigate to the project
cd "langgraph exercise"

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

### Environment Variables

Create a `.env` file:

```env
OPENAI_API_KEY=your-openai-api-key

# Optional: LangSmith tracing
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your-langsmith-api-key
LANGCHAIN_PROJECT=music-store-support-bot

# Default customer ID
DEFAULT_USER_ID=1
```

## Usage

### CLI Chat Loop

```bash
# Run the interactive chat
python -m app.main

# Or use the entry point
music-support
```

### Web UI (FastAPI + Vite build)

This repo includes a polished frontend in `Minimal Chatbot Interface Design/`. The backend serves the built UI and exposes `/api/chat` + `/api/resume` that follow the interrupt protocol (`app/ui/interrupt_protocol.md`).

1) Build the frontend:

```bash
cd "Minimal Chatbot Interface Design"
npm i
npm run build
```

2) Run the web server (from the repo root):

```bash
uv run uvicorn app.server:app --reload --port 8000
```

3) Open `http://localhost:8000`.

### Demo Script (Automated Tests)

```bash
# Run acceptance test scenarios
python demo_script.py
```

### LangGraph Studio

```bash
# Start the local server
langgraph up

# Open Studio at http://localhost:8000
```

## Project Structure

```
app/
├── main.py              # CLI entry point
├── server.py            # FastAPI server (serves UI + /api endpoints)
├── config.py            # Environment settings
├── db.py                # Chinook database bootstrap
├── models/
│   └── state.py         # State definitions (AppState, subgraph states)
├── graphs/
│   ├── app_graph.py     # Main graph with routing
│   ├── email_subgraph.py
│   ├── lyrics_subgraph.py
│   └── payment_subgraph.py
├── agents/
│   ├── router.py        # Intent classification
│   ├── music.py         # Music catalogue agent
│   └── customer.py      # Customer info agent
├── tools/
│   ├── db_tools.py      # Safe SQL queries
│   ├── twilio_mock.py   # SMS verification mock
│   ├── genius_mock.py   # Lyrics search mock
│   ├── youtube_mock.py  # Video search mock
│   └── payment_mock.py  # Payment processing mock
└── ui/
    └── interrupt_protocol.md  # UI contract documentation
```

Frontend:

```
Minimal Chatbot Interface Design/   # Vite + React UI (build output in build/)
```

## Example Interactions

### Music Query
```
You: What albums do you have by Queen?
Bot: Found 1 album(s):
     - Greatest Hits by Queen
```

### Email Update
```
You: I want to update my email
Bot: I can update your email. Send verification code to ***1234?
[Yes/No]: Yes
Bot: Code sent. Enter the 6-digit code.
[Input]: 123456
Bot: Verified! What's your new email?
[Input]: new@example.com
Bot: Done! Your email has been updated to new@example.com.
```

### Lyrics Search
```
You: What song goes "Is this the real life"
Bot: I think it's "Bohemian Rhapsody" by Queen! It's in our catalogue for $0.99.
     Would you like to listen?
[Yes/No]: Yes
Bot: [YouTube Player Embed]
     Want to buy this track for $0.99?
[Yes/No]: Yes
Bot: [Invoice #123 - $0.99]
     Purchase complete! Thank you for your order.
```

## Testing

The demo script covers these acceptance tests:

1. **Email Update - Cancel**: User declines verification
2. **Email Update - Success**: Full flow with correct code
3. **Email Update - Wrong Code Retry**: Retry after incorrect codes
4. **Email Update - Too Many Failures**: Flow fails after 3 wrong codes
5. **Lyrics Search - Purchase**: Full flow with payment
6. **Lyrics Search - Decline**: User declines at various points
7. **Normal Queries**: Music and account info queries

## Development

### Mock Services

All external services are mocked for demo purposes:

- **TwilioMock**: Default verification code is `123456`
- **GeniusMock**: Matches against a sample song database
- **YouTubeMock**: Generates deterministic video IDs
- **PaymentMock**: Always succeeds (configurable failure rate)

### Adding Real Services

Replace the mock classes with real API integrations:

1. `TwilioMock` → Twilio Verify API
2. `GeniusMock` → Genius API
3. `YouTubeMock` → YouTube Data API
4. `PaymentMock` → Stripe/PayPal

## License

MIT

