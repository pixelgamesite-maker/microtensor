"""
Client for the Microtensor verification API.

This is the contract the bot needs from the backend. Share this file (or just
the endpoint shapes below) with whoever is building the API side so both ends
can be developed in parallel.

-------------------------------------------------------------------------------
POST {BASE_URL}/discord/verify/start
    Starts a verification session and asks the API to generate an OTP.
    The API — not the bot — should generate and store the code, since the
    bot is not a trusted source of truth for what code was "really" sent.

    Request body:
        {
            "hotkey": "5F3sa2TJ...",      # the Bittensor hotkey being claimed
            "discord_user_id": "1234567890123456"
        }

    Response 200:
        {
            "session_id": "b3f1...",      # opaque, bot only needs to echo it back
            "otp_code": "482913",         # 6-digit code, bot DMs this to the user
            "expires_in_seconds": 300
        }

    Response 409 (already bound / already pending):
        { "error": "hotkey_already_bound" }   or   { "error": "discord_already_bound" }

    Response 422:
        { "error": "invalid_hotkey" }

-------------------------------------------------------------------------------
POST {BASE_URL}/discord/verify/confirm
    Confirms a code the user typed back to the bot. The API checks the code
    against the session, and on success performs the permanent bind.

    Request body:
        {
            "session_id": "b3f1...",
            "otp_code": "482913"
        }

    Response 200:
        {
            "success": true,
            "hotkey": "5F3sa2TJ...",
            "discord_user_id": "1234567890123456"
        }

    Response 400 (wrong code):
        { "error": "invalid_code", "attempts_remaining": 2 }

    Response 410 (expired):
        { "error": "session_expired" }
-------------------------------------------------------------------------------

Adjust field names/status codes here once the real API is confirmed — this
file is the single place that needs to change if the contract shifts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger("verify_bot.api")


class VerificationApiError(Exception):
    """Raised for any non-2xx response, carrying the parsed error code if present."""

    def __init__(self, status_code: int, error_code: Optional[str], raw: dict):
        self.status_code = status_code
        self.error_code = error_code or "unknown_error"
        self.raw = raw
        super().__init__(f"API error {status_code}: {self.error_code}")


@dataclass
class StartResult:
    session_id: str
    otp_code: str
    expires_in_seconds: int


@dataclass
class ConfirmResult:
    hotkey: str
    discord_user_id: str


class VerificationApiClient:
    """Thin async wrapper around the two endpoints above."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0):
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout

    async def start_verification(self, *, hotkey: str, discord_user_id: str) -> StartResult:
        url = f"{self._base_url}/discord/verify/start"
        payload = {"hotkey": hotkey, "discord_user_id": discord_user_id}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, json=payload, headers=self._headers)

        data = _safe_json(resp)
        if resp.status_code != 200:
            raise VerificationApiError(resp.status_code, data.get("error"), data)

        return StartResult(
            session_id=data["session_id"],
            otp_code=data["otp_code"],
            expires_in_seconds=data.get("expires_in_seconds", 300),
        )

    async def confirm_verification(self, *, session_id: str, otp_code: str) -> ConfirmResult:
        url = f"{self._base_url}/discord/verify/confirm"
        payload = {"session_id": session_id, "otp_code": otp_code}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, json=payload, headers=self._headers)

        data = _safe_json(resp)
        if resp.status_code != 200:
            raise VerificationApiError(resp.status_code, data.get("error"), data)

        return ConfirmResult(
            hotkey=data["hotkey"],
            discord_user_id=data["discord_user_id"],
        )


def _safe_json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except ValueError:
        log.warning("Non-JSON response from verification API: %s", resp.text[:200])
        return {}
