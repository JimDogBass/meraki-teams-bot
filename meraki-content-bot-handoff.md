# Jimmy Content Bot - Claude Code Handoff

## Project Overview

Microsoft Teams bot for Meraki Talent (recruitment agency). The bot generates content for recruiters including anonymised candidate specs, job ads, LinkedIn outreach messages, CV reformatting, and more.

## Current State: FULLY FUNCTIONAL ✅

The bot is live on Railway with all 7 content generation roles working, including CV Reformat with Word document output.

### What Works
- Bot appears in Teams as **"Jimmy Content"**
- Responds to messages using Azure OpenAI (gpt-4o-mini)
- **PDF and Word file upload** - extracts text automatically
- **7 content generation roles** - all working
- **CV Reformat** - generates branded Word documents with Meraki logo
- **Adaptive Card menu** - shows on "help", "hi", or ambiguous input
- **Hybrid routing** - detects intent via triggers, keywords, or AI classification
- **Conversation state** - remembers button selection for two-step flows
- **Azure Table Storage** - for role config and conversation state
- **Azure Blob Storage** - for CV file output (download links)

### What's Not Yet Implemented
- Conversation memory (beyond single button-click state)
- Database-seeded roles (using code defaults)

---

## Current Architecture

### Hosting
- **Platform:** Railway (railway.app)
- **URL:** https://meraki-teams-bot-production.up.railway.app
- **Plan:** Hobby ($5/month)
- **Workers:** gevent (non-blocking, handles large CVs)

### Code Repository
- **GitHub:** https://github.com/JimDogBass/meraki-teams-bot
- **Local folder:** C:\Projects\meraki-webapp
- **Stack:** Python (Flask) with Bot Framework

### Azure Resources (Resource Group: meraki-bot)
- **Azure OpenAI:** meraki-openai (UK South)
  - Model: gpt-4o-mini
  - Endpoint: https://meraki-openai.openai.azure.com/
- **Azure Bot Registration:** meraki-cv-bot (Single Tenant)
  - Microsoft App ID: 6aa3330e-eba0-4497-b067-66286829aef6
  - Tenant ID: 0591f50e-b7a3-41d0-a0b1-b26a2df48dfc
- **Azure Table Storage:**
  - `BotRoles` table (role configuration)
  - `BotState` table (conversation state for pending role selections)
- **Azure Blob Storage:**
  - `cv-outputs` container (generated Word documents)

### Current File Structure
```
C:\Projects\meraki-webapp\
├── app.py                 # Main Flask application with Bot Framework
├── cv_generator.py        # Word document generation from CV data
├── requirements.txt       # Python dependencies
├── Procfile              # Railway start command (gevent workers)
├── railway.toml          # Railway configuration
├── startup.txt           # Gunicorn startup (backup)
├── templates\
│   └── Meraki_CV_Template.docx  # Meraki branded CV template
└── teams-app\            # Teams manifest (for app installation)
    ├── manifest.json
    ├── color.png
    ├── outline.png
    └── cvbot.zip
```

### Deployment Process
1. Make changes to files in C:\Projects\meraki-webapp\
2. Push to GitHub:
   ```
   cd C:\Projects\meraki-webapp
   git add .
   git commit -m "description"
   git push
   ```
3. Railway auto-deploys from GitHub (takes ~1-2 minutes)

---

## Bot Capabilities - 7 Roles

| Role | Trigger | Aliases | Input Types | Output | Status |
|------|---------|---------|-------------|--------|--------|
| CV to Spec | `spec` | cv, candidate, specification | CV (text, PDF, Word) | Anonymised spec email | ✅ Working |
| Candidate Profile | `profile` | blurb | CV or notes | Short blurb for client | ✅ Working |
| Job Ad | `ad` | advert, jobad | JD or notes | Anonymised job advert | ✅ Working |
| Job Description | `jd` | jobdesc | Notes or role info | Formal JD document | ✅ Working |
| Candidate Pitch | `pitch` | script, sell | JD or notes | Script for calling candidates | ✅ Working |
| LinkedIn Outreach | `outreach` | linkedin, inmail | JD or notes | Short InMail message | ✅ Working |
| CV Reformat | `reformat` | format, template | CV (PDF, Word) | **Word document download** | ✅ Working |

### How to Use Each Role
Users can trigger roles in multiple ways:
- **Prefix:** `/spec`, `!ad`, `/outreach`
- **First word:** `spec [paste CV here]`
- **Keyword in message:** `"can you do a spec for this candidate"`
- **Button click:** Select from Adaptive Card menu, then upload file
- **Natural language:** AI classifies intent automatically

---

## CV Reformat Feature (New)

### How It Works
1. User clicks "CV Reformat" button or types "reformat"
2. Bot asks for CV content
3. User uploads PDF/Word CV
4. AI extracts structured data (name, profile, education, work history)
5. Bot generates branded Word document using Meraki template
6. Document uploaded to Azure Blob Storage
7. Bot sends download link (expires in 7 days)

### Template Features
- **Meraki logo** at top
- **Brand colors:** Blue headers (#1B4677), pink bullets (#EC008C)
- **Sections:** Personal Details, Candidate Profile, Education, Work Experience, Consultant Contact Details
- **Left blank for consultant:** Right to Work, Notice, Consultant Name/Tel

### Generated File
- Filename: `Meraki_CV_{CandidateName}_{Timestamp}.docx`
- Stored in: Azure Blob Storage `cv-outputs` container
- Download link valid for 7 days

---

## Conversation State (New)

The bot now remembers role selections for two-step flows:

1. User clicks "CV Reformat" button
2. Bot saves pending role in Azure Table Storage (`BotState` table)
3. User uploads file in next message
4. Bot retrieves pending role and processes with correct handler
5. State cleared after use (expires after 5 minutes if not used)

---

## Trigger Resolution - Hybrid Routing

The bot uses a 6-step hybrid routing system:

```
0. Check for pending role from previous button click → use saved role
   ↓ no pending
1. Check for Adaptive Card button press → role selected via menu
   ↓ no button
2. Check for explicit prefix → /spec, !spec
   ↓ no match
3. Check if first word is a known trigger → "spec [cv]"
   ↓ no match
4. Scan message for trigger keywords or aliases → "do a spec for me"
   ↓ no match
5. Ask OpenAI to classify intent → "can you turn this CV into a client email"
   ↓ unknown/ambiguous
6. Fallback → Show Adaptive Card menu
```

---

## Azure Table Storage Schema

### BotRoles Table
| Column | Type | Description |
|--------|------|-------------|
| PartitionKey | string | Always "roles" |
| RowKey | string | Role ID (e.g., "spec", "ad") |
| Name | string | Display name |
| Trigger | string | Primary trigger word |
| Aliases | string | Comma-separated alternatives |
| SystemPrompt | string | Full OpenAI system prompt |
| IsActive | boolean | Enable/disable role |

### BotState Table (New)
| Column | Type | Description |
|--------|------|-------------|
| PartitionKey | string | Always "pending_role" |
| RowKey | string | Hash of conversation ID |
| Role | string | Pending role ID |
| Timestamp_ | float | Unix timestamp for expiry |

---

## Technical Notes

### Stack
- **Language:** Python 3.13
- **Framework:** Flask with Bot Framework SDK
- **Hosting:** Railway with gevent workers
- **AI:** Azure OpenAI (gpt-4o-mini)
- **Storage:** Azure Table Storage + Blob Storage

### Dependencies (requirements.txt)
```
flask
gunicorn
openai
PyPDF2
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
- Max tokens: 8000 (for large CVs)
- Timeout: 120 seconds

---

## Known Issues & Solutions

### Large CVs (6+ pages) Timing Out
- **Solution:** Use gevent workers instead of sync workers
- **Config:** `--worker-class=gevent` in start command
- **If still failing:** Check Railway logs for "Using worker: gevent"
- **Manual fix:** Set start command in Railway dashboard if railway.toml not picked up

### "Unknown attachment type" Error
- **Cause:** Teams doesn't support base64 data URLs for file attachments
- **Solution:** Upload to Azure Blob Storage, return download link

### "Not sure what to do with this" After Button Click
- **Cause:** Bot was stateless, forgot button selection
- **Solution:** Conversation state in Azure Table Storage

---

## Build Phases - Progress

| Phase | Deliverable | Status |
|-------|-------------|--------|
| 1 | PDF file upload support | ✅ Complete |
| 2 | Database-driven roles (Azure Table Storage) | ✅ Complete |
| 3 | Adaptive Card menu | ✅ Complete |
| 4 | All 7 text roles with prompts | ✅ Complete |
| 5 | CV Reformat Word file output | ✅ Complete |
| 6 | Conversation state for two-step flows | ✅ Complete |

---

## Next Steps

### Immediate
1. **Verify gevent workers** - Check Railway logs show "Using worker: gevent"
2. **Test large CVs** - Try Grant Ward's 6-page CV after gevent is confirmed

### Future Enhancements (Not Planned Yet)
- Full conversation memory / context
- Multiple output variations per role
- Usage analytics
- Admin commands for cache refresh
- Prompt refinement via database

---

## Recent Changes (14 Jan 2025)

- **Renamed bot** to "Jimmy Content"
- **CV Reformat Word output** - Full implementation with Meraki template
- **Meraki branding** - Logo, blue headers, pink bullets preserved
- **Azure Blob Storage** - CV files uploaded with 7-day download links
- **Conversation state** - Two-step flows work (button click → file upload)
- **Gevent workers** - Non-blocking workers for large CV processing
- **Added dependencies:** azure-storage-blob, gevent
- **Added files:** cv_generator.py, templates/, Procfile, railway.toml
