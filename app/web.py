import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, FastAPI, Form, Request, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SECRET_KEY
from app.database import async_session, get_db
from app.models import (
    AuditLog,
    FREE_MAX_GUILDS,
    FREE_MAX_STREAMERS,
    PAID_MAX_STREAMERS,
    GuildConfig,
    PlatformCredential,
    StreamerPlatform,
    TrackedStreamer,
    User,
)

logger = logging.getLogger(__name__)

web_app = FastAPI()
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
web_app.mount("/static", StaticFiles(directory="app/static"), name="static")


# --- Helper ---

def hash_password(password: str) -> str:
    import hashlib
    return hashlib.sha256((password + SECRET_KEY).encode()).hexdigest()


async def get_current_user(request: Request, db: AsyncSession | None = None) -> User | None:
    token = request.cookies.get("session")
    if not token:
        return None
    if db is None:
        async with async_session() as s:
            return await _lookup_user_by_token(s, token)
    return await _lookup_user_by_token(db, token)


async def _lookup_user_by_token(db: AsyncSession, token: str) -> User | None:
    result = await db.execute(select(User).where(User.password_hash == token))
    return result.scalar_one_or_none()


async def _sidebar_guilds(user: User, db: AsyncSession) -> list:
    if not user:
        return []
    result = await db.execute(
        select(GuildConfig).where(GuildConfig.owner_id == user.id)
    )
    return result.scalars().all()


async def _audit(guild_id: int, action: str, detail: str | None = None):
    async with async_session() as s:
        s.add(AuditLog(guild_id=guild_id, action=action, detail=detail))
        await s.commit()


# --- Auth Routes ---

@web_app.get("/")
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    return templates.TemplateResponse("index.html", {"request": request, "user": user})


@web_app.get("/login")
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "user": None})


@web_app.post("/login")
async def login_post(request: Request, username: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or user.password_hash != hash_password(password):
        return templates.TemplateResponse("login.html", {"request": request, "user": None, "error": "Ungueltige Anmeldedaten"})
    resp = RedirectResponse(url="/dashboard", status_code=302)
    resp.set_cookie(key="session", value=user.password_hash, httponly=True, max_age=86400 * 7)
    return resp


@web_app.get("/register")
async def register_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("register.html", {"request": request, "user": None})


@web_app.post("/register")
async def register_post(request: Request, username: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == username))
    if result.scalar_one_or_none():
        return templates.TemplateResponse("register.html", {"request": request, "user": None, "error": "Benutzername bereits vergeben"})
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    resp = RedirectResponse(url="/dashboard", status_code=302)
    resp.set_cookie(key="session", value=user.password_hash, httponly=True, max_age=86400 * 7)
    return resp


@web_app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie("session")
    return resp


# --- Dashboard ---

@web_app.get("/dashboard")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    result = await db.execute(select(GuildConfig).where(GuildConfig.owner_id == user.id))
    guilds = result.scalars().all()
    sidebar_guilds = await _sidebar_guilds(user, db)
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "guilds": guilds,
        "sidebar_guilds": sidebar_guilds,
        "max_guilds": user.max_guilds(),
        "can_add_more": len(guilds) < user.max_guilds(),
    })


# --- Guild Settings ---

@web_app.get("/guild/{guild_id}")
async def guild_settings(request: Request, guild_id: int, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    gc = await db.get(GuildConfig, guild_id)
    if not gc or gc.owner_id != user.id:
        return templates.TemplateResponse("guild_settings.html", {"request": request, "user": user, "error": "Server nicht gefunden"})
    streamers = (await db.execute(
        select(TrackedStreamer).where(TrackedStreamer.guild_id == guild_id)
    )).scalars().all()
    sidebar_guilds = await _sidebar_guilds(user, db)
    return templates.TemplateResponse("guild_settings.html", {
        "request": request,
        "user": user,
        "guild": gc,
        "streamers": streamers,
        "sidebar_guilds": sidebar_guilds,
        "success": request.query_params.get("success", ""),
        "max_streamers": user.max_streamers(),
        "max_platforms": user.max_platforms_per_streamer(),
    })


@web_app.post("/guild/{guild_id}/channel")
async def update_channel(request: Request, guild_id: int, channel_id: int = Form(...), db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    gc = await db.get(GuildConfig, guild_id)
    if not gc or gc.owner_id != user.id:
        raise HTTPException(403)
    gc.notify_channel_id = channel_id
    await db.commit()
    await _audit(guild_id, "channel_update", f"Channel auf {channel_id} geaendert")
    return RedirectResponse(url=f"/guild/{guild_id}?success=Channel+aktualisiert", status_code=302)


@web_app.post("/guild/{guild_id}/template")
async def update_template(request: Request, guild_id: int, template: str = Form(...), db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    gc = await db.get(GuildConfig, guild_id)
    if not gc or gc.owner_id != user.id:
        raise HTTPException(403)
    gc.custom_message_template = template
    await db.commit()
    await _audit(guild_id, "template_update", "Template aktualisiert")
    return RedirectResponse(url=f"/guild/{guild_id}?success=Template+gespeichert", status_code=302)


@web_app.post("/guild/{guild_id}/streamer/add")
async def add_streamer(request: Request, guild_id: int, display_name: str = Form(...), db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    gc = await db.get(GuildConfig, guild_id)
    if not gc or gc.owner_id != user.id:
        raise HTTPException(403)
    streamers_count = (await db.execute(
        select(TrackedStreamer).where(TrackedStreamer.guild_id == guild_id)
    )).scalars().all()
    if len(streamers_count) >= user.max_streamers():
        return RedirectResponse(url=f"/guild/{guild_id}?success=Streamer-Limit+erreicht", status_code=302)
    s = TrackedStreamer(guild_id=guild_id, display_name=display_name)
    db.add(s)
    await db.commit()
    await _audit(guild_id, "streamer_add", f"Streamer {display_name} hinzugefuegt")
    return RedirectResponse(url=f"/guild/{guild_id}?success=Streamer+hinzugefuegt", status_code=302)


@web_app.post("/guild/{guild_id}/streamer/{streamer_id}/delete")
async def delete_streamer(request: Request, guild_id: int, streamer_id: int, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    gc = await db.get(GuildConfig, guild_id)
    if not gc or gc.owner_id != user.id:
        raise HTTPException(403)
    s = await db.get(TrackedStreamer, streamer_id)
    if s:
        await db.execute(
            __import__("sqlalchemy").delete(StreamerPlatform).where(StreamerPlatform.streamer_id == streamer_id)
        )
        await db.delete(s)
        await db.commit()
        await _audit(guild_id, "streamer_delete", f"Streamer {s.display_name} geloescht")
    return RedirectResponse(url=f"/guild/{guild_id}?success=Streamer+geloescht", status_code=302)


@web_app.post("/guild/{guild_id}/streamer/{streamer_id}/platform/add")
async def add_platform_to_streamer(
    request: Request, guild_id: int, streamer_id: int,
    platform: str = Form(...), username: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)
    gc = await db.get(GuildConfig, guild_id)
    if not gc or gc.owner_id != user.id:
        raise HTTPException(403)
    s = await db.get(TrackedStreamer, streamer_id)
    if not s:
        raise HTTPException(404)
    existing = await db.execute(
        select(StreamerPlatform).where(
            StreamerPlatform.streamer_id == streamer_id,
            StreamerPlatform.platform == platform,
            StreamerPlatform.username == username,
        )
    )
    if existing.scalar_one_or_none():
        return RedirectResponse(url=f"/guild/{guild_id}?success=Plattform+existiert+bereits", status_code=302)
    existing_count = await db.execute(
        select(StreamerPlatform).where(StreamerPlatform.streamer_id == streamer_id)
    )
    if len(existing_count.scalars().all()) >= user.max_platforms_per_streamer():
        return RedirectResponse(url=f"/guild/{guild_id}?success=Plattform-Limit+erreicht", status_code=302)
    sp = StreamerPlatform(streamer_id=streamer_id, platform=platform, username=username)
    db.add(sp)
    await db.commit()
    await _audit(guild_id, "platform_add", f"{platform}/{username} zu {s.display_name} hinzugefuegt")
    return RedirectResponse(url=f"/guild/{guild_id}?success=Plattform+hinzugefuegt", status_code=302)


@web_app.post("/guild/{guild_id}/platform/{platform_id}/delete")
async def delete_platform(request: Request, guild_id: int, platform_id: int, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    gc = await db.get(GuildConfig, guild_id)
    if not gc or gc.owner_id != user.id:
        raise HTTPException(403)
    sp = await db.get(StreamerPlatform, platform_id)
    if sp:
        await db.delete(sp)
        await db.commit()
        await _audit(guild_id, "platform_delete", f"{sp.platform}/{sp.username} geloescht")
    return RedirectResponse(url=f"/guild/{guild_id}?success=Plattform+geloescht", status_code=302)


@web_app.post("/guild/{guild_id}/platform/{platform_id}/edit")
async def edit_platform_username(
    request: Request, guild_id: int, platform_id: int,
    username: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user = await get_current_user(request, db)
    gc = await db.get(GuildConfig, guild_id)
    if not gc or gc.owner_id != user.id:
        raise HTTPException(403)
    sp = await db.get(StreamerPlatform, platform_id)
    if not sp:
        raise HTTPException(404)
    existing = await db.execute(
        select(StreamerPlatform).where(
            StreamerPlatform.streamer_id == sp.streamer_id,
            StreamerPlatform.platform == sp.platform,
            StreamerPlatform.username == username,
        )
    )
    if existing.scalar_one_or_none():
        return RedirectResponse(url=f"/guild/{guild_id}?success=Username+bereits+vergeben", status_code=302)
    sp.username = username
    await db.commit()
    await _audit(guild_id, "platform_edit", f"{sp.platform} Username geaendert")
    return RedirectResponse(url=f"/guild/{guild_id}?success=Username+aktualisiert", status_code=302)


@web_app.post("/guild/{guild_id}/disconnect")
async def disconnect_guild(request: Request, guild_id: int, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    gc = await db.get(GuildConfig, guild_id)
    if not gc or gc.owner_id != user.id:
        raise HTTPException(403)
    await db.delete(gc)
    await db.commit()
    return RedirectResponse(url="/dashboard", status_code=302)


# --- Audit Log ---

@web_app.get("/guild/{guild_id}/audit")
async def audit_log_page(request: Request, guild_id: int, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    gc = await db.get(GuildConfig, guild_id)
    if not gc or gc.owner_id != user.id:
        return templates.TemplateResponse("audit_log.html", {"request": request, "user": user, "error": "Server nicht gefunden"})
    entries = (await db.execute(
        select(AuditLog).where(AuditLog.guild_id == guild_id).order_by(AuditLog.created_at.desc()).limit(100)
    )).scalars().all()
    sidebar_guilds = await _sidebar_guilds(user, db)
    return templates.TemplateResponse("audit_log.html", {
        "request": request, "user": user, "guild": gc,
        "entries": entries, "sidebar_guilds": sidebar_guilds,
    })


# --- YouTube --

@web_app.get("/guild/{guild_id}/youtube")
async def youtube_page(request: Request, guild_id: int, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    gc = await db.get(GuildConfig, guild_id)
    if not gc or gc.owner_id != user.id:
        return templates.TemplateResponse("youtube.html", {"request": request, "user": user, "error": "Server nicht gefunden"})
    sidebar_guilds = await _sidebar_guilds(user, db)
    return templates.TemplateResponse("youtube.html", {
        "request": request, "user": user, "guild": gc, "sidebar_guilds": sidebar_guilds,
    })


# --- Premium ---

@web_app.get("/premium")
async def premium_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    return templates.TemplateResponse("premium.html", {"request": request, "user": user})


@web_app.post("/dev/toggle-premium")
async def dev_toggle_premium(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    user.is_premium = not user.is_premium
    await db.commit()
    return RedirectResponse(url="/dashboard", status_code=302)
