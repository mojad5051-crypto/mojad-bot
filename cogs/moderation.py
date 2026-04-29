import discord
from discord import app_commands
from discord.ext import commands


class VoidReasonModal(discord.ui.Modal, title="Void Infraction"):
    """Modal for admins to void an infraction"""
    void_reason = discord.ui.TextInput(
        label="Void Reason",
        placeholder="Enter the reason for voiding this infraction...",
        style=discord.TextStyle.paragraph,
        required=True,
        min_length=5,
        max_length=500
    )

    def __init__(self, infraction_id: int, user_id: int, role_to_remove: discord.Role, bot: commands.Bot, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.infraction_id = infraction_id
        self.user_id = user_id
        self.role_to_remove = role_to_remove
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle void submission by admin"""
        try:
            # Get the user
            user = interaction.guild.get_member(self.user_id)
            if user is None:
                await interaction.response.send_message("User not found in the server.", ephemeral=True)
                return

            # Remove the infraction role
            if self.role_to_remove and self.role_to_remove in user.roles:
                await user.remove_roles(self.role_to_remove, reason=f"Infraction voided: {self.void_reason.value}")

            # Update the database - set status to Expired
            self.bot.db.update_infraction_status(
                self.infraction_id,
                status="Expired",
                void_reason=self.void_reason.value
            )

            # Create confirmation embed
            embed = discord.Embed(
                title="🗑️ Infraction Voided",
                description=f"**Member:** {user.mention}\n**Status:** Infraction Expired",
                color=0xff6b6b,  # Red color
            )
            embed.add_field(name="👤 Voided By", value=interaction.user.mention, inline=False)
            embed.add_field(name="📝 Void Reason", value=f"*{self.void_reason.value}*", inline=False)
            embed.add_field(name="📌 Role Removed", value=f"`{self.role_to_remove.name}`", inline=False)
            embed.timestamp = discord.utils.utcnow()
            embed.set_footer(text=f"Infraction ID: {self.infraction_id}")

            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {str(e)}", ephemeral=True)


class VoidButton(discord.ui.Button):
    """Button for admins to void an infraction"""
    def __init__(self, infraction_id: int, user_id: int, role_to_remove: discord.Role, bot: commands.Bot, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.infraction_id = infraction_id
        self.user_id = user_id
        self.role_to_remove = role_to_remove
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle void button click - admin only"""
        # Check if user is admin
        has_admin_role = any(role.id == self.bot.config["staff_role_id"] for role in interaction.user.roles)
        if not (interaction.user.guild_permissions.manage_guild or has_admin_role):
            await interaction.response.send_message("❌ Only administrators can void infractions.", ephemeral=True)
            return

        # Show the void reason modal
        modal = VoidReasonModal(
            self.infraction_id,
            self.user_id,
            self.role_to_remove,
            self.bot
        )
        await interaction.response.send_modal(modal)


class InfractionView(discord.ui.View):
    """View with void button for infractions"""
    def __init__(self, infraction_id: int, user_id: int, role_to_remove: discord.Role, bot: commands.Bot):
        super().__init__(timeout=None)
        button = VoidButton(
            infraction_id,
            user_id,
            role_to_remove,
            bot,
            label="Void Infraction (Admin Only)",
            style=discord.ButtonStyle.danger,
            custom_id=f"void_infraction_{infraction_id}"
        )
        self.add_item(button)


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="infract", description="Issue an infraction to a user by assigning a role")
    @app_commands.choices(status=[
        app_commands.Choice(name="Appealable", value="Appealable"),
        app_commands.Choice(name="Unappealable", value="Unappealable")
    ])
    @app_commands.describe(
        user="The user to infract",
        role="The role to assign for the infraction",
        reason="The reason for the infraction",
        status="Whether the user can appeal this infraction"
    )
    async def infract_command(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        role: discord.Role,
        reason: str,
        status: app_commands.Choice[str] = None
    ) -> None:
        """Issue an infraction to a user"""
        # Check permissions
        has_role = any(role.id == self.bot.config["staff_role_id"] for role in interaction.user.roles)
        if not (interaction.user.guild_permissions.manage_guild or has_role):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        # Set appeal status - default to Appealable
        appeal_status = status.value if status else "Appealable"

        # Assign role
        await user.add_roles(role, reason=f"Infraction: {reason}")

        # Record in database
        infraction_id = self.bot.db.add_infraction(
            user_id=user.id,
            moderator_id=interaction.user.id,
            reason=reason,
            severity=f"Role: {role.name}",
            appeal_status=appeal_status
        )

        # Create embed with glass-like modern design
        embed = discord.Embed(
            title="⚠️ INFRACTION ISSUED",
            description=f"**Member:** {user.mention}\n**Status:** Active Infraction",
            color=0x1e40af,  # Glossy blue color
        )
        # Add user avatar
        embed.set_thumbnail(url=user.display_avatar.url)
        
        # Add fields with clear hierarchy
        embed.add_field(name="📌 Role Assigned", value=f"`{role.name}`", inline=True)
        embed.add_field(name="👤 Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="", value="", inline=False)  # Visual separator
        embed.add_field(name="📝 Reason", value=f"*{reason}*", inline=False)
        embed.add_field(name="🔔 Appeal Status", value=f"`{appeal_status}`", inline=False)
        
        # Add moderator avatar
        embed.set_author(name="Moderation Action", icon_url=self.bot.config.get("logo_url", interaction.user.display_avatar.url))
        
        # Timestamp and footer with accent color indicator
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text=f"Infraction ID: {infraction_id} • Glass UI", icon_url=interaction.guild.icon)

        # Send to log channel
        infraction_channel = interaction.guild.get_channel(self.bot.config.get("infraction_log_channel_id") or self.bot.config["review_channel_id"])
        if infraction_channel is not None:
            # Create the view with the void button
            view = InfractionView(infraction_id, user.id, role, self.bot)
            message = await infraction_channel.send(embed=embed, view=view)

            # Create a thread for proof submission
            try:
                thread = await message.create_thread(
                    name=f"Appeal Evidence - {user.name}",
                    auto_archive_duration=1440
                )
                embed.add_field(name="📋 Evidence Thread", value=f"[Submit Proof]({thread.jump_url})", inline=False)
                await message.edit(embed=embed)
            except discord.Forbidden:
                embed.add_field(name="⚠️ Note", value="Could not create thread - bot lacks permissions.", inline=False)
                await message.edit(embed=embed)

        await interaction.response.send_message("Infraction issued and logged.", ephemeral=True)

    @app_commands.command(name="promote", description="Promote a user by assigning a new role and removing the old one")
    @app_commands.describe(user="The user to promote", role="The new role to assign", reason="The reason for the promotion")
    async def promote_command(self, interaction: discord.Interaction, user: discord.Member, role: discord.Role, reason: str) -> None:
        # Check permissions
        has_role = any(role.id == self.bot.config["staff_role_id"] for role in interaction.user.roles)
        if not (interaction.user.guild_permissions.manage_guild or has_role):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        old_role = user.top_role.name if user.top_role is not None else "No role"
        await user.add_roles(role, reason=reason)
        # Auto-remove old top role if it's not the new role and not @everyone
        if user.top_role != role and user.top_role != interaction.guild.default_role:
            await user.remove_roles(user.top_role, reason=f"Promoted to {role.name}")

        # Create embed with glass-like modern design
        embed = discord.Embed(
            title="✨ MEMBER PROMOTED",
            description=f"**Member:** {user.mention}\n**Status:** Rank Advanced",
            color=0x1e40af,  # Glossy blue color
        )
        # Add user avatar
        embed.set_thumbnail(url=user.display_avatar.url)
        
        # Add fields with clear hierarchy
        embed.add_field(name="⬜ Previous Role", value=f"`{old_role}`", inline=True)
        embed.add_field(name="⬛ New Role", value=f"`{role.name}`", inline=True)
        embed.add_field(name="", value="", inline=False)  # Visual separator
        embed.add_field(name="📝 Reason", value=f"*{reason}*", inline=False)
        
        # Add moderator avatar
        embed.set_author(name=f"Promoted by {interaction.user.name}", icon_url=self.bot.config.get("logo_url", interaction.user.display_avatar.url))
        
        # Timestamp and footer with accent color indicator
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text="Promotion Logged • Glass UI", icon_url=interaction.guild.icon)

        # Send to log channel
        promotion_channel = interaction.guild.get_channel(self.bot.config.get("promotion_log_channel_id") or self.bot.config["review_channel_id"])
        if promotion_channel is not None:
            await promotion_channel.send(embed=embed)

        await interaction.response.send_message("Member promoted successfully.", ephemeral=True)

    @app_commands.command(name="embed", description="Send a custom embed with multiple sections")
    @app_commands.describe(
        header="Main header/title of the embed",
        title1="First section title",
        description1="First section description",
        title2="Second section title",
        description2="Second section description",
        footer="Footer text",
        color="Color code (default: blue)"
    )
    async def embed_command(
        self,
        interaction: discord.Interaction,
        header: str,
        title1: str,
        description1: str,
        title2: str,
        description2: str,
        footer: str,
        color: str = "3498DB"
    ) -> None:
        """Send a custom embed with multiple fields"""
        # Check permissions
        has_role = any(role.id == self.bot.config["staff_role_id"] for role in interaction.user.roles)
        if not (interaction.user.guild_permissions.manage_guild or has_role):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        # Convert color hex to int
        try:
            color_int = int(color.replace("#", ""), 16)
        except ValueError:
            color_int = 0x3498DB  # Default blue

        embed = discord.Embed(
            title=header,
            color=color_int
        )
        embed.add_field(name=title1, value=description1, inline=False)
        embed.add_field(name=title2, value=description2, inline=False)
        embed.set_footer(text=footer)
        embed.timestamp = discord.utils.utcnow()

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="application", description="Send moderator application form")
    async def application_command(self, interaction: discord.Interaction) -> None:
        """Send moderator application embed with link to website"""
        # Create the application embed
        embed = discord.Embed(
            title="📋 MODERATOR APPLICATION",
            description="Interested in becoming a moderator? Apply now!",
            color=0x6366f1  # Indigo color
        )
        embed.set_thumbnail(url=self.bot.config.get("logo_url", ""))
        embed.add_field(
            name="📝 Application Form",
            value="Click the button below to access the moderator application form.",
            inline=False
        )
        embed.add_field(
            name="⏱️ Processing Time",
            value="Applications are reviewed within 24-48 hours.",
            inline=False
        )
        embed.add_field(
            name="✅ Requirements",
            value="• Must be 15+ years old\n• Active in the community\n• Good communication skills",
            inline=False
        )
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text="Staff Team • Glass UI")

        # Create button view
        class ApplicationView(discord.ui.View):
            def __init__(self, website_url: str):
                super().__init__(timeout=None)
                self.add_item(discord.ui.Button(
                    label="Apply Now",
                    style=discord.ButtonStyle.link,
                    url=website_url,
                    emoji="🚀"
                ))

        website_url = "https://mojad5051-crypto.github.io/mojad/apply.html"
        view = ApplicationView(website_url)

        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))