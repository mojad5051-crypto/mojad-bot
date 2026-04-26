import json
import logging
import os
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from db import Database
from cogs.applications import ApplicationCog
from cogs.moderation import ModerationCog
from cogs.training import TrainingCog, TrainingShoutView

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def load_config() -> dict:
    load_dotenv()
    config = {}
    
    # Load from environment variables (required for deployment and local with .env)
    config["token"] = os.getenv("DISCORD_TOKEN")
    if not config["token"]:
        raise ValueError("DISCORD_TOKEN environment variable is required. Set it in Railway or create a .env file locally.")
    
    config["guild_id"] = int(os.getenv("GUILD_ID", "0"))
    config["review_channel_id"] = int(os.getenv("REVIEW_CHANNEL_ID", "0"))
    config["infraction_log_channel_id"] = int(os.getenv("INFRACTION_LOG_CHANNEL_ID", "0"))
    config["promotion_log_channel_id"] = int(os.getenv("PROMOTION_LOG_CHANNEL_ID", "0"))
    config["staff_role_id"] = int(os.getenv("STAFF_ROLE_ID", "0"))
    config["embed_color"] = int(os.getenv("EMBED_COLOR", "1973790"))
    config["panel_banner_url"] = os.getenv("PANEL_BANNER_URL", "")
    config["logo_url"] = os.getenv("LOGO_URL", "")
    
    return config


config = load_config()

def get_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.guilds = True
    intents.messages = True
    intents.members = True
    intents.reactions = True
    intents.message_content = True
    return intents


class FloridaRPBot(commands.Bot):
    def __init__(self, config: dict):
        super().__init__(command_prefix="!", intents=get_intents(), application_id=config.get("application_id"))
        self.config = config
        self.db = Database(BASE_DIR / "data" / "storage.sqlite")
        self.afk_users = {}
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self) -> None:
        await self.add_cog(ModerationCog(self))
        await self.add_cog(ApplicationCog(self))
        await self.add_cog(TrainingCog(self))
        self.add_view(TrainingShoutView())
        guild = discord.Object(id=self.config["guild_id"])
        self.tree.clear_commands(guild=guild)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def on_ready(self) -> None:
        logging.info("Logged in as %s (%s)", self.user, self.user.id)
        logging.info("Connected to guild %s", self.config["guild_id"])

    async def on_raw_message_create(self, payload: discord.RawMessageCreateEvent) -> None:
        if not payload.webhook_id:
            return
        embeds = payload.data.get('embeds', [])
        if not embeds:
            return
        if payload.data.get('components'):
            return
        title = embeds[0].get('title')
        if title not in {'Moderator Application Submission', 'New Moderator Application'}:
            return

        try:
            channel = self.get_channel(payload.channel_id)
            if channel is None:
                channel = await self.fetch_channel(payload.channel_id)
            if channel is None:
                return
            embed = discord.Embed.from_dict(embeds[0])
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label='Accept', style=discord.ButtonStyle.success, custom_id='app_accept'))
            view.add_item(discord.ui.Button(label='Deny', style=discord.ButtonStyle.danger, custom_id='app_deny'))
            await channel.send(embed=embed, view=view)
            try:
                message = await channel.fetch_message(payload.message_id)
                await message.delete()
            except Exception:
                pass
        except Exception as exc:
            logging.exception('Failed to repost webhook embed with buttons in raw event: %s', exc)

    async def on_message(self, message):
        if message.webhook_id:
            return
        if message.author.bot:
            return
        if message.author.id in self.afk_users:
            reason = self.afk_users.pop(message.author.id)
            if reason:
                await message.channel.send(f"Welcome back {message.author.mention} from {reason}!")
            else:
                await message.channel.send(f"Welcome back, {message.author.mention}!")
        await self.process_commands(message)

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == self.user.id:
            return
        if payload.emoji.name not in {'✅', '❌'}:
            return

        try:
            channel = self.get_channel(payload.channel_id) or await self.fetch_channel(payload.channel_id)
            if channel is None:
                return
            message = await channel.fetch_message(payload.message_id)
            if not message.embeds:
                return
            embed = message.embeds[0]
            if embed.title not in {'Moderator Application Submission', 'New Moderator Application'}:
                return

            guild = message.guild
            if guild is None:
                return
            member = guild.get_member(payload.user_id)
            if member is None or not any(role.id == self.config['staff_role_id'] for role in member.roles):
                try:
                    await message.remove_reaction(payload.emoji.name, discord.Object(id=payload.user_id))
                except Exception:
                    pass
                return

            if embed.description and '**Review decision:**' in embed.description:
                return

            status = 'Accepted' if payload.emoji.name == '✅' else 'Denied'
            color = 0x2ecc71 if status == 'Accepted' else 0xe74c3c
            new_embed = discord.Embed(
                title=embed.title,
                description=f"{embed.description}\n\n**Review decision:** {status}",
                color=color,
            )
            for field in embed.fields:
                new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
            new_embed.set_footer(text=embed.footer.text if embed.footer else None)
            new_embed.timestamp = embed.timestamp
            await message.edit(embed=new_embed)
            try:
                await message.clear_reactions()
            except Exception:
                pass

            discord_username = None
            for field in embed.fields:
                if field.name == 'Discord Username':
                    discord_username = field.value
                    break

            target_member = None
            if discord_username:
                if discord_username.isdigit():
                    target_member = guild.get_member(int(discord_username))
                if target_member is None and '#' in discord_username:
                    name, discrim = discord_username.split('#', 1)
                    for m in guild.members:
                        if m.name == name and m.discriminator == discrim:
                            target_member = m
                            break
                if target_member is None:
                    for m in guild.members:
                        if m.name == discord_username or str(m) == discord_username:
                            target_member = m
                            break

            if target_member is not None:
                try:
                    if status == 'Accepted':
                        role = guild.get_role(1496970734919094303)
                        if role:
                            await target_member.add_roles(role, reason='Moderator application accepted')
                        await target_member.send(
                            'Congratulations! Your moderator application has been accepted for Florida State Roleplay. Welcome to the team! Please be ready for next steps and review your staff duties.'
                        )
                    else:
                        await target_member.send(
                            'We are sorry, but your moderator application has been denied. Please keep playing and feel free to reapply in the future after gaining more experience.'
                        )
                except Exception as e:
                    logging.exception('DM/role error: %s', e)
        except Exception as exc:
            logging.exception('Failed processing staff reaction on application: %s', exc)

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return
        logging.exception("Unhandled app command error")
        if interaction.response.is_done():
            return
        await interaction.response.send_message("An unexpected error occurred. Please try again later.", ephemeral=True)


bot = FloridaRPBot(config)

embed_group = app_commands.Group(name="embed", description="Embed commands")

@embed_group.command(name="aplication", description="Create a moderator application embed with a website link")
@app_commands.checks.has_permissions(administrator=True)
async def application_embed(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Moderator Application",
        description="Apply to become a moderator in Florida State Roleplay. Please click the button below to open the application form.",
        color=0x9b59b6,
    )
    embed.set_footer(text="Florida State Roleplay • Application System")
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Apply Now", style=discord.ButtonStyle.link, url="https://mojad5051-crypto.github.io/mojad/apply.html"))
    await interaction.response.send_message(embed=embed, view=view)

bot.tree.add_command(embed_group)


@bot.tree.command(name="custom_embed", description="Create a custom structured embed")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    header="The main header/title of the embed",
    description="The description text",
    section1_title="Title for the first section",
    section1_text="Text for the first section",
    section2_title="Title for the second section",
    section2_text="Text for the second section",
    footer="Footer text for the embed"
)
async def create_embed(
    interaction: discord.Interaction,
    header: str = "Welcome to Florida State Roleplay Staff Team",
    description: str = "This is your central hub for all staff tools, systems, and resources.",
    section1_title: str = "Group Commands",
    section1_text: str = "/group-request",
    section2_title: str = "Links",
    section2_text: str = "• Training Guides\n• Whitelisted Group",
    footer: str = "Florida State Roleplay • System Panel"
) -> None:
    # Create the custom embed
    embed = discord.Embed(
        color=0x2b2d31,  # Clean dark theme
    )
    
    # Build the description with structured formatting
    embed_description = f"## {header}\n{description}\n\n"
    
    if section1_title and section1_text:
        embed_description += f"**{section1_title}:**\n{section1_text}\n\n"
    
    if section2_title and section2_text:
        embed_description += f"**{section2_title}:**\n{section2_text}"
    
    embed.description = embed_description
    
    # Add logo to author section
    embed.set_author(name="Florida State Roleplay", icon_url=config.get("logo_url", ""))
    
    # Add timestamp and custom footer text
    embed.timestamp = discord.utils.utcnow()
    embed.set_footer(text=footer, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="setup-panel", description="Create the Florida RP bot hub panel in the current channel.")
@app_commands.checks.has_permissions(administrator=True)
async def setup_panel(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="🎮 FLORIDA STATE ROLEPLAY",
        description="**Professional Moderation & Management System**\n\n**Commands:**\n`/infract @user @role reason` • Issue infractions\n`/promote @user @role reason` • Promote members\n`/ban @user reason` • Ban users\n\n**Features:**\n• Staff applications & role management\n• Roblox verification system\n• Automatic logging & tracking\n• Real-time moderation reports",
        color=0x1e40af,  # Glossy blue color
    )
    embed.set_thumbnail(url=config.get("panel_banner_url", "https://i.imgur.com/Hu4KZ7h.png"))
    embed.set_author(name="Professional Moderation Panel", icon_url=config.get("logo_url", ""))
    embed.timestamp = discord.utils.utcnow()
    embed.set_footer(text="Glass UI • Florida State Roleplay • Professional System")

    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Apply for Staff", style=discord.ButtonStyle.primary, custom_id="florida_rp_apply"))
    view.add_item(discord.ui.Button(label="Verify Roblox", style=discord.ButtonStyle.secondary, custom_id="florida_rp_verify"))

    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="sync-commands", description="Sync the bot's slash commands to the guild")
@app_commands.checks.has_permissions(administrator=True)
async def sync_commands(interaction: discord.Interaction) -> None:
    await bot.tree.sync(guild=discord.Object(id=config["guild_id"]))
    await interaction.response.send_message("✅ Slash commands synced.", ephemeral=True)


@bot.tree.command(name="afk", description="Set yourself as AFK.")
@app_commands.describe(reason="The reason for going AFK (optional)")
async def afk_command(interaction: discord.Interaction, reason: str = None):
    bot.afk_users[interaction.user.id] = reason
    if reason:
        await interaction.response.send_message(f"You have been successfully set AFK due to {reason}.", ephemeral=True)
    else:
        await interaction.response.send_message("You have been successfully set AFK.", ephemeral=True)


@bot.event
async def on_interaction(interaction: discord.Interaction) -> None:
    if interaction.type != discord.InteractionType.component:
        return

    if interaction.data.get("custom_id") == "florida_rp_apply":
        embed = discord.Embed(
            title="Staff Application",
            description="To apply for staff, please fill out our detailed application form.\n\n[Click here to apply](https://mojad5051-crypto.github.io/mojad/apply.html)",
            color=0x9b59b6,
        )
        embed.set_footer(text="Florida State Roleplay • Application System")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if interaction.data.get("custom_id") == "florida_rp_verify":
        await bot.get_cog("ApplicationCog").open_verify_modal(interaction)
        return

    if interaction.data.get("custom_id") in {"app_accept", "app_deny"}:
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None or not any(role.id == bot.config["staff_role_id"] for role in member.roles):
            await interaction.response.send_message("You do not have permission to review applications.", ephemeral=True)
            return

        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if embed is None:
            await interaction.response.send_message("Unable to process this application message.", ephemeral=True)
            return

        discord_username = None
        for field in embed.fields:
            if field.name == 'Discord Username':
                discord_username = field.value
                break

        target_member = None
        if discord_username:
            guild = interaction.guild
            if guild:
                if discord_username.isdigit() and 17 <= len(discord_username) <= 19:
                    target_member = guild.get_member(int(discord_username))
                if target_member is None and '#' in discord_username:
                    name, discrim = discord_username.split('#', 1)
                    for m in guild.members:
                        if m.name == name and m.discriminator == discrim:
                            target_member = m
                            break
                if target_member is None:
                    for m in guild.members:
                        if m.name == discord_username or str(m) == discord_username:
                            target_member = m
                            break

        status = 'Accepted' if interaction.data.get('custom_id') == 'app_accept' else 'Denied'
        color = 0x2ecc71 if status == 'Accepted' else 0xe74c3c
        result_description = f"This application has been {status.lower()} by {interaction.user.mention}."

        if target_member is not None:
            try:
                if status == 'Accepted':
                    role = interaction.guild.get_role(1496970734919094303)
                    if role:
                        await target_member.add_roles(role, reason='Moderator application accepted')
                    await target_member.send(
                        "Congratulations! Your moderator application has been accepted for Florida State Roleplay. Welcome to the team! Please be ready for next steps and review your staff duties."
                    )
                else:
                    await target_member.send(
                        "We are sorry, but your moderator application has been denied. Please keep playing and feel free to reapply in the future after gaining more experience."
                    )
            except Exception as e:
                print('DM/role error:', e)

        new_embed = discord.Embed(
            title=embed.title,
            description=f"{embed.description}\n\n**Review decision:** {status}",
            color=color,
        )
        for field in embed.fields:
            new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        new_embed.set_footer(text=embed.footer.text if embed.footer else "")
        new_embed.timestamp = embed.timestamp

        disabled_view = discord.ui.View()
        disabled_view.add_item(discord.ui.Button(label='Accept', style=discord.ButtonStyle.success, custom_id='app_accept', disabled=True))
        disabled_view.add_item(discord.ui.Button(label='Deny', style=discord.ButtonStyle.danger, custom_id='app_deny', disabled=True))

        await interaction.message.edit(embed=new_embed, view=disabled_view)
        await interaction.response.send_message(f"Application {status.lower()} successfully.", ephemeral=True)
        return


if __name__ == "__main__":
    bot.run(config["token"])
