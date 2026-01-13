import os
import asyncio
from flask import Flask, request, Response
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
from openai import AzureOpenAI

app = Flask(__name__)

# Bot Framework settings for Single Tenant
settings = BotFrameworkAdapterSettings(
    app_id=os.environ.get("MICROSOFT_APP_ID", ""),
    app_password=os.environ.get("MICROSOFT_APP_PASSWORD", ""),
    channel_auth_tenant=os.environ.get("MICROSOFT_APP_TENANT_ID", "")
)
adapter = BotFrameworkAdapter(settings)

# Azure OpenAI client
openai_client = AzureOpenAI(
    api_key=os.environ.get("AZURE_OPENAI_KEY"),
    api_version="2024-02-01",
    azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
)

async def on_turn(turn_context: TurnContext):
    if turn_context.activity.type == "message":
        user_text = turn_context.activity.text
        
        if user_text:
            try:
                response = openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a helpful recruitment assistant."},
                        {"role": "user", "content": user_text}
                    ]
                )
                reply_text = response.choices[0].message.content
            except Exception as e:
                reply_text = f"Error calling AI: {str(e)}"
        else:
            reply_text = "Send me a CV and I'll create an anonymised spec email."
        
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
