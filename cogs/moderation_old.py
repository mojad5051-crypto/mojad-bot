import discord
from discord import app_commands
from discord.ext import commands


class InfractionReasonModal(discord.ui.Modal, title="Issue Infraction"):
    reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.long, required=True)

    def __init__(self, bot: commands.Bot, member: discord.Member, severity: str):
        super().__init__()
        self.bot = bot
        self.member = member
        self.severity = severity

    async def on_submit(self, interaction: discord.Interaction) -> None:
        infraction_id = self.bot.db.add_infraction(
            user_id=self.member.id,
            moderator_id=interaction.user.id,
            reason=self.reason.value,
            severity=self.severity,
        )

        # Auto-assign role based on severity
        role_to_assign = None
        if self.severity == "W1":
            role_to_assign = interaction.guild.get_role(self.bot.config.get("w1_role_id"))
        elif self.severity == "W2":
            role_to_assign = interaction.guild.get_role(self.bot.config.get("w2_role_id"))
        elif self.severity == "W3":
            role_to_assign = interaction.guild.get_role(self.bot.config.get("w3_role_id"))
        elif self.severity == "S1":
            role_to_assign = interaction.guild.get_role(self.bot.config.get("s1_role_id"))
        elif self.severity == "S2":
            role_to_assign = interaction.guild.get_role(self.bot.config.get("s2_role_id"))
        elif self.severity == "S3":
            role_to_assign = interaction.guild.get_role(self.bot.config.get("s3_role_id"))
        elif self.severity == "Staff Blacklisted":
            role_to_assign = interaction.guild.get_role(self.bot.config.get("staff_blacklisted_role_id"))

        if role_to_assign:
            await self.member.add_roles(role_to_assign, reason=f"Infraction: {self.reason.value}")

        embed = discord.Embed(
            title="Infraction Recorded",
            description=f"{self.member.mention} received a new infraction.",
            color=0x7DD3FC,
        )
        embed.add_field(name="Severity", value=self.severity, inline=True)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=self.reason.value, inline=False)
        if role_to_assign:
            embed.add_field(name="Role Assigned", value=role_to_assign.name, inline=False)
        embed.set_footer(text=f"Infraction ID: {infraction_id} • Glass-style report")

        infraction_channel = interaction.guild.get_channel(self.bot.config.get("infraction_log_channel_id") or self.bot.config["review_channel_id"])
        if infraction_channel is not None:
            await infraction_channel.send(embed=embed)

        await interaction.response.send_message("Infraction recorded and sent to staff review.", ephemeral=True)


class InfractionSelectionView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=180.0)
        self.bot = bot
        self.member: discord.Member | None = None
        self.severity: str | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        has_role = any(role.id == self.bot.config["staff_role_id"] for role in interaction.user.roles)
        if interaction.user.guild_permissions.manage_guild or has_role:
            return True
        await interaction.response.send_message("You must be staff to use this moderation panel.", ephemeral=True)
        return False

    @discord.ui.user_select(custom_id="infraction_user", placeholder="Select the member to infract")
    async def user_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect) -> None:
        self.member = select.values[0]
        await interaction.response.send_message(
            f"Selected member: {self.member.mention}. Now choose a severity and press Continue.",
            ephemeral=True,
        )

    @discord.ui.string_select(
        custom_id="infraction_severity",
        placeholder="Select the infraction severity",
        options=[
            discord.SelectOption(label="W1", description="Warning Level 1"),
            discord.SelectOption(label="W2", description="Warning Level 2"),
            discord.SelectOption(label="W3", description="Warning Level 3"),
            discord.SelectOption(label="S1", description="Strike Level 1"),
            discord.SelectOption(label="S2", description="Strike Level 2"),
            discord.SelectOption(label="S3", description="Strike Level 3"),
            discord.SelectOption(label="Staff Blacklisted", description="Staff blacklist"),
        ],
    )
    async def severity_select(self, interaction: discord.Interaction, select: discord.ui.StringSelect) -> None:
        self.severity = select.values[0]
        await interaction.response.send_message(
            f"Severity set to **{self.severity}**. Press Continue to add a reason and submit.",
            ephemeral=True,
        )

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success)
    async def continue_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.member is None or self.severity is None:
            await interaction.response.send_message(
                "Select a member and severity before continuing.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(InfractionReasonModal(self.bot, self.member, self.severity))


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


class PromoteReasonModal(discord.ui.Modal, title="Promote Member"):
    reason = discord.ui.TextInput(label="Promotion Reason", style=discord.TextStyle.long, required=True)

    def __init__(self, bot: commands.Bot, member: discord.Member, role: discord.Role):
        super().__init__()
        self.bot = bot
        self.member = member
        self.role = role

    async def on_submit(self, interaction: discord.Interaction) -> None:
        old_role = self.member.top_role.name if self.member.top_role is not None else "No role"
        await self.member.add_roles(self.role, reason=self.reason.value)
        # Auto-remove old top role if it's not the new role and not @everyone
        if self.member.top_role != self.role and self.member.top_role != interaction.guild.default_role:
            await self.member.remove_roles(self.member.top_role, reason=f"Promoted to {self.role.name}")

        embed = discord.Embed(
            title="Member Promoted",
            description=f"{self.member.mention} earned a new role.",
            color=0x60A5FA,
        )
        embed.add_field(name="Previous Top Role", value=old_role, inline=True)
        embed.add_field(name="New Role", value=self.role.name, inline=True)
        embed.add_field(name="Reason", value=self.reason.value, inline=False)
        embed.set_footer(text=f"Promoted by {interaction.user}")

        promotion_channel = interaction.guild.get_channel(self.bot.config.get("promotion_log_channel_id") or self.bot.config["review_channel_id"])
        if promotion_channel is not None:
            await promotion_channel.send(embed=embed)

        await interaction.response.send_message("Promotion complete and logged to staff review.", ephemeral=True)


class PromotionSelectionView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=180.0)
        self.bot = bot
        self.member: discord.Member | None = None
        self.role: discord.Role | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        has_role = any(role.id == self.bot.config["staff_role_id"] for role in interaction.user.roles)
        if interaction.user.guild_permissions.manage_guild or has_role:
            return True
        await interaction.response.send_message("You must be staff to use this moderation panel.", ephemeral=True)
        return False

    @discord.ui.user_select(custom_id="promote_user", placeholder="Select a member to promote")
    async def user_select(self, interaction: discord.Interaction, select: discord.ui.UserSelect) -> None:
        self.member = select.values[0]
        await interaction.response.send_message(
            f"Selected member: {self.member.mention}. Now choose a role and press Continue.",
            ephemeral=True,
        )

    @discord.ui.role_select(custom_id="promote_role", placeholder="Select a role to assign")
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect) -> None:
        self.role = select.values[0]
        await interaction.response.send_message(
            f"Selected role: {self.role.mention}. Press Continue to finish promotion.",
            ephemeral=True,
        )

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success)
    async def continue_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.member is None or self.role is None:
            await interaction.response.send_message(
                "Select both a member and a role before continuing.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(PromoteReasonModal(self.bot, self.member, self.role))


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
        await interaction.response.send_message(
            "Select a member and severity for the infraction.",
            view=InfractionSelectionView(self.bot),
            ephemeral=True,
        )

    @discord.ui.button(label="Ban Member", style=discord.ButtonStyle.secondary, custom_id="moderation_ban")
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(BanModal(self.bot))

    @discord.ui.button(label="Promote Member", style=discord.ButtonStyle.success, custom_id="moderation_promote")
    async def promote_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "Select the member and the new role for promotion.",
            view=PromotionSelectionView(self.bot),
            ephemeral=True,
        )


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="infract", description="Issue an infraction to a user by assigning a role")
    @app_commands.describe(user="The user to infract", role="The role to assign for the infraction", reason="The reason for the infraction")
    async def infract_command(self, interaction: discord.Interaction, user: discord.Member, role: discord.Role, reason: str) -> None:
        # Check permissions
        has_role = any(role.id == self.bot.config["staff_role_id"] for role in interaction.user.roles)
        if not (interaction.user.guild_permissions.manage_guild or has_role):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        # Assign role
        await user.add_roles(role, reason=f"Infraction: {reason}")

        # Record in DB
        infraction_id = self.bot.db.add_infraction(
            user_id=user.id,
            moderator_id=interaction.user.id,
            reason=reason,
            severity=f"Role: {role.name}",
        )

        # Create embed
        embed = discord.Embed(
            title="Infraction Issued",
            description=f"{user.mention} received an infraction.",
            color=0x7DD3FC,
        )
        embed.add_field(name="Role Assigned", value=role.name, inline=True)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"Infraction ID: {infraction_id} • Glass-style report")

        # Send to log channel
        infraction_channel = interaction.guild.get_channel(self.bot.config.get("infraction_log_channel_id") or self.bot.config["review_channel_id"])
        if infraction_channel is not None:
            await infraction_channel.send(embed=embed)

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

        # Create embed
        embed = discord.Embed(
            title="Member Promoted",
            description=f"{user.mention} earned a new role.",
            color=0x60A5FA,
        )
        embed.add_field(name="Previous Top Role", value=old_role, inline=True)
        embed.add_field(name="New Role", value=role.name, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text=f"Promoted by {interaction.user}")

        # Send to log channel
        promotion_channel = interaction.guild.get_channel(self.bot.config.get("promotion_log_channel_id") or self.bot.config["review_channel_id"])
        if promotion_channel is not None:
            await promotion_channel.send(embed=embed)

        await interaction.response.send_message("Promotion complete and logged.", ephemeral=True)

    @app_commands.command(name="ban", description="Ban a user from the server")
    @app_commands.describe(user="The user to ban", reason="The reason for the ban")
    async def ban_command(self, interaction: discord.Interaction, user: discord.User, reason: str) -> None:
        # Check permissions
        has_role = any(role.id == self.bot.config["staff_role_id"] for role in interaction.user.roles)
        if not (interaction.user.guild_permissions.ban_members or has_role):
            await interaction.response.send_message("You do not have permission to ban members.", ephemeral=True)
            return

        await interaction.guild.ban(user, reason=reason)

        # Create embed
        embed = discord.Embed(
            title="User Banned",
            description=f"{user.mention} has been banned.",
            color=0x992D22,
        )
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)

        # Send to log channel
        review_channel = interaction.guild.get_channel(self.bot.config["review_channel_id"])
        if review_channel is not None:
            await review_channel.send(embed=embed)

        await interaction.response.send_message("User has been banned and the action was logged.", ephemeral=True)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(ModerationCog(bot))
