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

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# Configuration
CONFIG = {
    'DISCORD_TOKEN': os.getenv('DISCORD_TOKEN', 'YOUR_DISCORD_TOKEN'),
    'GITHUB_TOKEN': os.getenv('GITHUB_TOKEN', 'YOUR_GITHUB_TOKEN'),
    'CHANNEL_ID': int(os.getenv('CHANNEL_ID', '0')),
    'CHECK_INTERVAL': 60,  # seconds
    'ADMIN_ROLE_NAME': 'Bot Admin'  # Role name for admins
}

# Data storage
DATA_FILE = 'bot_data.json'
DEFAULT_REPOS_FILE = 'default_repos.json'

def load_default_repos():
    """Load default repositories from config file"""
    try:
        with open(DEFAULT_REPOS_FILE, 'r') as f:
            data = json.load(f)
            return data.get('default_repos', [])
    except FileNotFoundError:
        print(f"⚠️ {DEFAULT_REPOS_FILE} not found, using empty defaults")
        return []
    except json.JSONDecodeError:
        print(f"⚠️ Error parsing {DEFAULT_REPOS_FILE}, using empty defaults")
        return []

def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            # Add default repos if not already present
            default_repos = load_default_repos()
            for repo in default_repos:
                if repo not in data['repos']:
                    data['repos'].append(repo)
                    print(f"✅ Added default repo: {repo}")
            return data
    except FileNotFoundError:
        # Initialize with default repos
        default_repos = load_default_repos()
        return {'repos': default_repos.copy(), 'last_commits': {}, 'admins': []}

def save_data(data):
    with open(DATA_FILE, 'r') as f:
        json.dump(data, f, indent=2)

# Initialize bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents, help_command=None)

# Bot start time for uptime
start_time = datetime.now()
bot_data = load_data()

# Fetch commits from GitHub
async def fetch_commits(session, repo):
    try:
        headers = {}
        if CONFIG['GITHUB_TOKEN'] and CONFIG['GITHUB_TOKEN'] != 'YOUR_GITHUB_TOKEN':
            headers['Authorization'] = f"token {CONFIG['GITHUB_TOKEN']}"
        
        url = f"https://api.github.com/repos/{repo}/commits"
        async with session.get(url, headers=headers, params={'per_page': 5}) as response:
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
        url=commit['html_url'],
        color=0x0366d6,
        description=commit['commit']['message'][:300],
        timestamp=datetime.fromisoformat(commit['commit']['author']['date'].replace('Z', '+00:00'))
    )
    
    author = commit.get('author', {})
    embed.set_author(
        name=commit['commit']['author']['name'],
        icon_url=author.get('avatar_url', '')
    )
    
    embed.add_field(name='SHA', value=f"`{commit['sha'][:7]}`", inline=True)
    embed.add_field(name='Branch', value='main', inline=True)
    embed.set_footer(text=f"Repository: {repo}")
    
    return embed

# Check for new commits
@tasks.loop(seconds=CONFIG['CHECK_INTERVAL'])
async def check_commits():
    if CONFIG['CHANNEL_ID'] == 0:
        return
    
    channel = bot.get_channel(CONFIG['CHANNEL_ID'])
    if not channel:
        return
    
    async with aiohttp.ClientSession() as session:
        for repo in bot_data['repos']:
            commits = await fetch_commits(session, repo)
            
            if not commits:
                continue
            
            latest_commit = commits[0]
            last_sha = bot_data['last_commits'].get(repo)
            
            # Initialize tracking
            if not last_sha:
                bot_data['last_commits'][repo] = latest_commit['sha']
                save_data(bot_data)
                continue
            
            # Check for new commits
            if last_sha != latest_commit['sha']:
                new_commits = []
                for commit in commits:
                    if commit['sha'] == last_sha:
                        break
                    new_commits.append(commit)
                
                # Send embeds (oldest first)
                for commit in reversed(new_commits):
                    embed = create_commit_embed(commit, repo)
                    await channel.send(embed=embed)
                
                bot_data['last_commits'][repo] = latest_commit['sha']
                save_data(bot_data)

# Check if user is admin
def is_admin(ctx):
    if ctx.author.id in bot_data['admins']:
        return True
    
    role = discord.utils.get(ctx.author.roles, name=CONFIG['ADMIN_ROLE_NAME'])
    return role is not None

# Commands
@bot.event
async def on_ready():
    print(f'✅ Bot logged in as {bot.user.name}')
    print(f'📊 Monitoring {len(bot_data["repos"])} repositories')
    check_commits.start()

@bot.command(name='help')
async def help_command(ctx):
    embed = discord.Embed(
        title="🤖 GitHub Commit Bot - Help",
        color=0x5865F2,
        description="Monitor GitHub repositories and get commit notifications!"
    )
    
    embed.add_field(
        name="📋 General Commands",
        value=(
            "`/help` - Show this help message\n"
            "`/uptime` - Show bot uptime\n"
            "`/listrepos` - List all monitored repositories\n"
            "`/adminlist` - List all bot admins"
        ),
        inline=False
    )
    
    embed.add_field(
        name="⚙️ Admin Commands",
        value=(
            "`/addrepo <owner/repo>` - Add a repository to monitor\n"
            "`/removerepo <owner/repo>` - Remove a repository\n"
            "`/addadmin @user` - Add a bot admin\n"
            "`/removeadmin @user` - Remove a bot admin\n"
            "`/setchannel` - Set current channel for notifications"
        ),
        inline=False
    )
    
    embed.set_footer(text="Admin permissions required for admin commands")
    await ctx.send(embed=embed)

@bot.command(name='uptime')
async def uptime_command(ctx):
    uptime = datetime.now() - start_time
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    embed = discord.Embed(
        title="⏱️ Bot Uptime",
        color=0x00ff00,
        description=f"**{days}d {hours}h {minutes}m {seconds}s**"
    )
    embed.add_field(name="Started", value=start_time.strftime("%Y-%m-%d %H:%M:%S UTC"))
    await ctx.send(embed=embed)

@bot.command(name='adminlist')
async def adminlist_command(ctx):
    embed = discord.Embed(
        title="👑 Bot Administrators",
        color=0xffa500
    )
    
    admin_mentions = []
    for admin_id in bot_data['admins']:
        user = await bot.fetch_user(admin_id)
        admin_mentions.append(f"• {user.mention} ({user.name})")
    
    if admin_mentions:
        embed.description = "\n".join(admin_mentions)
    else:
        embed.description = "No admins added yet. Users with 'Bot Admin' role can use admin commands."
    
    await ctx.send(embed=embed)

@bot.command(name='listrepos')
async def listrepos_command(ctx):
    embed = discord.Embed(
        title="📚 Monitored Repositories",
        color=0x0366d6
    )
    
    if bot_data['repos']:
        default_repos = load_default_repos()
        repo_lines = []
        for repo in bot_data['repos']:
            if repo in default_repos:
                repo_lines.append(f"• `{repo}` 🔒 (default)")
            else:
                repo_lines.append(f"• `{repo}`")
        embed.description = "\n".join(repo_lines)
        embed.add_field(
            name="ℹ️ Info",
            value="Repos marked with 🔒 are default repos and cannot be removed",
            inline=False
        )
    else:
        embed.description = "No repositories being monitored yet."
    
    embed.set_footer(text=f"Total: {len(bot_data['repos'])} repositories")
    await ctx.send(embed=embed)

@bot.command(name='addrepo')
async def addrepo_command(ctx, repo: str = None):
    if not is_admin(ctx):
        await ctx.send("❌ You need admin permissions to use this command!")
        return
    
    if not repo:
        await ctx.send("❌ Please provide a repository in format: `owner/repo`")
        return
    
    if '/' not in repo or repo.count('/') != 1:
        await ctx.send("❌ Invalid format! Use: `owner/repo`")
        return
    
    if repo in bot_data['repos']:
        await ctx.send(f"⚠️ Repository `{repo}` is already being monitored!")
        return
    
    bot_data['repos'].append(repo)
    save_data(bot_data)
    
    embed = discord.Embed(
        title="✅ Repository Added",
        description=f"Now monitoring: `{repo}`",
        color=0x00ff00
    )
    await ctx.send(embed=embed)

@bot.command(name='removerepo')
async def removerepo_command(ctx, repo: str = None):
    if not is_admin(ctx):
        await ctx.send("❌ You need admin permissions to use this command!")
        return
    
    if not repo:
        await ctx.send("❌ Please provide a repository in format: `owner/repo`")
        return
    
    if repo not in bot_data['repos']:
        await ctx.send(f"⚠️ Repository `{repo}` is not being monitored!")
        return
    
    # Check if it's a default repo
    default_repos = load_default_repos()
    if repo in default_repos:
        await ctx.send(f"❌ Cannot remove `{repo}` - it's a default repository!")
        return
    
    bot_data['repos'].remove(repo)
    if repo in bot_data['last_commits']:
        del bot_data['last_commits'][repo]
    save_data(bot_data)
    
    embed = discord.Embed(
        title="✅ Repository Removed",
        description=f"Stopped monitoring: `{repo}`",
        color=0xff0000
    )
    await ctx.send(embed=embed)

@bot.command(name='addadmin')
async def addadmin_command(ctx, member: discord.Member = None):
    if not is_admin(ctx):
        await ctx.send("❌ You need admin permissions to use this command!")
        return
    
    if not member:
        await ctx.send("❌ Please mention a user to add as admin!")
        return
    
    if member.id in bot_data['admins']:
        await ctx.send(f"⚠️ {member.mention} is already an admin!")
        return
    
    bot_data['admins'].append(member.id)
    save_data(bot_data)
    
    await ctx.send(f"✅ {member.mention} has been added as a bot admin!")

@bot.command(name='removeadmin')
async def removeadmin_command(ctx, member: discord.Member = None):
    if not is_admin(ctx):
        await ctx.send("❌ You need admin permissions to use this command!")
        return
    
    if not member:
        await ctx.send("❌ Please mention a user to remove from admins!")
        return
    
    if member.id not in bot_data['admins']:
        await ctx.send(f"⚠️ {member.mention} is not an admin!")
        return
    
    bot_data['admins'].remove(member.id)
    save_data(bot_data)
    
    await ctx.send(f"✅ {member.mention} has been removed from bot admins!")

@bot.command(name='setchannel')
async def setchannel_command(ctx):
    if not is_admin(ctx):
        await ctx.send("❌ You need admin permissions to use this command!")
        return
    
    CONFIG['CHANNEL_ID'] = ctx.channel.id
    
    embed = discord.Embed(
        title="✅ Channel Set",
        description=f"Commit notifications will be sent to {ctx.channel.mention}",
        color=0x00ff00
    )
    await ctx.send(embed=embed)

# Start the bot
if __name__ == '__main__':
    keep_alive()
    bot.run(CONFIG['DISCORD_TOKEN'])
