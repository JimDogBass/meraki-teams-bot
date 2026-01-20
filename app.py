import os
import asyncio
import io
import time
import base64
import httpx
import tempfile
import subprocess
from flask import Flask, request, Response
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity, Attachment
from openai import AzureOpenAI
from PyPDF2 import PdfReader
import pdfplumber
from docx import Document
from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta
from cv_generator import create_meraki_cv, parse_cv_json, CV_EXTRACTION_PROMPT

app = Flask(__name__)

settings = BotFrameworkAdapterSettings(
    app_id=os.environ.get("MICROSOFT_APP_ID", ""),
    app_password=os.environ.get("MICROSOFT_APP_PASSWORD", ""),
    channel_auth_tenant=os.environ.get("MICROSOFT_APP_TENANT_ID", "")
)
adapter = BotFrameworkAdapter(settings)

openai_client = AzureOpenAI(
    api_key=os.environ.get("AZURE_OPENAI_KEY"),
    api_version="2024-02-01",
    azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
)

# Azure Storage connection
storage_connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
table_service_client = None
blob_service_client = None
if storage_connection_string:
    table_service_client = TableServiceClient.from_connection_string(storage_connection_string)
    blob_service_client = BlobServiceClient.from_connection_string(storage_connection_string)
    # Ensure cv-outputs container exists
    try:
        blob_service_client.create_container("cv-outputs")
    except Exception:
        pass  # Container already exists

# Role cache
roles_cache = {}
roles_cache_timestamp = 0
CACHE_TTL_SECONDS = 300  # 5 minutes

# Conversation state - tracks pending role selections using Azure Table Storage
PENDING_ROLE_TTL_SECONDS = 300  # 5 minutes


def get_pending_role(conversation_id: str) -> str:
    """Get pending role for a conversation from Azure Table Storage."""
    if not table_service_client:
        print("[DEBUG] No table_service_client for pending role")
        return None

    try:
        table_client = table_service_client.get_table_client("BotState")
        # Use hash of conversation_id as RowKey (conversation IDs can have special chars)
        row_key = str(hash(conversation_id) & 0xFFFFFFFF)

        try:
            entity = table_client.get_entity(partition_key="pending_role", row_key=row_key)
            timestamp = entity.get("Timestamp_", 0)

            # Check if expired
            if time.time() - timestamp < PENDING_ROLE_TTL_SECONDS:
                print(f"[DEBUG] Found pending role: {entity.get('Role')}")
                return entity.get("Role")
            else:
                # Expired, clean up
                table_client.delete_entity(partition_key="pending_role", row_key=row_key)
                print("[DEBUG] Pending role expired")
        except Exception:
            # Entity not found
            print("[DEBUG] No pending role found in table")
            pass
    except Exception as e:
        print(f"[DEBUG] Error getting pending role: {e}")

    return None


def set_pending_role(conversation_id: str, role_id: str):
    """Set a pending role selection in Azure Table Storage."""
    if not table_service_client:
        print("[DEBUG] No table_service_client to set pending role")
        return

    try:
        table_client = table_service_client.get_table_client("BotState")

        # Create table if it doesn't exist
        try:
            table_service_client.create_table("BotState")
        except Exception:
            pass  # Table already exists

        row_key = str(hash(conversation_id) & 0xFFFFFFFF)
        entity = {
            "PartitionKey": "pending_role",
            "RowKey": row_key,
            "ConversationId": conversation_id[:900],  # Truncate if too long
            "Role": role_id,
            "Timestamp_": time.time()
        }
        table_client.upsert_entity(entity)
        print(f"[DEBUG] Set pending role in table: {role_id} for {row_key}")
    except Exception as e:
        print(f"[DEBUG] Error setting pending role: {e}")


def clear_pending_role(conversation_id: str):
    """Clear pending role from Azure Table Storage."""
    if not table_service_client:
        return

    try:
        table_client = table_service_client.get_table_client("BotState")
        row_key = str(hash(conversation_id) & 0xFFFFFFFF)
        table_client.delete_entity(partition_key="pending_role", row_key=row_key)
        print(f"[DEBUG] Cleared pending role for {row_key}")
    except Exception as e:
        print(f"[DEBUG] Error clearing pending role: {e}")


# Refinement state - tracks output for conversational refinement
REFINEMENT_TTL_SECONDS = 1800  # 30 minutes


def get_refinement_state(conversation_id: str) -> dict:
    """Get refinement state for a conversation from Azure Table Storage."""
    if not table_service_client:
        return None

    try:
        table_client = table_service_client.get_table_client("BotState")
        row_key = str(hash(conversation_id) & 0xFFFFFFFF)

        try:
            entity = table_client.get_entity(partition_key="refinement", row_key=row_key)
            timestamp = entity.get("Timestamp_", 0)

            if time.time() - timestamp < REFINEMENT_TTL_SECONDS:
                print(f"[DEBUG] Found refinement state for role: {entity.get('RoleId')}")
                return {
                    "output": entity.get("Output", ""),
                    "role_id": entity.get("RoleId", "")
                }
            else:
                table_client.delete_entity(partition_key="refinement", row_key=row_key)
                print("[DEBUG] Refinement state expired")
        except Exception:
            print("[DEBUG] No refinement state found")
            pass
    except Exception as e:
        print(f"[DEBUG] Error getting refinement state: {e}")

    return None


def set_refinement_state(conversation_id: str, output: str, role_id: str):
    """Set refinement state in Azure Table Storage."""
    if not table_service_client:
        return

    try:
        table_client = table_service_client.get_table_client("BotState")

        try:
            table_service_client.create_table("BotState")
        except Exception:
            pass

        row_key = str(hash(conversation_id) & 0xFFFFFFFF)
        # Truncate output if too long for table storage (max 64KB per property)
        truncated_output = output[:60000] if len(output) > 60000 else output
        entity = {
            "PartitionKey": "refinement",
            "RowKey": row_key,
            "ConversationId": conversation_id[:900],
            "Output": truncated_output,
            "RoleId": role_id,
            "Timestamp_": time.time()
        }
        table_client.upsert_entity(entity)
        print(f"[DEBUG] Set refinement state for role: {role_id}")
    except Exception as e:
        print(f"[DEBUG] Error setting refinement state: {e}")


def clear_refinement_state(conversation_id: str):
    """Clear refinement state from Azure Table Storage."""
    if not table_service_client:
        return

    try:
        table_client = table_service_client.get_table_client("BotState")
        row_key = str(hash(conversation_id) & 0xFFFFFFFF)
        table_client.delete_entity(partition_key="refinement", row_key=row_key)
        print(f"[DEBUG] Cleared refinement state")
    except Exception as e:
        print(f"[DEBUG] Error clearing refinement state: {e}")


def load_roles_from_table():
    """Load roles from Azure Table Storage."""
    global roles_cache, roles_cache_timestamp

    if not table_service_client:
        return get_default_roles()

    try:
        table_client = table_service_client.get_table_client("BotRoles")
        entities = table_client.query_entities("PartitionKey eq 'roles'")

        roles = {}
        for entity in entities:
            if entity.get("IsActive", True):
                role_id = entity["RowKey"]
                roles[role_id] = {
                    "id": role_id,
                    "name": entity.get("Name", role_id),
                    "trigger": entity.get("Trigger", role_id),
                    "aliases": [a.strip() for a in entity.get("Aliases", "").split(",") if a.strip()],
                    "system_prompt": entity.get("SystemPrompt", ""),
                    "output_template": entity.get("OutputTemplate", ""),
                    "icon": entity.get("Icon", "")
                }

        if roles:
            roles_cache = roles
            roles_cache_timestamp = time.time()
            return roles
    except Exception as e:
        print(f"Error loading roles from table: {e}")

    # Return cached or default if table load fails
    if roles_cache:
        return roles_cache
    return get_default_roles()


def get_default_roles():
    """Return default role configuration (fallback)."""
    return {
        "spec": {
            "id": "spec",
            "name": "CV to Spec Email",
            "trigger": "spec",
            "aliases": ["cv", "candidate", "specification"],
            "icon": "Document",
            "system_prompt": """You are a recruitment consultant assistant. When given CV information or candidate details, create an anonymised candidate spec email.

RULES:
- Anonymise all company names using DESCRIPTIVE terms - NEVER use the word "Anonymised"
  - Good examples: "Leading Growth Equity Firm", "Big 4 Accountancy Firm", "Global Investment Bank", "Top-Tier PE Fund (>$20bn AUM)", "Boutique Real Estate Fund"
  - BAD: "Anonymised Investment Firm" - NEVER write this
- Include company size/AUM where relevant (e.g., "PE Fund >$20bn AUM")
- Include ONLY the last 2 COMPANIES (not 3, not 4 - exactly 2) - but show ALL roles they held at each of those 2 companies (e.g., if they were Associate then Senior Associate then VP at one firm, show all three titles)
- BE CONCISE: Include 3-4 SHORT bullet points per company - each bullet should be one line, not a paragraph
- Keep the intro brief - one or two sentences max
- Anonymise university names (e.g., "Top 100 University", "Russell Group University", "Ivy League University")
- Do not include candidate name, contact details, or any identifying information
- Do not include gender
- Do not include pronouns that reveal gender - use "they/their"
- Use **bold** markdown formatting ONLY for company descriptions and role titles in the career section - NOT in the intro sentences
- CRITICAL: Add a blank line (containing just &nbsp;) between sections to create visual spacing

FUNCTION: Identify the candidate's actual function/specialism from their CV (e.g., Fundraising & IR, Private Equity, Credit Risk, Actuarial, Asset Management). Do NOT just use their job title - use their specialism.

EXAMPLE OUTPUT (copy this format exactly, including the &nbsp; lines for spacing):

Subject: Candidate Spec - Vice President Fundraising & IR - New York

Hi

I am working with an exceptional Fundraising & IR professional with a strong background in private equity and alternative investments, actively seeking a new opportunity in New York. Below are highlights of their career; let me know if you would like to see a full resume or discuss the market.

&nbsp;

**Leading Growth Equity Firm | New York**
**Vice President (June 2024 – Present)**
- Secured $250mm+ in capital from family offices and institutional investors
- Raised capital across growth equity, credit, climate, and infrastructure funds
- Led fundraising efforts in the Southeast and Midwest U.S.
- Delivered portfolio updates to investors, enhancing client service

&nbsp;

**Boutique Private Equity Firm | New York**
**Vice President (Feb 2023 – Jun 2024) | Senior Associate (Feb 2021 – Jan 2023) | Associate (Jun 2019 – Jan 2021)**
- Secured $700mm+ in new capital across private equity and real estate
- Expanded investor network and originated new opportunities
- Conducted market research and supported product development
- Advised 25+ managers on capital formation and fundraising strategy

&nbsp;

**Education**
Top 100 University - A.B. in Psychology (2017)"""
        },
        "profile": {
            "id": "profile",
            "name": "Candidate Profile",
            "trigger": "profile",
            "aliases": ["blurb"],
            "icon": "Person",
            "system_prompt": """You are a recruitment consultant assistant. Create a short candidate profile blurb to send alongside a CV to a client.

RULES:
- Keep it concise (2-3 sentences max)
- Highlight key selling points and current situation
- Use "they/their" pronouns
- Mention notice period and salary expectations if provided
- Make it punchy and compelling

FORMAT:
A brief paragraph that could be pasted into an email above an attached CV."""
        },
        "ad": {
            "id": "ad",
            "name": "Job Advert",
            "trigger": "ad",
            "aliases": ["advert", "jobad"],
            "icon": "Megaphone",
            "system_prompt": """You are a recruitment consultant assistant. Create an anonymised job advert for posting on job boards.

RULES:
- Anonymise the company name (use descriptors like "Leading Fintech", "Global Investment Bank")
- Make it engaging and compelling
- Include key requirements and responsibilities
- Include salary range if provided
- Keep it professional but not boring

FORMAT:
Standard job advert format with sections for: About the Role, Responsibilities, Requirements, What's On Offer."""
        },
        "jd": {
            "id": "jd",
            "name": "Job Description",
            "trigger": "jd",
            "aliases": ["jobdesc"],
            "icon": "ClipboardList",
            "system_prompt": """You are a recruitment consultant assistant. Create a professional job description from client call notes or role information.

INPUT: You will receive rough notes from a client call. Transform these into a polished, professional job description.

RULES:
- Use the REAL company name (do NOT anonymise)
- Only include information that was provided - do NOT infer or make up details
- If compensation/benefits not provided, omit those sections entirely
- Responsibilities should be specific to the role, not generic
- Keep bullet points concise - one line each where possible
- Qualifications: separate required from nice-to-have/preferred

FORMAT (use bold markdown headers):

**[Job Title]**

**Firm Overview**
[Company description including: what they do, AUM/fund size if known, investment focus/strategy, team size, culture. 1-2 paragraphs based on what's provided.]

**Position Overview**
[Brief summary of the role, who they report to, why the role exists. 1-2 paragraphs.]

**Key Responsibilities**
- [6-12 bullet points of specific duties]

**Qualifications**
- [Required skills, experience, education - 5-8 bullets]

**Preferred/Nice-to-Have** (only if applicable)
- [Additional desirable qualities - 2-4 bullets]

**Compensation** (only if provided)
[Salary range, bonus structure]

**Benefits** (only if provided)
- [Perks and benefits list]

EXAMPLE RESPONSIBILITY BULLETS (be this specific):
- Conduct company, industry, and financial diligence
- Build financial models and valuation analyses
- Support ongoing portfolio company initiatives
- Respond to investor requests from current limited partners

EXAMPLE QUALIFICATION BULLETS:
- 3-5 years of experience in investment banking, private equity, or consulting
- Strong quantitative skills and understanding of financial statements
- Bachelor's degree required; Finance or Economics focus preferred
- Advanced proficiency with Microsoft Excel and PowerPoint"""
        },
        "pitch": {
            "id": "pitch",
            "name": "Candidate Pitch Script",
            "trigger": "pitch",
            "aliases": ["script", "sell"],
            "icon": "Phone",
            "system_prompt": """You are a recruitment consultant assistant. Create a script for calling candidates to pitch a role.

RULES:
- Make it conversational and natural
- Include key selling points upfront
- Anticipate common questions
- Keep it concise - recruiters talk fast
- Include a hook to grab interest

FORMAT:
Opening Hook:
Key Selling Points:
Role Overview:
Why This Opportunity:
Questions to Ask Them:
Objection Handlers:"""
        },
        "outreach": {
            "id": "outreach",
            "name": "LinkedIn Outreach",
            "trigger": "outreach",
            "aliases": ["linkedin", "inmail"],
            "icon": "Send",
            "system_prompt": """You are a recruitment consultant assistant. Create a LinkedIn InMail message for candidate outreach.

STRUCTURE (follow this order):
1. Opening: Use ONE of these (vary each time, don't always use the same one):
   - "Would you be open to discussing career options currently?"
   - "Would you be open to discussing career opportunities currently?"
   - "Are you currently open to exploring new opportunities?"
   - "I came across your profile and wanted to reach out about a role that might interest you."
   - "Hope you're well – I wanted to get in touch about a role I think could be a great fit."
   - "I hope this message finds you well. I have an opportunity that I thought might be of interest."
   - "Your profile caught my attention and I wanted to share an opportunity with you."
   - "I wanted to reach out as I have a role that aligns well with your background."
   - "Are you open to hearing about new opportunities at the moment?"
   - "I'm reaching out as I think you could be a great fit for a role I'm working on."
2. Company intro: Anonymise the company - describe it generically (e.g., "a leading Global Private Bank", "a boutique International Bank", "a FTSE 250 Financial Services firm", "a Global Asset Manager")
3. Role & contract: State the role title and that it's permanent (if stated)
4. Location & salary: ONLY include if explicitly stated in the input - do not infer or make up location, hybrid working, or salary
5. Selling points: Start with "It is a great role which..." and highlight 2-3 key responsibilities or selling points from the input
6. Call to action: "Please drop me a note if interested in hearing more."
7. Sign-off: "Best Regards"

RULES:
- ALWAYS anonymise the company name - never include the actual company name
- NEVER infer or make up details - only include location, salary, hybrid working, contract type if explicitly stated in the input
- If salary/location/hybrid not provided, simply omit those details from the message
- Keep the selling points concise but specific to the role
- Professional but warm tone
- Do NOT include your name after "Best Regards" - the recruiter will add their own

EXAMPLE 1 (Quantitative role):
"Would you be open to discussing career options currently?

My client, a leading Global Private Bank, is currently looking to hire a Quantitative Investment Strategist on a permanent basis.

The role is based in the West End (hybrid working), reports to the Head of Asset Allocation and is paying to 140k basic with strong benefits and bonus on top.

It is a great role which plays a key role in supporting the Advisory business (for both UHNW and Family Office clients), with MAI portfolios and investment solutions. The role also devises trade ideas, investment strategies and bespoke portfolio solutions.

Please drop me a note if interested in hearing more.

Best Regards"

EXAMPLE 2 (Risk role):
"Would you be open to discussing career options currently?

My client, a boutique International Bank, is currently looking to hire a Prudential Risk Manager on a permanent basis. It is a permanent role, based in the West End and is paying to £115,000 basic salary plus benefits and bonus.

The role reports directly to the CRO and takes responsibility for the origination, review and updating of the Bank's regulatory documents for ICAAP, ILAAP, Recovery and Resolution, the Funding Plan and Pillar 3 disclosures.

Please drop me a note if interested in hearing more.

Best Regards"

EXAMPLE 3 (Senior leadership role):
"Would you be open to discussing career opportunities currently?

My client, a FTSE 250 listed Financial Services firm, is currently looking to hire a Head of Prudential Regulation into their growing Finance function.

It is a permanent role and can be based either their Leeds or Liverpool offices (hybrid working – 3 days in office). Salary is anticipated to be in the 95-115k basic range plus benefits and bonus.

It is a great role which reports directly to the Group Treasurer. You will be leading a newly formed team which is dedicated to prudential management under PRA and FCA basis.

Please drop me a note if this role sounds appropriate and of interest.

Best Regards"

Just output the message, nothing else."""
        },
        "reformat": {
            "id": "reformat",
            "name": "CV Reformat",
            "trigger": "reformat",
            "aliases": ["format", "template"],
            "icon": "ArrowRepeat",
            "system_prompt": CV_EXTRACTION_PROMPT,
            "output_type": "word"
        }
    }


def get_roles():
    """Get roles with caching."""
    global roles_cache, roles_cache_timestamp

    current_time = time.time()
    if roles_cache and (current_time - roles_cache_timestamp) < CACHE_TTL_SECONDS:
        return roles_cache

    return load_roles_from_table()


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF file bytes, including tables."""
    text_parts = []

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            # Extract regular text
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

            # Extract tables (pdfplumber handles these better)
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    # Filter out None values and join cells
                    row_text = [cell.strip() if cell else "" for cell in row]
                    row_text = [cell for cell in row_text if cell]
                    if row_text:
                        text_parts.append(" | ".join(row_text))

    return "\n".join(text_parts).strip()


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from Word document bytes, including tables."""
    doc = Document(io.BytesIO(file_bytes))

    # Extract text from paragraphs
    text_parts = [para.text for para in doc.paragraphs]

    # Extract text from tables (many CVs use tables for layout)
    for table in doc.tables:
        for row in table.rows:
            row_text = []
            for cell in row.cells:
                cell_text = cell.text.strip()
                if cell_text:
                    row_text.append(cell_text)
            if row_text:
                text_parts.append(" | ".join(row_text))

    return "\n".join(text_parts).strip()


def extract_text_from_doc(file_bytes: bytes) -> str:
    """Extract text from old .doc format using antiword."""
    with tempfile.NamedTemporaryFile(suffix='.doc', delete=False) as tmp:
        tmp.write(file_bytes)
        tmp.flush()
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ['antiword', tmp_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            raise ValueError(f"antiword failed: {result.stderr}")
    finally:
        os.unlink(tmp_path)


async def download_attachment(attachment, turn_context: TurnContext) -> bytes:
    """Download attachment from Teams."""
    download_url = None

    if attachment.content_type == "application/vnd.microsoft.teams.file.download.info":
        if isinstance(attachment.content, dict) and "downloadUrl" in attachment.content:
            download_url = attachment.content["downloadUrl"]

    if not download_url and attachment.content_url:
        download_url = attachment.content_url

    if not download_url:
        raise ValueError("No download URL found in attachment")

    async with httpx.AsyncClient() as client:
        response = await client.get(download_url, follow_redirects=True)
        response.raise_for_status()
        return response.content


async def extract_text_from_attachment(attachment, turn_context: TurnContext) -> str:
    """Download and extract text from an attachment."""
    name = attachment.name or ""
    if not name and isinstance(attachment.content, dict):
        name = attachment.content.get("name", "")
    content_type = attachment.content_type or ""

    try:
        file_bytes = await download_attachment(attachment, turn_context)

        if name.lower().endswith('.pdf') or 'pdf' in content_type.lower():
            return extract_text_from_pdf(file_bytes)
        elif name.lower().endswith('.docx') or 'wordprocessingml' in content_type.lower():
            return extract_text_from_docx(file_bytes)
        elif name.lower().endswith('.doc'):
            return extract_text_from_doc(file_bytes)
        else:
            return f"[Unsupported file type: {name}]"
    except Exception as e:
        return f"[Error extracting text from {name}: {str(e)}]"


def create_help_card():
    """Create an Adaptive Card with role selection buttons."""
    roles = get_roles()

    # Define button order and grouping (two rows to avoid overflow)
    row1_roles = ["spec", "profile", "ad", "jd"]
    row2_roles = ["pitch", "outreach", "reformat"]

    row1_actions = []
    for role_id in row1_roles:
        if role_id in roles:
            role = roles[role_id]
            row1_actions.append({
                "type": "Action.Submit",
                "title": role["name"],
                "data": {"action": "select_role", "role": role_id}
            })

    row2_actions = []
    for role_id in row2_roles:
        if role_id in roles:
            role = roles[role_id]
            row2_actions.append({
                "type": "Action.Submit",
                "title": role["name"],
                "data": {"action": "select_role", "role": role_id}
            })

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "What do you need?",
                "weight": "Bolder",
                "size": "Medium"
            },
            {
                "type": "TextBlock",
                "text": "Select an option or just send me your content with a trigger word (e.g., 'spec', 'ad', 'outreach').",
                "wrap": True,
                "size": "Small",
                "color": "Accent"
            },
            {
                "type": "ActionSet",
                "actions": row1_actions
            },
            {
                "type": "ActionSet",
                "actions": row2_actions
            }
        ]
    }

    return Attachment(
        content_type="application/vnd.microsoft.card.adaptive",
        content=card
    )


def create_refinement_card():
    """Create an Adaptive Card with refinement options (for non-reformat outputs)."""
    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "Want to make changes? Just tell me what to adjust, or:",
                "wrap": True,
                "size": "Small",
                "color": "Accent"
            }
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Done",
                "data": {"action": "exit_refinement"}
            },
            {
                "type": "Action.Submit",
                "title": "Start New",
                "data": {"action": "start_new"}
            }
        ]
    }

    return Attachment(
        content_type="application/vnd.microsoft.card.adaptive",
        content=card
    )


def create_start_new_card():
    """Create an Adaptive Card with just Start New button (for reformat outputs)."""
    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Start New",
                "data": {"action": "start_new"}
            }
        ]
    }

    return Attachment(
        content_type="application/vnd.microsoft.card.adaptive",
        content=card
    )


def refine_output(original_output: str, user_instruction: str, role_id: str) -> str:
    """Call Azure OpenAI to refine the output based on user instruction."""
    roles = get_roles()
    role = roles.get(role_id, {})
    role_name = role.get("name", "content")

    refinement_prompt = f"""Here is the previous {role_name} output:

{original_output}

The user has requested the following changes:
{user_instruction}

Return the revised version, maintaining the same format and style. Only output the revised content, no explanations."""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"You are a helpful assistant that refines {role_name} content based on user feedback. Maintain the original format and style while applying the requested changes."},
                {"role": "user", "content": refinement_prompt}
            ],
            max_tokens=8000,
            timeout=120
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error refining output: {str(e)}"


def check_explicit_trigger(message: str) -> str:
    """
    Check for EXPLICIT role triggers only (prefix or first word).
    Does NOT use AI classification.
    Returns role_id if found, None otherwise.
    """
    if not message:
        return None

    roles = get_roles()
    message_lower = message.lower().strip()
    words = message_lower.split()

    # Build lookup dictionary
    trigger_to_role = {}
    for role_id, role in roles.items():
        trigger_to_role[role["trigger"].lower()] = role_id
        for alias in role["aliases"]:
            trigger_to_role[alias.lower()] = role_id

    # Check for explicit prefix (/spec, !spec)
    if words and len(words[0]) > 1:
        first_word = words[0]
        if first_word.startswith('/') or first_word.startswith('!'):
            trigger = first_word[1:]
            if trigger in trigger_to_role:
                return trigger_to_role[trigger]

    # Check if first word is a known trigger
    if words and words[0] in trigger_to_role:
        return trigger_to_role[words[0]]

    return None


def resolve_role(message: str, card_data: dict = None) -> tuple:
    """
    Hybrid routing: resolve which role the user wants.
    Returns (role_id, remaining_message) or (None, None) if ambiguous.
    """
    roles = get_roles()

    # Step 0: Check for Adaptive Card button press
    if card_data and card_data.get("action") == "select_role":
        role_id = card_data.get("role")
        if role_id in roles:
            return role_id, ""

    if not message:
        return None, None

    message_lower = message.lower().strip()
    words = message_lower.split()

    # Build lookup dictionaries
    trigger_to_role = {}
    for role_id, role in roles.items():
        trigger_to_role[role["trigger"].lower()] = role_id
        for alias in role["aliases"]:
            trigger_to_role[alias.lower()] = role_id

    # Step 1: Check for explicit prefix (/spec, !spec)
    if words and len(words[0]) > 1:
        first_word = words[0]
        if first_word.startswith('/') or first_word.startswith('!'):
            trigger = first_word[1:]
            if trigger in trigger_to_role:
                remaining = ' '.join(words[1:])
                return trigger_to_role[trigger], remaining

    # Step 2: Check if first word is a known trigger
    if words and words[0] in trigger_to_role:
        remaining = ' '.join(words[1:])
        return trigger_to_role[words[0]], remaining

    # Step 3: Scan message for trigger keywords
    for trigger, role_id in trigger_to_role.items():
        if trigger in message_lower:
            return role_id, message

    # Step 4: Ask OpenAI to classify intent
    try:
        role_options = ", ".join(trigger_to_role.keys())
        classification_prompt = f"""Given this user message, which task are they requesting?
Options: {role_options}, none

Message: "{message}"

Reply with ONLY the task name or "none". Nothing else."""

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": classification_prompt}],
            max_tokens=20
        )

        classification = response.choices[0].message.content.strip().lower()
        if classification in trigger_to_role:
            return trigger_to_role[classification], message
    except Exception as e:
        print(f"Error classifying intent: {e}")

    # Step 5: Fallback - return None to trigger help menu
    return None, None


async def on_turn(turn_context: TurnContext):
    if turn_context.activity.type == "message":
        user_text = turn_context.activity.text or ""
        attachments = turn_context.activity.attachments or []

        # Get conversation ID for state management
        conversation_id = turn_context.activity.conversation.id

        # Check for Adaptive Card button data
        card_data = None
        if turn_context.activity.value:
            card_data = turn_context.activity.value

        # Handle help command
        if user_text.lower().strip() in ["help", "/help", "menu", "start", "hi", "hello"]:
            clear_refinement_state(conversation_id)
            help_card = create_help_card()
            reply = Activity(type="message", attachments=[help_card])
            await turn_context.send_activity(reply)
            return

        # Handle refinement button presses
        if card_data:
            action = card_data.get("action")
            if action == "exit_refinement":
                clear_refinement_state(conversation_id)
                await turn_context.send_activity("Great! Let me know if you need anything else.")
                help_card = create_help_card()
                reply = Activity(type="message", attachments=[help_card])
                await turn_context.send_activity(reply)
                return
            elif action == "start_new":
                clear_refinement_state(conversation_id)
                help_card = create_help_card()
                reply = Activity(type="message", attachments=[help_card])
                await turn_context.send_activity(reply)
                return

        # Extract text from any file attachments
        attachment_texts = []
        for attachment in attachments:
            if attachment.content_type and attachment.content_type.startswith('image/'):
                continue
            extracted = await extract_text_from_attachment(attachment, turn_context)
            if extracted and not extracted.startswith('['):
                attachment_texts.append(f"--- Content from {attachment.name} ---\n{extracted}")
            elif extracted.startswith('['):
                attachment_texts.append(extracted)

        # Combine user text with any extracted file content
        combined_input = user_text
        if attachment_texts:
            file_content = "\n\n".join(attachment_texts)
            if user_text:
                combined_input = f"{user_text}\n\n{file_content}"
            else:
                combined_input = file_content

        # Check for refinement mode BEFORE resolve_role
        refinement_state = get_refinement_state(conversation_id)

        # If in refinement mode, only check for EXPLICIT triggers (not AI classification)
        # This prevents "a bit shorter" from being classified as "reformat"
        if refinement_state and user_text and not card_data:
            # Check for explicit triggers only (prefix or first-word match)
            explicit_role = check_explicit_trigger(user_text)

            if explicit_role:
                # User explicitly requested a new role - exit refinement
                clear_refinement_state(conversation_id)
                print(f"[DEBUG] Exiting refinement mode due to explicit trigger: {explicit_role}")
                role_id = explicit_role
                content_for_role = user_text
            else:
                # No explicit trigger - treat as refinement instruction
                print(f"[DEBUG] In refinement mode, processing instruction: {user_text[:50]}...")
                refined_output = refine_output(
                    refinement_state["output"],
                    user_text,
                    refinement_state["role_id"]
                )
                # Update stored output with refined version
                set_refinement_state(conversation_id, refined_output, refinement_state["role_id"])
                # Send refined output with refinement buttons
                refinement_card = create_refinement_card()
                reply = Activity(type="message", text=refined_output, attachments=[refinement_card])
                await turn_context.send_activity(reply)
                return
        else:
            # Not in refinement mode - use full resolve_role (including AI classification)
            role_id, content_for_role = resolve_role(user_text, card_data)

        # If a role was identified via button while in refinement mode, exit refinement
        if card_data and refinement_state:
            clear_refinement_state(conversation_id)
            print(f"[DEBUG] Exiting refinement mode due to button press")

        # If card button was pressed with no content, ask for input and save pending role
        if role_id and card_data and not combined_input.strip():
            roles = get_roles()
            role = roles[role_id]
            set_pending_role(conversation_id, role_id)  # Remember the selection
            print(f"[DEBUG] Set pending role: conversation_id={conversation_id}, role_id={role_id}")
            await turn_context.send_activity(f"Great! Send me the content for **{role['name']}** - you can paste text or upload a PDF/Word file.")
            return

        # If no role identified, check for pending role from previous button click
        if not role_id:
            pending = get_pending_role(conversation_id)
            print(f"[DEBUG] No role_id. conversation_id={conversation_id}, pending={pending}, has_content={bool(combined_input)}, content_starts_with_bracket={combined_input[:20] if combined_input else 'N/A'}")
            if pending and combined_input and not combined_input.startswith('['):
                # Use the pending role from button click
                role_id = pending
                content_for_role = combined_input
                clear_pending_role(conversation_id)
            elif combined_input and not combined_input.startswith('['):
                # There's content but no clear role - show options
                help_card = create_help_card()
                reply = Activity(
                    type="message",
                    text="I'm not sure what you'd like me to do with this. Please select an option:",
                    attachments=[help_card]
                )
                await turn_context.send_activity(reply)
                return
            else:
                help_card = create_help_card()
                reply = Activity(type="message", attachments=[help_card])
                await turn_context.send_activity(reply)
                return

        # Get the role configuration
        roles = get_roles()
        role = roles[role_id]

        # Use file content if available, otherwise use the content from routing
        if attachment_texts:
            final_content = combined_input
        else:
            final_content = content_for_role if content_for_role else combined_input

        if not final_content or final_content.startswith('['):
            if final_content and final_content.startswith('['):
                await turn_context.send_activity(final_content)
            else:
                await turn_context.send_activity(f"Please send me content for **{role['name']}** - paste text or upload a PDF/Word file.")
            return

        # Call OpenAI with the role's system prompt
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": role["system_prompt"]},
                    {"role": "user", "content": final_content}
                ],
                max_tokens=8000,  # Allow large responses for full CVs
                timeout=120  # 2 minute timeout for large CVs
            )
            reply_text = response.choices[0].message.content
        except Exception as e:
            await turn_context.send_activity(f"Error calling AI: {str(e)}")
            return

        # Handle special output types (CV Reformat - no refinement mode)
        if role.get("output_type") == "word":
            # Generate Word document for CV reformat
            try:
                cv_data = parse_cv_json(reply_text)
                doc_bytes = create_meraki_cv(cv_data)

                # Create filename from candidate name
                candidate_name = cv_data.get("name", "Candidate").replace(" ", "_")
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                filename = f"Meraki_CV_{candidate_name}_{timestamp}.docx"

                # Upload to Azure Blob Storage
                if blob_service_client:
                    container_client = blob_service_client.get_container_client("cv-outputs")
                    blob_client = container_client.get_blob_client(filename)
                    blob_client.upload_blob(doc_bytes, overwrite=True)

                    # Generate SAS URL valid for 7 days
                    account_name = blob_service_client.account_name
                    account_key = storage_connection_string.split("AccountKey=")[1].split(";")[0]
                    sas_token = generate_blob_sas(
                        account_name=account_name,
                        container_name="cv-outputs",
                        blob_name=filename,
                        account_key=account_key,
                        permission=BlobSasPermissions(read=True),
                        expiry=datetime.utcnow() + timedelta(days=7)
                    )
                    download_url = f"https://{account_name}.blob.core.windows.net/cv-outputs/{filename}?{sas_token}"

                    # Send output with Start New button (no refinement for reformat)
                    start_new_card = create_start_new_card()
                    reply = Activity(
                        type="message",
                        text=f"Here's the reformatted CV for **{cv_data.get('name', 'the candidate')}**:\n\n"
                             f"[Download {filename}]({download_url})\n\n"
                             f"_Link expires in 7 days_",
                        attachments=[start_new_card]
                    )
                    await turn_context.send_activity(reply)
                else:
                    await turn_context.send_activity("Error: Storage not configured for file uploads")
            except ValueError as e:
                await turn_context.send_activity(f"Error parsing CV data: {str(e)}\n\nRaw response:\n{reply_text[:500]}...")
            except Exception as e:
                await turn_context.send_activity(f"Error generating Word document: {str(e)}")
            return

        # For non-reformat outputs: enter refinement mode
        # Store output and show refinement options
        set_refinement_state(conversation_id, reply_text, role_id)
        refinement_card = create_refinement_card()
        reply = Activity(type="message", text=reply_text, attachments=[refinement_card])
        await turn_context.send_activity(reply)


@app.route("/")
def home():
    return "Bot is running!"


@app.route("/api/messages", methods=["POST"])
def messages():
    if "application/json" in request.headers.get("Content-Type", ""):
        body = request.json
    else:
        return Response(status=415)

    activity = Activity().deserialize(body)
    auth_header = request.headers.get("Authorization", "")

    async def call_bot():
        await adapter.process_activity(activity, auth_header, on_turn)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(call_bot())
    loop.close()

    return Response(status=200)


if __name__ == "__main__":
    app.run()
