#!/usr/bin/env python3
import os
import sys
import logging
import time
from pathlib import Path

import discord
from discord.ext import commands
from discord import app_commands
from aiohttp import web
from dotenv import load_dotenv

from db import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
REVIEW_CHANNEL_ID = int(os.getenv("REVIEW_CHANNEL_ID", "1497630261607792792"))
STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID", "1496970697430536489"))
INFRACTION_LOG_CHANNEL_ID = int(os.getenv("INFRACTION_LOG_CHANNEL_ID", str(REVIEW_CHANNEL_ID)))
PROMOTION_LOG_CHANNEL_ID = int(os.getenv("PROMOTION_LOG_CHANNEL_ID", str(REVIEW_CHANNEL_ID)))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "1497628703381917827"))
ACCEPT_ROLE_ID = int(os.getenv("ACCEPT_ROLE_ID", "1496970734919094303"))
PORT = int(os.getenv("PORT", "8080"))
EMBED_COLOR = int(os.getenv("EMBED_COLOR", "1973790"))
PANEL_BANNER_URL = os.getenv("PANEL_BANNER_URL", "https://imgur.com/WxeW12e")
LOGO_URL = os.getenv("LOGO_URL", "https://imgur.com/WxeW12e")
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/database.db"))
SYNC_COMMANDS_ON_START = os.getenv("SYNC_COMMANDS_ON_START", "false").strip().lower() in {"1", "true", "yes", "on"}

if not TOKEN or GUILD_ID == 0 or REVIEW_CHANNEL_ID == 0:
    logger.error(
        "Missing required environment variables. "
        "DISCORD_TOKEN, GUILD_ID, and REVIEW_CHANNEL_ID must all be set."
    )
    sys.exit(1)

logger.info(
    f"Starting Discord bot with PORT={PORT}, GUILD_ID={GUILD_ID}, REVIEW_CHANNEL_ID={REVIEW_CHANNEL_ID}, "
    f"STAFF_ROLE_ID={STAFF_ROLE_ID}, DATABASE_PATH={DATABASE_PATH}"
)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS, GET",
    "Access-Control-Allow-Headers": "Content-Type"
}


def build_application_embed(data: dict) -> discord.Embed:
    applicant_id_raw = str(data.get("discordUserId", "")).strip()
    applicant_mention = f"<@{applicant_id_raw}>" if applicant_id_raw.isdigit() else "Unknown applicant ID"

    embed = discord.Embed(
        title="Moderator Application",
        description="A new moderator application has been submitted.",
        color=0x1E90FF,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="Applicant", value=applicant_mention, inline=True)
    embed.add_field(name="Roblox Username", value=data.get("robloxUsername", "N/A"), inline=True)
    embed.add_field(name="Discord Username", value=data.get("discordUsername", "N/A"), inline=True)
    embed.add_field(name="Discord ID", value=data.get("discordUserId", "N/A"), inline=True)
    embed.add_field(name="Age", value=str(data.get("age", "N/A")), inline=True)
    embed.add_field(name="AI Agreement", value=data.get("aiAgreement", "N/A"), inline=True)
    embed.add_field(name="Rush Agreement", value=data.get("rushAgreement", "N/A"), inline=True)
    embed.add_field(name="RDM", value=data.get("rdm", "N/A"), inline=False)
    embed.add_field(name="VDM", value=data.get("vdm", "N/A"), inline=False)
    embed.add_field(name="NLR", value=data.get("nlr", "N/A"), inline=False)
    embed.add_field(name="NITRP", value=data.get("nitrp", "N/A"), inline=False)
    embed.add_field(name="AA/MA", value=data.get("aama", "N/A"), inline=False)
    embed.add_field(name="Scenario 1", value=data.get("scenario1", "N/A"), inline=False)
    embed.add_field(name="Scenario 2", value=data.get("scenario2", "N/A"), inline=False)
    embed.add_field(name="Scenario 3", value=data.get("scenario3", "N/A"), inline=False)
    embed.add_field(name="Scenario 4", value=data.get("scenario4", "N/A"), inline=False)
    embed.add_field(name="Additional Info", value=data.get("additional", "No additional info provided."), inline=False)
    embed.set_footer(text=f"Review role: <@&{STAFF_ROLE_ID}>")
    return embed


def build_decision_embed(
    data: dict,
    accepted: bool,
    reviewer: discord.Member,
    role_assigned: bool,
    reason: str,
) -> discord.Embed:
    applicant_id_raw = str(data.get("discordUserId", "")).strip()
    applicant_mention = f"<@{applicant_id_raw}>" if applicant_id_raw.isdigit() else "Unknown applicant ID"

    if accepted:
        title = "Moderator Application Approved"
        description = (
            "Your application has been reviewed and approved by our staff team. "
            "A moderator role has been assigned, and you may now begin assisting with enforcement duties."
        )
        color = 0x2ECC71
    else:
        title = "Moderator Application Declined"
        description = (
            "Thank you for your application. After careful review, your application was not accepted at this time. "
            "Please continue to participate positively in the community and feel free to reapply later."
        )
        color = 0xE74C3C

    embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
    embed.add_field(name="Applicant", value=applicant_mention, inline=True)
    embed.add_field(name="Discord ID", value=data.get("discordUserId", "N/A"), inline=True)
    embed.add_field(name="Reviewed By", value=reviewer.display_name, inline=True)
    embed.add_field(name="Decision", value="Accepted" if accepted else "Denied", inline=True)
    embed.add_field(name="Reason", value=reason or "No reason provided.", inline=False)
    embed.add_field(name="Role Granted", value="Yes" if role_assigned else "No", inline=False)
    embed.set_footer(text="Florida State Roleplay Staff Review")
    return embed


def build_log_embed(
    data: dict,
    accepted: bool,
    reviewer: discord.Member,
    role_assigned: bool,
    applicant_member: discord.Member | None,
    reason: str,
    dm_status: str,
) -> discord.Embed:
    applicant_id_raw = str(data.get("discordUserId", "")).strip()
    applicant_mention = f"<@{applicant_id_raw}>" if applicant_id_raw.isdigit() else "Unknown applicant ID"

    status = "Accepted" if accepted else "Denied"
    color = 0x2ECC71 if accepted else 0xE74C3C
    embed = discord.Embed(
        title=f"Application {status}",
        description=f"Application reviewed by {reviewer.mention}.",
        color=color,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="Applicant", value=applicant_mention, inline=True)
    embed.add_field(name="Discord ID", value=data.get("discordUserId", "N/A"), inline=True)
    embed.add_field(name="Decision", value=status, inline=True)
    embed.add_field(name="Reason", value=reason or "No reason provided.", inline=False)
    embed.add_field(name="Role Granted", value="Yes" if role_assigned else "No", inline=True)
    embed.add_field(name="DM Status", value=dm_status, inline=True)
    embed.add_field(name="Applicant in Guild", value="Yes" if applicant_member else "No", inline=True)
    embed.add_field(name="Submitted At", value=data.get("submittedAt", "N/A"), inline=False)
    return embed


def reviewer_allowed(member: discord.Member) -> bool:
    if member.guild_permissions.manage_roles or member.guild_permissions.administrator:
        return True
    return any(role.id == STAFF_ROLE_ID for role in member.roles)


class ApplicationReviewView(discord.ui.View):
    def __init__(self, bot: commands.Bot, application_data: dict):
        super().__init__(timeout=None)
        self.bot = bot
        self.application_data = application_data
        self.processed = False

    async def disable_buttons(self):
        for child in self.children:
            child.disabled = True

    async def handle_decision(
        self,
        interaction: discord.Interaction,
        accepted: bool,
        reason: str,
        review_message: discord.Message | None,
    ):
        if self.processed:
            await interaction.response.send_message("This application has already been processed.", ephemeral=True)
            return

        if not isinstance(interaction.user, discord.Member) or not reviewer_allowed(interaction.user):
            await interaction.response.send_message("You are not authorized to review applications.", ephemeral=True)
            return

        self.processed = True
        await interaction.response.defer(ephemeral=True)

        application = self.application_data
        reviewer = interaction.user
        accepted_role_assigned = False
        guild = interaction.guild or self.bot.get_guild(GUILD_ID)
        applicant_member = None
        applicant_id = int(str(application.get("discordUserId", "0")).strip() or 0)

        if guild and applicant_id:
            try:
                applicant_member = guild.get_member(applicant_id)
                if applicant_member is None:
                    applicant_member = await guild.fetch_member(applicant_id)
            except Exception:
                applicant_member = None

        if accepted and applicant_member is not None and ACCEPT_ROLE_ID:
            try:
                accepted_role = guild.get_role(ACCEPT_ROLE_ID)
                if accepted_role is not None:
                    await applicant_member.add_roles(accepted_role, reason="Moderator application accepted")
                    accepted_role_assigned = True
            except Exception as e:
                logger.warning(f"Failed to assign accepted role: {e}")

        dm_status = await send_applicant_dm(
            self.bot,
            application,
            accepted,
            reviewer,
            accepted_role_assigned,
            reason,
            applicant_member,
        )
        await log_application_decision(
            self.bot,
            application,
            accepted,
            reviewer,
            accepted_role_assigned,
            applicant_member,
            reason,
            dm_status,
        )

        # Update review message: remove raw ID field and show decision details.
        message_to_update = review_message
        if message_to_update is not None and message_to_update.embeds:
            original = message_to_update.embeds[0]
            updated = discord.Embed(
                title=original.title,
                description=original.description,
                color=(0x2ECC71 if accepted else 0xE74C3C),
                timestamp=original.timestamp,
            )
            for field in original.fields:
                if field.name == "Discord ID":
                    continue
                updated.add_field(name=field.name, value=field.value, inline=field.inline)

            applicant_id_raw = str(application.get("discordUserId", "")).strip()
            applicant_mention = f"<@{applicant_id_raw}>" if applicant_id_raw.isdigit() else application.get("discordUsername", "N/A")
            updated.add_field(name="Applicant", value=applicant_mention, inline=True)
            updated.add_field(name="Reviewed By", value=reviewer.mention, inline=True)
            updated.add_field(name="Decision", value=("Accepted" if accepted else "Denied"), inline=True)
            updated.add_field(name="Reason", value=(reason or "No reason provided."), inline=False)
            updated.set_footer(text=original.footer.text if original.footer else None)

            await self.disable_buttons()
            await message_to_update.edit(embed=updated, view=self)

        await interaction.followup.send(
            (
                f"Application {'accepted' if accepted else 'denied'}.\n"
                f"DM status: {dm_status}"
            ),
            ephemeral=True
        )

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="app_accept")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReviewReasonModal(self, accepted=True, review_message=interaction.message))

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="app_deny")
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReviewReasonModal(self, accepted=False, review_message=interaction.message))


class ReviewReasonModal(discord.ui.Modal, title="Application Review Reason"):
    reason = discord.ui.TextInput(
        label="Reason for this decision",
        style=discord.TextStyle.long,
        required=True,
        max_length=1000,
        placeholder="Enter the reason sent to the applicant and logs.",
    )

    def __init__(self, review_view: ApplicationReviewView, accepted: bool, review_message: discord.Message | None):
        super().__init__()
        self.review_view = review_view
        self.accepted = accepted
        self.review_message = review_message

    async def on_submit(self, interaction: discord.Interaction):
        await self.review_view.handle_decision(
            interaction,
            accepted=self.accepted,
            reason=self.reason.value.strip(),
            review_message=self.review_message,
        )


async def send_applicant_dm(
    bot: commands.Bot,
    data: dict,
    accepted: bool,
    reviewer: discord.Member,
    role_assigned: bool,
    reason: str,
    applicant_member: discord.Member | None,
) -> str:
    embed = build_decision_embed(data, accepted, reviewer, role_assigned, reason)
    applicant_id_raw = str(data.get("discordUserId", "")).strip()

    try:
        if applicant_member is not None:
            await applicant_member.send(embed=embed)
            return "Sent"

        if not applicant_id_raw.isdigit():
            return "Not sent (invalid Discord User ID in application)"

        user = await bot.fetch_user(int(applicant_id_raw))
        await user.send(embed=embed)
        return "Sent"
    except discord.Forbidden:
        return "Failed (user has DMs closed)"
    except Exception as e:
        logger.warning(f"Failed to DM applicant: {e}")
        return "Failed (unexpected error)"


async def log_application_decision(
    bot: commands.Bot,
    data: dict,
    accepted: bool,
    reviewer: discord.Member,
    role_assigned: bool,
    applicant_member: discord.Member | None,
    reason: str,
    dm_status: str,
):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        except Exception as e:
            logger.warning(f"Failed to fetch log channel: {e}")
            return

    embed = build_log_embed(data, accepted, reviewer, role_assigned, applicant_member, reason, dm_status)
    await channel.send(embed=embed)


class FloridaRPBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.guilds = True
        intents.reactions = True
        
        super().__init__(command_prefix="!", intents=intents)
        self.web_runner = None
        self._commands_synced = False
        self.config = {}
        self.ssu_latest_stats: dict = {}
        self.ssu_last_update_ts: int = 0
        self.db = Database(DATABASE_PATH)
        self.config.update({
            "review_channel_id": REVIEW_CHANNEL_ID,
            "staff_role_id": STAFF_ROLE_ID,
            "infraction_log_channel_id": INFRACTION_LOG_CHANNEL_ID,
            "promotion_log_channel_id": PROMOTION_LOG_CHANNEL_ID,
            "embed_color": EMBED_COLOR,
            "panel_banner_url": PANEL_BANNER_URL,
            "logo_url": LOGO_URL,
            "ssu_api_key": os.getenv("SSU_API_KEY", ""),
            "ssu_api_url": os.getenv("SSU_API_URL", ""),
            "ssu_server_name": os.getenv("SSU_SERVER_NAME", "Florida Sessions Roleplay"),
            "ssu_server_owner": os.getenv("SSU_SERVER_OWNER", "<@1311973437924966462>"),
            "ssu_server_code": os.getenv("SSU_SERVER_CODE", "FLSRPSAP"),
            "session_role_id": int(os.getenv("SESSION_ROLE_ID", "1497021079842193558") or "1497021079842193558"),
            "server_online_url": os.getenv("SERVER_ONLINE_URL", ""),
        })
        self.ssu_session_state = "Shutdown"
    
    async def setup_hook(self):
        logger.info("Setting up bot")
        
        # Load cogs
        cogs = ["cogs.moderation", "cogs.applications", "cogs.training", "cogs.assistance"]
        for cog_module in cogs:
            try:
                await self.load_extension(cog_module)
                logger.info(f"Loaded {cog_module}")
            except Exception as e:
                logger.warning(f"Could not load {cog_module}: {e}")
        
        # Start web server early so Railway health checks succeed quickly.
        await self.start_web_server()

        # Sync commands only when explicitly enabled.
        if SYNC_COMMANDS_ON_START:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Commands synced")
        else:
            logger.info("Skipping command sync on startup (SYNC_COMMANDS_ON_START=false)")
    
    async def on_ready(self):
        logger.info(f"Logged in as {self.user}")
        if not self._commands_synced:
            self._commands_synced = True
            self.loop.create_task(self._sync_commands_background())

    async def _sync_commands_background(self) -> None:
        try:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Background command sync completed")
        except Exception as exc:
            logger.warning(f"Background command sync failed: {exc}")
    
    async def start_web_server(self):
        async def handle_root(request):
            return web.Response(text="OK", status=200, headers=CORS_HEADERS)
        
        async def handle_health(request):
            logger.info("Health check")
            return web.Response(text="OK", status=200, headers=CORS_HEADERS)
        
        async def handle_apply(request):
            logger.info("Application received")
            try:
                data = await request.json()
                logger.info(f"Application from {data.get('robloxUsername', 'unknown')}")

                channel = self.get_channel(REVIEW_CHANNEL_ID)
                if channel is None:
                    channel = await self.fetch_channel(REVIEW_CHANNEL_ID)

                if channel is None:
                    raise RuntimeError(f"Review channel {REVIEW_CHANNEL_ID} not found.")

                embed = build_application_embed(data)
                view = ApplicationReviewView(self, data)
                applicant_id_raw = str(data.get("discordUserId", "")).strip()
                applicant_mention = f"<@{applicant_id_raw}>" if applicant_id_raw.isdigit() else "`Unknown applicant ID`"
                await channel.send(
                    content=(
                        f"<@&{STAFF_ROLE_ID}> {applicant_mention} A new moderator application has been submitted for review. "
                        "Please use the buttons below to Accept or Deny the application."
                    ),
                    embed=embed,
                    view=view
                )
                logger.info("Application sent to Discord review channel")

                return web.json_response({"success": True}, headers=CORS_HEADERS)
            except Exception as e:
                logger.exception("Error handling application")
                return web.json_response({"success": False, "error": str(e)}, status=500, headers=CORS_HEADERS)
        
        async def handle_ssu_stats(request: web.Request):
            try:
                config = self.config
                expected_key = str(config.get("ssu_api_key", "") or "").strip()
                if not expected_key:
                    return web.json_response({"success": False, "error": "SSU API key not configured"}, status=503, headers=CORS_HEADERS)

                provided_key = (
                    request.headers.get("x-api-key")
                    or request.headers.get("X-API-Key")
                    or request.headers.get("authorization", "").replace("Bearer ", "").strip()
                )
                if provided_key != expected_key:
                    return web.json_response({"success": False, "error": "Unauthorized"}, status=401, headers=CORS_HEADERS)

                data = await request.json()
                if not isinstance(data, dict):
                    return web.json_response({"success": False, "error": "Invalid JSON body"}, status=400, headers=CORS_HEADERS)

                self.ssu_latest_stats = {
                    "players": data.get("playerCount", data.get("players", "N/A")),
                    "staff": data.get("staffOnline", data.get("staff", "N/A")),
                    "queue": data.get("queueCount", data.get("queue", "N/A")),
                    "status": data.get("serverStatus", data.get("status", "Online")),
                    "server_name": data.get("serverName", config.get("ssu_server_name", "Florida Sessions Roleplay")),
                    "server_code": data.get("serverCode", config.get("ssu_server_code", "N/A")),
                }
                self.ssu_last_update_ts = int(time.time())
                return web.json_response({"success": True}, headers=CORS_HEADERS)
            except Exception as exc:
                logger.exception("Failed to ingest SSU stats: %s", exc)
                return web.json_response({"success": False, "error": "Failed to ingest stats"}, status=500, headers=CORS_HEADERS)

        async def handle_options(request):
            return web.Response(status=204, headers=CORS_HEADERS)
        
        try:
            app = web.Application()
            app.router.add_get("/", handle_root)
            app.router.add_get("/health", handle_health)
            app.router.add_post("/apply", handle_apply)
            app.router.add_options("/apply", handle_options)
            app.router.add_post("/ssu/stats", handle_ssu_stats)
            app.router.add_options("/ssu/stats", handle_options)
            
            self.web_runner = web.AppRunner(app)
            await self.web_runner.setup()
            
            site = web.TCPSite(self.web_runner, "0.0.0.0", PORT)
            await site.start()
            logger.info(f"Web server started on port {PORT}")
        except Exception as e:
            logger.exception("Web server error")
            raise


if __name__ == "__main__":
    bot = FloridaRPBot()
    bot.run(TOKEN)