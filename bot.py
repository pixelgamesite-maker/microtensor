"""
Entry point. Run with: python bot.py

Required environment variables — see .env.example.
"""

from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from api_client import VerificationApiClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("verify_bot")

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
API_BASE_URL = os.environ["VERIFICATION_API_BASE_URL"]
API_KEY = os.environ["VERIFICATION_API_KEY"]
GUILD_ID = os.environ.get("VERIFICATION_GUILD_ID")  # optional: for instant command sync


class VerifyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        # DMing users and reading their own slash-command input doesn't need
        # message_content; keep intents minimal.
        super().__init__(command_prefix="!", intents=intents)
        self.verification_api_client = VerificationApiClient(
            base_url=API_BASE_URL, api_key=API_KEY
        )

    async def setup_hook(self):
        await self.load_extension("cogs.verification")

        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced commands to guild %s", GUILD_ID)
        else:
            await self.tree.sync()
            log.info("Synced commands globally (can take up to an hour to propagate)")

    async def on_ready(self):
        log.info("Logged in as %s (id=%s)", self.user, self.user.id)


async def main():
    bot = VerifyBot()
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
