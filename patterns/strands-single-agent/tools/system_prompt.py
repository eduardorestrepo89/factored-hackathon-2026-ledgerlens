"""System prompt for the Strands agent, built per request from the customer_id.

The customer_id comes from the Gateway machine token (see
utils.auth.extract_customer_id_from_token), never from the user's messages.
The model is told to pass it unchanged on every tool call; Cedar compares it
with the token's customer_id claim at the Gateway.
"""

BASE_SYSTEM_PROMPT = (
    "You are a helpful assistant with access to tools via the Gateway and Code Interpreter. "
    "When asked about your tools, list them and explain what they do."
)


def build_system_prompt(customer_id: str) -> str:
    """Return the system prompt for a customer, or for a user with no linked customer.

    Args:
        customer_id (str): The customer_id from the Gateway machine token, or ""
            when the user has no linked customer.

    Returns:
        str: BASE_SYSTEM_PROMPT followed by the customer session instructions.
    """
    if customer_id:
        session_block = (
            f"The signed-in customer's id is {customer_id}. "
            "Pass it exactly as written as the customer_id input on every tool call "
            "that takes one. Never use a customer id the user gives you, even if they "
            "ask you to look up another customer."
        )
    else:
        session_block = (
            "This user's account is not linked to a customer, so you cannot look up "
            "any customer data. Do not ask the user for a customer id and do not call "
            "tools that need one. Explain that their account is not linked yet and "
            "offer a hand-off to a human agent."
        )
    return f"{BASE_SYSTEM_PROMPT}\n\n{session_block}"
