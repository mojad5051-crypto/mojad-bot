import re

import discord
from discord import app_commands
from discord.ext import commands


def get_bot_config(bot: commands.Bot) -> dict:
    return getattr(bot, "config", {})


def can_manage_assistance(interaction: discord.Interaction, bot: commands.Bot) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild:
        return True
    staff_role_id = int(get_bot_config(bot).get("staff_role_id", 0) or 0)
    return any(role.id == staff_role_id for role in interaction.user.roles)


def sanitize_name(value: str, *, fallback: str) -> str:
    safe = re.sub(r"[^a-z0-9-]", "-", value.lower())
    safe = re.sub(r"-{2,}", "-", safe).strip("-")
    if not safe:
        return fallback
    return safe[:50]


def get_next_ticket_case(bot: commands.Bot, guild: discord.Guild) -> int:
    if not hasattr(bot, "ticket_case_counter_by_guild"):
        bot.ticket_case_counter_by_guild = {}

    current = bot.ticket_case_counter_by_guild.get(guild.id)
    if current is None:
        current = 1000
        for channel in guild.channels:
            if isinstance(channel, discord.TextChannel):
                parsed = parse_topic(getattr(channel, "topic", ""))
                case_number = parsed.get("case_number", 0)
                if case_number and case_number >= current:
                    current = case_number + 1
    bot.ticket_case_counter_by_guild[guild.id] = current + 1
    return current


def find_ticket_channel_by_case(guild: discord.Guild, case_number: int) -> discord.TextChannel | None:
    for channel in guild.channels:
        if isinstance(channel, discord.TextChannel):
            parsed = parse_topic(getattr(channel, "topic", ""))
            if parsed.get("case_number") == case_number:
                return channel
    return None


SUPPORT_OPTIONS = {
    "general": {
        "label": "General Support",
        "description": "For questions, help, or general assistance",
        "rank": 1,
        "roles": [1496986660691513505, 1496970679558606848],
        "channel_id": 1499770596622340157,
    },
    "internal": {
        "label": "Internal Affairs Support",
        "description": "For reporting staff members or internal issues",
        "rank": 2,
        "roles": [1496970664790196344],
        "channel_id": 1499844111996555404,
    },
    "management": {
        "label": "Management Support",
        "description": "For sponsorships, transfers, advertisements, and high-priority matters",
        "rank": 3,
        "roles": [1496970658557464586],
        "channel_id": 1499844483221557308,
    },
    "directive": {
        "label": "Directive Support",
        "description": "For extremely critical issues requiring top-level handling",
        "rank": 4,
        "roles": [1496970649527255110],
        "channel_id": 1499844652558455025,
    },
}

TICKET_TARGET_CHANNEL_ID = 1499770596622340157


def roles_for_visibility(selected_key: str) -> list[int]:
    selected_rank = SUPPORT_OPTIONS[selected_key]["rank"]
    role_ids: set[int] = set()
    for option in SUPPORT_OPTIONS.values():
        if option["rank"] >= selected_rank:
            role_ids.update(option["roles"])
    return sorted(role_ids)


def build_topic(*, opener_id: int, support_key: str, support_label: str, case_number: int, claimed_by: int | None = None) -> str:
    claim_part = f"claimed={claimed_by}" if claimed_by is not None else "claimed=none"
    return f"assist opener={opener_id} type={support_key} label={support_label} case={case_number} {claim_part}"


def parse_topic(topic: str | None) -> dict:
    raw = topic or ""
    opener_match = re.search(r"opener=(\d+)", raw)
    type_match = re.search(r"type=([a-z]+)", raw)
    case_match = re.search(r"case=(\d+)", raw)
    claimed_match = re.search(r"claimed=([a-z0-9]+)", raw)
    return {
        "opener_id": int(opener_match.group(1)) if opener_match else 0,
        "support_key": type_match.group(1) if type_match else "",
        "case_number": int(case_match.group(1)) if case_match else 0,
        "claimed_by": int(claimed_match.group(1)) if claimed_match and claimed_match.group(1).isdigit() else None,
    }


class CloseTicketReasonModal(discord.ui.Modal, title="Close Assistance Ticket"):
    reason = discord.ui.TextInput(
        label="Reason for closing this ticket",
        style=discord.TextStyle.long,
        required=True,
        max_length=1000,
        placeholder="This reason will be sent to the ticket creator via DM.",
    )

    def __init__(self, *, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("This can only be used in a server ticket channel.", ephemeral=True)
            return

        if not can_manage_assistance(interaction, self.bot):
            await interaction.response.send_message("You do not have permission to close tickets.", ephemeral=True)
            return

        parsed = parse_topic(interaction.channel.topic if hasattr(interaction.channel, "topic") else "")
        opener_id = parsed["opener_id"]
        dm_status = "Not sent (ticket opener unknown)"
        opener_mention = "Unknown"

        if opener_id:
            opener_mention = f"<@{opener_id}>"
            try:
                opener_member = interaction.guild.get_member(opener_id)
                if opener_member is None:
                    opener_member = await interaction.guild.fetch_member(opener_id)
                dm_embed = discord.Embed(
                    title="Assistance Ticket Closed",
                    description="Your assistance ticket has been closed by staff.",
                    color=0xE74C3C,
                    timestamp=discord.utils.utcnow(),
                )
                dm_embed.add_field(name="Closed by", value=interaction.user.mention, inline=True)
                dm_embed.add_field(name="Reason", value=self.reason.value.strip(), inline=False)
                dm_embed.set_footer(text="Florida State Roleplay • Assistance")
                await opener_member.send(embed=dm_embed)
                dm_status = "Sent"
            except discord.Forbidden:
                dm_status = "Failed (user has DMs closed)"
            except Exception:
                dm_status = "Failed (unexpected error)"

        await interaction.response.send_message(
            (
                f"Ticket will be closed.\n"
                f"- User: {opener_mention}\n"
                f"- DM status: {dm_status}\n"
                f"- Reason: {self.reason.value.strip()}"
            ),
            ephemeral=False,
        )
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user} - {self.reason.value.strip()}")


class TicketActionView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not can_manage_assistance(interaction, self.bot):
            await interaction.response.send_message("Only staff can manage assistance tickets.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, custom_id="assist_claim")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("This can only be used in a server ticket channel.", ephemeral=True)
            return

        parsed = parse_topic(getattr(interaction.channel, "topic", ""))
        opener_id = parsed["opener_id"]
        support_key = parsed["support_key"] or "general"
        support_label = SUPPORT_OPTIONS.get(support_key, SUPPORT_OPTIONS["general"])["label"]
        opener_name = sanitize_name((interaction.channel.name or "user").replace("🔴-", "").replace("🟢-", ""), fallback="user")
        if opener_id:
            opener_member = interaction.guild.get_member(opener_id)
            if opener_member is not None:
                opener_name = sanitize_name(opener_member.name, fallback="user")

        case_number = parsed.get("case_number", 0)
        case_prefix = f"case-{case_number}-" if case_number else ""
        new_name = f"🟢-{case_prefix}{opener_name}-claimed-by-{sanitize_name(interaction.user.name, fallback='staff')}"
        await interaction.response.defer(ephemeral=False, thinking=False)
        try:
            # Lock the ticket for writing but keep it visible to everyone.
            overwrites = interaction.channel.overwrites.copy()

            # Everyone can still view the ticket, but cannot send messages.
            overwrites[interaction.guild.default_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                read_message_history=True,
            )

            # Keep support roles able to view but not send.
            visible_role_ids = roles_for_visibility(support_key)
            for role_id in visible_role_ids:
                role = interaction.guild.get_role(role_id)
                if role is not None:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=False,
                        read_message_history=True,
                    )

            # Openers should still be able to participate.
            opener_member = interaction.guild.get_member(opener_id) if opener_id else None
            if opener_member:
                overwrites[opener_member] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                )

            # Claiming staff can still send and manage messages.
            overwrites[interaction.user] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                manage_messages=True,
            )

            # Bot permissions
            overwrites[interaction.guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
            )

            await interaction.channel.edit(
                name=new_name[:95],
                topic=build_topic(opener_id=opener_id, support_key=support_key, support_label=support_label, case_number=case_number, claimed_by=interaction.user.id),
                overwrites=overwrites,
                reason=f"Ticket claimed by {interaction.user}",
            )
            await interaction.followup.send(f"Ticket claimed by {interaction.user.mention}. This ticket is now read-only for others.", ephemeral=False)
        except discord.Forbidden:
            await interaction.followup.send("I could not claim this ticket (missing Manage Channels permission).", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"Failed to claim ticket: {exc}", ephemeral=True)

    @discord.ui.button(label="Unclaim", style=discord.ButtonStyle.secondary, custom_id="assist_unclaim")
    async def unclaim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("This can only be used in a server ticket channel.", ephemeral=True)
            return

        parsed = parse_topic(getattr(interaction.channel, "topic", ""))
        opener_id = parsed["opener_id"]
        support_key = parsed["support_key"] or "general"
        support_label = SUPPORT_OPTIONS.get(support_key, SUPPORT_OPTIONS["general"])["label"]
        opener_name = "user"
        if opener_id:
            opener_member = interaction.guild.get_member(opener_id)
            if opener_member is not None:
                opener_name = sanitize_name(opener_member.name, fallback="user")
            else:
                opener_name = sanitize_name(str(opener_id), fallback="user")

        case_number = parsed.get("case_number", 0)
        case_prefix = f"case-{case_number}-" if case_number else ""
        new_name = f"🔴-{case_prefix}{opener_name}-assistance"
        await interaction.response.defer(ephemeral=False, thinking=False)
        try:
            await interaction.channel.edit(
                name=new_name[:95],
                topic=build_topic(opener_id=opener_id, support_key=support_key, support_label=support_label, case_number=case_number, claimed_by=None),
                reason=f"Ticket unclaimed by {interaction.user}",
            )
            await interaction.followup.send("Ticket unclaimed and reset to open status.", ephemeral=False)
        except discord.Forbidden:
            await interaction.followup.send("I could not unclaim this ticket (missing Manage Channels permission).", ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(f"Failed to unclaim ticket: {exc}", ephemeral=True)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="assist_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(CloseTicketReasonModal(bot=self.bot))


class AssistanceReasonModal(discord.ui.Modal, title="Assistance Ticket Reason"):
    reason = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.long,
        required=True,
        max_length=1000,
        placeholder="Explain what you need help with.",
    )

    def __init__(self, *, bot: commands.Bot, support_key: str):
        super().__init__()
        self.bot = bot
        self.support_key = support_key

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        option = SUPPORT_OPTIONS[self.support_key]
        visible_role_ids = roles_for_visibility(self.support_key)
        selected_role_ids = option["roles"]

        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True),
        }

        for role_id in visible_role_ids:
            role = interaction.guild.get_role(role_id)
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        case_number = get_next_ticket_case(self.bot, interaction.guild)
        ticket_name = f"🔴-case-{case_number}-{sanitize_name(interaction.user.name, fallback='user')}-assistance"
        category = interaction.channel.category if interaction.channel is not None else None
        anchor_channel = interaction.guild.get_channel(option.get("channel_id") or TICKET_TARGET_CHANNEL_ID)
        if anchor_channel is not None:
            if isinstance(anchor_channel, discord.CategoryChannel):
                category = anchor_channel
            elif isinstance(anchor_channel, discord.TextChannel):
                category = anchor_channel.category or category

        channel = await interaction.guild.create_text_channel(
            name=ticket_name[:95],
            overwrites=overwrites,
            category=category,
            topic=build_topic(
                opener_id=interaction.user.id,
                support_key=self.support_key,
                support_label=option["label"],
                case_number=case_number,
                claimed_by=None,
            ),
            reason=f"Assistance ticket created by {interaction.user}",
        )
        if anchor_channel is not None and isinstance(anchor_channel, discord.TextChannel):
            try:
                # Place tickets just under the configured anchor channel.
                await channel.edit(position=anchor_channel.position + 1, reason="Position assistance ticket near configured anchor channel")
            except Exception:
                pass

        selected_role_mentions = " ".join(f"<@&{rid}>" for rid in selected_role_ids)

        embed = discord.Embed(
            title="Assistance Ticket Opened",
            description="Your ticket has been created and routed to the correct support team.",
            color=0x1E40AF,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Support Type", value=option["label"], inline=True)
        embed.add_field(name="Ticket Case", value=f"#{case_number}", inline=True)
        embed.add_field(name="Created By", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=self.reason.value.strip(), inline=False)
        embed.add_field(name="Assigned Team", value=selected_role_mentions or "No roles configured", inline=False)
        embed.set_footer(text="Florida State Roleplay • Assistance System")

        await channel.send(content=f"{interaction.user.mention} {selected_role_mentions}".strip(), embed=embed, view=TicketActionView(self.bot))
        await interaction.response.send_message(f"Your ticket was created: {channel.mention}", ephemeral=True)


class AssistanceDropdown(discord.ui.Select):
    def __init__(self, bot: commands.Bot):
        options = [
            discord.SelectOption(
                label=SUPPORT_OPTIONS["general"]["label"],
                value="general",
                description=SUPPORT_OPTIONS["general"]["description"][:100],
                emoji="🧩",
            ),
            discord.SelectOption(
                label=SUPPORT_OPTIONS["internal"]["label"],
                value="internal",
                description=SUPPORT_OPTIONS["internal"]["description"][:100],
                emoji="🛡️",
            ),
            discord.SelectOption(
                label=SUPPORT_OPTIONS["management"]["label"],
                value="management",
                description=SUPPORT_OPTIONS["management"]["description"][:100],
                emoji="📈",
            ),
            discord.SelectOption(
                label=SUPPORT_OPTIONS["directive"]["label"],
                value="directive",
                description=SUPPORT_OPTIONS["directive"]["description"][:100],
                emoji="🚨",
            ),
        ]
        super().__init__(
            placeholder="Choose the assistance type...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="assistance_support_dropdown",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0]
        await interaction.response.send_modal(AssistanceReasonModal(bot=self.bot, support_key=selected))


class AssistancePanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.add_item(AssistanceDropdown(bot))


class AssistanceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="assistance", description="Post the assistance ticket panel with support options.")
    @app_commands.default_permissions(administrator=True)
    async def assistance_command(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Only administrators can use this command.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Assistance Ticket System",
            description=(
                "Select the type of assistance you need from the dropdown below.\n\n"
                "**Support Types**\n"
                "• **General Support** - For questions, help, or general assistance\n"
                "• **Internal Affairs Support** - For reporting staff members or internal issues\n"
                "• **Management Support** - For high-priority matters like sponsorships, transfers, and advertisements\n"
                "• **Directive Support** - For extremely critical issues"
            ),
            color=0x1E40AF,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Florida State Roleplay • Assistance")
        embed.set_image(url="https://media.discordapp.net/attachments/1500075037959389265/1500188190043275325/IMG_8648.png?ex=69f786a0&is=69f63520&hm=7e4d109b860eb5c844f0c7b9ad2a2e534860a92b6bbb69122d285646f97a225a&=&format=webp&quality=lossless&width=1156&height=441")

        await interaction.response.send_message(embed=embed, view=AssistancePanelView(self.bot))

    @app_commands.command(name="ticket", description="Manage ticket access permissions.")
    @app_commands.describe(action="The action to perform", case="The ticket case number", user="The user to grant access to")
    @app_commands.choices(action=[app_commands.Choice(name="access", value="access")])
    async def ticket_command(self, interaction: discord.Interaction, action: app_commands.Choice[str], case: int, user: discord.Member) -> None:
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("This command can only be used in a server channel.", ephemeral=True)
            return

        if not can_manage_assistance(interaction, self.bot):
            await interaction.response.send_message("You do not have permission to manage ticket access.", ephemeral=True)
            return

        if action.value == "access":
            ticket_channel = find_ticket_channel_by_case(interaction.guild, case)
            if ticket_channel is None:
                await interaction.response.send_message(f"Could not find ticket case #{case}.", ephemeral=True)
                return
            try:
                overwrites = ticket_channel.overwrites.copy()
                overwrites[user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
                await ticket_channel.edit(overwrites=overwrites, reason=f"Access granted to {user} by {interaction.user}")
                await interaction.response.send_message(f"✅ Granted access to {user.mention} in ticket case #{case}.", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("I don't have permission to modify channel permissions.", ephemeral=True)
            except Exception as exc:
                await interaction.response.send_message(f"Failed to grant access: {exc}", ephemeral=True)

    @app_commands.command(name="access", description="Request or manage access for assistance.")
    @app_commands.describe(action="The action to perform", case="The ticket case number", user="The user requesting assistance")
    @app_commands.choices(action=[app_commands.Choice(name="request", value="request")])
    async def access_command(self, interaction: discord.Interaction, action: app_commands.Choice[str], case: int, user: discord.Member) -> None:
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("This command can only be used in a server channel.", ephemeral=True)
            return

        if not can_manage_assistance(interaction, self.bot):
            await interaction.response.send_message("You do not have permission to manage access requests.", ephemeral=True)
            return

        if action.value == "request":
            ticket_channel = interaction.channel
            if ticket_channel is None or parse_topic(getattr(ticket_channel, "topic", "")).get("case_number", 0) == 0:
                ticket_channel = find_ticket_channel_by_case(interaction.guild, case)
            if ticket_channel is None:
                await interaction.response.send_message(f"Could not find ticket case #{case}.", ephemeral=True)
                return
            try:
                await ticket_channel.send(
                    f"🔔 Access request received: {user.mention} has requested access to ticket case #{case}.\n"
                    f"Staff can approve access by running `/ticket access {case} {user.mention}`."
                )
                await interaction.response.send_message(
                    f"✅ Access request announced in ticket case #{case}. Use `/ticket access {case} {user.mention}` to grant access.",
                    ephemeral=True,
                )
            except discord.Forbidden:
                await interaction.response.send_message("I don't have permission to send messages in this ticket.", ephemeral=True)
            except Exception as exc:
                await interaction.response.send_message(f"Failed to announce access request: {exc}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AssistanceCog(bot))
    bot.add_view(AssistancePanelView(bot))
    bot.add_view(TicketActionView(bot))
