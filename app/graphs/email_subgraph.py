"""Email update subgraph with phone verification.

This subgraph handles the email update flow:
1. Confirm sending verification code
2. Send code via Twilio
3. Verify code (with retry logic)
4. Get new email address
5. Update database

Uses interrupts for user confirmations and input.
"""

import re
from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command

from app.models.state import AppState
from app.db import get_engine
from app.tools.db_tools import get_customer_contact, update_customer_email
from app.tools.twilio_mock import get_twilio


def add_assistant_message(state: AppState, text: str) -> list[dict]:
    """Helper to add a text message to assistant_messages."""
    current = state.get("assistant_messages", []) or []
    return current + [{"type": "text", "text": text}]


# Node A0: Initialize email flow
def email_init(state: AppState) -> dict:
    """Initialize the email update flow by fetching current contact info."""
    user_id = state.get("user_id")
    if not user_id:
        return {
            "email_flow": {
                "status": "failed",
                "error": "No user ID provided",
            },
            "assistant_messages": add_assistant_message(
                state, "Sorry, I couldn't identify your account. Please try again."
            ),
        }
    
    engine = get_engine()
    try:
        contact = get_customer_contact(engine, user_id)
    except ValueError as e:
        return {
            "email_flow": {
                "status": "failed",
                "error": str(e),
            },
            "assistant_messages": add_assistant_message(
                state, "Sorry, I couldn't find your account information."
            ),
        }
    
    phone = contact.get("Phone", "")
    email = contact.get("Email", "")
    
    # Mask phone for display
    phone_display = f"***{phone[-4:]}" if len(phone) >= 4 else "****"
    
    return {
        "email_flow": {
            "status": "confirm_send",
            "current_email": email,
            "phone": phone,
            "code_attempts_left": 3,
            "verification_id": "",
            "last_code_entered": "",
            "proposed_email": "",
            "error": "",
        },
        "assistant_messages": add_assistant_message(
            state,
            f"I can update your email address. For security, I'll need to verify "
            f"using the phone number on file ending in {phone_display}. "
            f"Would you like me to send a verification code?"
        ),
    }


# Node A1: Interrupt to confirm sending code
def email_interrupt_confirm_send(state: AppState) -> Command[Literal["email_send_code", "email_cancel"]]:
    """Interrupt to confirm sending verification code."""
    decision = interrupt({
        "type": "confirm",
        "title": "Send Verification Code",
        "text": "Send verification code to the phone number on file?",
        "choices": ["Yes", "No"],
    })
    
    if decision == "Yes":
        return Command(goto="email_send_code")
    else:
        return Command(goto="email_cancel")


# Node A2: Send verification code
def email_send_code(state: AppState) -> dict:
    """Send verification code via Twilio."""
    phone = state.get("email_flow", {}).get("phone", "")
    
    twilio = get_twilio()
    verification_id = twilio.send_code(phone)
    
    return {
        "email_flow": {
            **state.get("email_flow", {}),
            "status": "await_code",
            "verification_id": verification_id,
        },
        "assistant_messages": add_assistant_message(
            state, "I've sent a verification code to your phone. Please enter the 6-digit code."
        ),
    }


# Node A3: Interrupt to enter code
def email_interrupt_enter_code(state: AppState) -> Command[Literal["email_check_code"]]:
    """Interrupt to get verification code from user."""
    email_flow = state.get("email_flow", {})
    attempts_left = email_flow.get("code_attempts_left", 3)
    
    # Check if this is a retry after a failed attempt
    # Initial attempts_left is 3, so if it's less than 3, there was a failed attempt
    is_retry = attempts_left < 3
    
    if is_retry:
        # Show error context and remaining attempts
        interrupt_data = {
            "type": "input",
            "title": "Enter Verification Code",
            "context": f"Incorrect code. {attempts_left} attempt(s) left.",
            "text": "Please enter the 6-digit verification code sent to your phone.",
            "placeholder": "123456",
        }
    else:
        # First attempt - no error context
        interrupt_data = {
            "type": "input",
            "title": "Enter Verification Code",
            "text": "Please enter the 6-digit verification code sent to your phone.",
            "placeholder": "123456",
        }
    
    code = interrupt(interrupt_data)
    
    # Store the entered code and proceed to check
    return Command(
        update={
            "email_flow": {
                **email_flow,
                "last_code_entered": code,
            },
        },
        goto="email_check_code",
    )


# Node A4: Check verification code
def email_check_code(state: AppState) -> Command[Literal["email_interrupt_new_email", "email_interrupt_enter_code", "email_failed"]]:
    """Check the verification code."""
    email_flow = state.get("email_flow", {})
    verification_id = email_flow.get("verification_id", "")
    code = email_flow.get("last_code_entered", "")
    attempts_left = email_flow.get("code_attempts_left", 0)
    
    twilio = get_twilio()
    is_valid = twilio.check_code(verification_id, code)
    
    if is_valid:
        return Command(
            update={
                "email_flow": {
                    **email_flow,
                    "status": "await_new_email",
                },
                "assistant_messages": add_assistant_message(
                    state, "Code verified! What's your new email address?"
                ),
            },
            goto="email_interrupt_new_email",
        )
    else:
        new_attempts = attempts_left - 1
        
        if new_attempts > 0:
            return Command(
                update={
                    "email_flow": {
                        **email_flow,
                        "code_attempts_left": new_attempts,
                    },
                    "assistant_messages": add_assistant_message(
                        state,
                        f"Incorrect code. {new_attempts} attempt(s) left."
                    ),
                },
                goto="email_interrupt_enter_code",
            )
        else:
            return Command(
                update={
                    "email_flow": {
                        **email_flow,
                        "code_attempts_left": 0,
                        "error": "Too many failed attempts",
                    },
                },
                goto="email_failed",
            )


# Node A5: Interrupt to get new email
def email_interrupt_new_email(state: AppState) -> Command[Literal["email_update_db"]]:
    """Interrupt to get the new email address from user."""
    new_email = interrupt({
        "type": "input",
        "title": "New Email Address",
        "text": "Please enter your new email address.",
        "placeholder": "newemail@example.com",
    })
    
    return Command(
        update={
            "email_flow": {
                **state.get("email_flow", {}),
                "proposed_email": new_email,
            },
        },
        goto="email_update_db",
    )


# Node A6: Update email in database
def email_update_db(state: AppState) -> Command[Literal["email_done", "email_interrupt_new_email"]]:
    """Validate and update the email in the database."""
    email_flow = state.get("email_flow", {})
    proposed_email = email_flow.get("proposed_email", "")
    user_id = state.get("user_id")
    
    # Simple email validation
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(email_pattern, proposed_email):
        return Command(
            update={
                "assistant_messages": add_assistant_message(
                    state,
                    f"'{proposed_email}' doesn't look like a valid email address. Please try again."
                ),
            },
            goto="email_interrupt_new_email",
        )
    
    # Update in database
    engine = get_engine()
    try:
        update_customer_email(engine, user_id, proposed_email)
    except Exception as e:
        return Command(
            update={
                "email_flow": {
                    **email_flow,
                    "status": "failed",
                    "error": str(e),
                },
                "assistant_messages": add_assistant_message(
                    state, f"Sorry, there was an error updating your email: {str(e)}"
                ),
            },
            goto="email_done",
        )
    
    return Command(
        update={
            "email_flow": {
                **email_flow,
                "status": "done",
            },
            "assistant_messages": add_assistant_message(
                state, f"Done! Your email has been updated to {proposed_email}."
            ),
        },
        goto="email_done",
    )


# Node A7: Cancel flow
def email_cancel(state: AppState) -> dict:
    """Handle cancellation of email update flow."""
    return {
        "email_flow": {
            **state.get("email_flow", {}),
            "status": "cancelled",
        },
        "assistant_messages": add_assistant_message(
            state, "No problem! Email update cancelled. What else can I help you with?"
        ),
    }


# Node A8: Failed flow
def email_failed(state: AppState) -> dict:
    """Handle failure of email update flow."""
    error = state.get("email_flow", {}).get("error", "verification failed")
    
    return {
        "email_flow": {
            **state.get("email_flow", {}),
            "status": "failed",
        },
        "assistant_messages": add_assistant_message(
            state,
            f"Sorry, the email update could not be completed: {error}. "
            "Please try again later or contact support."
        ),
    }


# Node A9: Done (terminal node)
def email_done(state: AppState) -> dict:
    """Terminal node for email flow."""
    # Just pass through - state already updated by previous nodes
    return {}


def create_email_subgraph() -> StateGraph:
    """Create the email update subgraph."""
    builder = StateGraph(AppState)
    
    # Add all nodes
    builder.add_node("email_init", email_init)
    builder.add_node("email_interrupt_confirm_send", email_interrupt_confirm_send)
    builder.add_node("email_send_code", email_send_code)
    builder.add_node("email_interrupt_enter_code", email_interrupt_enter_code)
    builder.add_node("email_check_code", email_check_code)
    builder.add_node("email_interrupt_new_email", email_interrupt_new_email)
    builder.add_node("email_update_db", email_update_db)
    builder.add_node("email_cancel", email_cancel)
    builder.add_node("email_failed", email_failed)
    builder.add_node("email_done", email_done)
    
    # Add edges
    builder.set_entry_point("email_init")
    builder.add_edge("email_init", "email_interrupt_confirm_send")
    builder.add_edge("email_send_code", "email_interrupt_enter_code")
    builder.add_edge("email_cancel", "email_done")
    builder.add_edge("email_failed", "email_done")
    builder.add_edge("email_done", END)
    
    # Note: email_interrupt_confirm_send, email_interrupt_enter_code, 
    # email_check_code, email_interrupt_new_email, email_update_db
    # use Command to specify their next nodes
    
    return builder


# Compile the subgraph (without checkpointer - parent provides it)
email_subgraph = create_email_subgraph().compile()

