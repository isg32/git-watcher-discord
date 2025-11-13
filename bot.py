import discord
from discord.ext import commands, tasks
import aiohttp
import json
import os
from datetime import datetime
from threading import Thread

# Third-party libraries (Flask for keep-alive)
from flask import Flask

# --- CONFIGURATION ---

CONFIG = {
    "DISCORD_TOKEN": os.getenv("DISCORD_TOKEN", "YOUR_DISCORD_TOKEN"),
    "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN", "YOUR_GITHUB_TOKEN"),
    "CHANNEL_ID": int(os.getenv("CHANNEL_ID", "0")),
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
        print(f"⚠️ Error with {DEFAULT_REPOS_FILE}, using empty defaults.")
        return []


def load_data():
    """Load bot data from JSON file (r mode), initializing if not found or corrupted."""
    default_structure = {"repos": load_default_repos().copy(), "last_commits": {}}

    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)

            # Ensure the structure keys exist
            if "repos" not in data:
                data["repos"] = []
            if "last_commits" not in data:
                data["last_commits"] = {}

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
# This must be enabled in the Discord Developer Portal for commands to work
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

    # Check A: Channel ID Verification
    if CONFIG["CHANNEL_ID"] == 0:
        print("🔴 [LOOP] Skipping check: CHANNEL_ID is 0. Use /setchannel.")
        return

    channel = bot.get_channel(CONFIG["CHANNEL_ID"])
    if not channel:
        print(
            f"🔴 [LOOP] Skipping check: Could not find channel with ID {CONFIG['CHANNEL_ID']}."
        )
        return

    print(
        f"🟢 [LOOP] Starting commit check for {len(bot_data['repos'])} repos at {datetime.now().strftime('%H:%M:%S')}"
    )

    async with aiohttp.ClientSession() as session:
        for repo in bot_data["repos"]:
            # Check B: GitHub Fetch
            commits = await fetch_commits(session, repo)
            print(f"🟢 [REPO:{repo}] Fetched {len(commits)} commits.")

            if not commits:
                continue

            latest_commit = commits[0]
            latest_commit_sha = latest_commit["sha"]
            last_saved_sha = bot_data["last_commits"].get(repo)

            # Check C: Commit Tracking

            # 1. Initialize tracking (skips notification on first check)
            if not last_saved_sha:
                bot_data["last_commits"][repo] = latest_commit_sha
                save_data(bot_data)
                print(
                    f"🟡 [REPO:{repo}] Initializing tracking with SHA: {latest_commit_sha[:7]}. Skipping notification."
                )
                continue

            # 2. Check for new commits
            if last_saved_sha != latest_commit_sha:
                print(f"🔔 [REPO:{repo}] NEW COMMIT DETECTED!")
                print(f"   - Old SHA: {last_saved_sha[:7]}")
                print(f"   - New SHA: {latest_commit_sha[:7]}")

                new_commits = []
                # Find all new commits between last_saved_sha and latest_commit
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
    keep_alive()
    bot.run(CONFIG["DISCORD_TOKEN"])
