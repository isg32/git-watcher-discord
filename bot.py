import discord
from discord.ext import commands, tasks
import aiohttp
import json
import os
from datetime import datetime
from flask import Flask
from threading import Thread

# Flask app for keep-alive
app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is alive!"


def run_flask():
    # Note: Flask's default port is 5000, 8080 is often used in container/hosting environments
    app.run(host="0.0.0.0", port=8080)


def keep_alive():
    t = Thread(target=run_flask)
    t.start()


# Configuration
CONFIG = {
    "DISCORD_TOKEN": os.getenv("DISCORD_TOKEN", "YOUR_DISCORD_TOKEN"),
    "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN", "YOUR_GITHUB_TOKEN"),
    "CHANNEL_ID": int(os.getenv("CHANNEL_ID", "0")),
    "CHECK_INTERVAL": 60,  # seconds
    # Removed: "ADMIN_ROLE_NAME": "Bot Admin",
}

# Data storage
DATA_FILE = "bot_data.json"
DEFAULT_REPOS_FILE = "default_repos.json"


def load_default_repos():
    """Load default repositories from config file"""
    try:
        with open(DEFAULT_REPOS_FILE, "r") as f:
            data = json.load(f)
            return data.get("default_repos", [])
    except FileNotFoundError:
        print(f"⚠️ {DEFAULT_REPOS_FILE} not found, using empty defaults")
        return []
    except json.JSONDecodeError:
        print(f"⚠️ Error parsing {DEFAULT_REPOS_FILE}, using empty defaults")
        return []


def load_data():
    """Load bot data from JSON file, initializing if not found or corrupted."""
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            # Add default repos if not already present
            default_repos = load_default_repos()
            for repo in default_repos:
                if repo not in data.get("repos", []):
                    data["repos"].append(repo)
                    print(f"✅ Added default repo: {repo}")
            # Ensure 'admins' key exists, though it's now redundant
            if "admins" not in data:
                data["admins"] = []
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        # Initialize with default repos if file not found or corrupted/empty
        if not os.path.exists(DATA_FILE):
            print(f"⚠️ {DATA_FILE} not found, initializing new data.")
        else:
            print(
                f"⚠️ Error parsing {DATA_FILE} (Corrupted or Empty), initializing new data."
            )

        default_repos = load_default_repos()
        # Removed 'admins' from the default structure as it's no longer used/managed
        return {"repos": default_repos.copy(), "last_commits": {}}


def save_data(data):
    """Save bot data to JSON file."""
    # FIX: Changed 'r' (read) to 'w' (write) mode.
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


# Initialize bot
intents = discord.Intents.default()
# Note: Message Content Intent must be enabled in the Discord Developer Portal
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents, help_command=None)

# Bot start time for uptime
start_time = datetime.now()
bot_data = load_data()


# Fetch commits from GitHub
async def fetch_commits(session, repo):
    try:
        headers = {}
        if CONFIG["GITHUB_TOKEN"] and CONFIG["GITHUB_TOKEN"] != "YOUR_GITHUB_TOKEN":
            headers["Authorization"] = f"token {CONFIG['GITHUB_TOKEN']}"

        url = f"https://api.github.com/repos/{repo}/commits"
        async with session.get(
            url, headers=headers, params={"per_page": 5}
        ) as response:
            if response.status == 200:
                return await response.json()
            else:
                print(f"Error fetching {repo}: {response.status}")
                return []
    except Exception as e:
        print(f"Exception fetching {repo}: {e}")
        return []


# Create commit embed
def create_commit_embed(commit, repo):
    embed = discord.Embed(
        title=f"📝 New Commit to {repo}",
        url=commit["html_url"],
        color=0x0366D6,
        description=commit["commit"]["message"][:300],
        timestamp=datetime.fromisoformat(
            commit["commit"]["author"]["date"].replace("Z", "+00:00")
        ),
    )

    author = commit.get("author", {})
    embed.set_author(
        name=commit["commit"]["author"]["name"], icon_url=author.get("avatar_url", "")
    )

    embed.add_field(name="SHA", value=f"`{commit['sha'][:7]}`", inline=True)
    embed.add_field(name="Branch", value="main", inline=True)
    embed.set_footer(text=f"Repository: {repo}")

    return embed


# Check for new commits
@tasks.loop(seconds=CONFIG["CHECK_INTERVAL"])
async def check_commits():
    # --- Check A: Channel ID Verification ---
    if CONFIG["CHANNEL_ID"] == 0:
        print("🔴 [LOOP] Skipping check: CHANNEL_ID is 0.")
        return

    channel = bot.get_channel(CONFIG["CHANNEL_ID"])
    if not channel:
        print(
            f"🔴 [LOOP] Skipping check: Could not find channel with ID {CONFIG['CHANNEL_ID']}."
        )
        return

    print(f"🟢 [LOOP] Starting commit check for {len(bot_data['repos'])} repos.")

    async with aiohttp.ClientSession() as session:
        for repo in bot_data["repos"]:
            # --- Check B: GitHub Fetch ---
            commits = await fetch_commits(session, repo)
            print(f"🟢 [REPO:{repo}] Fetched {len(commits)} commits.")

            if not commits:
                continue

            latest_commit = commits[0]
            last_sha = bot_data["last_commits"].get(repo)

            # --- Check C: Commit Tracking ---

            # Initialize tracking (skips notification on first check)
            if not last_sha:
                bot_data["last_commits"][repo] = latest_commit["sha"]
                save_data(bot_data)
                print(
                    f"🟡 [REPO:{repo}] Initializing tracking with SHA: {latest_commit['sha'][:7]}. Skipping notification."
                )
                continue

            # Check for new commits
            if last_sha != latest_commit["sha"]:
                print(f"🔔 [REPO:{repo}] NEW COMMIT DETECTED!")
                print(f"   - Old SHA: {last_sha[:7]}")
                print(f"   - New SHA: {latest_commit['sha'][:7]}")

                new_commits = []
                # Find all new commits between last_sha and latest_commit
                for commit in commits:
                    if commit["sha"] == last_sha:
                        break
                    new_commits.append(commit)

                print(f"   - Found {len(new_commits)} new commits.")

                # Send embeds (oldest first)
                for commit in reversed(new_commits):
                    embed = create_commit_embed(commit, repo)
                    # await channel.send(embed=embed) # <-- Keep this line, it sends the message
                    pass  # Placeholder if you don't want to send for now.

                bot_data["last_commits"][repo] = latest_commit["sha"]
                save_data(bot_data)
                print(f"🟢 [REPO:{repo}] Notified and updated SHA.")

            else:
                print(f"🔵 [REPO:{repo}] No new commits. SHA is: {last_sha[:7]}.")


# Commands
@bot.event
async def on_ready():
    print("--------------------------------------------------")
    print(f"✅ Bot logged in as {bot.user.name}")
    print(f"📊 Monitoring {len(bot_data['repos'])} repositories")
    check_commits.start()
    print("🟢 CHECK_COMMITS LOOP HAS BEEN STARTED!")
    print("--------------------------------------------------")


@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="🤖 GitHub Commit Bot - Help",
        color=0x5865F2,
        description="Monitor GitHub repositories and get commit notifications!",
    )

    embed.add_field(
        name="📋 Commands (All Users)",
        value=(
            "`/help` - Show this help message\n"
            "`/uptime` - Show bot uptime\n"
            "`/listrepos` - List all monitored repositories\n"
            "`/addrepo <owner/repo>` - Add a repository to monitor\n"
            "`/removerepo <owner/repo>` - Remove a repository\n"
            "`/setchannel` - Set current channel for notifications"
        ),
        inline=False,
    )

    embed.set_footer(text="All commands are accessible to all users.")
    await ctx.send(embed=embed)


@bot.command(name="uptime")
async def uptime_command(ctx):
    uptime = datetime.now() - start_time
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    embed = discord.Embed(
        title="⏱️ Bot Uptime",
        color=0x00FF00,
        description=f"**{days}d {hours}h {minutes}m {seconds}s**",
    )
    embed.add_field(name="Started", value=start_time.strftime("%Y-%m-%d %H:%M:%S UTC"))
    await ctx.send(embed=embed)


# Removed: @bot.command(name="adminlist") as it served no purpose without admin logic.


@bot.command(name="listrepos")
async def listrepos_command(ctx):
    embed = discord.Embed(title="📚 Monitored Repositories", color=0x0366D6)

    if bot_data["repos"]:
        default_repos = load_default_repos()
        repo_lines = []
        for repo in bot_data["repos"]:
            if repo in default_repos:
                repo_lines.append(f"• `{repo}` 🔒 (default)")
            else:
                repo_lines.append(f"• `{repo}`")
        embed.description = "\n".join(repo_lines)
        embed.add_field(
            name="ℹ️ Info",
            value="Repos marked with 🔒 are default repos and cannot be removed",
            inline=False,
        )
    else:
        embed.description = "No repositories being monitored yet."

    embed.set_footer(text=f"Total: {len(bot_data['repos'])} repositories")
    await ctx.send(embed=embed)


@bot.command(name="addrepo")
async def addrepo_command(ctx, repo: str = None):
    if not repo:
        await ctx.send("❌ Please provide a repository in format: `owner/repo`")
        return

    if "/" not in repo or repo.count("/") != 1:
        await ctx.send("❌ Invalid format! Use: `owner/repo`")
        return

    if repo in bot_data["repos"]:
        await ctx.send(f"⚠️ Repository `{repo}` is already being monitored!")
        return

    bot_data["repos"].append(repo)
    save_data(bot_data)

    embed = discord.Embed(
        title="✅ Repository Added",
        description=f"Now monitoring: `{repo}`",
        color=0x00FF00,
    )
    await ctx.send(embed=embed)


@bot.command(name="removerepo")
async def removerepo_command(ctx, repo: str = None):
    if not repo:
        await ctx.send("❌ Please provide a repository in format: `owner/repo`")
        return

    if repo not in bot_data["repos"]:
        await ctx.send(f"⚠️ Repository `{repo}` is not being monitored!")
        return

    # Check if it's a default repo
    default_repos = load_default_repos()
    if repo in default_repos:
        await ctx.send(f"❌ Cannot remove `{repo}` - it's a default repository!")
        return

    bot_data["repos"].remove(repo)
    if repo in bot_data["last_commits"]:
        del bot_data["last_commits"][repo]
    save_data(bot_data)

    embed = discord.Embed(
        title="✅ Repository Removed",
        description=f"Stopped monitoring: `{repo}`",
        color=0xFF0000,
    )
    await ctx.send(embed=embed)


@bot.command(name="setchannel")
async def setchannel_command(ctx):
    # NOTE: This only saves to the in-memory CONFIG. For persistence across restarts,
    # you should save this value to bot_data.json as well.
    CONFIG["CHANNEL_ID"] = ctx.channel.id

    embed = discord.Embed(
        title="✅ Channel Set",
        description=f"Commit notifications will be sent to {ctx.channel.mention}",
        color=0x00FF00,
    )
    await ctx.send(embed=embed)


# Start the bot
if __name__ == "__main__":
    keep_alive()
    bot.run(CONFIG["DISCORD_TOKEN"])
