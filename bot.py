#!/usr/bin/env python3
import os
import logging
from pathlib import Path

import discord
from discord.ext import commands
from discord import app_commands
from aiohttp import web
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
REVIEW_CHANNEL_ID = int(os.getenv("REVIEW_CHANNEL_ID", "0"))
STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))

if not TOKEN or GUILD_ID == 0 or REVIEW_CHANNEL_ID == 0 or STAFF_ROLE_ID == 0:
    logger.error("Missing required environment variables")
    exit(1)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS, GET",
    "Access-Control-Allow-Headers": "Content-Type"
}


class ApplicationReviewView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="app_accept")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Application accepted!", ephemeral=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="app_deny")
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Application denied.", ephemeral=True)


class FloridaRPBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.guilds = True
        intents.reactions = True
        
        super().__init__(command_prefix="!", intents=intents)
        self.web_runner = None
    
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
                if channel:
                    embed = discord.Embed(
                        title="Moderator Application",
                        description="New application submitted",
                        color=0x1e40af
                    )
                    embed.add_field(name="Roblox Username", value=data.get("robloxUsername", "N/A"))
                    embed.add_field(name="Discord Username", value=data.get("discordUsername", "N/A"))
                    embed.add_field(name="Age", value=str(data.get("age", "N/A")))
                    
                    await channel.send(embed=embed, view=ApplicationReviewView(self))
                    logger.info("Application sent to Discord")
                
                return web.json_response({"success": True}, headers=CORS_HEADERS)
            except Exception as e:
                logger.error(f"Error: {e}")
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
            logger.error(f"Web server error: {e}")


if __name__ == "__main__":
    bot = FloridaRPBot()
    bot.run(TOKEN)