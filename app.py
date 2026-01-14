import os
import asyncio
import io
import httpx
from flask import Flask, request, Response
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
from openai import AzureOpenAI
from PyPDF2 import PdfReader
from docx import Document

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

    # Teams file uploads come with content_type = application/vnd.microsoft.teams.file.download.info
    # and content contains a dict with downloadUrl
    if attachment.content_type == "application/vnd.microsoft.teams.file.download.info":
        if isinstance(attachment.content, dict) and "downloadUrl" in attachment.content:
            download_url = attachment.content["downloadUrl"]

    # Fallback to content_url if available
    if not download_url and attachment.content_url:
        download_url = attachment.content_url

    if not download_url:
        raise ValueError("No download URL found in attachment")

    # Teams provides pre-authenticated download URLs, no auth header needed
    async with httpx.AsyncClient() as client:
        response = await client.get(download_url, follow_redirects=True)
        response.raise_for_status()
        return response.content


async def extract_text_from_attachment(attachment, turn_context: TurnContext) -> str:
    """Download and extract text from an attachment."""
    # Get filename - might be in attachment.name or in content dict for Teams
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


SYSTEM_PROMPT = """You are a recruitment consultant assistant. When given CV information or candidate details, create an anonymised candidate spec email.

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
[Anonymised University Description] - [Degree], [Specialization] ([Year])

For general questions not about CVs, respond helpfully as a recruitment assistant."""

async def on_turn(turn_context: TurnContext):
    if turn_context.activity.type == "message":
        user_text = turn_context.activity.text or ""
        attachments = turn_context.activity.attachments or []

        # Extract text from any file attachments
        attachment_texts = []
        for attachment in attachments:
            # Skip inline images and other non-document attachments
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

        if combined_input and not combined_input.startswith('['):
            try:
                response = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": combined_input}
                    ]
                )
                reply_text = response.choices[0].message.content
            except Exception as e:
                reply_text = f"Error calling AI: {str(e)}"
        elif combined_input.startswith('['):
            # Error message from file extraction
            reply_text = combined_input
        else:
            reply_text = "Send me a CV (paste text, or upload PDF/Word file) and I'll create an anonymised spec email for you."

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
