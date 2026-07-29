import logging

import discord
from discord.ext import commands

from app.config import DISCORD_BOT_TOKEN
from app.database import async_session
from app.models import GuildConfig, AuditLog

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


async def notify_live(guild_id: int, display_name: str, platform: str):
    async with async_session() as session:
        guild_config = await session.get(GuildConfig, guild_id)
        if guild_config and guild_config.notify_channel_id:
            channel = bot.get_channel(guild_config.notify_channel_id)
            if channel:
                msg = (guild_config.custom_message_template or "{name} ist jetzt live auf {platform}! 🎉").format(
                    name=display_name, platform=platform
                )
                await channel.send(msg)


@bot.event
async def on_ready():
    logger.info(f"Bot eingeloggt als {bot.user}")
    try:
        synced = await bot.tree.sync()
        logger.info(f"{len(synced)} Slash-Commands synchronisiert")
    except Exception as e:
        logger.warning(f"Slash-Command Sync fehlgeschlagen: {e}")


@bot.tree.command(name="setup", description="Server mit einem Benutzer verknuepfen")
async def setup_slash(interaction: discord.Interaction, username: str):
    async with async_session() as session:
        guild_id = interaction.guild_id
        existing = await session.get(GuildConfig, guild_id)
        if existing:
            await interaction.response.send_message(f"Server bereits verbunden mit Benutzer {existing.owner_id}.", ephemeral=True)
            return
        from app.models import User
        user = await session.execute(__import__("sqlalchemy").select(User).where(User.username == username))
        user = user.scalar_one_or_none()
        if not user:
            await interaction.response.send_message("Benutzer nicht gefunden.", ephemeral=True)
            return
        gc = GuildConfig(
            guild_id=guild_id,
            guild_name=interaction.guild.name,
            notify_channel_id=interaction.channel_id,
            owner_id=user.id,
        )
        session.add(gc)
        await session.commit()
        await interaction.response.send_message(f"Server verbunden mit Benutzer {username}! Nutze /status zum Pruefen.", ephemeral=True)


@bot.tree.command(name="status", description="Zeigt den Status des Servers an")
async def status_slash(interaction: discord.Interaction):
    async with async_session() as session:
        gc = await session.get(GuildConfig, interaction.guild_id)
        if not gc:
            await interaction.response.send_message("Server nicht eingerichtet. Nutze /setup <username>.", ephemeral=True)
            return
        channel_mention = f"<#{gc.notify_channel_id}>" if gc.notify_channel_id else "Nicht gesetzt"
        await interaction.response.send_message(
            f"Server: {gc.guild_name}\nBenachrichtigungs-Channel: {channel_mention}",
            ephemeral=True,
        )


async def setup_discord_bot():
    await bot.start(DISCORD_BOT_TOKEN)
