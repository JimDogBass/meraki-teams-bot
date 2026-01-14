import os
import asyncio
import io
import time
import httpx
from flask import Flask, request, Response
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity, Attachment
from openai import AzureOpenAI
from PyPDF2 import PdfReader
from docx import Document
from azure.data.tables import TableServiceClient

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

# Azure Table Storage connection
storage_connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
table_service_client = None
if storage_connection_string:
    table_service_client = TableServiceClient.from_connection_string(storage_connection_string)

# Role cache
roles_cache = {}
roles_cache_timestamp = 0
CACHE_TTL_SECONDS = 300  # 5 minutes


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
- Anonymise all company names (e.g., "RE Mega Fund", "Big 4 Accountancy Firm", "Global Investment Bank", "Leading Asset Manager", "Top-Tier PE Fund")
- Include company size/AUM where relevant (e.g., "RE Fund > $20bn AUM")
- Only include the last 2 roles
- Include 3-4 bullet points per role highlighting achievements and responsibilities
- Anonymise university names (e.g., "Top 100 College", "Russell Group University", "Top Tier Business School")
- Do not include candidate name, contact details, or any identifying information
- Do not include gender
- Do not include pronouns that reveal gender - use "they/their"

FORMAT (follow exactly):

Subject: Candidate Spec - [Seniority] [Function] - [Location]

Hi

I am working with an exceptional [Function] professional who has a solid background within [Industry/Sector]. They are actively seeking a new opportunity in [Location].

I have highlighted some of their career below; let me know if you would be interested in seeing a full resume or would be interested in having a chat about the general market.

[Anonymised Company Description] | [Location]
[Role Title] ([Dates])
- [Achievement/responsibility]
- [Achievement/responsibility]
- [Achievement/responsibility]
- [Achievement/responsibility]

[Anonymised Company Description] | [Location]
[Role Title] ([Dates])
- [Achievement/responsibility]
- [Achievement/responsibility]
- [Achievement/responsibility]

Education
[Anonymised University Description] - [Degree], [Specialization] ([Year])"""
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
            "system_prompt": """You are a recruitment consultant assistant. Create a formal job description document from notes or role information.

RULES:
- Create a professional, formal document
- Include all standard JD sections
- Be comprehensive but not verbose
- Include clear requirements vs nice-to-haves

FORMAT:
Job Title:
Reports To:
Location:
Salary Range:

About the Company:
Role Overview:
Key Responsibilities:
Required Skills & Experience:
Desirable Skills:
Benefits & Perks:"""
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

RULES:
- Keep it SHORT (3-5 sentences max)
- Be casual and direct, not corporate
- Don't sound like a template
- Include a hook specific to the role
- Soft call to action (not pushy)
- No "Hope this finds you well" or recruiter cliches

TONE: Like a message from someone who actually read their profile

EXAMPLE STYLE:
"Hi Sarah - came across your profile and thought this might be up your street. Head of Engineering role, scaling a team from 5 to 20, Series B fintech that's actually profitable. Interested in a quick chat?"

Just output the message, nothing else."""
        },
        "reformat": {
            "id": "reformat",
            "name": "CV Reformat",
            "trigger": "reformat",
            "aliases": ["format", "template"],
            "icon": "ArrowRepeat",
            "system_prompt": """You are a recruitment consultant assistant. The user wants to reformat a CV onto the Meraki template.

Note: Full CV reformatting to Word template is coming soon. For now, provide the CV content in a clean, structured format that can be easily copied into a Word template.

FORMAT:
PERSONAL DETAILS
Name:
Location:
Contact:

PROFILE SUMMARY
[2-3 sentence summary]

EXPERIENCE
[Company] | [Location]
[Title] | [Dates]
- [Achievement]
- [Achievement]

EDUCATION
[Qualification] - [Institution] ([Year])

SKILLS
[Comma-separated list]"""
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
    """Extract text from PDF file bytes."""
    reader = PdfReader(io.BytesIO(file_bytes))
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text.strip()


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from Word document bytes."""
    doc = Document(io.BytesIO(file_bytes))
    text = "\n".join([para.text for para in doc.paragraphs])
    return text.strip()


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
            return "[Error: Old .doc format not supported. Please save as .docx]"
        else:
            return f"[Unsupported file type: {name}]"
    except Exception as e:
        return f"[Error extracting text from {name}: {str(e)}]"


def create_help_card():
    """Create an Adaptive Card with role selection buttons."""
    roles = get_roles()

    actions = []
    for role_id, role in roles.items():
        actions.append({
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
            }
        ],
        "actions": actions
    }

    return Attachment(
        content_type="application/vnd.microsoft.card.adaptive",
        content=card
    )


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

        # Check for Adaptive Card button data
        card_data = None
        if turn_context.activity.value:
            card_data = turn_context.activity.value

        # Handle help command
        if user_text.lower().strip() in ["help", "/help", "menu", "start", "hi", "hello"]:
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

        # Resolve which role to use
        role_id, content_for_role = resolve_role(user_text, card_data)

        # If card button was pressed with no content, ask for input
        if role_id and card_data and not combined_input.strip():
            roles = get_roles()
            role = roles[role_id]
            await turn_context.send_activity(f"Great! Send me the content for **{role['name']}** - you can paste text or upload a PDF/Word file.")
            return

        # If no role identified, show help
        if not role_id:
            if combined_input and not combined_input.startswith('['):
                # There's content but no clear role - show options
                help_card = create_help_card()
                reply = Activity(
                    type="message",
                    text="I'm not sure what you'd like me to do with this. Please select an option:",
                    attachments=[help_card]
                )
                await turn_context.send_activity(reply)
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
                ]
            )
            reply_text = response.choices[0].message.content
        except Exception as e:
            reply_text = f"Error calling AI: {str(e)}"

        await turn_context.send_activity(reply_text)


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
