
### **Commands**
- `/help` - Shows all available commands
- `/uptime` - Displays how long the bot has been running
- `/adminlist` - Lists all bot administrators
- `/listrepos` - Shows all monitored repositories
- `/addrepo owner/repo` - Add a repository (admin only)
- `/removerepo owner/repo` - Remove a repository (admin only)
- `/addadmin @user` - Add a bot admin (admin only)
- `/removeadmin @user` - Remove a bot admin (admin only)
- `/setchannel` - Set current channel for commit notifications (admin only)

### **Admin System**
- Users with "Bot Admin" role can use admin commands
- You can also manually add admins with `/addadmin`
- First admin should be added via the Discord role

### **Keep-Alive for Render**
- Flask server runs on port 8080
- Prevents Render from putting the bot to sleep
- Responds to health checks at root URL

## **Setup for Render.com**

1. **Create `requirements.txt`** (I've created this in the second artifact)

2. **Push to GitHub**
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin your-repo-url
git push -u origin main
```

3. **Deploy on Render**
   - Go to [render.com](https://render.com)
   - Click "New +" → "Web Service"
   - Connect your GitHub repository
   - Configure:
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `python bot.py`
   - Add Environment Variables:
     - `DISCORD_TOKEN` - Your Discord bot token
     - `GITHUB_TOKEN` - Your GitHub token (optional)
     - `CHANNEL_ID` - Your Discord channel ID (or set it later with `/setchannel`)

4. **Add Health Check (Important!)**
   - In Render dashboard, add health check path: `/`
   - This keeps your bot alive on the free tier

5. **Create "Bot Admin" Role in Discord**
   - Go to Server Settings → Roles
   - Create a role named "Bot Admin"
   - Assign it to yourself

## **Usage**

Once deployed:
1. Use `/setchannel` in the channel where you want notifications
2. Use `/addrepo owner/repo` to add repositories
3. Bot will check for new commits every 60 seconds

### **Default Repositories System**
- Default repos are loaded from `default_repos.json` on startup
- They're automatically added to the monitoring list
- **Cannot be removed** using `/removerepo` command
- Marked with 🔒 icon in `/listrepos` command

### **How It Works**

1. **Create `default_repos.json`** in your project root (I've created an example)
2. Add repositories you want hardcoded:
```json
{
  "default_repos": [
    "owner/repo1",
    "owner/repo2",
    "anotherowner/repo3"
  ]
}
```

3. These repos will:
   - Be automatically monitored when bot starts
   - Persist even if `bot_data.json` is deleted
   - Be protected from removal
   - Show with a 🔒 icon in the repo list

### **Example default_repos.json**
I've created an example with popular repos (Linux, VS Code, React). Replace these with your actual repositories.

### **File Structure**
Your project should now have:
```
├── bot.py
├── requirements.txt
├── default_repos.json    # Your hardcoded repos
└── bot_data.json          # Auto-generated runtime data
```

