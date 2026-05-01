#!/usr/bin/env python3
import os
import sys
import logging
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
REVIEW_CHANNEL_ID = int(os.getenv("REVIEW_CHANNEL_ID", "0"))
STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID", "0"))
INFRACTION_LOG_CHANNEL_ID = int(os.getenv("INFRACTION_LOG_CHANNEL_ID", str(REVIEW_CHANNEL_ID)))
PROMOTION_LOG_CHANNEL_ID = int(os.getenv("PROMOTION_LOG_CHANNEL_ID", str(REVIEW_CHANNEL_ID)))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", str(PROMOTION_LOG_CHANNEL_ID or INFRACTION_LOG_CHANNEL_ID or REVIEW_CHANNEL_ID)))
ACCEPT_ROLE_ID = int(os.getenv("ACCEPT_ROLE_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))
EMBED_COLOR = int(os.getenv("EMBED_COLOR", "1973790"))
PANEL_BANNER_URL = os.getenv("PANEL_BANNER_URL", "https://imgur.com/WxeW12e")
LOGO_URL = os.getenv("LOGO_URL", "https://imgur.com/WxeW12e")
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "data/database.db"))

if not TOKEN or GUILD_ID == 0 or REVIEW_CHANNEL_ID == 0 or STAFF_ROLE_ID == 0:
    logger.error(
        "Missing required environment variables. "
        "DISCORD_TOKEN, GUILD_ID, REVIEW_CHANNEL_ID, and STAFF_ROLE_ID must all be set."
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
    embed = discord.Embed(
        title="Moderator Application",
        description="A new moderator application has been submitted.",
        color=0x1E90FF,
        timestamp=discord.utils.utcnow()
    )
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


def build_decision_embed(data: dict, accepted: bool, reviewer: discord.Member, role_assigned: bool) -> discord.Embed:
    if accepted:
        title = "Application Accepted"
        description = (
            "Congratulations! Your moderator application has been accepted. "
            "Please check your Discord DMs for next steps."
        )
        color = 0x2ECC71
    else:
        title = "Application Denied"
        description = (
            "Thank you for applying. After review, your application was not accepted at this time. "
            "Please review the rules and consider reapplying later."
        )
        color = 0xE74C3C

    embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
    embed.add_field(name="Applicant", value=data.get("discordUsername", "N/A"), inline=True)
    embed.add_field(name="Discord ID", value=data.get("discordUserId", "N/A"), inline=True)
    embed.add_field(name="Reviewer", value=reviewer.display_name, inline=True)
    embed.add_field(name="Decision", value="Accepted" if accepted else "Denied", inline=True)
    embed.add_field(name="Role Granted", value="Yes" if role_assigned else "No", inline=False)
    return embed


def build_log_embed(data: dict, accepted: bool, reviewer: discord.Member, role_assigned: bool, applicant_member: discord.Member | None) -> discord.Embed:
    status = "Accepted" if accepted else "Denied"
    color = 0x2ECC71 if accepted else 0xE74C3C
    embed = discord.Embed(
        title=f"Application {status}",
        description=f"Application reviewed by {reviewer.mention}.",
        color=color,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="Applicant", value=data.get("discordUsername", "N/A"), inline=True)
    embed.add_field(name="Discord ID", value=data.get("discordUserId", "N/A"), inline=True)
    embed.add_field(name="Decision", value=status, inline=True)
    embed.add_field(name="Role Granted", value="Yes" if role_assigned else "No", inline=True)
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

    async def handle_decision(self, interaction: discord.Interaction, accepted: bool):
        if self.processed:
            await interaction.response.send_message("This application has already been processed.", ephemeral=True)
            return

        if not isinstance(interaction.user, discord.Member) or not reviewer_allowed(interaction.user):
            await interaction.response.send_message("You are not authorized to review applications.", ephemeral=True)
            return

        self.processed = True
        await self.disable_buttons()
        await interaction.response.defer(ephemeral=True)
        await interaction.message.edit(view=self)

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

        await send_applicant_dm(self.bot, application, accepted, reviewer, accepted_role_assigned)
        await log_application_decision(self.bot, application, accepted, reviewer, accepted_role_assigned, applicant_member)

        await interaction.followup.send(
            f"Application {'accepted' if accepted else 'denied'}. Applicant has been notified.",
            ephemeral=True
        )

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="app_accept")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_decision(interaction, accepted=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="app_deny")
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_decision(interaction, accepted=False)


async def send_applicant_dm(bot: commands.Bot, data: dict, accepted: bool, reviewer: discord.Member, role_assigned: bool):
    try:
        user = await bot.fetch_user(int(str(data.get("discordUserId", "0")).strip() or 0))
        if user is None:
            return
        embed = build_decision_embed(data, accepted, reviewer, role_assigned)
        await user.send(embed=embed)
    except Exception as e:
        logger.warning(f"Failed to DM applicant: {e}")


async def log_application_decision(bot: commands.Bot, data: dict, accepted: bool, reviewer: discord.Member, role_assigned: bool, applicant_member: discord.Member | None):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        except Exception as e:
            logger.warning(f"Failed to fetch log channel: {e}")
            return

    embed = build_log_embed(data, accepted, reviewer, role_assigned, applicant_member)
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
        self.config = {}
        self.db = Database(DATABASE_PATH)
        self.config.update({
            "review_channel_id": REVIEW_CHANNEL_ID,
            "staff_role_id": STAFF_ROLE_ID,
            "infraction_log_channel_id": INFRACTION_LOG_CHANNEL_ID,
            "promotion_log_channel_id": PROMOTION_LOG_CHANNEL_ID,
            "embed_color": EMBED_COLOR,
            "panel_banner_url": PANEL_BANNER_URL,
            "logo_url": LOGO_URL,
        })
    
    async def setup_hook(self):
        logger.info("Setting up bot")
        
        # Load cogs
        cogs = ["cogs.moderation", "cogs.applications", "cogs.training"]
        for cog_module in cogs:
            try:
                await self.load_extension(cog_module)
                logger.info(f"Loaded {cog_module}")
            except Exception as e:
                logger.warning(f"Could not load {cog_module}: {e}")
        
        # Sync commands
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        logger.info("Commands synced")
        
        await self.start_web_server()
    
    async def on_ready(self):
        logger.info(f"Logged in as {self.user}")
    
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
                await channel.send(
                    content=f"<@&{STAFF_ROLE_ID}> A new moderator application has been submitted.",
                    embed=embed,
                    view=view
                )
                logger.info("Application sent to Discord")

                return web.json_response({"success": True}, headers=CORS_HEADERS)
            except Exception as e:
                logger.exception("Error handling application")
                return web.json_response({"success": False, "error": str(e)}, status=500, headers=CORS_HEADERS)
        
        async def handle_options(request):
            return web.Response(status=204, headers=CORS_HEADERS)
        
        try:
            app = web.Application()
            app.router.add_get("/", handle_root)
            app.router.add_get("/health", handle_health)
            app.router.add_post("/apply", handle_apply)
            app.router.add_options("/apply", handle_options)
            
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