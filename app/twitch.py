import logging
from datetime import datetime, timezone

import httpx

from app.config import TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET
from app.database import async_session
from app.models import GuildConfig, TrackedStreamer, StreamerPlatform
from app.bot import notify_live

logger = logging.getLogger(__name__)

_APP_TOKEN: str | None = None

async def _get_app_token(client: httpx.AsyncClient) -> str:
    global _APP_TOKEN
    resp = await client.post(
        "https://id.twitch.tv/oauth2/token",
        params={
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
    )
    data = resp.json()
    _APP_TOKEN = data["access_token"]
    logger.info("Twitch App-Token erneuert")
    return _APP_TOKEN

async def check_all_streamers():
    logger.info("Live-Check gestartet...")
    headers = {"Client-ID": TWITCH_CLIENT_ID}
    async with httpx.AsyncClient(timeout=15) as client:
        if not _APP_TOKEN:
            await _get_app_token(client)
        headers["Authorization"] = f"Bearer {_APP_TOKEN}"

        async with async_session() as session:
            platforms = await session.execute(
                __import__("sqlalchemy").select(StreamerPlatform).where(StreamerPlatform.platform == "twitch")
            )
            platforms = platforms.scalars().all()

            for sp in platforms:
                resp = await client.get(
                    "https://api.twitch.tv/helix/streams",
                    params={"user_login": sp.username},
                    headers=headers,
                )
                if resp.status_code == 401:
                    await _get_app_token(client)
                    headers["Authorization"] = f"Bearer {_APP_TOKEN}"
                    resp = await client.get(
                        "https://api.twitch.tv/helix/streams",
                        params={"user_login": sp.username},
                        headers=headers,
                    )
                data = resp.json()
                is_live = len(data.get("data", [])) > 0

                if is_live and not sp.is_live:
                    sp.is_live = True
                    sp.last_live_at = datetime.now(timezone.utc)
                    streamer = await session.get(TrackedStreamer, sp.streamer_id)
                    guild = await session.get(GuildConfig, streamer.guild_id)
                    if guild:
                        display = streamer.display_name or sp.username
                        await notify_live(guild.guild_id, display, sp.platform)
                elif not is_live and sp.is_live:
                    sp.is_live = False

                sp.last_check_at = datetime.now(timezone.utc)

            await session.commit()
    logger.info("Live-Check abgeschlossen")
