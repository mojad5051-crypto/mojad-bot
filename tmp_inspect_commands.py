import bot

bot_instance = bot.bot
print('Commands from tree:')
for cmd in bot_instance.tree.walk_commands():
    print(cmd.name, type(cmd))
print('Cog names:', [c.__class__.__name__ for c in bot_instance.cogs.values()])
