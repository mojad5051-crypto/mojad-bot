# Florida RP Discord Bot

A Python Discord bot designed for Florida State Roleplay-style servers.

## Features

- Main panel with buttons for moderation, applications, and Roblox verification
- Staff-friendly moderation system with infraction, ban, and promotion forms
- Application submission via modal forms and review embeds
- Roblox username linking with persistent account storage
- SQLite persistence for infractions, applications, and verifications
- Clean embed-based interface with role-based access controls

## Setup

1. Copy `config.example.json` to `config.json`.
2. Fill in your Discord bot token, server IDs, and staff role ID.
3. Install requirements:

```bash
python -m pip install -r requirements.txt
```

4. Run the bot:

```bash
python bot.py
```

5. Use `/setup-panel` in your server to create the hub message.

## Deployment (24/7 Hosting)

### Railway (Recommended - Free Tier Available)

1. **Create a Railway account** at [railway.app](https://railway.app)
2. **Connect your GitHub repository** or upload your project files
3. **Set environment variables** in Railway dashboard:
   - `DISCORD_TOKEN`: Your bot token
   - `GUILD_ID`: Your Discord server ID
   - `REVIEW_CHANNEL_ID`: Channel ID for application reviews
   - `INFRACTION_LOG_CHANNEL_ID`: Channel ID for infraction logs
   - `PROMOTION_LOG_CHANNEL_ID`: Channel ID for promotion logs
   - `STAFF_ROLE_ID`: Role ID for staff permissions
   - `MODERATOR_ROLE_ID`: Role to give applicants on acceptance
   - `EMBED_COLOR`: Hex color code (default: 1973790)
   - `PANEL_BANNER_URL`: URL for panel banner image
   - `LOGO_URL`: URL for logo image

4. **Deploy** - Railway will automatically detect Python and install dependencies
5. **Monitor logs** in the Railway dashboard to ensure the bot starts successfully

### Alternative Options

- **Heroku**: Similar setup, create app and set config vars
- **VPS**: DigitalOcean, Linode, etc. - More control but requires server management
- **Render**: Free tier available, similar to Railway

## Notes

- `config.json` should never be committed to source control.
- The bot stores data in `data/storage.sqlite`.
- Make sure the bot has `Manage Roles`, `Ban Members`, `Send Messages`, and `Use Slash Commands` permissions.
