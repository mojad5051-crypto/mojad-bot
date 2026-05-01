import discord
from discord.ext import commands


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

        review_channel = interaction.guild.get_channel(self.bot.config["review_channel_id"]) if interaction.guild else None
        if review_channel is not None:
            await review_channel.send(embed=embed)

        await interaction.response.send_message("Your application has been submitted to staff review.", ephemeral=True)


class VerifyRobloxModal(discord.ui.Modal, title="Verify Roblox Username"):
    roblox_username = discord.ui.TextInput(label="Roblox Username", placeholder="Your Roblox username", required=True)

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return

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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ApplicationCog(bot))
