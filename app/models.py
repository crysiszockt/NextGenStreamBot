from sqlalchemy import Column, Integer, String, BigInteger, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


FREE_MAX_GUILDS = 1
FREE_MAX_STREAMERS = 1
PAID_MAX_STREAMERS = 5


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    is_premium = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    guild_configs = relationship("GuildConfig", back_populates="owner")

    def max_guilds(self) -> int:
        return 999999 if self.is_premium else FREE_MAX_GUILDS

    def max_streamers(self) -> int:
        return PAID_MAX_STREAMERS if self.is_premium else FREE_MAX_STREAMERS

    def max_platforms_per_streamer(self) -> int:
        return 10 if self.is_premium else 1


class GuildConfig(Base):
    __tablename__ = "guild_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, unique=True, nullable=False, index=True)
    guild_name = Column(String(128), default="Unknown")
    notify_channel_id = Column(BigInteger, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    custom_message_template = Column(Text, nullable=True)
    is_premium = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="guild_configs")
    tracked_streamers = relationship("TrackedStreamer", back_populates="guild", cascade="all, delete-orphan")
    platform_credentials = relationship("PlatformCredential", back_populates="guild", cascade="all, delete-orphan")


class TrackedStreamer(Base):
    __tablename__ = "tracked_streamers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guild_configs.guild_id"), nullable=False)
    display_name = Column(String(64), nullable=True)
    custom_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    guild = relationship("GuildConfig", back_populates="tracked_streamers")
    platforms = relationship("StreamerPlatform", back_populates="streamer", cascade="all, delete-orphan")


class StreamerPlatform(Base):
    __tablename__ = "streamer_platforms"
    __table_args__ = (
        UniqueConstraint("streamer_id", "platform", "username", name="uq_streamer_platform_username"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    streamer_id = Column(Integer, ForeignKey("tracked_streamers.id"), nullable=False)
    platform = Column(String(32), nullable=False)
    username = Column(String(64), nullable=False)
    is_live = Column(Boolean, default=False)
    last_live_at = Column(DateTime, nullable=True)
    last_check_at = Column(DateTime, nullable=True)

    streamer = relationship("TrackedStreamer", back_populates="platforms")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guild_configs.guild_id"), nullable=False, index=True)
    action = Column(String(64), nullable=False)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PlatformCredential(Base):
    __tablename__ = "platform_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, ForeignKey("guild_configs.guild_id"), nullable=False)
    platform = Column(String(32), nullable=False)
    api_key = Column(String(256), nullable=True)
    api_secret = Column(String(256), nullable=True)
    enabled = Column(Boolean, default=False)

    guild = relationship("GuildConfig", back_populates="platform_credentials")
