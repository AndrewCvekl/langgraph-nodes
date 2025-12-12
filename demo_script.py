#!/usr/bin/env python3
"""Demo script with deterministic test scenarios.

This script runs through the acceptance test scenarios to verify
the bot's behavior without requiring interactive input.

Run with: python demo_script.py
"""

import uuid
import sys
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver

# Add app to path
sys.path.insert(0, ".")

from app.graphs.app_graph import create_app_graph
from app.models.state import get_initial_state


def print_header(title: str):
    """Print a section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_step(step: str):
    """Print a step marker."""
    print(f"\n>>> {step}")


def print_result(result: dict):
    """Print relevant parts of a result."""
    if "__interrupt__" in result and result["__interrupt__"]:
        interrupt = result["__interrupt__"][0]
        value = interrupt.value if hasattr(interrupt, 'value') else interrupt
        print(f"    [INTERRUPT] {value.get('title', 'Unknown')}: {value.get('text', '')}")
        return True
    
    messages = result.get("assistant_messages", [])
    for msg in messages:
        if msg.get("type") == "text":
            print(f"    [BOT] {msg.get('text', '')[:100]}...")
        elif msg.get("type") == "embed":
            print(f"    [EMBED] YouTube: {msg.get('url', '')}")
        elif msg.get("type") == "invoice":
            print(f"    [INVOICE] #{msg.get('invoice_id')} - ${msg.get('total', 0):.2f}")
    
    return False


def run_scenario(name: str, steps: list[tuple[str, Any]]):
    """Run a test scenario.
    
    Args:
        name: Scenario name.
        steps: List of (action, value) tuples.
               action: "user" (send message) or "resume" (resume interrupt)
               value: message text or resume value
    """
    print_header(name)
    
    # Create fresh graph with in-memory checkpointer
    checkpointer = MemorySaver()
    graph = create_app_graph().compile(checkpointer=checkpointer)
    
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    user_id = 1
    
    current_messages = []
    
    for action, value in steps:
        if action == "user":
            print_step(f"User: {value}")
            current_messages.append(HumanMessage(content=value))
            
            result = graph.invoke(
                {
                    "messages": current_messages,
                    "user_id": user_id,
                },
                config,
            )
        elif action == "resume":
            print_step(f"Resume with: {value}")
            result = graph.invoke(Command(resume=value), config)
        else:
            print(f"    [ERROR] Unknown action: {action}")
            continue
        
        is_interrupt = print_result(result)
        
        # Update messages if available
        if result.get("messages"):
            current_messages = result["messages"]
    
    print("\n    [SCENARIO COMPLETE]")


def test_email_update_cancel():
    """Test: Email update flow - user cancels."""
    run_scenario("Email Update - Cancel", [
        ("user", "I want to update my email address"),
        ("resume", "No"),  # Cancel at confirmation
    ])


def test_email_update_success():
    """Test: Email update flow - full success."""
    run_scenario("Email Update - Success", [
        ("user", "update my email"),
        ("resume", "Yes"),      # Confirm send code
        ("resume", "123456"),   # Enter correct code
        ("resume", "new@example.com"),  # Enter new email
    ])


def test_email_update_wrong_code():
    """Test: Email update flow - wrong code then correct."""
    run_scenario("Email Update - Wrong Code Retry", [
        ("user", "change my email please"),
        ("resume", "Yes"),      # Confirm send code
        ("resume", "000000"),   # Wrong code
        ("resume", "111111"),   # Wrong code again
        ("resume", "123456"),   # Correct code
        ("resume", "fixed@example.com"),  # New email
    ])


def test_email_update_too_many_failures():
    """Test: Email update flow - too many wrong codes."""
    run_scenario("Email Update - Too Many Failures", [
        ("user", "I need to change my email"),
        ("resume", "Yes"),      # Confirm send code
        ("resume", "000000"),   # Wrong code 1
        ("resume", "111111"),   # Wrong code 2
        ("resume", "222222"),   # Wrong code 3 - should fail
    ])


def test_lyrics_search_in_catalogue():
    """Test: Lyrics search - song in catalogue, purchase."""
    run_scenario("Lyrics Search - In Catalogue + Purchase", [
        ("user", "What song has the lyrics 'Is this the real life'"),
        ("resume", "Yes"),  # Listen?
        ("resume", "Yes"),  # Buy?
        ("resume", "Yes"),  # Confirm purchase
    ])


def test_lyrics_search_decline_listen():
    """Test: Lyrics search - decline to listen."""
    run_scenario("Lyrics Search - Decline Listen", [
        ("user", "song that goes 'hotel california'"),
        ("resume", "No"),  # Don't want to listen
    ])


def test_lyrics_search_decline_buy():
    """Test: Lyrics search - listen but decline purchase."""
    run_scenario("Lyrics Search - Listen, Decline Buy", [
        ("user", "find song with 'purple haze in my brain'"),
        ("resume", "Yes"),  # Listen
        ("resume", "No"),   # Don't buy
    ])


def test_normal_music_query():
    """Test: Normal music catalogue query."""
    run_scenario("Normal Conversation - Music Query", [
        ("user", "What albums do you have by AC/DC?"),
    ])


def test_normal_account_query():
    """Test: Normal account info query."""
    run_scenario("Normal Conversation - Account Query", [
        ("user", "What email do you have on file for me?"),
    ])


def main():
    """Run all demo scenarios."""
    print("\n" + "#" * 70)
    print("#" + " " * 68 + "#")
    print("#" + "  MUSIC STORE SUPPORT BOT - DEMO SCENARIOS".center(68) + "#")
    print("#" + " " * 68 + "#")
    print("#" * 70)
    
    print("\nThis script demonstrates the bot's behavior with deterministic inputs.")
    print("Each scenario tests a specific flow or edge case.\n")
    
    try:
        # Run test scenarios
        test_email_update_cancel()
        test_email_update_success()
        test_email_update_wrong_code()
        test_email_update_too_many_failures()
        test_lyrics_search_in_catalogue()
        test_lyrics_search_decline_listen()
        test_lyrics_search_decline_buy()
        test_normal_music_query()
        test_normal_account_query()
        
        print_header("ALL SCENARIOS COMPLETED")
        print("\nThe demo script ran all test scenarios successfully.")
        print("Review the output above to verify correct behavior.")
        
        return 0
        
    except Exception as e:
        print(f"\n\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

