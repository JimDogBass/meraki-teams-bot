"""
Fernando Format - CV Reformat Bot for Meraki Talent
Single-function bot that reformats CVs with Meraki branding and generates alternative candidate profiles.
Stripped down from "Jimmy Content" bot to focus solely on CV reformatting.
"""
import os
import asyncio
import io
import time
import httpx
import tempfile
import subprocess
from flask import Flask, request, Response
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity, Attachment
from openai import AzureOpenAI
import pdfplumber
from docx import Document
from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta
from cv_generator import create_meraki_cv, parse_cv_json, CV_EXTRACTION_PROMPT

app = Flask(__name__)

# Bot Framework adapter setup
settings = BotFrameworkAdapterSettings(
    app_id=os.environ.get("MICROSOFT_APP_ID", ""),
    app_password=os.environ.get("MICROSOFT_APP_PASSWORD", ""),
    channel_auth_tenant=os.environ.get("MICROSOFT_APP_TENANT_ID", "")
)
adapter = BotFrameworkAdapter(settings)

# Azure OpenAI client setup
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

# Pending state TTL - for button click -> file upload flow
PENDING_ROLE_TTL_SECONDS = 300  # 5 minutes

# Alternative Candidate Profile prompt
ALTERNATIVE_PROFILE_PROMPT = """Based on this CV data, write a short alternative candidate profile (2-3 sentences max).

This is a punchy summary to send alongside the CV to a client. Use "they/their" pronouns. Highlight their key strengths, current situation, and what makes them stand out. Keep it compelling and concise.

CV Data:
{cv_json}

Output ONLY the profile text, nothing else."""


def get_pending_reformat(conversation_id: str) -> bool:
    """Check if there's a pending reformat request for this conversation."""
    if not table_service_client:
        print("[DEBUG] No table_service_client for pending state")
        return False

    try:
        table_client = table_service_client.get_table_client("BotState")
        row_key = str(hash(conversation_id) & 0xFFFFFFFF)

        try:
            entity = table_client.get_entity(partition_key="pending_role", row_key=row_key)
            timestamp = entity.get("Timestamp_", 0)

            if time.time() - timestamp < PENDING_ROLE_TTL_SECONDS:
                print(f"[DEBUG] Found pending reformat state")
                return True
            else:
                table_client.delete_entity(partition_key="pending_role", row_key=row_key)
                print("[DEBUG] Pending state expired")
        except Exception:
            print("[DEBUG] No pending state found in table")
    except Exception as e:
        print(f"[DEBUG] Error getting pending state: {e}")

    return False


def set_pending_reformat(conversation_id: str):
    """Set a pending reformat request in Azure Table Storage."""
    if not table_service_client:
        print("[DEBUG] No table_service_client to set pending state")
        return

    try:
        table_client = table_service_client.get_table_client("BotState")

        try:
            table_service_client.create_table("BotState")
        except Exception:
            pass  # Table already exists

        row_key = str(hash(conversation_id) & 0xFFFFFFFF)
        entity = {
            "PartitionKey": "pending_role",
            "RowKey": row_key,
            "ConversationId": conversation_id[:900],
            "Role": "reformat",
            "Timestamp_": time.time()
        }
        table_client.upsert_entity(entity)
        print(f"[DEBUG] Set pending reformat state for {row_key}")
    except Exception as e:
        print(f"[DEBUG] Error setting pending state: {e}")


def clear_pending_reformat(conversation_id: str):
    """Clear pending reformat state from Azure Table Storage."""
    if not table_service_client:
        return

    try:
        table_client = table_service_client.get_table_client("BotState")
        row_key = str(hash(conversation_id) & 0xFFFFFFFF)
        table_client.delete_entity(partition_key="pending_role", row_key=row_key)
        print(f"[DEBUG] Cleared pending state for {row_key}")
    except Exception as e:
        print(f"[DEBUG] Error clearing pending state: {e}")


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF file bytes, including tables."""
    text_parts = []

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    row_text = [cell.strip() if cell else "" for cell in row]
                    row_text = [cell for cell in row_text if cell]
                    if row_text:
                        text_parts.append(" | ".join(row_text))

    return "\n".join(text_parts).strip()


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from Word document bytes, including tables."""
    doc = Document(io.BytesIO(file_bytes))

    text_parts = [para.text for para in doc.paragraphs]

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
    """Create a simple Adaptive Card with single Reformat CV button."""
    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "Fernando Format",
                "weight": "Bolder",
                "size": "Medium"
            },
            {
                "type": "TextBlock",
                "text": "Upload a CV (PDF or Word) to reformat it with Meraki branding.",
                "wrap": True,
                "size": "Small",
                "color": "Accent"
            }
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Reformat CV",
                "data": {"action": "reformat_cv"}
            }
        ]
    }

    return Attachment(
        content_type="application/vnd.microsoft.card.adaptive",
        content=card
    )


def create_start_new_card():
    """Create an Adaptive Card with just Start New button."""
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


def generate_alternative_profile(cv_json: str) -> str:
    """Generate a short alternative candidate profile from CV data."""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": ALTERNATIVE_PROFILE_PROMPT.format(cv_json=cv_json)}
            ],
            max_tokens=500,
            timeout=60
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[DEBUG] Error generating alternative profile: {e}")
        return ""


def is_reformat_trigger(text: str) -> bool:
    """Check if the message contains reformat trigger words."""
    if not text:
        return False
    text_lower = text.lower().strip()
    triggers = ["reformat", "format", "template", "/reformat", "!reformat"]
    words = text_lower.split()
    return any(trigger in words or text_lower.startswith(trigger) for trigger in triggers)


async def process_cv_reformat(cv_text: str, turn_context: TurnContext):
    """Process CV text and generate reformatted Word document with alternative profile."""
    try:
        # Step 1: Extract structured CV data using OpenAI
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": CV_EXTRACTION_PROMPT},
                {"role": "user", "content": cv_text}
            ],
            max_tokens=8000,
            timeout=120
        )
        cv_json_text = response.choices[0].message.content

        # Step 2: Parse JSON and generate Word document
        cv_data = parse_cv_json(cv_json_text)
        doc_bytes = create_meraki_cv(cv_data)

        # Create filename from candidate name
        candidate_name = cv_data.get("name", "Candidate").replace(" ", "_")
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"Meraki_CV_{candidate_name}_{timestamp}.docx"

        # Step 3: Generate alternative candidate profile
        alternative_profile = generate_alternative_profile(cv_json_text)

        # Step 4: Upload to Azure Blob Storage
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

            # Build response message
            response_text = (
                f"Here's the reformatted CV for **{cv_data.get('name', 'the candidate')}**:\n\n"
                f"[Download {filename}]({download_url})\n\n"
                f"_Link expires in 7 days_"
            )

            # Add alternative profile if generated
            if alternative_profile:
                response_text += f"\n\n**Alternative Candidate Profile:**\n{alternative_profile}"

            # Send output with Start New button
            start_new_card = create_start_new_card()
            reply = Activity(
                type="message",
                text=response_text,
                attachments=[start_new_card]
            )
            await turn_context.send_activity(reply)
        else:
            await turn_context.send_activity("Error: Storage not configured for file uploads")

    except ValueError as e:
        await turn_context.send_activity(f"Error parsing CV data: {str(e)}")
    except Exception as e:
        await turn_context.send_activity(f"Error generating Word document: {str(e)}")


async def on_turn(turn_context: TurnContext):
    """
    Simplified message handler for Fernando Format bot.

    Flow:
    1. Help commands -> show simple card
    2. "Start New" button -> show simple card
    3. "Reformat CV" button (no content) -> set pending state, ask for CV
    4. Pending state + content -> process CV
    5. Reformat trigger words in message -> process CV
    6. File attached (no trigger) -> assume reformat, process CV
    7. Fallback -> show simple card
    """
    if turn_context.activity.type == "message":
        user_text = turn_context.activity.text or ""
        attachments = turn_context.activity.attachments or []
        conversation_id = turn_context.activity.conversation.id

        # Check for Adaptive Card button data
        card_data = turn_context.activity.value

        # 1. Handle help commands
        if user_text.lower().strip() in ["help", "/help", "menu", "start", "hi", "hello", "hey"]:
            clear_pending_reformat(conversation_id)
            help_card = create_help_card()
            reply = Activity(type="message", attachments=[help_card])
            await turn_context.send_activity(reply)
            return

        # 2. Handle "Start New" button
        if card_data and card_data.get("action") == "start_new":
            clear_pending_reformat(conversation_id)
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

        # Combine user text with extracted file content
        combined_input = user_text
        if attachment_texts:
            file_content = "\n\n".join(attachment_texts)
            if user_text:
                combined_input = f"{user_text}\n\n{file_content}"
            else:
                combined_input = file_content

        # 3. Handle "Reformat CV" button press with no content
        if card_data and card_data.get("action") == "reformat_cv":
            if not combined_input.strip() or combined_input.startswith('['):
                set_pending_reformat(conversation_id)
                await turn_context.send_activity("Great! Send me the CV - you can paste text or upload a PDF/Word file.")
                return
            else:
                # Button pressed with content attached - process immediately
                clear_pending_reformat(conversation_id)
                await process_cv_reformat(combined_input, turn_context)
                return

        # 4. Check for pending reformat state with content
        if get_pending_reformat(conversation_id) and combined_input and not combined_input.startswith('['):
            clear_pending_reformat(conversation_id)
            await process_cv_reformat(combined_input, turn_context)
            return

        # 5. Check for reformat trigger words in message
        if is_reformat_trigger(user_text):
            # Remove trigger word from content if it's a prefix
            content_to_process = combined_input
            if content_to_process and not attachment_texts:
                # Strip trigger from beginning if present
                words = content_to_process.split(None, 1)
                if len(words) > 1 and is_reformat_trigger(words[0]):
                    content_to_process = words[1]

            if content_to_process and not content_to_process.startswith('['):
                await process_cv_reformat(content_to_process, turn_context)
                return
            else:
                set_pending_reformat(conversation_id)
                await turn_context.send_activity("Send me the CV to reformat - paste text or upload a PDF/Word file.")
                return

        # 6. File attached with no explicit trigger -> assume reformat
        if attachment_texts and not combined_input.startswith('['):
            await process_cv_reformat(combined_input, turn_context)
            return

        # 7. Handle extraction errors
        if combined_input.startswith('['):
            await turn_context.send_activity(combined_input)
            return

        # 8. Fallback -> show help card
        help_card = create_help_card()
        reply = Activity(type="message", attachments=[help_card])
        await turn_context.send_activity(reply)


@app.route("/")
def home():
    return "Fernando Format bot is running!"


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
