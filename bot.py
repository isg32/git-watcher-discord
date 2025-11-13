import os
import json
import asyncio
import aiohttp
import discord
from discord.ext import commands, tasks
from discord import Embed
from flask import Flask
from threading import Thread

# --------------------------------------------------
#                    CONFIG
# --------------------------------------------------
CONFIG = {
    "DISCORD_TOKEN": os.getenv("DISCORD_TOKEN"),
    "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN"),
    "CHANNEL_ID": int(os.getenv("CHANNEL_ID")),
    "CHECK_INTERVAL": int(os.getenv("CHECK_INTERVAL", 300)),
    "DATA_FILE": "bot_data.json",
}

bot_data = {"repos": [], "latest_commits": {}}

# --------------------------------------------------
#                    FLASK KEEP-ALIVE
# --------------------------------------------------
app = Flask("keep_alive")


@app.route("/")
def home():
    return "✅ GitHub Watcher Discord Bot is Running!"


def run_web():
    app.run(host="0.0.0.0", port=8080)


def keep_alive():
    t = Thread(target=run_web)
    t.start()


# --------------------------------------------------
#                    DISCORD BOT SETUP
# --------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents, help_command=None)


# --------------------------------------------------
#                    UTILITIES
# --------------------------------------------------
def save_data():
    with open(CONFIG["DATA_FILE"], "w") as f:
        json.dump(bot_data, f, indent=2)


def load_data():
    global bot_data
    if os.path.exists(CONFIG["DATA_FILE"]):
        try:
            with open(CONFIG["DATA_FILE"], "r") as f:
                bot_data = json.load(f)
            # Ensure backward compatibility
            if "repos" not in bot_data:
                bot_data["repos"] = []
            if "latest_commits" not in bot_data:
                bot_data["latest_commits"] = {}
        except Exception as e:
            print(f"⚠️ Failed to load data file: {e}")
            bot_data = {"repos": [], "latest_commits": {}}
    else:
        bot_data = {"repos": [], "latest_commits": {}}


def create_commit_embed(commit, repo):
    sha = commit["sha"][:7]
    msg = commit["commit"]["message"]
    author = commit["commit"]["author"]["name"]
    url = commit["html_url"]

    embed = Embed(title=f"🌀 New Commit in {repo}", color=0x3498DB)
    embed.add_field(name="Message", value=msg[:256], inline=False)
    embed.add_field(name="Author", value=author, inline=True)
    embed.add_field(name="SHA", value=f"`{sha}`", inline=True)
    embed.add_field(name="URL", value=f"[View Commit]({url})", inline=False)
    return embed


# --------------------------------------------------
#                    GITHUB FETCH
# --------------------------------------------------
async def fetch_commits(session, repo):
    """Fetch the latest commits from a GitHub repository."""
    try:
        headers = {}
        if CONFIG["GITHUB_TOKEN"] and CONFIG["GITHUB_TOKEN"] != "YOUR_GITHUB_TOKEN":
            headers["Authorization"] = f"Bearer {CONFIG['GITHUB_TOKEN']}"
            headers["X-GitHub-Api-Version"] = "2022-11-28"

        url = f"https://api.github.com/repos/{repo}/commits"
        async with session.get(
            url, headers=headers, params={"per_page": 5}
        ) as response:
            if response.status == 200:
                return await response.json()
            elif response.status == 401:
                print(
                    f"🔴 [GITHUB] Unauthorized (401) for {repo}. Check your GITHUB_TOKEN."
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


# --------------------------------------------------
#                    TASK LOOP
# --------------------------------------------------
@tasks.loop(seconds=CONFIG["CHECK_INTERVAL"])
async def check_for_new_commits():
    if not bot_data["repos"]:
        return

    print("🔍 Checking for new commits...")
    async with aiohttp.ClientSession() as session:
        for repo in bot_data["repos"]:
            commits = await fetch_commits(session, repo)
            if not commits:
                continue

            latest_sha = commits[0]["sha"]
            last_stored_sha = bot_data["latest_commits"].get(repo)

            if latest_sha != last_stored_sha:
                channel = bot.get_channel(CONFIG["CHANNEL_ID"])
                if channel:
                    embed = create_commit_embed(commits[0], repo)
                    await channel.send(embed=embed)
                bot_data["latest_commits"][repo] = latest_sha
                save_data()


# --------------------------------------------------
#                    COMMANDS
# --------------------------------------------------
@bot.command(name="addrepo")
async def add_repo(ctx, repo_name: str):
    """Add a repository to monitor."""
    if repo_name in bot_data["repos"]:
        await ctx.send(f"⚠️ Repository `{repo_name}` is already being monitored.")
        return
    bot_data["repos"].append(repo_name)
    save_data()
    await ctx.send(f"✅ Added `{repo_name}` to monitoring list.")


@bot.command(name="removerepo")
async def remove_repo(ctx, repo_name: str):
    """Remove a repository from monitoring."""
    if repo_name not in bot_data["repos"]:
        await ctx.send(f"⚠️ Repository `{repo_name}` is not in the list.")
        return
    bot_data["repos"].remove(repo_name)
    bot_data["latest_commits"].pop(repo_name, None)
    save_data()
    await ctx.send(f"✅ Removed `{repo_name}` from monitoring list.")


@bot.command(name="listrepos")
async def list_repos(ctx):
    """List all monitored repositories."""
    if not bot_data["repos"]:
        await ctx.send("ℹ️ No repositories are being monitored.")
        return
    msg = "\n".join([f"• `{r}`" for r in bot_data["repos"]])
    await ctx.send(f"📦 **Currently Monitored Repositories:**\n{msg}")


@bot.command(name="latestcommits")
async def latestcommits_command(ctx, repo: str = None):
    """Show latest commits for a repo or all repos."""
    async with aiohttp.ClientSession() as session:
        if repo:
            if repo not in bot_data["repos"]:
                await ctx.send(f"⚠️ `{repo}` is not being monitored.")
                return
            repos = [repo]
        else:
            repos = bot_data["repos"]

        if not repos:
            await ctx.send("❌ No repositories are being monitored.")
            return

        await ctx.send(
            f"🔍 Fetching latest commits for `{len(repos)}` repository(ies)..."
        )

        for repo_name in repos:
            commits = await fetch_commits(session, repo_name)
            if not commits:
                await ctx.send(f"⚠️ No commits found for `{repo_name}`.")
                continue
            for commit in commits[: 3 if not repo else 5]:
                embed = create_commit_embed(commit, repo_name)
                await ctx.send(embed=embed)


@bot.command(name="help")
async def help_command(ctx):
    """Show help for available commands."""
    embed = Embed(title="🛠️ GitHub Watcher Bot Commands", color=0x00FFAA)
    embed.add_field(
        name="/addrepo <user/repo>",
        value="Start monitoring a GitHub repo.",
        inline=False,
    )
    embed.add_field(
        name="/removerepo <user/repo>", value="Stop monitoring a repo.", inline=False
    )
    embed.add_field(
        name="/listrepos", value="List all currently monitored repos.", inline=False
    )
    embed.add_field(
        name="/latestcommits [user/repo]",
        value="Show recent commits (specific or all).",
        inline=False,
    )
    embed.add_field(name="/help", value="Display this help message.", inline=False)
    await ctx.send(embed=embed)


# --------------------------------------------------
#                    EVENTS
# --------------------------------------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    load_data()
    if CONFIG["CHANNEL_ID"]:
        check_for_new_commits.start()
    print("📡 Bot is now monitoring GitHub repositories.")


# --------------------------------------------------
#                    STARTUP CHECKS
# --------------------------------------------------
if __name__ == "__main__":
    keep_alive()

    print("--------------------------------------------------")
    print("          STARTUP CONFIGURATION CHECK")
    print("--------------------------------------------------")

    def mask_token(token):
        if not token:
            return "(NOT SET)"
        return f"***{token[-4:]}" if len(token) > 4 else "***"

    dt = CONFIG["DISCORD_TOKEN"]
    gt = CONFIG["GITHUB_TOKEN"]
    cid = CONFIG["CHANNEL_ID"]

    print(f"DISCORD_TOKEN: {mask_token(dt)}")
    print(f"GITHUB_TOKEN:  {mask_token(gt)}")
    print(f"CHANNEL_ID:    {cid if cid else '(NOT SET)'}")
    print(f"CHECK_INTERVAL:{CONFIG['CHECK_INTERVAL']} seconds")

    if not dt:
        print("❌ ERROR: DISCORD_TOKEN not set!")
    else:
        bot.run(dt)
