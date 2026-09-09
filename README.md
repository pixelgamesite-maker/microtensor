# Microtensor Discord verification bot

Binds a Discord account to a Bittensor hotkey via a one-time code, per the
"Joining" flow in the Compute whitepaper (§6): verify once through Discord,
binding is permanent, every login after is just the hotkey signature.

## How it works

1. User runs `/verify <hotkey>` in the server.
2. Bot calls the API to start a session — **the API generates the OTP**, not
   the bot. The bot is just the delivery channel.
3. Bot DMs the code to the user.
4. User runs `/confirm <code>` in the server.
5. Bot forwards the code to the API, which validates it and performs the
   permanent bind.

The bot holds no authority over what counts as a valid code — it only shows
the code the API gave it, and relays whatever the user types back. That
keeps the actual security decision in one place (the API), not duplicated
between two codebases.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in .env, then:
python bot.py
```

Set `VERIFICATION_GUILD_ID` to your server's ID during development —
without it, slash commands sync globally and can take up to an hour to
appear.

## The API contract this bot needs

Full request/response shapes are documented at the top of `api_client.py`.
Summary for a quick read:

- `POST /discord/verify/start` — body: `{hotkey, discord_user_id}`.
  API generates the OTP and a `session_id`, stores them server-side with an
  expiry, and returns both to the bot for delivery. Should reject if the
  hotkey or Discord account is already bound.

- `POST /discord/verify/confirm` — body: `{session_id, otp_code}`.
  API checks the code against the session and, on success, performs the
  permanent `discord_user_id <-> hotkey` bind. Should support a limited
  number of attempts per session before invalidating it.

Whoever owns the API side only needs to read `api_client.py` — that file
**is** the contract. If a field name or status code needs to change, change
it there first and the rest of the bot follows.

## Things worth deciding before this goes to production

- **OTP delivery failure**: if a user has DMs closed, `/verify` currently
  tells them to enable DMs and retry. Fine for launch; a fallback (e.g. an
  ephemeral in-channel code) is an easy follow-up if it turns out to be a
  common complaint.
- **Rate limiting**: nothing here throttles repeated `/verify` calls. If the
  API doesn't already rate-limit per Discord ID or per hotkey, worth adding
  before this is public.
- **Multi-process deployment**: pending sessions are held in memory in the
  cog. Fine for a single bot process; move to Redis or the database if the
  bot ever runs more than one replica.
