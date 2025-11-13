

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

