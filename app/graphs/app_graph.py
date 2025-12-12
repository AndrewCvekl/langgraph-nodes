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

from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver

from app.models.state import AppState, get_initial_state
from app.config import config
from app.agents.router import get_route_choice
from app.agents.music import music_agent
from app.agents.customer import customer_agent
from app.graphs.email_subgraph import email_subgraph
from app.graphs.lyrics_subgraph import lyrics_subgraph

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
    
    # Clear completed email flow to prevent accidental re-entry
    email_flow = state.get("email_flow", {})
    email_flow_status = email_flow.get("status", "")
    updates = {
        "last_user_msg": last_user_msg,
        "assistant_messages": [],  # Clear for new turn
    }
    
    # If email flow completed, reset it
    if email_flow_status in ("done", "cancelled", "failed"):
        updates["email_flow"] = {}
    
    return updates


# Node 2: Route intent
def route_intent(state: AppState) -> Command[Literal["normal_conversation", "run_email_update_subgraph", "run_lyrics_subgraph"]]:
    """Use the router agent to determine intent and route accordingly."""
    messages = state.get("messages", [])
    logger.info(f"[route_intent] Routing with {len(messages)} message(s)")
    
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
    else:
        return Command(
            update={"route": "normal"},
            goto="normal_conversation",
        )


# Node 3: Normal conversation (music/customer queries)
def normal_conversation(state: AppState) -> dict:
    """Handle normal conversation using music or customer agents."""
    messages = state.get("messages", [])
    user_id = state.get("user_id", 1)
    last_msg = state.get("last_user_msg", "").lower()
    
    logger.info(f"[normal_conversation] Handling: {last_msg[:50]}...")
    
    # Check if this is a fresh conversation start after a conversation-ending message
    # This prevents the agent from misinterpreting greetings in context of previous conversations
    is_fresh_start = False
    if messages:
        # Get the last assistant message
        last_assistant_msg = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                last_assistant_msg = msg.content.lower() if hasattr(msg, 'content') else str(msg).lower()
                break
        
        # Check if last assistant message was a conversation-ending message
        conversation_enders = [
            "is there anything else i can help with",
            "let me know if you need anything else",
            "let me know if you change your mind",
            "what else can i help you with",
            "anything else i can help with",
        ]
        
        # Check if current message is a simple greeting
        simple_greetings = ["hi", "hello", "hey", "hi there", "hello there", "hey there"]
        
        if last_assistant_msg and any(ender in last_assistant_msg for ender in conversation_enders):
            if any(greeting == last_msg.strip() for greeting in simple_greetings):
                is_fresh_start = True
                logger.info("[normal_conversation] Detected fresh conversation start after ending message")
    
    # Filter messages if it's a fresh start - only pass the current greeting
    messages_to_use = messages
    if is_fresh_start:
        # Only include the current user message (the greeting)
        last_user_message = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_user_message = msg
                break
        if last_user_message:
            messages_to_use = [last_user_message]
            logger.info("[normal_conversation] Filtered conversation history for fresh start")
    
    # Determine which agent to use based on message content
    # Simple heuristic: if mentions account/email/phone/address -> customer agent
    customer_keywords = ["account", "email", "phone", "address", "profile", "info", "invoice", "purchase", "order"]
    use_customer_agent = any(kw in last_msg for kw in customer_keywords)
    
    logger.info(f"[normal_conversation] Using {'customer' if use_customer_agent else 'music'} agent")
    
    try:
        if use_customer_agent:
            response = customer_agent(messages_to_use, user_id)
        else:
            response = music_agent(messages_to_use, user_id)
        
        response_text = response.content if hasattr(response, 'content') else str(response)
        logger.info(f"[normal_conversation] Response generated: {response_text[:50]}...")
        
        return {
            "messages": [AIMessage(content=response_text)],
            "assistant_messages": add_assistant_message(state, response_text),
        }
    except Exception as e:
        logger.error(f"[normal_conversation] Error: {e}", exc_info=True)
        error_msg = f"I apologize, but I encountered an error: {str(e)}. Please try again."
        return {
            "messages": [AIMessage(content=error_msg)],
            "assistant_messages": add_assistant_message(state, error_msg),
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
    builder.add_node("normal_conversation", normal_conversation)
    builder.add_node("run_email_update_subgraph", run_email_update_subgraph)
    # Add lyrics subgraph directly (not wrapped) so state updates show before interrupts
    builder.add_node("run_lyrics_subgraph", lyrics_subgraph)
    
    # Add edges
    builder.add_edge(START, "ingest_user_message")
    builder.add_edge("ingest_user_message", "route_intent")
    # route_intent uses Command to specify next node
    builder.add_edge("normal_conversation", END)
    builder.add_edge("run_email_update_subgraph", END)
    builder.add_edge("run_lyrics_subgraph", END)
    
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

