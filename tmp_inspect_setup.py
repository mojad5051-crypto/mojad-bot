import asyncio
import bot

async def main():
    bot_instance = bot.bot
    await bot_instance.setup_hook()
    print('Commands from tree after setup_hook:')
    for cmd in bot_instance.tree.walk_commands():
        print(cmd.name, type(cmd))
    print('Cog names:', [c.__class__.__name__ for c in bot_instance.cogs.values()])

asyncio.run(main())
