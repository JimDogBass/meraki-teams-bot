import os
import asyncio
from flask import Flask, request, Response
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
from openai import AzureOpenAI

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
        user_text = turn_context.activity.text
        
        if user_text:
            try:
                response = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_text}
                    ]
                )
                reply_text = response.choices[0].message.content
            except Exception as e:
                reply_text = f"Error calling AI: {str(e)}"
        else:
            reply_text = "Send me CV details and I'll create an anonymised spec email for you."
        
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
