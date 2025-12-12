"""Mock payment service for processing purchases.

This is a mock implementation for demo purposes.
In production, this would integrate with Stripe or another payment processor.
"""

import uuid
import logging
from typing import Literal

logger = logging.getLogger(__name__)


class PaymentMock:
    """Mock payment service.
    
    Simulates processing payments. Implements idempotency by tracking
    payment intents - calling charge with the same intent_id returns
    the same result.
    """
    
    def __init__(self, failure_rate: float = 0.0):
        """Initialize the mock payment service.
        
        Args:
            failure_rate: Probability of payment failure (0.0 to 1.0).
                         Default 0.0 means all payments succeed.
        """
        self.failure_rate = failure_rate
        # Track processed payments for idempotency: intent_id -> result
        self._processed: dict[str, dict] = {}
    
    def charge(
        self,
        intent_id: str,
        amount: float,
        customer_id: int,
        items: list[dict]
    ) -> dict:
        """Process a payment charge.
        
        This method is idempotent: calling with the same intent_id
        returns the same result without charging again.
        
        Args:
            intent_id: Unique payment intent ID.
            amount: Amount to charge.
            customer_id: Customer making the purchase.
            items: List of items being purchased.
            
        Returns:
            Dict with status, transaction_id, and optional reason.
        """
        # Check for existing processed payment (idempotency)
        if intent_id in self._processed:
            logger.info(f"[PaymentMock] Returning cached result for intent {intent_id}")
            return self._processed[intent_id]
        
        # Simulate payment processing
        import random
        
        if random.random() < self.failure_rate:
            result = {
                "status": "failed",
                "transaction_id": "",
                "reason": "Card declined (simulated failure)",
            }
        else:
            transaction_id = f"txn_{uuid.uuid4().hex[:12]}"
            result = {
                "status": "succeeded",
                "transaction_id": transaction_id,
                "reason": "",
            }
            logger.info(
                f"[PaymentMock] Payment succeeded: ${amount:.2f} "
                f"(txn: {transaction_id})"
            )
        
        # Store for idempotency
        self._processed[intent_id] = result
        
        return result
    
    def create_payment_intent(
        self,
        amount: float,
        customer_id: int,
        items: list[dict]
    ) -> str:
        """Create a new payment intent.
        
        Args:
            amount: Amount to charge.
            customer_id: Customer making the purchase.
            items: List of items being purchased.
            
        Returns:
            Payment intent ID.
        """
        intent_id = f"pi_{uuid.uuid4().hex[:16]}"
        logger.info(f"[PaymentMock] Created payment intent: {intent_id} for ${amount:.2f}")
        return intent_id
    
    def get_payment_status(self, intent_id: str) -> Literal["pending", "succeeded", "failed"] | None:
        """Get the status of a payment intent.
        
        Args:
            intent_id: Payment intent ID.
            
        Returns:
            Status string or None if not found.
        """
        result = self._processed.get(intent_id)
        if result is None:
            return "pending"
        return result.get("status")
    
    def refund(self, transaction_id: str, amount: float | None = None) -> dict:
        """Process a refund (mock implementation).
        
        Args:
            transaction_id: Original transaction ID.
            amount: Amount to refund (None for full refund).
            
        Returns:
            Refund result dict.
        """
        refund_id = f"ref_{uuid.uuid4().hex[:12]}"
        logger.info(f"[PaymentMock] Refund processed: {refund_id}")
        
        return {
            "status": "succeeded",
            "refund_id": refund_id,
            "amount": amount,
        }


# Global instance for convenience
_payment: PaymentMock | None = None


def get_payment() -> PaymentMock:
    """Get the global PaymentMock instance."""
    global _payment
    if _payment is None:
        _payment = PaymentMock()
    return _payment

