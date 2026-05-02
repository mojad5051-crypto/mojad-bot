import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
import time


def get_bot_config(bot: commands.Bot) -> dict:
    return getattr(bot, "config", {})


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
        bot_config = get_bot_config(self.bot)
        has_admin_role = any(role.id == bot_config.get("staff_role_id", 0) for role in interaction.user.roles)
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


class SessionRoleToggleButton(discord.ui.Button):
    def __init__(self, bot: commands.Bot):
        super().__init__(label="Session Role", style=discord.ButtonStyle.secondary, custom_id="ssu_toggle_role")
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This button only works in a server.", ephemeral=True)
            return

        config = get_bot_config(self.bot)
        session_role_id = int(config.get("session_role_id", 0) or 0)
        if session_role_id == 0:
            await interaction.response.send_message("Session role is not configured yet.", ephemeral=True)
            return

        role = interaction.guild.get_role(session_role_id)
        if role is None:
            await interaction.response.send_message("Configured session role was not found in this server.", ephemeral=True)
            return

        if role in interaction.user.roles:
            await interaction.user.remove_roles(role, reason="SSU panel role toggle")
            await interaction.response.send_message(f"Removed {role.mention}.", ephemeral=True)
        else:
            await interaction.user.add_roles(role, reason="SSU panel role toggle")
            await interaction.response.send_message(f"Added {role.mention}.", ephemeral=True)


class SSUPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        config = get_bot_config(bot)
        self.add_item(SessionRoleToggleButton(bot))
        join_url = str(config.get("server_online_url", "") or "").strip()
        if join_url:
            self.add_item(discord.ui.Button(label="Server Online", style=discord.ButtonStyle.link, url=join_url))


class ModerationCog(commands.Cog):
    ssu_group = app_commands.Group(name="ssu", description="Session dashboard commands")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._ssu_panels: dict[int, tuple[int, int]] = {}
        self._http_session: aiohttp.ClientSession | None = None
        self.ssu_refresh_loop.start()

    def cog_unload(self) -> None:
        self.ssu_refresh_loop.cancel()

    async def _ensure_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        return self._http_session

    def _safe_int(self, value, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _pick_stat(self, payload: dict, *keys: str, default: str = "N/A") -> str:
        for key in keys:
            if key in payload and payload[key] is not None:
                return str(payload[key])
        return default

    async def _fetch_ssu_stats(self) -> tuple[dict, bool]:
        config = get_bot_config(self.bot)
        api_url = str(config.get("ssu_api_url", "") or "").strip()
        api_key = str(config.get("ssu_api_key", "") or "").strip()
        api_mode = str(config.get("ssu_api_mode", "auto") or "auto").strip().lower()
        if not api_key:
            return {"status": "API Offline", "players": "API Offline", "staff": "API Offline", "queue": "API Offline"}, False

        def _offline():
            return {"status": "API Offline", "players": "API Offline", "staff": "API Offline", "queue": "API Offline"}, False

        async def _try_push_cache() -> tuple[dict, bool]:
            latest = getattr(self.bot, "ssu_latest_stats", {}) or {}
            last_update_ts = int(getattr(self.bot, "ssu_last_update_ts", 0) or 0)
            if latest and last_update_ts > 0 and (int(time.time()) - last_update_ts) <= 180:
                stats = {
                    "status": str(latest.get("status", "Online")),
                    "players": str(latest.get("players", "N/A")),
                    "staff": str(latest.get("staff", "N/A")),
                    "queue": str(latest.get("queue", "N/A")),
                    "server_name": str(latest.get("server_name", config.get("ssu_server_name", "Florida Sessions Roleplay"))),
                    "server_code": str(latest.get("server_code", config.get("ssu_server_code", "N/A"))),
                }
                return stats, True
            return _offline()

        async def _try_prc_v2() -> tuple[dict, bool]:
            try:
                session = await self._ensure_http_session()
                url = api_url or "https://api.policeroleplay.community/v2/server?Staff=true&Queue=true&Players=true"
                headers = {
                    "server-key": api_key,  # PRC v2 requires this header
                    "Server-Key": api_key,
                    "Accept": "application/json",
                }
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        return _offline()
                    payload = await response.json()
                    if not isinstance(payload, dict):
                        return _offline()

                    current_players = payload.get("CurrentPlayers")
                    max_players = payload.get("MaxPlayers")
                    join_key = payload.get("JoinKey")

                    # Prefer computing "staff online" from the live Players list.
                    # PRC's Staff object is not always "currently online" count.
                    staff_online = 0
                    players_list = payload.get("Players")
                    if isinstance(players_list, list):
                        for p in players_list:
                            if not isinstance(p, dict):
                                continue
                            permission = str(p.get("Permission") or "").strip().lower()
                            if permission and permission not in {"normal", "civilian", "player"}:
                                staff_online += 1
                    else:
                        staff_obj = payload.get("Staff") or {}
                        admins = staff_obj.get("Admins") or {}
                        mods = staff_obj.get("Mods") or {}
                        helpers = staff_obj.get("Helpers") or {}
                        for m in (admins, mods, helpers):
                            if isinstance(m, dict):
                                staff_online += len(m.keys())

                    queue = payload.get("Queue")
                    queue_count = len(queue) if isinstance(queue, list) else payload.get("QueueCount") or payload.get("queueCount") or "N/A"

                    status = "Online"
                    try:
                        if isinstance(current_players, int) and isinstance(max_players, int) and max_players > 0 and current_players >= max_players:
                            status = "Full"
                    except Exception:
                        pass

                    stats = {
                        "status": status,
                        "players": f"{current_players}/{max_players}" if isinstance(current_players, int) and isinstance(max_players, int) else str(current_players or "N/A"),
                        "staff": str(staff_online),
                        "queue": str(queue_count),
                        "server_name": str(payload.get("Name") or config.get("ssu_server_name", "Florida Sessions Roleplay")),
                        "server_code": str(join_key or config.get("ssu_server_code", "N/A")),
                    }
                    return stats, True
            except Exception:
                return _offline()

        # Mode selection
        if api_mode == "push":
            return await _try_push_cache()
        if api_mode == "prc":
            return await _try_prc_v2()

        # auto:
        # - if a URL is provided, use it (existing flexible parser below)
        # - else try PRC v2, then fall back to push cache
        if not api_url:
            stats, ok = await _try_prc_v2()
            if ok:
                return stats, True
            return await _try_push_cache()

        try:
            session = await self._ensure_http_session()
            headers = {
                "Authorization": f"Bearer {api_key}",
                "x-api-key": api_key,
                "X-API-Key": api_key,
                "server-key": api_key,
                "Server-Key": api_key,
                "Accept": "application/json",
            }
            async with session.get(api_url, headers=headers) as response:
                if response.status != 200:
                    return _offline()
                payload = await response.json()
                if not isinstance(payload, dict):
                    return _offline()

                players_raw = self._pick_stat(payload, "playerCount", "player_count", "players", "currentPlayers")
                max_players = self._safe_int(self._pick_stat(payload, "maxPlayers", "max_players", "capacity", default="0"), 0)
                players_int = self._safe_int(players_raw, 0)
                status_raw = self._pick_stat(payload, "serverStatus", "server_status", "status", "state", default="Online")
                status = status_raw
                if max_players > 0 and players_int >= max_players:
                    status = "Full"

                stats = {
                    "status": status,
                    "players": players_raw,
                    "staff": self._pick_stat(payload, "staffOnline", "staff_online", "staffCount", "staff", default="N/A"),
                    "queue": self._pick_stat(payload, "queueCount", "queue_count", "queue", default="N/A"),
                    "server_name": self._pick_stat(payload, "serverName", "server_name", default=str(config.get("ssu_server_name", "Florida Sessions Roleplay"))),
                    "server_code": self._pick_stat(payload, "serverCode", "server_code", default=str(config.get("ssu_server_code", "N/A"))),
                }
                return stats, True
        except Exception:
            return {"status": "API Offline", "players": "API Offline", "staff": "API Offline", "queue": "API Offline"}, False

    def _build_ssu_embed(self, *, stats: dict, api_ok: bool) -> discord.Embed:
        config = get_bot_config(self.bot)
        now_ts = int(time.time())
        session_state = getattr(self.bot, "ssu_session_state", "Shutdown")
        embed = discord.Embed(
            title="🌆 Florida Sessions Roleplay",
            description=(
                "Get updates on live player counts, queue status, and online staff.\n"
                "This panel updates automatically every 30 seconds."
            ),
            color=(0x2ECC71 if api_ok else 0xE74C3C),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="📊 Server Status",
            value=(
                f"- **Player Count:** {stats.get('players', 'N/A')}\n"
                f"- **Staff Online:** {stats.get('staff', 'N/A')}\n"
                f"- **Queue Count:** {stats.get('queue', 'N/A')}\n"
                f"- **Server Status:** {stats.get('status', 'N/A')}\n"
                f"- **Session State:** {session_state}\n"
                f"- **Last Updated:** <t:{now_ts}:R>"
            ),
            inline=False,
        )
        embed.add_field(
            name="🖥️ Server Information",
            value=(
                f"- **Server Name:** {stats.get('server_name', config.get('ssu_server_name', 'Florida Sessions Roleplay'))}\n"
                f"- **Server Owner:** {config.get('ssu_server_owner', 'Florida Sessions Management')}\n"
                f"- **Server Code:** {stats.get('server_code', config.get('ssu_server_code', 'N/A'))}"
            ),
            inline=False,
        )
        if not api_ok:
            embed.set_footer(text="API Offline - retrying every 30 seconds")
        else:
            embed.set_footer(text="Live dashboard refreshes every 30 seconds")
        return embed

    async def _refresh_ssu_panels_once(self) -> None:
        if not self._ssu_panels:
            return
        stale_message_ids: list[int] = []
        for message_id, (guild_id, channel_id) in list(self._ssu_panels.items()):
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            channel = guild.get_channel(channel_id)
            if channel is None or not isinstance(channel, discord.TextChannel):
                continue
            try:
                stats, api_ok = await self._fetch_ssu_stats()

                # Staff Online should come from Melonly on-shift role (if configured).
                config = get_bot_config(self.bot)
                shift_role_id = int(config.get("ssu_staff_online_role_id", 0) or 0)
                if shift_role_id:
                    role = guild.get_role(shift_role_id)
                    if role is not None:
                        # Count members with the on-shift role.
                        staff_online = sum(1 for m in guild.members if role in m.roles)
                        stats["staff"] = str(staff_online)

                embed = self._build_ssu_embed(stats=stats, api_ok=api_ok)
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed, view=SSUPanelView(self.bot))
            except discord.NotFound:
                # Message deleted -> remove from refresh list
                stale_message_ids.append(message_id)
            except discord.Forbidden:
                # Missing permissions -> remove from refresh list
                stale_message_ids.append(message_id)
            except Exception as exc:
                # Transient failure (rate limit, network hiccup, API glitch).
                # Keep the panel and retry on next tick.
                try:
                    logger.warning(f"SSU refresh transient failure for message {message_id}: {exc}")
                except Exception:
                    pass
        for message_id in stale_message_ids:
            self._ssu_panels.pop(message_id, None)

    @tasks.loop(seconds=30)
    async def ssu_refresh_loop(self) -> None:
        await self._refresh_ssu_panels_once()

    @ssu_refresh_loop.error
    async def ssu_refresh_loop_error(self, error: Exception) -> None:
        # Ensure the loop doesn't die permanently on an unexpected exception.
        try:
            logger.exception("SSU refresh loop crashed: %s", error)
        except Exception:
            pass
        try:
            if not self.ssu_refresh_loop.is_running():
                self.ssu_refresh_loop.start()
        except Exception:
            pass

    @ssu_refresh_loop.before_loop
    async def before_ssu_refresh_loop(self) -> None:
        await self.bot.wait_until_ready()

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
        bot_config = get_bot_config(self.bot)
        has_role = any(role.id == bot_config.get("staff_role_id", 0) for role in interaction.user.roles)
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
        bot_config = get_bot_config(self.bot)
        embed.set_author(name="Moderation Action", icon_url=bot_config.get("logo_url", interaction.user.display_avatar.url))
        
        # Timestamp and footer with accent color indicator
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text=f"Infraction ID: {infraction_id} • Glass UI", icon_url=interaction.guild.icon)

        # Send to log channel
        bot_config = get_bot_config(self.bot)
        infraction_channel = interaction.guild.get_channel(bot_config.get("infraction_log_channel_id") or bot_config.get("review_channel_id"))
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
        bot_config = get_bot_config(self.bot)
        has_role = any(role.id == bot_config.get("staff_role_id", 0) for role in interaction.user.roles)
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
        
        # Add moderator avatar and clean footer layout
        bot_config = get_bot_config(self.bot)
        embed.set_author(name=f"Promoted by {interaction.user.name}", icon_url=bot_config.get("logo_url", interaction.user.display_avatar.url))
        embed.set_image(url="https://media.discordapp.net/attachments/1500075037959389265/1500134196142670004/ASD.png?ex=69f75457&is=69f602d7&hm=46d33dbc5daeffc6acffac489c1b2624181e2c33a663af024c38727b3094a9fe&=&format=webp&quality=lossless&width=1156&height=457")
        
        # Timestamp and footer with accent color indicator
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text="Promotion Logged • Glass UI", icon_url=interaction.guild.icon)

        # Send to log channel
        promotion_channel = interaction.guild.get_channel(bot_config.get("promotion_log_channel_id") or bot_config.get("review_channel_id"))
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
        bot_config = get_bot_config(self.bot)
        has_role = any(role.id == bot_config.get("staff_role_id", 0) for role in interaction.user.roles)
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
        bot_config = get_bot_config(self.bot)
        embed.set_thumbnail(url=bot_config.get("logo_url", ""))
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

    @ssu_group.command(name="panel", description="Post a live server status dashboard that updates every 30 seconds.")
    async def ssu_panel_command(self, interaction: discord.Interaction) -> None:
        bot_config = get_bot_config(self.bot)
        has_role = any(role.id == bot_config.get("staff_role_id", 0) for role in interaction.user.roles)
        if not (interaction.user.guild_permissions.administrator or has_role):
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return

        stats, api_ok = await self._fetch_ssu_stats()
        embed = self._build_ssu_embed(stats=stats, api_ok=api_ok)
        view = SSUPanelView(self.bot)
        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()
        if interaction.guild is not None:
            self._ssu_panels[message.id] = (interaction.guild.id, interaction.channel_id)

    @ssu_group.command(name="start-stop", description="Start or shut down the session state shown on the SSU panel.")
    @app_commands.describe(action="Choose Start or Shutdown")
    @app_commands.choices(action=[
        app_commands.Choice(name="Start", value="start"),
        app_commands.Choice(name="Shutdown", value="shutdown"),
    ])
    async def ssu_start_stop_command(self, interaction: discord.Interaction, action: app_commands.Choice[str]) -> None:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Only administrators can use this command.", ephemeral=True)
            return

        new_state = "Started" if action.value == "start" else "Shutdown"
        setattr(self.bot, "ssu_session_state", new_state)
        await self._refresh_ssu_panels_once()
        await interaction.response.send_message(f"Session state updated to **{new_state}**.", ephemeral=True)

        # Notify session role in-channel so members get pinged.
        try:
            notify_role_id = 1497021079842193558
            notify_text = (
                f"<@&{notify_role_id}> **Session Started** — the server is now online."
                if new_state == "Started"
                else f"<@&{notify_role_id}> **Session Shutdown** — the server is now offline."
            )
            await interaction.channel.send(notify_text)
        except Exception:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))