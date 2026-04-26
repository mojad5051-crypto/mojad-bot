"""
Florida RP Discord Bot

This file contains a complete bot implementation with:
- Control hub panel
- Moderation tools (infraction, ban, promote)
- Staff application form
- Roblox verification form
- SQLite persistence for infractions, applications, and Roblox links

To use:
1. Copy config.example.json to config.json
2. Fill in token, guild_id, review_channel_id, and staff_role_id
3. Install dependencies: python -m pip install discord.py>=2.4.0 python-dotenv
4. Run: python florida_rp_bot.py

Keep your bot token secret. Never send it to anyone.
"""

import json
import logging
import sqlite3
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
DATA_PATH = BASE_DIR / "data" / "storage.sqlite"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.json is missing. Copy config.example.json to config.json and fill in your values.")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS infractions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    user_name TEXT NOT NULL,
                    age TEXT NOT NULL,
                    experience TEXT NOT NULL,
                    availability TEXT NOT NULL,
                    motivation TEXT NOT NULL,
                    status TEXT DEFAULT 'Pending',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS roblox_verifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    roblox_username TEXT NOT NULL,
                    linked_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def add_infraction(self, user_id: int, moderator_id: int, reason: str, severity: str) -> int:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO infractions (user_id, moderator_id, reason, severity) VALUES (?, ?, ?, ?)",
                (user_id, moderator_id, reason, severity),
            )
        return cursor.lastrowid

    def add_application(self, user_id: int, user_name: str, age: str, experience: str, availability: str, motivation: str) -> int:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO applications (user_id, user_name, age, experience, availability, motivation) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, user_name, age, experience, availability, motivation),
            )
        return cursor.lastrowid

    def add_roblox_verification(self, user_id: int, roblox_username: str) -> int:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO roblox_verifications (user_id, roblox_username) VALUES (?, ?)",
                (user_id, roblox_username),
            )
        return cursor.lastrowid


class InfractionModal(discord.ui.Modal, title="Issue Infraction"):
    user_id = discord.ui.TextInput(label="Discord User ID", placeholder="123456789012345678", required=True)
    severity = discord.ui.TextInput(label="Severity", placeholder="Warning / Mute / Strike", required=True)
    reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.long, required=True)

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = interaction.guild.get_member(int(self.user_id.value))
        if member is None:
            await interaction.response.send_message("Could not find that member in this server.", ephemeral=True)
            return

        infraction_id = self.bot.db.add_infraction(
            user_id=member.id,
            moderator_id=interaction.user.id,
            reason=self.reason.value,
            severity=self.severity.value,
        )

        embed = discord.Embed(
            title="Infraction Recorded",
            description=f"{member.mention} received a new infraction.",
            color=0xE74C3C,
        )
        embed.add_field(name="Severity", value=self.severity.value, inline=True)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=self.reason.value, inline=False)
        embed.set_footer(text=f"Infraction ID: {infraction_id}")

        review_channel = interaction.guild.get_channel(self.bot.config["review_channel_id"])
        if review_channel is not None:
            await review_channel.send(embed=embed)

        await interaction.response.send_message("Infraction recorded and sent to staff review.", ephemeral=True)


class BanModal(discord.ui.Modal, title="Ban Member"):
    user_id = discord.ui.TextInput(label="Discord User ID", placeholder="123456789012345678", required=True)
    reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.long, required=True)

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This interaction must be used in a server.", ephemeral=True)
            return

        try:
            user_id = int(self.user_id.value)
        except ValueError:
            await interaction.response.send_message("Please supply a valid Discord user ID.", ephemeral=True)
            return

        await guild.ban(discord.Object(id=user_id), reason=self.reason.value)

        embed = discord.Embed(
            title="User Banned",
            description=f"A ban was issued for <@{user_id}>.",
            color=0x992D22,
        )
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=self.reason.value, inline=False)

        review_channel = guild.get_channel(self.bot.config["review_channel_id"])
        if review_channel is not None:
            await review_channel.send(embed=embed)

        await interaction.response.send_message("User has been banned and the action was logged.", ephemeral=True)


class PromoteModal(discord.ui.Modal, title="Promote Member"):
    user_id = discord.ui.TextInput(label="Discord User ID", placeholder="123456789012345678", required=True)
    role_id = discord.ui.TextInput(label="Role ID", placeholder="123456789012345678", required=True)

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This interaction must be used in a server.", ephemeral=True)
            return

        try:
            user_id = int(self.user_id.value)
            role_id = int(self.role_id.value)
        except ValueError:
            await interaction.response.send_message("Please use valid numeric IDs.", ephemeral=True)
            return

        member = guild.get_member(user_id)
        role = guild.get_role(role_id)
        if member is None or role is None:
            await interaction.response.send_message("Could not find the member or role in this server.", ephemeral=True)
            return

        await member.add_roles(role, reason=f"Promoted by {interaction.user}")

        embed = discord.Embed(
            title="Member Promoted",
            description=f"{member.mention} was given the {role.name} role.",
            color=0x2ECC71,
        )
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Role", value=role.name, inline=True)

        review_channel = guild.get_channel(self.bot.config["review_channel_id"])
        if review_channel is not None:
            await review_channel.send(embed=embed)

        await interaction.response.send_message("Promotion complete and logged to staff review.", ephemeral=True)


class ModerationPanel(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        has_role = any(role.id == self.bot.config["staff_role_id"] for role in interaction.user.roles)
        if interaction.user.guild_permissions.manage_guild or has_role:
            return True
        await interaction.response.send_message("You must be staff to use this moderation panel.", ephemeral=True)
        return False

    @discord.ui.button(label="Issue Infraction", style=discord.ButtonStyle.danger, custom_id="moderation_infraction")
    async def infraction_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(InfractionModal(self.bot))

    @discord.ui.button(label="Ban Member", style=discord.ButtonStyle.secondary, custom_id="moderation_ban")
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(BanModal(self.bot))

    @discord.ui.button(label="Promote Member", style=discord.ButtonStyle.success, custom_id="moderation_promote")
    async def promote_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(PromoteModal(self.bot))


class ApplicationModal(discord.ui.Modal, title="Staff Application"):
    age = discord.ui.TextInput(label="Age", placeholder="Your age", required=True)
    experience = discord.ui.TextInput(label="Experience", style=discord.TextStyle.paragraph, placeholder="Your past roleplay or staff experience", required=True)
    availability = discord.ui.TextInput(label="Availability", placeholder="Days and times you are available", required=True)
    motivation = discord.ui.TextInput(label="Why should we accept you?", style=discord.TextStyle.paragraph, placeholder="Tell us why you want to join staff", required=True)

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        application_id = self.bot.db.add_application(
            user_id=interaction.user.id,
            user_name=str(interaction.user),
            age=self.age.value,
            experience=self.experience.value,
            availability=self.availability.value,
            motivation=self.motivation.value,
        )

        embed = discord.Embed(
            title="New Staff Application",
            description=f"Application from {interaction.user.mention}",
            color=0x3498DB,
        )
        embed.add_field(name="Age", value=self.age.value, inline=True)
        embed.add_field(name="Availability", value=self.availability.value, inline=True)
        embed.add_field(name="Experience", value=self.experience.value, inline=False)
        embed.add_field(name="Motivation", value=self.motivation.value, inline=False)
        embed.set_footer(text=f"Application ID: {application_id}")

        review_channel = interaction.guild.get_channel(self.bot.config["review_channel_id"])
        if review_channel is not None:
            await review_channel.send(embed=embed)

        await interaction.response.send_message("Your application has been submitted to staff review.", ephemeral=True)


class VerifyRobloxModal(discord.ui.Modal, title="Verify Roblox Username"):
    roblox_username = discord.ui.TextInput(label="Roblox Username", placeholder="Your Roblox username", required=True)

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.bot.db.add_roblox_verification(
            user_id=interaction.user.id,
            roblox_username=self.roblox_username.value,
        )

        embed = discord.Embed(
            title="Roblox Verification Linked",
            description=f"{interaction.user.mention} linked Roblox username **{self.roblox_username.value}**.",
            color=0x00BFFF,
        )
        embed.set_footer(text="Stored for persistent identity tracking.")

        review_channel = interaction.guild.get_channel(self.bot.config["review_channel_id"])
        if review_channel is not None:
            await review_channel.send(embed=embed)

        await interaction.response.send_message("Your Roblox account has been linked successfully.", ephemeral=True)


class ApplicationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def open_application_modal(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ApplicationModal(self.bot))

    async def open_verify_modal(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(VerifyRobloxModal(self.bot))


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self.bot.add_view(ModerationPanel(self.bot))

    async def send_moderation_panel(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Moderation Control Panel",
            description="Use these tools to manage infractions, bans, and promotions from a polished staff interface.",
            color=0xFFB347,
        )
        embed.add_field(name="Infraction", value="Issue warnings and record behavior.", inline=False)
        embed.add_field(name="Ban", value="Ban users quickly while keeping staff logs.", inline=False)
        embed.add_field(name="Promote", value="Assign roles without typing commands.", inline=False)
        await interaction.response.send_message(embed=embed, view=ModerationPanel(self.bot), ephemeral=True)


class FloridaRPBot(commands.Bot):
    def __init__(self, config: dict):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.messages = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, application_id=config.get("application_id"))
        self.config = config
        self.db = Database(DATA_PATH)
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self) -> None:
        await self.add_cog(ModerationCog(self))
        await self.add_cog(ApplicationCog(self))
        self.tree.copy_global_to(guild=discord.Object(id=self.config["guild_id"]))
        await self.tree.sync(guild=discord.Object(id=self.config["guild_id"]))

    async def on_ready(self) -> None:
        logging.info("Logged in as %s (%s)", self.user, self.user.id)
        logging.info("Connected to guild %s", self.config["guild_id"])

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
        logging.exception("Unhandled app command error")
        if interaction.response.is_done():
            return
        await interaction.response.send_message("An unexpected error occurred. Please try again later.", ephemeral=True)


config = load_config()
bot = FloridaRPBot(config)


@bot.tree.command(name="setup-panel", description="Create the Florida RP bot hub panel in the current channel.")
@app_commands.checks.has_permissions(administrator=True)
async def setup_panel(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="Florida RP Control Hub",
        description="Use the buttons below to open moderation tools, submit a staff application, or verify your Roblox username.",
        color=config["embed_color"],
    )
    embed.set_thumbnail(url=config.get("panel_banner_url", "https://i.imgur.com/Hu4KZ7h.png"))
    embed.add_field(name="Moderation", value="Staff can manage infractions, promotions, and bans from a clean panel.", inline=False)
    embed.add_field(name="Applications", value="Apply for staff with a polished modal and review embed.", inline=False)
    embed.add_field(name="Verification", value="Link your Discord account to Roblox for identity tracking.", inline=False)

    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Open Moderation Panel", style=discord.ButtonStyle.danger, custom_id="florida_rp_moderation"))
    view.add_item(discord.ui.Button(label="Apply for Staff", style=discord.ButtonStyle.primary, custom_id="florida_rp_apply"))
    view.add_item(discord.ui.Button(label="Verify Roblox", style=discord.ButtonStyle.secondary, custom_id="florida_rp_verify"))

    await interaction.response.send_message(embed=embed, view=view)


@bot.event
async def on_interaction(interaction: discord.Interaction) -> None:
    if interaction.type != discord.InteractionType.component:
        return

    custom_id = interaction.data.get("custom_id")
    if custom_id == "florida_rp_moderation":
        await bot.get_cog("ModerationCog").send_moderation_panel(interaction)
        return
    if custom_id == "florida_rp_apply":
        await bot.get_cog("ApplicationCog").open_application_modal(interaction)
        return
    if custom_id == "florida_rp_verify":
        await bot.get_cog("ApplicationCog").open_verify_modal(interaction)
        return


if __name__ == "__main__":
    bot.run(config["token"])
