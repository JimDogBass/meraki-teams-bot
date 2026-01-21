# Fernando Format - Claude Code Handoff

## Project Overview

Microsoft Teams bot for Meraki Talent (recruitment agency). Single-function bot that reformats CVs with Meraki branding and generates alternative candidate profiles.

**Note:** This bot was previously "Jimmy Content" - a multi-function bot with 7 roles. It was stripped down to focus solely on CV reformatting.

## Current State: FULLY FUNCTIONAL

The bot reformats CVs and generates alternative candidate profiles.

### What Works
- Bot appears in Teams as **"Fernando Format"**
- Responds to messages using Azure OpenAI (gpt-4o-mini)
- **PDF and Word file upload** - extracts text automatically (.pdf, .docx, .doc)
- **CV Reformat** - generates branded Word documents with Meraki logo
- **Alternative Candidate Profile** - generates 2-3 sentence summary alongside CV
- **Simple Adaptive Card menu** - single "Reformat CV" button
- **Conversation state** - remembers button selection for two-step flows
- **Azure Blob Storage** - for CV file output (download links)

---

## Architecture

### Hosting
- **Platform:** Railway (railway.app)
- **URL:** https://meraki-teams-bot-production.up.railway.app
- **Workers:** gevent (non-blocking, handles large CVs)

### Code Repository
- **GitHub:** https://github.com/JimDogBass/meraki-teams-bot
- **Local folder:** C:\Projects\fernando-format
- **Stack:** Python (Flask) with Bot Framework

### Azure Resources (Resource Group: meraki-bot)
- **Azure OpenAI:** meraki-openai (UK South)
  - Model: gpt-4o-mini
  - Endpoint: https://meraki-openai.openai.azure.com/
- **Azure Bot Registration:** meraki-cv-bot (Single Tenant)
  - Microsoft App ID: 6aa3330e-eba0-4497-b067-66286829aef6
  - Tenant ID: 0591f50e-b7a3-41d0-a0b1-b26a2df48dfc
- **Azure Table Storage:**
  - `BotState` table (conversation state for pending reformat requests)
- **Azure Blob Storage:**
  - `cv-outputs` container (generated Word documents)

### File Structure
```
C:\Projects\fernando-format\
├── app.py                 # Main Flask application (simplified)
├── cv_generator.py        # Word document generation from CV data
├── requirements.txt       # Python dependencies
├── Procfile              # Railway start command (gevent workers)
├── railway.toml          # Railway configuration
├── nixpacks.toml         # Installs antiword for .doc support
├── startup.txt           # Gunicorn startup (backup)
├── templates\
│   └── meraki_logo.png   # Meraki logo for CV header
└── teams-app\            # Teams manifest (for app installation)
    ├── manifest.json
    ├── color.png
    ├── outline.png
    └── cvbot.zip
```

### Deployment Process
1. Make changes to files in C:\Projects\fernando-format\
2. Push to GitHub:
   ```
   cd C:\Projects\fernando-format
   git add .
   git commit -m "description"
   git push
   ```
3. Railway auto-deploys from GitHub

---

## Bot Capabilities

### CV Reformat + Alternative Profile

| Feature | Description |
|---------|-------------|
| **Input** | PDF, Word (.docx, .doc), or pasted CV text |
| **Output 1** | Meraki-branded Word document (download link) |
| **Output 2** | Alternative Candidate Profile (2-3 sentences in chat) |

### How to Use

Users can trigger CV reformat in multiple ways:
- **Button click:** Click "Reformat CV" button, then upload file
- **Direct upload:** Just upload a PDF/Word CV file (assumes reformat)
- **Trigger word:** Type "reformat" or "format" followed by content
- **Prefix:** `/reformat` or `!reformat`

### Output Format

After processing, the bot returns:
```
Here's the reformatted CV for **{Candidate Name}**:

Download {Meraki_CV_Name_Timestamp.docx}

_Link expires in 7 days_

**Alternative Candidate Profile:**
{2-3 sentence punchy summary using they/their pronouns}
```

---

## Message Flow

```
User says "hi"/"help" → Show simple card with "Reformat CV" button
         ↓
User clicks "Reformat CV" → "Great! Send me the CV..."
         ↓
User uploads CV file → Process CV → Return Word doc + Alternative Profile
         ↓
Show "Start New" button

OR

User uploads file directly → Assume reformat → Process CV
```

---

## Technical Notes

### Dependencies (requirements.txt)
```
flask
gunicorn
openai
PyPDF2
pdfplumber
python-docx
httpx
botbuilder-core
botbuilder-schema
aiohttp
azure-data-tables
azure-storage-blob
gevent
```

### Railway Configuration
**Start Command (railway.toml):**
```
gunicorn --bind=0.0.0.0:$PORT --timeout 600 --worker-class=gevent --workers=2 app:app
```

### Railway Environment Variables
- AZURE_OPENAI_ENDPOINT
- AZURE_OPENAI_KEY
- MICROSOFT_APP_ID
- MICROSOFT_APP_PASSWORD
- MICROSOFT_APP_TENANT_ID
- AZURE_STORAGE_CONNECTION_STRING
- PORT

### OpenAI Settings
- Model: gpt-4o-mini
- Max tokens: 8000 (for CV extraction)
- Timeout: 120 seconds (CV extraction), 60 seconds (alternative profile)

---

## Azure Table Storage Schema

### BotState Table
| Column | Type | Description |
|--------|------|-------------|
| PartitionKey | string | Always "pending_role" |
| RowKey | string | Hash of conversation ID |
| Role | string | Always "reformat" |
| Timestamp_ | float | Unix timestamp for expiry (5 min TTL) |

---

## What Was Removed (from Jimmy Content)

The following features were removed when stripping down to Fernando Format:

### Removed Roles
- CV to Spec Email (spec)
- Candidate Profile (profile)
- Job Advert (ad)
- Job Description (jd)
- Candidate Pitch Script (pitch)
- LinkedIn Outreach (outreach)

### Removed Functions
- `get_default_roles()` - 7-role configuration
- `load_roles_from_table()` - BotRoles table integration
- `get_roles()` - Role caching
- `roles_cache` / `CACHE_TTL_SECONDS` - Role cache variables
- `get_refinement_state()` / `set_refinement_state()` / `clear_refinement_state()` - Refinement mode
- `refine_output()` - Output refinement via AI
- `create_refinement_card()` - Refinement buttons card
- `check_explicit_trigger()` - Explicit trigger detection
- `resolve_role()` - Hybrid routing with AI classification
- AI intent classification - No longer needed with single function

### Code Reduction
- **Old app.py:** 1,135 lines
- **New app.py:** 537 lines
- **Reduction:** 598 lines (53% smaller)

---

## New Features Added

### Alternative Candidate Profile
After generating the reformatted CV, Fernando also generates a short "Alternative Candidate Profile" using a second OpenAI call.

**Prompt:**
```
Based on this CV data, write a short alternative candidate profile (2-3 sentences max).

This is a punchy summary to send alongside the CV to a client. Use "they/their" pronouns.
Highlight their key strengths, current situation, and what makes them stand out.
Keep it compelling and concise.
```

This profile appears in the chat message below the download link, ready to copy/paste into client emails.

---

## Known Issues & Solutions

### Large CVs (6+ pages) Timing Out
- **Solution:** Use gevent workers instead of sync workers
- **Config:** `--worker-class=gevent` in start command

### "Unknown attachment type" Error
- **Cause:** Teams doesn't support base64 data URLs for file attachments
- **Solution:** Upload to Azure Blob Storage, return download link

---

## History

| Date | Change |
|------|--------|
| Jan 2025 | Original "Jimmy Content" bot with 7 roles |
| Jan 2025 | Stripped down to "Fernando Format" - CV reformat only |
| Jan 2025 | Added Alternative Candidate Profile feature |
