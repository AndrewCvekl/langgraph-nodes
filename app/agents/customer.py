"""Customer agent for handling account info queries.

Handles questions about customer account information.
Note: Email updates are handled by a separate subgraph, not this agent.
"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, SystemMessage, AIMessage
from langchain_core.tools import tool

from app.config import config
from app.db import get_engine
from app.tools.db_tools import get_customer_info, get_customer_invoices, get_customer_contact


CUSTOMER_SYSTEM_PROMPT = """You are a helpful customer service assistant for a music store.

Your job is to help customers with questions about their account information.

You have access to tools to look up customer data:
- get_account_info: Get the customer's full account information
- get_purchase_history: Get the customer's recent purchases/invoices

IMPORTANT SECURITY RULES:
- You can ONLY access information for the current logged-in user
- Never reveal information about other customers
- The customer ID is provided automatically - don't ask for it

For email updates/changes, let the customer know they'll need to go through a verification process.
Do not try to update emails directly - that's handled by a different system.

Be helpful and friendly. Protect customer privacy."""


def make_customer_tools(user_id: int):
    """Create customer tools bound to a specific user ID.
    
    This ensures the customer can only access their own data.
    """
    
    @tool
    def get_account_info() -> str:
        """Get the current customer's account information.
        
        Returns their name, email, phone, and address on file.
        """
        engine = get_engine()
        try:
            info = get_customer_info(engine, user_id)
            return (
                f"Account Information:\n"
                f"- Name: {info['FirstName']} {info['LastName']}\n"
                f"- Email: {info['Email']}\n"
                f"- Phone: {info['Phone']}\n"
                f"- Address: {info['Address']}, {info['City']}, {info['State']} {info['PostalCode']}\n"
                f"- Country: {info['Country']}"
            )
        except ValueError as e:
            return f"Error retrieving account info: {str(e)}"
    
    @tool
    def get_purchase_history() -> str:
        """Get the current customer's recent purchase history.
        
        Returns their recent invoices with dates and totals.
        """
        engine = get_engine()
        try:
            invoices = get_customer_invoices(engine, user_id)
            if not invoices:
                return "No purchase history found."
            
            result = f"Recent Purchases ({len(invoices)} total):\n"
            for inv in invoices[:5]:
                result += f"- Invoice #{inv['InvoiceId']} on {inv['InvoiceDate']}: ${inv['Total']:.2f}\n"
            
            if len(invoices) > 5:
                result += f"... and {len(invoices) - 5} more purchases."
            
            return result
        except Exception as e:
            return f"Error retrieving purchase history: {str(e)}"
    
    return [get_account_info, get_purchase_history]


def get_customer_model() -> ChatOpenAI:
    """Get the LLM configured for customer queries."""
    return ChatOpenAI(
        model=config.OPENAI_MODEL,
        temperature=0.3,
        streaming=True,
    )


def customer_agent(messages: list[BaseMessage], user_id: int) -> AIMessage:
    """Run the customer agent to answer account queries.
    
    Args:
        messages: Conversation messages.
        user_id: The authenticated user's ID.
        
    Returns:
        AI response message.
    """
    model = get_customer_model()
    tools = make_customer_tools(user_id)
    model_with_tools = model.bind_tools(tools)
    
    # Prepend system prompt
    full_messages = [SystemMessage(content=CUSTOMER_SYSTEM_PROMPT)] + messages
    
    # First call - may include tool calls
    response = model_with_tools.invoke(full_messages)
    
    # If there are tool calls, execute them and get final response
    if response.tool_calls:
        tool_messages = []
        tools_by_name = {t.name: t for t in tools}
        
        for tool_call in response.tool_calls:
            tool_fn = tools_by_name.get(tool_call["name"])
            if tool_fn:
                from langchain_core.messages import ToolMessage
                result = tool_fn.invoke(tool_call["args"])
                tool_messages.append(
                    ToolMessage(content=result, tool_call_id=tool_call["id"])
                )
        
        # Get final response with tool results
        full_messages = full_messages + [response] + tool_messages
        response = model.invoke(full_messages)
    
    return response

