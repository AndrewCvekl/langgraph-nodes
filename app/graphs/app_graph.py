"""Main application graph for the music store support bot.

This is the top-level graph that:
1. Ingests user messages
2. Routes to appropriate handlers based on intent
3. Invokes subgraphs for specialized flows (email, lyrics, payment)
4. Handles normal conversation with music/customer agents

Compiles with a checkpointer for persistence and interrupt handling.
"""

import logging
from typing import Literal, Any

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode
import re

from app.models.state import AppState, get_initial_state
from app.config import config
from app.agents.router import get_route_choice
from app.agents.music import MUSIC_SYSTEM_PROMPT, get_music_model, get_music_tools
from app.agents.customer import CUSTOMER_SYSTEM_PROMPT, get_customer_model, make_customer_tools
from app.graphs.email_subgraph import email_subgraph
from app.graphs.lyrics_subgraph import lyrics_subgraph
from app.graphs.purchase_subgraph import purchase_subgraph

logger = logging.getLogger(__name__)


def add_assistant_message(state: AppState, text: str) -> list[dict]:
    """Helper to add a text message to assistant_messages."""
    current = state.get("assistant_messages", []) or []
    return current + [{"type": "text", "text": text}]


# Node 1: Ingest user message
def ingest_user_message(state: AppState) -> dict:
    """Process incoming user message and prepare for routing.
    
    This node:
    - Stores the last user message for easy access
    - Clears previous assistant messages for new turn
    - Clears completed flows to prevent re-entry
    """
    messages = state.get("messages", [])
    logger.info(f"[ingest_user_message] Processing {len(messages)} message(s)")
    
    # Get the last user message
    last_user_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg.content
            break
    
    logger.info(f"[ingest_user_message] Last user message: {last_user_msg[:50]}...")
    
    # Clear completed flows to prevent accidental re-entry
    email_flow = state.get("email_flow", {})
    email_flow_status = email_flow.get("status", "")
    purchase_flow = state.get("purchase_flow", {})
    purchase_flow_status = purchase_flow.get("status", "")
    updates = {
        "last_user_msg": last_user_msg,
        "assistant_messages": [],  # Clear for new turn
    }
    
    # If email flow completed, reset it
    if email_flow_status in ("done", "cancelled", "failed"):
        updates["email_flow"] = {}
    if purchase_flow_status in ("done", "cancelled", "failed"):
        updates["purchase_flow"] = {}
    
    return updates


# Node 2: Route intent
def route_intent(
    state: AppState,
) -> Command[
    Literal[
        "normal_select_agent",
        "run_email_update_subgraph",
        "run_lyrics_subgraph",
        "run_purchase_subgraph",
    ]
]:
    """Use the router agent to determine intent and route accordingly."""
    messages = state.get("messages", [])
    logger.info(f"[route_intent] Routing with {len(messages)} message(s)")
    
    # Deterministic routing overrides (best practice: don't make the LLM guess):
    # - If user replies with a bare number after we showed Track IDs, treat it as a purchase selection.
    last_msg_raw = (state.get("last_user_msg", "") or "").strip()
    last_msg = last_msg_raw.lower()
    last_track_ids = state.get("last_track_ids", []) or []
    if re.fullmatch(r"\d+", last_msg) and last_track_ids:
        logger.info("[route_intent] Detected numeric selection with last_track_ids context -> purchase")
        return Command(update={"route": "purchase"}, goto="run_purchase_subgraph")

    # Get route from router agent
    route = get_route_choice(messages)
    logger.info(f"[route_intent] Route decision: {route}")
    
    # Simple fix: If email flow just completed, don't start it again unless explicitly requested
    email_flow = state.get("email_flow", {})
    email_flow_status = email_flow.get("status", "")
    if route == "update_email" and email_flow_status in ("done", "cancelled", "failed"):
        # Check if user is explicitly requesting email update again
        last_msg = state.get("last_user_msg", "").lower()
        explicit_keywords = ["update", "change", "modify", "new email"]
        if not any(keyword in last_msg for keyword in explicit_keywords):
            logger.info(f"[route_intent] Email flow just completed ({email_flow_status}), treating as normal conversation")
            route = "normal"
    
    # Map route to node
    if route == "update_email":
        return Command(
            update={"route": "update_email"},
            goto="run_email_update_subgraph",
        )
    elif route == "lyrics_search":
        return Command(
            update={"route": "lyrics_search"},
            goto="run_lyrics_subgraph",
        )
    elif route == "purchase":
        return Command(
            update={"route": "purchase"},
            goto="run_purchase_subgraph",
        )
    else:
        return Command(
            update={"route": "normal"},
            goto="normal_select_agent",
        )


def _messages_for_normal_turn(state: AppState) -> list:
    """Get the message list to use for the normal conversation LLM call.

    We preserve the previous "fresh start" behavior where a greeting after a
    conversation-ending message is treated as a fresh start.
    """
    messages = state.get("messages", []) or []
    last_msg = (state.get("last_user_msg", "") or "").lower()

    is_fresh_start = False
    if messages:
        last_assistant_msg = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                last_assistant_msg = msg.content.lower() if hasattr(msg, "content") else str(msg).lower()
                break

        conversation_enders = [
            "is there anything else i can help with",
            "let me know if you need anything else",
            "let me know if you change your mind",
            "what else can i help you with",
            "anything else i can help with",
        ]

        simple_greetings = ["hi", "hello", "hey", "hi there", "hello there", "hey there"]

        if last_assistant_msg and any(ender in last_assistant_msg for ender in conversation_enders):
            if any(greeting == last_msg.strip() for greeting in simple_greetings):
                is_fresh_start = True
                logger.info("[normal] Detected fresh conversation start after ending message")

    if not is_fresh_start:
        return messages

    # Only include the current user message (the greeting)
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            logger.info("[normal] Filtered conversation history for fresh start")
            return [msg]
    return messages


# Node 3a: Decide which normal agent to use (music vs customer)
def normal_select_agent(
    state: AppState,
) -> Command[Literal["normal_music_llm", "normal_customer_llm"]]:
    last_msg = (state.get("last_user_msg", "") or "").lower()
    customer_keywords = ["account", "email", "phone", "address", "profile", "info", "invoice", "purchase", "order"]
    use_customer_agent = any(kw in last_msg for kw in customer_keywords)

    choice: Literal["music", "customer"] = "customer" if use_customer_agent else "music"
    logger.info(f"[normal] Selected agent: {choice}")

    return Command(
        update={"normal_agent": choice},
        goto="normal_customer_llm" if choice == "customer" else "normal_music_llm",
    )


def normal_music_llm(state: AppState) -> Command[Literal["normal_music_tools", "normal_finalize"]]:
    """LLM step for music queries. Returns tool calls or a final answer."""
    model = get_music_model()
    tools = get_music_tools()
    model_with_tools = model.bind_tools(tools)

    msgs = _messages_for_normal_turn(state)
    response = model_with_tools.invoke([SystemMessage(content=MUSIC_SYSTEM_PROMPT)] + msgs)
    goto = "normal_music_tools" if getattr(response, "tool_calls", None) else "normal_finalize"
    return Command(update={"messages": [response]}, goto=goto)


def normal_customer_llm(state: AppState) -> Command[Literal["normal_customer_tools", "normal_finalize"]]:
    """LLM step for customer/account queries. Returns tool calls or a final answer."""
    user_id = state.get("user_id", 1)
    model = get_customer_model()
    tools = make_customer_tools(user_id)
    model_with_tools = model.bind_tools(tools)

    msgs = _messages_for_normal_turn(state)
    response = model_with_tools.invoke([SystemMessage(content=CUSTOMER_SYSTEM_PROMPT)] + msgs)
    goto = "normal_customer_tools" if getattr(response, "tool_calls", None) else "normal_finalize"
    return Command(update={"messages": [response]}, goto=goto)


# Tool nodes for normal conversation loops
_music_tools_node = ToolNode(get_music_tools())


def normal_customer_tools(state: AppState) -> dict:
    """Execute customer tool calls via ToolNode, binding tools to the current user."""
    user_id = state.get("user_id", 1)
    tools = make_customer_tools(user_id)
    node = ToolNode(tools)
    # ToolNode expects a state with "messages"; it returns {"messages": [ToolMessage, ...]}.
    return node.invoke({"messages": state.get("messages", [])})


def normal_finalize(state: AppState) -> dict:
    """Finalize normal conversation turn by emitting UI output + track-id context."""
    messages = state.get("messages", []) or []

    # Find the last AI message (should be the final answer after tool loop).
    last_ai: AIMessage | None = None
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            last_ai = m
            break

    if last_ai is None:
        # Defensive fallback
        text = "How can I help you today?"
        return {"assistant_messages": add_assistant_message(state, text)}

    response_text = last_ai.content if hasattr(last_ai, "content") else str(last_ai)

    # Capture Track IDs from the assistant response to support “buy it” follow-ups.
    track_ids = [int(x) for x in re.findall(r"\bTrack ID:\s*(\d+)\b", response_text)]

    return {
        "assistant_messages": add_assistant_message(state, response_text),
        "last_track_ids": track_ids[:10],
    }


# Node 4: Run email update subgraph
def run_email_update_subgraph(state: AppState, config: RunnableConfig) -> dict:
    """Invoke the email update subgraph."""
    logger.info("[run_email_update_subgraph] Starting email update flow")
    # The email subgraph will handle everything including interrupts
    # Since we add it as a node, LangGraph handles the subgraph execution
    result = email_subgraph.invoke(state, config)
    
    logger.info(f"[run_email_update_subgraph] Completed, status: {result.get('email_flow', {}).get('status')}")
    
    # Merge relevant state back including the verified flag
    return {
        "email_flow": result.get("email_flow", {}),
        "verified": result.get("verified", False),
        "messages": result.get("messages", []),
        "assistant_messages": result.get("assistant_messages", []),
    }


# Note: For lyrics subgraph, we add it directly as a node
# (not wrapped in a function) so LangGraph handles state properly
# including showing messages before interrupts


def create_app_graph() -> StateGraph:
    """Create the main application graph."""
    builder = StateGraph(AppState)
    
    # Add nodes
    builder.add_node("ingest_user_message", ingest_user_message)
    builder.add_node("route_intent", route_intent)
    builder.add_node("normal_select_agent", normal_select_agent)
    builder.add_node("normal_music_llm", normal_music_llm)
    builder.add_node("normal_music_tools", _music_tools_node)
    builder.add_node("normal_customer_llm", normal_customer_llm)
    builder.add_node("normal_customer_tools", normal_customer_tools)
    builder.add_node("normal_finalize", normal_finalize)
    builder.add_node("run_email_update_subgraph", run_email_update_subgraph)
    # Add lyrics subgraph directly (not wrapped) so state updates show before interrupts
    builder.add_node("run_lyrics_subgraph", lyrics_subgraph)
    # Add purchase subgraph directly so interrupts work cleanly
    builder.add_node("run_purchase_subgraph", purchase_subgraph)
    
    # Add edges
    builder.add_edge(START, "ingest_user_message")
    builder.add_edge("ingest_user_message", "route_intent")
    # route_intent uses Command to specify next node
    builder.add_edge("normal_finalize", END)
    builder.add_edge("run_email_update_subgraph", END)
    builder.add_edge("run_lyrics_subgraph", END)
    builder.add_edge("run_purchase_subgraph", END)

    # Normal conversation loop edges
    builder.add_edge("normal_music_tools", "normal_music_llm")
    builder.add_edge("normal_customer_tools", "normal_customer_llm")
    
    return builder


def get_checkpointer() -> MemorySaver:
    """Get the checkpointer for persistence.
    
    Uses MemorySaver for development. For production with SQLite,
    install langgraph-checkpoint-sqlite and use:
    from langgraph_checkpoint_sqlite import SqliteSaver
    return SqliteSaver.from_conn_string(config.CHECKPOINT_DB_PATH)
    """
    return MemorySaver()


def compile_app_graph(checkpointer=None):
    """Compile the app graph with optional checkpointer.
    
    Args:
        checkpointer: Optional checkpointer. If None, creates a new one.
        
    Returns:
        Compiled graph.
    """
    if checkpointer is None:
        checkpointer = get_checkpointer()
    
    builder = create_app_graph()
    return builder.compile(checkpointer=checkpointer)


# Create a default compiled graph for import
# Note: For LangGraph Studio, compile without checkpointer
# The studio will provide its own checkpointer
app_graph = create_app_graph().compile()


def get_compiled_graph():
    """Get a compiled graph with checkpointer for CLI usage."""
    return compile_app_graph()

