import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")
SECRET_KEY = os.getenv("SECRET_KEY", "fallback-dev-key")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./streamer_bot.db")
TWITCH_CHECK_INTERVAL = int(os.getenv("TWITCH_CHECK_INTERVAL", "120"))
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
