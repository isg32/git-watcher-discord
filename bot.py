import discord
from discord.ext import commands, tasks
import aiohttp
import json
import os
from datetime import datetime
from threading import Thread
import sys

# Third-party libraries (Flask for keep-alive)
from flask import Flask

# --- CONFIGURATION ---

CONFIG = {
    "DISCORD_TOKEN": os.getenv("DISCORD_TOKEN"),
    "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN"),
    # Read CHANNEL_ID as int. It will be 0 if not set.
    "CHANNEL_ID": int(os.getenv("CHANNEL_ID", "1438551192786440355")),
    "CHECK_INTERVAL": 60,  # seconds
}

# Data storage files
DATA_FILE = "bot_data.json"
DEFAULT_REPOS_FILE = "default_repos.json"


# --- KEEP-ALIVE (FLASK) ---

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is alive!"


def run_flask():
    """Runs the Flask web server in a thread."""
    app.run(host="0.0.0.0", port=8080)


def keep_alive():
    """Starts the Flask server thread."""
    t = Thread(target=run_flask)
    t.start()


# --- DATA PERSISTENCE ---


def load_default_repos():
    """Load default repositories from config file."""
    try:
        with open(DEFAULT_REPOS_FILE, "r") as f:
            data = json.load(f)
            return data.get("default_repos", [])
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"⚠️ Error with {DEFAULT_REPOS_FILE} or not found, using empty defaults.")
        return []


def load_data():
    """Load bot data from JSON file, initializing if not found or corrupted."""
    default_structure = {"repos": load_default_repos().copy(), "last_commits": {}}

    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)

            # Ensure the structure keys exist
            data.setdefault("repos", [])
            data.setdefault("last_commits", {})

            # Add default repos if missing from loaded data
            for repo in default_structure["repos"]:
                if repo not in data["repos"]:
                    data["repos"].append(repo)
                    print(f"✅ Added default repo: {repo}")

            return data

    except (FileNotFoundError, json.JSONDecodeError):
        # Initialize if file not found or corrupted/empty
        log_msg = f"⚠️ {DATA_FILE} not found or corrupted, initializing new data."
        print(log_msg)

        return default_structure


def save_data(data):
    """Save bot data to JSON file (w mode)."""
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


# --- BOT INITIALIZATION ---

intents = discord.Intents.default()
# MUST be enabled in Discord Developer Portal for commands to work
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents, help_command=None)
start_time = datetime.now()
bot_data = load_data()


# --- GITHUB LOGIC ---


async def fetch_commits(session, repo):
    """Fetches the latest commits from a GitHub repository."""
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
            elif response.status == 401:
                # Log the specific 401 error
                print(
                    f"🔴 [GITHUB] Error fetching {repo}: 401 Bad credentials. Check GITHUB_TOKEN."
                )
                return []
            else:
                print(
                    f"🔴 [GITHUB] Error fetching {repo}: {response.status} - {await response.text()}"
                )
                return []
    except Exception as e:
        print(f"🔴 [GITHUB] Exception fetching {repo}: {e}")
        return []


def create_commit_embed(commit, repo):
    """Creates a Discord embed for a new commit."""
    timestamp = datetime.fromisoformat(
        commit["commit"]["author"]["date"].replace("Z", "+00:00")
    )

    embed = discord.Embed(
        title=f"📝 New Commit to {repo}",
        url=commit["html_url"],
        color=0x0366D6,
        description=commit["commit"]["message"][:300],
        timestamp=timestamp,
    )

    author = commit.get("author", {})
    embed.set_author(
        name=commit["commit"]["author"]["name"], icon_url=author.get("avatar_url", "")
    )

    embed.add_field(name="SHA", value=f"`{commit['sha'][:7]}`", inline=True)
    embed.add_field(name="Branch", value="main", inline=True)
    embed.set_footer(text=f"Repository: {repo}")

    return embed


# --- BOT TASKS ---


@tasks.loop(seconds=CONFIG["CHECK_INTERVAL"])
async def check_commits():
    """Periodically checks monitored GitHub repos for new commits."""

    channel_id = CONFIG["CHANNEL_ID"]
    if channel_id == 0:
        print("🔴 [LOOP] Skipping check: CHANNEL_ID is 0. Use /setchannel.")
        return

    # 1. Channel Retrieval (with fetch_channel fallback)
    channel = bot.get_channel(channel_id)

    if not channel:
        try:
            # Fallback: Attempt to fetch the channel directly via API
            channel = await bot.fetch_channel(channel_id)
            print(
                f"🟡 [LOOP] Channel ID {channel_id} fetched successfully via API call."
            )
        except discord.errors.NotFound:
            print(
                f"🔴 [LOOP] Skipping check: Channel ID {channel_id} not found on Discord. Check bot's server membership/permissions."
            )
            return
        except Exception as e:
            print(f"🔴 [LOOP] Skipping check: Error fetching channel {channel_id}: {e}")
            return

    # Check if the fetched object is a TextChannel (or similar, like a Forum or Stage channel)
    if not isinstance(channel, discord.TextChannel):
        print(
            f"🔴 [LOOP] Skipping check: Channel {channel_id} is not a valid text channel for sending embeds."
        )
        return

    print(
        f"🟢 [LOOP] Starting commit check for {len(bot_data['repos'])} repos at {datetime.now().strftime('%H:%M:%S')}"
    )

    async with aiohttp.ClientSession() as session:
        for repo in bot_data["repos"]:
            commits = await fetch_commits(session, repo)
            print(f"🟢 [REPO:{repo}] Fetched {len(commits)} commits.")

            if not commits:
                continue

            latest_commit_sha = commits[0]["sha"]
            last_saved_sha = bot_data["last_commits"].get(repo)

            # Commit Tracking Logic

            if not last_saved_sha:
                bot_data["last_commits"][repo] = latest_commit_sha
                save_data(bot_data)
                print(
                    f"🟡 [REPO:{repo}] Initializing tracking with SHA: {latest_commit_sha[:7]}. Skipping notification."
                )
                continue

            if last_saved_sha != latest_commit_sha:
                print(
                    f"🔔 [REPO:{repo}] NEW COMMIT DETECTED! Old: {last_saved_sha[:7]}, New: {latest_commit_sha[:7]}"
                )

                new_commits = []
                for commit in commits:
                    if commit["sha"] == last_saved_sha:
                        break
                    new_commits.append(commit)

                print(f"   - Found {len(new_commits)} new commits.")

                # Send embeds (oldest first)
                for commit in reversed(new_commits):
                    embed = create_commit_embed(commit, repo)
                    await channel.send(embed=embed)

                # Update tracking
                bot_data["last_commits"][repo] = latest_commit_sha
                save_data(bot_data)
                print(f"🟢 [REPO:{repo}] Notified and updated SHA.")

            else:
                print(f"🔵 [REPO:{repo}] No new commits. SHA is: {last_saved_sha[:7]}.")


# --- BOT EVENTS AND COMMANDS ---


@bot.event
async def on_ready():
    """Fires when the bot is ready and connected to Discord."""
    print("--------------------------------------------------")
    print(f"✅ Bot logged in as {bot.user.name}")
    print(f"📊 Monitoring {len(bot_data['repos'])} repositories")

    # Check if the token is the default placeholder, but the bot is running
    if CONFIG["GITHUB_TOKEN"] == "YOUR_GITHUB_TOKEN":
        print("🔴 WARNING: GITHUB_TOKEN is placeholder, API calls will fail with 401.")

    check_commits.start()
    print("🟢 CHECK_COMMITS LOOP HAS BEEN STARTED!")
    print("--------------------------------------------------")


@bot.command(name="help")
async def help_command(ctx):
    """Shows the bot's help message."""
    embed = discord.Embed(
        title="🤖 GitHub Commit Bot - Help",
        color=0x5865F2,
        description="Monitor GitHub repositories and get commit notifications. All commands are public.",
    )

    embed.add_field(
        name="📋 General Commands",
        value=(
            "`/help` - Show this help message\n"
            "`/uptime` - Show bot uptime\n"
            "`/listrepos` - List all monitored repositories"
        ),
        inline=False,
    )

    embed.add_field(
        name="⚙️ Management Commands",
        value=(
            "`/addrepo <owner/repo>` - Add a repository to monitor\n"
            "`/removerepo <owner/repo>` - Remove a repository\n"
            "`/setchannel` - Set current channel for notifications"
        ),
        inline=False,
    )

    await ctx.send(embed=embed)


@bot.command(name="uptime")
async def uptime_command(ctx):
    """Shows how long the bot has been running."""
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


@bot.command(name="listrepos")
async def listrepos_command(ctx):
    """Lists all repositories currently being monitored."""
    embed = discord.Embed(title="📚 Monitored Repositories", color=0x0366D6)

    if bot_data["repos"]:
        default_repos = load_default_repos()
        repo_lines = []
        for repo in bot_data["repos"]:
            is_default = " 🔒 (default)" if repo in default_repos else ""
            repo_lines.append(f"• `{repo}`{is_default}")
        embed.description = "\n".join(repo_lines)
        embed.add_field(
            name="ℹ️ Info",
            value="Repos marked with 🔒 are default repos and cannot be removed.",
            inline=False,
        )
    else:
        embed.description = "No repositories being monitored yet."

    embed.set_footer(text=f"Total: {len(bot_data['repos'])} repositories")
    await ctx.send(embed=embed)


@bot.command(name="addrepo")
async def addrepo_command(ctx, repo: str = None):
    """Adds a GitHub repository to the monitoring list."""
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
    """Removes a repository from the monitoring list."""
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
    # Also remove its last commit SHA
    bot_data["last_commits"].pop(repo, None)
    save_data(bot_data)

    embed = discord.Embed(
        title="✅ Repository Removed",
        description=f"Stopped monitoring: `{repo}`",
        color=0xFF0000,
    )
    await ctx.send(embed=embed)


@bot.command(name="setchannel")
async def setchannel_command(ctx):
    """Sets the current channel as the destination for commit notifications."""

    # NOTE: This only saves to the in-memory CONFIG. For persistence across restarts,
    # you would need to save this value to bot_data.json and update load_data/CONFIG.
    CONFIG["CHANNEL_ID"] = ctx.channel.id

    embed = discord.Embed(
        title="✅ Channel Set",
        description=f"Commit notifications will be sent to {ctx.channel.mention}",
        color=0x00FF00,
    )
    await ctx.send(embed=embed)


# --- STARTUP ---

if __name__ == "__main__":
    # --------------------------------------------------
    # ADDED: Printing Configuration for Testing
    # --------------------------------------------------
    print("--------------------------------------------------")
    print("          STARTUP CONFIGURATION CHECK             ")
    print("--------------------------------------------------")

    # Discord Token (Masked for security)
    dt = CONFIG["DISCORD_TOKEN"]
    print(f"DISCORD_TOKEN: {'***' + dt[-4:] if len(dt) > 4 else dt}")

    # GitHub Token (Masked for security)
    gt = CONFIG["GITHUB_TOKEN"]
    is_placeholder = "(PLACEHOLDER)" if gt == "YOUR_GITHUB_TOKEN" else ""
    print(f"GITHUB_TOKEN:  {'***' + gt[-4:] if len(gt) > 4 else gt} {is_placeholder}")

    # Channel ID
    cid = CONFIG["CHANNEL_ID"]
    status = "(NOT SET/0)" if cid == 0 else "(OK)"
    print(f"CHANNEL_ID:    {cid} {status}")
    print(f"CHECK_INTERVAL:{CONFIG['CHECK_INTERVAL']} seconds")

    print("--------------------------------------------------")

    # --- GitHub Token Validation (Re-enabled for visibility) ---
    if CONFIG["GITHUB_TOKEN"] == "YOUR_GITHUB_TOKEN":
        print("FATAL: GITHUB_TOKEN is placeholder. API calls will fail with 401.")
        # sys.exit(1) # Uncomment this to force a crash if placeholder is used

    # --- Keep Alive and Bot Run ---
    keep_alive()
    bot.run(CONFIG["DISCORD_TOKEN"])
