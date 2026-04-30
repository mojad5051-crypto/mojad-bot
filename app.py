from flask import Flask, request, jsonify
import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import asyncio
import threading

load_dotenv()

app = Flask(__name__)

# Discord bot setup
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
REVIEW_CHANNEL_ID = int(os.getenv("REVIEW_CHANNEL_ID", "0"))
STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID", "0"))

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

def run_bot():
    bot.run(TOKEN)

# Start Discord bot in background thread
bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/health')
def health():
    return "OK"

@app.route('/apply', methods=['POST', 'OPTIONS'])
def apply():
    if request.method == 'OPTIONS':
        response = app.make_default_options_response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

    try:
        data = request.get_json()
        print(f"Application received: {data.get('robloxUsername', 'unknown')}")

        # Send to Discord (async)
        asyncio.run_coroutine_threadsafe(send_to_discord(data), bot.loop)

        response = jsonify({"success": True})
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    except Exception as e:
        print(f"Error: {e}")
        response = jsonify({"success": False, "error": str(e)})
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response, 500

async def send_to_discord(data):
    try:
        channel = bot.get_channel(REVIEW_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="Moderator Application",
                description="New application submitted",
                color=0x1e40af
            )
            embed.add_field(name="Roblox Username", value=data.get("robloxUsername", "N/A"))
            embed.add_field(name="Discord Username", value=data.get("discordUsername", "N/A"))
            embed.add_field(name="Age", value=str(data.get("age", "N/A")))

            await channel.send(embed=embed)
            print("Application sent to Discord")
    except Exception as e:
        print(f"Discord error: {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)