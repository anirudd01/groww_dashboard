"""Singleton GrowwAPI authentication client for session management."""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class GrowwAPIClient:
    """
    Singleton authentication client for Groww API.
    Authenticates ONCE per session and provides reusable GrowwAPI instance.
    """
    _instance = None
    _lock = {}  # Simple lock mechanism (replace with threading.Lock for async)

    def __init__(
        self,
        api_key: Optional[str] = None,
        totp_secret: Optional[str] = None,
        api_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        auth_mode: Optional[str] = None
    ):
        self.api_key = api_key or os.getenv("GROWW_API_KEY")
        self.totp_secret = totp_secret or os.getenv("GROWW_TOTP_SECRET")
        self.api_secret = api_secret or os.getenv("GROWW_API_SECRET")
        self.access_token = access_token or os.getenv("GROWW_ACCESS_TOKEN")
        self.auth_mode = (auth_mode or os.getenv("GROWW_AUTH_MODE", "TOTP")).upper()

        self.session = None
        self.auth_error = None
        self._authenticate()

    @classmethod
    def get_instance(cls, **kwargs) -> "GrowwAPIClient":
        """Get singleton instance. Creates one on first call."""
        if cls._instance is None:
            cls._instance = cls(**kwargs)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset singleton (for testing/re-auth)."""
        cls._instance = None

    def _authenticate(self):
        """Authenticates with Groww API based on selected flow."""
        try:
            from growwapi import GrowwAPI

            # 1. Direct access token provided
            if self.access_token and self.access_token.strip():
                self.session = GrowwAPI(self.access_token.strip())
                logger.info("✓ Authenticated using direct access token")
                return

            # 2. TOTP flow (Recommended)
            if self.auth_mode == "TOTP":
                if not self.api_key or not self.totp_secret:
                    self.auth_error = "GROWW_API_KEY (TOTP Token) or GROWW_TOTP_SECRET is missing."
                    return

                import pyotp
                totp_gen = pyotp.TOTP(self.totp_secret.replace(" ", "").strip())
                current_totp = totp_gen.now()
                token = GrowwAPI.get_access_token(api_key=self.api_key.strip(), totp=current_totp)
                self.access_token = token
                self.session = GrowwAPI(token)
                logger.info("✓ Authenticated using TOTP flow")
                return

            # 3. API Key and Secret flow
            if self.auth_mode in ("API_KEY", "SECRET"):
                if not self.api_key or not self.api_secret:
                    self.auth_error = "GROWW_API_KEY or GROWW_API_SECRET is missing."
                    return

                token = GrowwAPI.get_access_token(api_key=self.api_key.strip(), secret=self.api_secret.strip())
                self.access_token = token
                self.session = GrowwAPI(token)
                logger.info("✓ Authenticated using API Key & Secret flow")
                return

            self.auth_error = f"Unsupported auth mode: {self.auth_mode}"

        except ImportError as e:
            self.auth_error = f"Missing library: {e}. Run 'pip install growwapi pyotp'"
        except Exception as e:
            self.auth_error = f"Authentication failed: {str(e)}"
            logger.error("Authentication error: %s", e)

    @property
    def is_connected(self) -> bool:
        """Check if authenticated."""
        return self.session is not None
