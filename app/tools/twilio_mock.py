"""Twilio verification service for phone verification.

Integrates with the Twilio Verify API for sending and checking verification codes.
Falls back to mock mode if Twilio credentials are not configured.
"""

import os
import re
import uuid
import random
import logging
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env file from project root (relative to this file)
# This file is at: app/tools/twilio_mock.py
# Project root is: ../../
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
env_path = os.path.join(project_root, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path, override=False)
    logger.info(f"[Twilio] Loaded .env from: {env_path}")
else:
    # Fallback: try find_dotenv() which searches upward from current directory
    from dotenv import find_dotenv
    found = find_dotenv()
    if found:
        load_dotenv(found, override=False)
        logger.info(f"[Twilio] Loaded .env from: {found}")
    else:
        load_dotenv(override=False)  # Current directory as last resort
        logger.warning(f"[Twilio] .env not found. Tried: {env_path} and current directory")


class TwilioService:
    """Twilio verification service.
    
    Uses the Twilio Verify API for SMS verification.
    Falls back to mock mode if credentials are not configured.
    """
    
    def __init__(self, use_random_codes: bool = False):
        """Initialize the Twilio service.
        
        Args:
            use_random_codes: If True and in mock mode, generate random codes.
                            If False, always use "123456" for easy testing.
        """
        self.use_random_codes = use_random_codes
        
        # Twilio credentials
        self.account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        self.auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        self.verify_service_sid = os.getenv('TWILIO_VERIFY_SERVICE_SID')
        
        # Debug: log which credentials are missing
        missing = []
        if not self.account_sid:
            missing.append('TWILIO_ACCOUNT_SID')
        if not self.auth_token:
            missing.append('TWILIO_AUTH_TOKEN')
        if not self.verify_service_sid:
            missing.append('TWILIO_VERIFY_SERVICE_SID')
        if missing:
            logger.warning(f"[Twilio] Missing env vars: {', '.join(missing)}")
        
        # Check if Twilio is fully configured
        self._client = None
        self.twilio_enabled = all([self.account_sid, self.auth_token, self.verify_service_sid])
        
        if self.twilio_enabled:
            try:
                from twilio.rest import Client
                self._client = Client(self.account_sid, self.auth_token)
                logger.info("[Twilio] Initialized with real API")
            except ImportError:
                logger.warning("[Twilio] twilio package not installed, using mock mode")
                self.twilio_enabled = False
            except Exception as e:
                logger.warning(f"[Twilio] Failed to initialize client: {e}, using mock mode")
                self.twilio_enabled = False
        else:
            logger.info("[Twilio] Credentials not configured, using mock mode")
        
        # Store for mock verifications and phone tracking
        self._verifications: dict[str, dict] = {}
    
    @property
    def is_live(self) -> bool:
        """Check if using real API or mock mode."""
        return self.twilio_enabled and self._client is not None
    
    def _format_phone_number(self, phone: str) -> str:
        """Format phone number to E.164 format required by Twilio."""
        digits = re.sub(r'\D', '', phone)
        
        if phone.startswith('+'):
            return '+' + digits
        if len(digits) == 10:
            return f'+1{digits}'
        if len(digits) == 11 and digits.startswith('1'):
            return f'+{digits}'
        if len(digits) > 10:
            return f'+{digits}'
        return f'+1{digits}'
    
    def _mask_phone(self, phone: str) -> str:
        """Mask phone number for display."""
        return phone[:-4] + '****' if len(phone) > 4 else '****'
    
    def send_code(self, phone: str) -> str:
        """Send a verification code to a phone number.
        
        Args:
            phone: Phone number to send code to.
            
        Returns:
            Verification ID to use when checking the code.
        """
        formatted_phone = self._format_phone_number(phone)
        
        if self.is_live:
            return self._send_code_real(formatted_phone)
        else:
            return self._send_code_mock(formatted_phone)
    
    def _send_code_real(self, phone: str) -> str:
        """Send verification code using Twilio Verify API."""
        try:
            from twilio.base.exceptions import TwilioRestException
            
            verification = self._client.verify.v2.services(
                self.verify_service_sid
            ).verifications.create(
                to=phone,
                channel='sms'
            )
            
            # Store verification info (using SID as verification_id)
            verification_id = verification.sid
            self._verifications[verification_id] = {
                'phone': phone,
                'status': 'pending',
                'created_at': datetime.now(),
                'expires_at': datetime.now() + timedelta(minutes=10),
            }
            
            masked = self._mask_phone(phone)
            logger.info(f"[Twilio] Sent verification to {masked}, status: {verification.status}")
            print(f"📱 Verification code sent to {masked}")
            
            return verification_id
            
        except Exception as e:
            logger.error(f"[Twilio] Failed to send code: {e}")
            # Fall back to mock on error
            return self._send_code_mock(phone)
    
    def _send_code_mock(self, phone: str) -> str:
        """Send mock verification code."""
        verification_id = str(uuid.uuid4())
        
        if self.use_random_codes:
            code = str(random.randint(100000, 999999))
        else:
            code = "123456"
        
        self._verifications[verification_id] = {
            'phone': phone,
            'code': code,
            'status': 'pending',
            'created_at': datetime.now(),
        }
        
        masked = self._mask_phone(phone)
        logger.info(f"[Twilio/Mock] Sent code {code} to {masked}")
        print(f"📱 [Mock] Verification code sent to {masked}: {code}")
        
        return verification_id
    
    def check_code(self, verification_id: str, code: str) -> bool:
        """Check if a verification code is correct.
        
        Args:
            verification_id: ID returned from send_code.
            code: Code entered by the user.
            
        Returns:
            True if the code matches, False otherwise.
        """
        verification = self._verifications.get(verification_id)
        
        if not verification:
            logger.warning(f"[Twilio] Unknown verification ID: {verification_id}")
            return False
        
        if self.is_live and 'code' not in verification:
            # Real Twilio verification - check via API
            return self._check_code_real(verification['phone'], code, verification_id)
        else:
            # Mock verification - check stored code
            return self._check_code_mock(verification_id, code)
    
    def _check_code_real(self, phone: str, code: str, verification_id: str) -> bool:
        """Verify code using Twilio Verify API."""
        try:
            verification_check = self._client.verify.v2.services(
                self.verify_service_sid
            ).verification_checks.create(
                to=phone,
                code=code.strip()
            )
            
            is_valid = verification_check.status == 'approved'
            
            if is_valid:
                self._verifications[verification_id]['status'] = 'verified'
                logger.info("[Twilio] Code verified successfully")
            else:
                logger.info(f"[Twilio] Invalid code, status: {verification_check.status}")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"[Twilio] Verification check failed: {e}")
            return False
    
    def _check_code_mock(self, verification_id: str, code: str) -> bool:
        """Check mock verification code."""
        verification = self._verifications.get(verification_id)
        expected = verification.get('code') if verification else None
        
        if expected is None:
            return False
        
        is_valid = code.strip() == expected
        
        if is_valid:
            del self._verifications[verification_id]
            logger.info("[Twilio/Mock] Code verified successfully")
        else:
            logger.info(f"[Twilio/Mock] Invalid code: expected {expected}, got {code}")
        
        return is_valid
    
    def get_pending_code(self, verification_id: str) -> Optional[str]:
        """Get the pending code for a verification (mock mode only, for testing).
        
        Args:
            verification_id: Verification ID.
            
        Returns:
            The code (if mock mode), or None.
        """
        verification = self._verifications.get(verification_id)
        return verification.get('code') if verification else None


# Global instance for convenience
_twilio: TwilioService | None = None


def get_twilio() -> TwilioService:
    """Get the global Twilio service instance."""
    global _twilio
    if _twilio is None:
        _twilio = TwilioService()
    return _twilio
