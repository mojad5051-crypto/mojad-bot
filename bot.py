#!/usr/bin/env python3
import os
from aiohttp import web
from discord.ext import tasks
import discord
from dotenv import load_dotenv
import asyncio

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "test-token")
PORT = int(os.getenv("PORT", "8080"))

async def test_handler(request):
    return web.Response(text="OK", status=200)

async def start_http_server():
    app = web.Application()
    app.router.add_get("/", test_handler)
    app.router.add_get("/health", test_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"HTTP server running on port {PORT}")
    return runner

async def main():
    runner = await start_http_server()
    
    # Keep the async function running
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
