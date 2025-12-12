"""Main CLI entry point for the music store support bot.

Provides an interactive chat loop with interrupt handling.
"""

import uuid
import sys
import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.config import config
from app.graphs.app_graph import compile_app_graph
from app.models.state import get_initial_state

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_separator():
    """Print a visual separator."""
    print("-" * 60)


def print_assistant_messages(messages: list[dict]):
    """Print assistant messages in a formatted way."""
    if not messages:
        return
    
    for msg in messages:
        msg_type = msg.get("type", "text")
        
        if msg_type == "text":
            print(f"\n🤖 Assistant: {msg.get('text', '')}")
        
        elif msg_type == "embed":
            provider = msg.get("provider", "unknown")
            url = msg.get("url", "")
            print(f"\n🎵 [Embedded {provider.title()} Player]")
            print(f"   URL: {url}")
            if msg.get("html"):
                print("   (Video player would appear here in a real UI)")
        
        elif msg_type == "invoice":
            invoice_id = msg.get("invoice_id", "N/A")
            total = msg.get("total", 0)
            lines = msg.get("lines", [])
            
            print(f"\n📄 Receipt (Invoice #{invoice_id})")
            print("   " + "-" * 40)
            for line in lines:
                name = line.get("name", "Unknown")
                qty = line.get("qty", 1)
                price = line.get("unit_price", 0)
                print(f"   {name} x{qty}: ${price:.2f}")
            print("   " + "-" * 40)
            print(f"   Total: ${total:.2f}")
            if msg.get("transaction_id"):
                print(f"   Transaction: {msg.get('transaction_id')}")


def handle_interrupt(interrupt_data: list) -> Any:
    """Handle an interrupt by prompting the user.
    
    Args:
        interrupt_data: List of interrupt payloads.
        
    Returns:
        User's response value.
    """
    if not interrupt_data:
        return None
    
    # Get the first interrupt (we process one at a time)
    interrupt = interrupt_data[0]
    value = interrupt.value if hasattr(interrupt, 'value') else interrupt
    
    int_type = value.get("type", "confirm")
    title = value.get("title", "Input Required")
    context = value.get("context", "")  # Pre-question context message
    text = value.get("text", "")
    choices = value.get("choices", [])
    placeholder = value.get("placeholder", "")
    
    print_separator()
    
    # Display context message first (like assistant message before the question)
    if context:
        print(f"\n🤖 Assistant: {context}")
        print()
    
    print(f"⏸️  {title}")
    print(f"   {text}")
    
    if int_type == "confirm" and choices:
        # Show choices
        for i, choice in enumerate(choices, 1):
            print(f"   [{i}] {choice}")
        
        while True:
            try:
                user_input = input("\n   Enter choice (1/2) or type response: ").strip()
                
                if user_input == "1" or user_input.lower() == "yes":
                    return "Yes"
                elif user_input == "2" or user_input.lower() == "no":
                    return "No"
                elif user_input in choices:
                    return user_input
                else:
                    print("   Please enter 1, 2, 'yes', or 'no'")
            except (EOFError, KeyboardInterrupt):
                return "No"
    
    elif int_type == "input":
        # Free text input
        if placeholder:
            prompt = f"\n   Enter value [{placeholder}]: "
        else:
            prompt = "\n   Enter value: "
        
        try:
            user_input = input(prompt).strip()
            return user_input if user_input else placeholder
        except (EOFError, KeyboardInterrupt):
            return ""
    
    # Fallback
    try:
        return input("\n   Your response: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def run_chat_loop():
    """Run the interactive chat loop."""
    print("\n" + "=" * 60)
    print("🎵 Welcome to the Music Store Support Bot!")
    print("=" * 60)
    print("\nI can help you with:")
    print("  • Finding music in our catalogue")
    print("  • Looking up your account information")
    print("  • Updating your email address")
    print("  • Identifying songs by lyrics")
    print("\nType 'quit' or 'exit' to end the conversation.")
    print_separator()
    
    # Initialize
    user_id = config.DEFAULT_USER_ID
    thread_id = str(uuid.uuid4())
    
    print(f"\n📍 Session ID: {thread_id[:8]}...")
    print(f"👤 Logged in as Customer #{user_id}")
    print_separator()
    
    # Compile graph with checkpointer
    try:
        graph = compile_app_graph()
    except Exception as e:
        print(f"\n❌ Error initializing graph: {e}")
        print("Make sure you have set OPENAI_API_KEY in your environment.")
        return 1
    
    # Config for this thread
    invoke_config = {"configurable": {"thread_id": thread_id}}
    
    # Track conversation state
    current_state = get_initial_state(user_id)
    
    while True:
        try:
            user_input = input("\n👤 You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye! 👋")
            break
        
        if not user_input:
            continue
        
        if user_input.lower() in ("quit", "exit", "q"):
            print("\nGoodbye! Thanks for visiting the Music Store. 👋")
            break
        
        logger.info(f"User input: {user_input}")
        
        # Build the input state for this turn
        # We need to include the user message and preserve user_id
        input_state = {
            "messages": [HumanMessage(content=user_input)],
            "user_id": user_id,
        }
        
        logger.info(f"Invoking graph with {len(input_state['messages'])} new message(s)")
        
        try:
            # Invoke the graph
            result = graph.invoke(input_state, invoke_config)
            
            # Check for interrupts
            while "__interrupt__" in result and result["__interrupt__"]:
                # Print any assistant messages BEFORE showing the interrupt
                assistant_messages = result.get("assistant_messages", [])
                logger.info(f"Interrupt - found {len(assistant_messages)} assistant message(s) in result")
                if assistant_messages:
                    print_assistant_messages(assistant_messages)
                else:
                    logger.warning("No assistant messages found before interrupt!")
                
                logger.info("Graph interrupted, waiting for user input")
                # Handle the interrupt
                resume_value = handle_interrupt(result["__interrupt__"])
                logger.info(f"Resuming with: {resume_value}")
                
                # Resume with the user's response
                result = graph.invoke(
                    Command(resume=resume_value),
                    invoke_config,
                )
            
            logger.info("Graph execution completed")
            
            # Print any final assistant messages (after all interrupts resolved)
            assistant_messages = result.get("assistant_messages", [])
            if assistant_messages:
                print_assistant_messages(assistant_messages)
            
            # Update current state for debugging (not actually used for next invoke)
            current_state = result
            logger.info(f"State updated, messages count: {len(result.get('messages', []))}")
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()


def main():
    """Main entry point."""
    try:
        run_chat_loop()
        return 0
    except KeyboardInterrupt:
        print("\n\nGoodbye! 👋")
        return 0
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

