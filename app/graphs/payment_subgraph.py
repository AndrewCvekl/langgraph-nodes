"""Payment subgraph for processing purchases.

This subgraph handles the payment flow:
1. Build quote from items
2. Confirm purchase
3. Execute charge
4. Commit invoice to database
5. Render receipt

Uses interrupts for payment confirmation.
Implements idempotency via payment intent IDs.
"""

import uuid
from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command

from app.models.state import AppState
from app.db import get_engine
from app.tools.db_tools import create_invoice_for_track
from app.tools.payment_mock import get_payment


def add_assistant_message(state: AppState, msg: dict | str) -> list[dict]:
    """Helper to add a message to assistant_messages."""
    current = state.get("assistant_messages", []) or []
    if isinstance(msg, str):
        msg = {"type": "text", "text": msg}
    return current + [msg]


# Node P0: Build quote
def payment_build_quote(state: AppState) -> dict:
    """Build a payment quote from items."""
    payment = state.get("payment", {})
    items = payment.get("items", [])
    
    if not items:
        return {
            "payment": {
                **payment,
                "status": "failed",
                "error": "No items to purchase",
            },
            "assistant_messages": add_assistant_message(
                state, "Sorry, there was an error with your order. No items found."
            ),
        }
    
    # Calculate total
    total = sum(item.get("unit_price", 0) * item.get("qty", 1) for item in items)
    
    # Generate payment intent ID for idempotency
    payment_intent_id = f"pi_{uuid.uuid4().hex[:16]}"
    
    # Format items for display
    items_display = ", ".join(
        f"{item.get('name', 'Unknown')} (${item.get('unit_price', 0):.2f})"
        for item in items
    )
    
    return {
        "payment": {
            **payment,
            "status": "draft",
            "payment_intent_id": payment_intent_id,
            "total": total,
        },
        "assistant_messages": add_assistant_message(
            state, f"Order summary: {items_display}\n\nTotal: ${total:.2f}"
        ),
    }


# Node P1: Interrupt to confirm payment
def payment_interrupt_confirm(state: AppState) -> Command[Literal["payment_execute_charge", "payment_cancel"]]:
    """Interrupt to confirm the purchase."""
    payment = state.get("payment", {})
    total = payment.get("total", 0)
    
    decision = interrupt({
        "type": "confirm",
        "title": "Confirm Purchase",
        "text": f"Confirm purchase for ${total:.2f}?",
        "choices": ["Yes", "No"],
    })
    
    if decision == "Yes":
        return Command(
            update={
                "payment": {
                    **payment,
                    "status": "confirmed",
                },
            },
            goto="payment_execute_charge",
        )
    else:
        return Command(goto="payment_cancel")


# Node P2: Execute charge
def payment_execute_charge(state: AppState) -> Command[Literal["payment_commit_invoice", "payment_failed"]]:
    """Execute the payment charge."""
    payment = state.get("payment", {})
    user_id = state.get("user_id")
    
    intent_id = payment.get("payment_intent_id", "")
    total = payment.get("total", 0)
    items = payment.get("items", [])
    
    payment_service = get_payment()
    result = payment_service.charge(intent_id, total, user_id, items)
    
    if result.get("status") == "succeeded":
        return Command(
            update={
                "payment": {
                    **payment,
                    "status": "succeeded",
                    "transaction_id": result.get("transaction_id", ""),
                },
            },
            goto="payment_commit_invoice",
        )
    else:
        return Command(
            update={
                "payment": {
                    **payment,
                    "status": "failed",
                    "error": result.get("reason", "Payment failed"),
                },
            },
            goto="payment_failed",
        )


# Node P3: Commit invoice to database
def payment_commit_invoice(state: AppState) -> dict:
    """Create invoice in the database."""
    payment = state.get("payment", {})
    user_id = state.get("user_id")
    items = payment.get("items", [])
    
    engine = get_engine()
    
    try:
        # For simplicity, handle first item (could extend for multiple)
        if items:
            item = items[0]
            invoice_result = create_invoice_for_track(
                engine,
                customer_id=user_id,
                track_id=item.get("track_id"),
                unit_price=item.get("unit_price", 0.99),
                qty=item.get("qty", 1),
            )
            
            return {
                "payment": {
                    **payment,
                    "invoice_id": invoice_result.get("invoice_id"),
                },
            }
    except Exception as e:
        # Log error but don't fail - payment already succeeded
        print(f"Warning: Failed to create invoice: {e}")
    
    return {}


# Node P4: Render receipt
def payment_render_receipt(state: AppState) -> dict:
    """Render the purchase receipt."""
    payment = state.get("payment", {})
    items = payment.get("items", [])
    total = payment.get("total", 0)
    invoice_id = payment.get("invoice_id", 0)
    transaction_id = payment.get("transaction_id", "")
    
    # Build invoice message
    lines = []
    for item in items:
        lines.append({
            "name": item.get("name", "Unknown"),
            "qty": item.get("qty", 1),
            "unit_price": item.get("unit_price", 0),
        })
    
    messages = state.get("assistant_messages", []) or []
    messages = messages + [
        {
            "type": "invoice",
            "invoice_id": invoice_id,
            "transaction_id": transaction_id,
            "total": total,
            "lines": lines,
        },
        {
            "type": "text",
            "text": "Purchase complete! Thank you for your order.",
        },
    ]
    
    return {
        "assistant_messages": messages,
    }


# Node P5: Cancel payment
def payment_cancel(state: AppState) -> dict:
    """Handle payment cancellation."""
    payment = state.get("payment", {})
    
    return {
        "payment": {
            **payment,
            "status": "cancelled",
        },
        "assistant_messages": add_assistant_message(
            state, "No problem! Purchase cancelled. Let me know if you change your mind."
        ),
    }


# Node P6: Payment failed
def payment_failed(state: AppState) -> dict:
    """Handle payment failure."""
    payment = state.get("payment", {})
    error = payment.get("error", "Unknown error")
    
    return {
        "assistant_messages": add_assistant_message(
            state, f"Sorry, the payment could not be processed: {error}. Please try again."
        ),
    }


# Node P7: Done (terminal node)
def payment_done(state: AppState) -> dict:
    """Terminal node for payment flow."""
    return {}


def create_payment_subgraph() -> StateGraph:
    """Create the payment subgraph."""
    builder = StateGraph(AppState)
    
    # Add all nodes
    builder.add_node("payment_build_quote", payment_build_quote)
    builder.add_node("payment_interrupt_confirm", payment_interrupt_confirm)
    builder.add_node("payment_execute_charge", payment_execute_charge)
    builder.add_node("payment_commit_invoice", payment_commit_invoice)
    builder.add_node("payment_render_receipt", payment_render_receipt)
    builder.add_node("payment_cancel", payment_cancel)
    builder.add_node("payment_failed", payment_failed)
    builder.add_node("payment_done", payment_done)
    
    # Add edges
    builder.set_entry_point("payment_build_quote")
    builder.add_edge("payment_build_quote", "payment_interrupt_confirm")
    builder.add_edge("payment_commit_invoice", "payment_render_receipt")
    builder.add_edge("payment_render_receipt", "payment_done")
    builder.add_edge("payment_cancel", "payment_done")
    builder.add_edge("payment_failed", "payment_done")
    builder.add_edge("payment_done", END)
    
    # Note: payment_interrupt_confirm and payment_execute_charge use Command
    
    return builder


# Compile the subgraph (without checkpointer - parent provides it)
payment_subgraph = create_payment_subgraph().compile()

