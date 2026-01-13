from flask import Flask, request, jsonify
import os
from openai import AzureOpenAI

app = Flask(__name__)

client = AzureOpenAI(
    api_key=os.environ.get("AZURE_OPENAI_KEY"),
    api_version="2024-02-01",
    azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
)

@app.route("/")
def home():
    return "Bot is running!"

@app.route("/api/messages", methods=["POST"])
def messages():
    try:
        body = request.get_json()
        activity_type = body.get("type", "")
        
        if activity_type == "message":
            user_text = body.get("text", "")
            
            if user_text:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a helpful recruitment assistant."},
                        {"role": "user", "content": user_text}
                    ]
                )
                reply_text = response.choices[0].message.content
            else:
                reply_text = "Send me a CV and I'll create an anonymised spec email."
            
            return jsonify({
                "type": "message",
                "from": body.get("recipient"),
                "recipient": body.get("from"),
                "conversation": body.get("conversation"),
                "text": reply_text,
                "replyToId": body.get("id")
            })
        
        return "", 200
    
    except Exception as e:
        return jsonify({"type": "message", "text": f"Error: {str(e)}"})

if __name__ == "__main__":
    app.run()
