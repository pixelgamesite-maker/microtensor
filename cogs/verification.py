"""
/verify and /confirm — binds a Discord account to a Bittensor hotkey.

Flow (matches "Joining" in the Compute whitepaper, §6):
    1. User runs /verify <hotkey> in the server.
    2. Bot asks the API to start a session; the API generates the OTP.
    3. Bot DMs the OTP to the user and remembers their session_id.
    4. User runs /confirm <code>.
    5. Bot forwards the code to the API, which validates and performs the
       permanent discord_id <-> hotkey bind.

The bot never generates or validates the code itself — it only delivers it
and relays the user's reply. The API is the source of truth throughout.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from api_client import VerificationApiClient, VerificationApiError

log = logging.getLogger("verify_bot.cog")

# How long we'll accept /confirm after /verify, as a client-side backstop.
# The API's own expiry is authoritative; this just avoids a stale local entry
# sitting around forever if a user never comes back.
LOCAL_SESSION_TTL_PADDING_SECONDS = 30


@dataclass
class PendingSession:
    session_id: str
    hotkey: str
    created_at: float
    expires_at: float


class VerificationCog(commands.Cog):
    def __init__(self, bot: commands.Bot, api_client: VerificationApiClient):
        self.bot = bot
        self.api = api_client
        # user_id -> PendingSession. In-memory is fine for a single bot process;
        # move to Redis/DB if the bot ever runs more than one instance.
        self._pending: dict[int, PendingSession] = {}

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [uid for uid, s in self._pending.items() if s.expires_at < now]
        for uid in expired:
            del self._pending[uid]

    @app_commands.command(
        name="verify",
        description="Link your Discord account to your Bittensor hotkey.",
    )
    @app_commands.describe(hotkey="Your Bittensor hotkey (ss58 address)")
    async def verify(self, interaction: discord.Interaction, hotkey: str):
        await interaction.response.defer(ephemeral=True)
        self._cleanup_expired()

        hotkey = hotkey.strip()
        if not _looks_like_hotkey(hotkey):
            await interaction.followup.send(
                "That doesn't look like a valid hotkey. Double-check and try again.",
                ephemeral=True,
            )
            return

        try:
            result = await self.api.start_verification(
                hotkey=hotkey,
                discord_user_id=str(interaction.user.id),
            )
        except VerificationApiError as e:
            await interaction.followup.send(_friendly_start_error(e), ephemeral=True)
            return
        except Exception:
            log.exception("start_verification failed for user %s", interaction.user.id)
            await interaction.followup.send(
                "Something went wrong reaching the verification service. Try again shortly.",
                ephemeral=True,
            )
            return

        self._pending[interaction.user.id] = PendingSession(
            session_id=result.session_id,
            hotkey=hotkey,
            created_at=time.time(),
            expires_at=time.time() + result.expires_in_seconds + LOCAL_SESSION_TTL_PADDING_SECONDS,
        )

        try:
            await interaction.user.send(
                f"Your Microtensor verification code is **{result.otp_code}**.\n"
                f"It expires in {result.expires_in_seconds // 60} minutes.\n\n"
                f"Back in the server, run `/confirm {result.otp_code}` to finish linking "
                f"hotkey `{hotkey}`."
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "I couldn't DM you the code — please enable direct messages from "
                "server members and run `/verify` again.",
                ephemeral=True,
            )
            del self._pending[interaction.user.id]
            return

        await interaction.followup.send(
            "Check your DMs for a verification code, then run `/confirm <code>` here.",
            ephemeral=True,
        )

    @app_commands.command(
        name="confirm",
        description="Confirm the verification code sent to your DMs.",
    )
    @app_commands.describe(code="The 6-digit code sent to your DMs")
    async def confirm(self, interaction: discord.Interaction, code: str):
        await interaction.response.defer(ephemeral=True)
        self._cleanup_expired()

        session = self._pending.get(interaction.user.id)
        if session is None:
            await interaction.followup.send(
                "No verification in progress. Run `/verify <hotkey>` to start one.",
                ephemeral=True,
            )
            return

        try:
            result = await self.api.confirm_verification(
                session_id=session.session_id,
                otp_code=code.strip(),
            )
        except VerificationApiError as e:
            await interaction.followup.send(_friendly_confirm_error(e), ephemeral=True)
            return
        except Exception:
            log.exception("confirm_verification failed for user %s", interaction.user.id)
            await interaction.followup.send(
                "Something went wrong reaching the verification service. Try again shortly.",
                ephemeral=True,
            )
            return

        del self._pending[interaction.user.id]

        await interaction.followup.send(
            f"Verified. Hotkey `{result.hotkey}` is now linked to your Discord account.",
            ephemeral=True,
        )
        log.info("Bound discord=%s hotkey=%s", result.discord_user_id, result.hotkey)


def _looks_like_hotkey(value: str) -> bool:
    # Loose check — ss58 addresses are base58, typically 47-48 chars. Real
    # validation belongs server-side; this just filters obvious junk input.
    return 40 <= len(value) <= 60 and " " not in value


def _friendly_start_error(e: VerificationApiError) -> str:
    return {
        "hotkey_already_bound": "That hotkey is already linked to a Discord account.",
        "discord_already_bound": "Your Discord account is already linked to a hotkey.",
        "invalid_hotkey": "That hotkey doesn't look valid. Double-check and try again.",
    }.get(e.error_code, "Couldn't start verification right now. Try again shortly.")


def _friendly_confirm_error(e: VerificationApiError) -> str:
    return {
        "invalid_code": "That code doesn't match. Check the message and try again.",
        "session_expired": "That code expired. Run `/verify <hotkey>` again to get a new one.",
    }.get(e.error_code, "Couldn't confirm right now. Try again shortly.")


async def setup(bot: commands.Bot):
    api_client: VerificationApiClient = bot.verification_api_client  # type: ignore[attr-defined]
    await bot.add_cog(VerificationCog(bot, api_client))
