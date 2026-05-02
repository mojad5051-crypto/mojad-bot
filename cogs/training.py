import time

import discord
from discord import app_commands
from discord.ext import commands


def get_bot_config(bot: commands.Bot) -> dict:
    return getattr(bot, "config", {})


def has_role_id(member: discord.Member, role_id: int) -> bool:
    role = member.guild.get_role(role_id)
    return role is not None and role in member.roles


class TrainingVoteButton(discord.ui.Button):
    def __init__(self, view: "TrainingShoutView"):
        super().__init__(label="Vote", style=discord.ButtonStyle.primary, custom_id="training_vote")
        self.training_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        if not has_role_id(interaction.user, 1496970734919094303):
            await interaction.response.send_message("❌ Only staff trainees can vote.", ephemeral=True)
            return

        if interaction.user.id in self.training_view.voters:
            await interaction.response.send_message("✅ You already voted.", ephemeral=True)
            return

        self.training_view.voters.add(interaction.user.id)
        await interaction.response.send_message("Successfully voted", ephemeral=True)


class TrainingStartButton(discord.ui.Button):
    def __init__(self, view: "TrainingShoutView"):
        super().__init__(label="Start Training", style=discord.ButtonStyle.success, custom_id="training_start")
        self.training_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        if not has_role_id(interaction.user, 1496970700097978419):
            await interaction.response.send_message("❌ Only the training team can start training.", ephemeral=True)
            return

        mentions = " ".join(f"<@{user_id}>" for user_id in self.training_view.voters) if self.training_view.voters else ""
        result_text = f"Training has been started head to briefing room {mentions}" if self.training_view.voters else "Training has been started head to briefing room"
        for item in self.training_view.children:
            item.disabled = True
        await interaction.message.edit(view=self.training_view)
        await interaction.response.defer()
        await interaction.followup.send(result_text)


class VoidTrainingButton(discord.ui.Button):
    def __init__(self, view: "TrainingShoutView"):
        super().__init__(label="Void Training", style=discord.ButtonStyle.danger, custom_id="training_void")
        self.training_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        if not has_role_id(interaction.user, 1496970700097978419):
            await interaction.response.send_message("❌ Only the training team can void training.", ephemeral=True)
            return

        for item in self.training_view.children:
            item.disabled = True
        await interaction.message.edit(view=self.training_view)
        await interaction.response.defer()
        await interaction.followup.send("Training has been voided")


class TrainingShoutView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.voters: set[int] = set()
        self.add_item(TrainingVoteButton(self))
        self.add_item(TrainingStartButton(self))
        self.add_item(VoidTrainingButton(self))


class TrainingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._recent_embed_log: dict[str, float] = {}

    def check_training_team(self, interaction: discord.Interaction) -> bool:
        """Check if user has training team role or is admin"""
        bot_config = get_bot_config(self.bot)
        has_role = any(role.id == bot_config.get("staff_role_id", 0) for role in interaction.user.roles)
        return interaction.user.guild_permissions.manage_guild or has_role

    def _embed_signature(self, channel_id: int, embed: discord.Embed) -> str:
        parts = [str(channel_id), str(embed.title), str(embed.description), str(embed.footer.text if embed.footer else "")]
        if embed.author:
            parts.extend([str(embed.author.name), str(embed.author.icon_url)])
        for field in embed.fields:
            parts.extend([str(field.name), str(field.value), str(field.inline)])
        return "::".join(parts)

    def _should_send_embed_once(self, channel_id: int, embed: discord.Embed, window_seconds: int = 5) -> bool:
        now = time.time()
        self._recent_embed_log = {
            sig: ts for sig, ts in self._recent_embed_log.items() if now - ts < window_seconds
        }
        signature = self._embed_signature(channel_id, embed)
        if signature in self._recent_embed_log:
            return False
        self._recent_embed_log[signature] = now
        return True

    @app_commands.command(name="request-training", description="Request a training session (Staff Trainees)")
    @app_commands.describe(
        when="When do you want to train? (e.g., Today, Tomorrow, Friday)",
        timezone="Your timezone (e.g., EST, PST, UTC)"
    )
    async def request_training(
        self,
        interaction: discord.Interaction,
        when: str,
        timezone: str
    ) -> None:
        """Request a training session"""
        # Require the specific trainee role to request training
        if not has_role_id(interaction.user, 1496970734919094303):
            await interaction.response.send_message("❌ You must have the Staff Trainee role to request training.", ephemeral=True)
            return

        # Create training request embed
        embed = discord.Embed(
            title="📚 TRAINING SESSION REQUESTED",
            description=f"**Trainee:** {interaction.user.mention}\n**Status:** Awaiting Trainer Assignment",
            color=0x6366f1,  # Indigo color
        )
        
        # Add trainee avatar
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        
        # Add field for training details
        embed.add_field(name="⏰ Preferred Time", value=f"`{when}`", inline=True)
        embed.add_field(name="🌍 Timezone", value=f"`{timezone}`", inline=True)
        embed.add_field(name="", value="", inline=False)  # Visual separator
        embed.add_field(name="👤 Trainee Name", value=f"`{interaction.user.name}`", inline=False)
        
        # Add footer
        bot_config = get_bot_config(self.bot)
        embed.set_author(name="Training Request System", icon_url=bot_config.get("logo_url", ""))
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text="Training Team • Glass UI", icon_url=interaction.guild.icon)

        # Send to training request channel with role mention
        training_request_channel = interaction.guild.get_channel(1496970978729791701)
        if training_request_channel is not None:
            # Get the training team role
            training_team_role = interaction.guild.get_role(1496970700097978419)
            role_mention = training_team_role.mention if training_team_role else "<@&1496970700097978419>"
            signature = self._embed_signature(training_request_channel.id, embed)
            if self._should_send_embed_once(training_request_channel.id, embed) and not self.bot.db.has_recent_embed_signature(training_request_channel.id, signature):
                await training_request_channel.send(f"{role_mention} New training request!", embed=embed)
                self.bot.db.record_embed_signature(training_request_channel.id, signature)
            else:
                await training_request_channel.send(f"{role_mention} Duplicate training request skipped.")

        await interaction.response.send_message("✅ Training request submitted! A trainer will contact you soon.", ephemeral=True)

    @app_commands.command(name="training-shout", description="Create a training shout with vote/start/void buttons")
    @app_commands.describe(
        when="When the training will take place",
        timezone="Timezone for the training session"
    )
    async def training_shout(
        self,
        interaction: discord.Interaction,
        when: str,
        timezone: str
    ) -> None:
        """Create a training shout announcement"""
        if not has_role_id(interaction.user, 1496970700097978419):
            await interaction.response.send_message("❌ Only the training team can create a training shout.", ephemeral=True)
            return

        if interaction.channel.id != 1496970973612867654:
            await interaction.response.send_message(
                "❌ This command can only be used in <#1496970973612867654>.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        embed = discord.Embed(
            title="📣 TRAINING SHOUT",
            description=f"**Host:** {interaction.user.mention}\n**When:** {when}\n**Timezone:** {timezone}\n\n**Vote button:** staff trainees can vote.\n**Start Training:** training team only.\n**Void Training:** training team only.",
            color=0x5b21b6,
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="Instructions", value="Trainees with the trainee role can click Vote. Training team can start or void.", inline=False)
        embed.set_footer(text="Training Shout • Glass UI", icon_url=self.bot.config.get("logo_url", ""))
        embed.timestamp = discord.utils.utcnow()

        shout_channel = interaction.channel
        view = TrainingShoutView()
        signature = self._embed_signature(shout_channel.id, embed)
        if self._should_send_embed_once(shout_channel.id, embed) and not self.bot.db.has_recent_embed_signature(shout_channel.id, signature):
            await shout_channel.send(embed=embed, view=view)
            self.bot.db.record_embed_signature(shout_channel.id, signature)
        else:
            await shout_channel.send("Duplicate training shout skipped.")

        # Tag staff trainees
        trainee_role = interaction.guild.get_role(1496970734919094303)
        if trainee_role:
            await shout_channel.send(f"{trainee_role.mention} Training shout posted!")

        await interaction.followup.send("✅ Training shout posted.", ephemeral=True)

    @app_commands.command(name="training-result", description="Submit training results (Trainers Only)")
    @app_commands.describe(
        trainee="The trainee being trained",
        driving="Driving skill rating (1-10)",
        spag="Spelling and Grammar rating (1-10)",
        knowledge="Knowledge rating (1-10)",
        mod_calls="Mod Calls handling rating (1-10)"
    )
    async def training_result(
        self,
        interaction: discord.Interaction,
        trainee: discord.Member,
        driving: int,
        spag: int,
        knowledge: int,
        mod_calls: int
    ) -> None:
        """Submit training results"""
        # Check if user has training team role
        if not self.check_training_team(interaction):
            await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
            return

        # Validate ratings are 1-10
        ratings = {"Driving": driving, "Spelling & Grammar": spag, "Knowledge": knowledge, "Mod Calls": mod_calls}
        for name, rating in ratings.items():
            if not (1 <= rating <= 10):
                await interaction.response.send_message(f"❌ {name} rating must be between 1 and 10.", ephemeral=True)
                return

        # Calculate average
        average = (driving + spag + knowledge + mod_calls) / 4

        # Determine pass/fail
        status = "✅ PASSED" if average >= 7 else "❌ FAILED"
        color = 0x00b894 if average >= 7 else 0xff6b6b  # Green if passed, red if failed

        # Create training result embed
        embed = discord.Embed(
            title="🎓 TRAINING RESULTS",
            description=f"**Trainee:** {trainee.mention}\n**Trainer:** {interaction.user.mention}\n**Overall Status:** {status}",
            color=color,
        )
        
        # Add trainee avatar
        embed.set_thumbnail(url=trainee.display_avatar.url)
        
        # Add individual ratings
        embed.add_field(name="🚗 Driving", value=f"`{driving}/10`", inline=True)
        embed.add_field(name="📝 Spelling & Grammar", value=f"`{spag}/10`", inline=True)
        embed.add_field(name="💡 Knowledge", value=f"`{knowledge}/10`", inline=True)
        embed.add_field(name="📞 Mod Calls", value=f"`{mod_calls}/10`", inline=True)
        embed.add_field(name="", value="", inline=False)  # Visual separator
        
        # Add average score
        embed.add_field(
            name="📊 Average Score",
            value=f"`{average:.1f}/10`",
            inline=False
        )

        # Assign or remove roles based on pass/fail result
        training_passed_role = interaction.guild.get_role(1496970687372464240)
        training_remove_role = interaction.guild.get_role(1496970734919094303)
        if average >= 7:
            if training_passed_role is not None and training_passed_role not in trainee.roles:
                await trainee.add_roles(training_passed_role, reason="Training passed")
            if training_remove_role is not None and training_remove_role in trainee.roles:
                await trainee.remove_roles(training_remove_role, reason="Training result processed")
        else:
            if training_remove_role is not None and training_remove_role in trainee.roles:
                await trainee.remove_roles(training_remove_role, reason="Training result processed")

        # Add footer
        bot_config = get_bot_config(self.bot)
        embed.set_author(name="Training System", icon_url=bot_config.get("logo_url", ""))
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text="Training Team • Glass UI", icon_url=interaction.guild.icon)

        # Send to training results channel
        training_results_channel = interaction.guild.get_channel(1496970976955727882)
        if training_results_channel is not None:
            signature = self._embed_signature(training_results_channel.id, embed)
            if self._should_send_embed_once(training_results_channel.id, embed) and not self.bot.db.has_recent_embed_signature(training_results_channel.id, signature):
                await training_results_channel.send(embed=embed)
                self.bot.db.record_embed_signature(training_results_channel.id, signature)
            else:
                await training_results_channel.send("Duplicate training result skipped.")

        await interaction.response.send_message("✅ Training results submitted and logged!", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TrainingCog(bot))
