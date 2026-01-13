from flask import Flask, request, jsonify
import os
from openai import AzureOpenAI

app = Flask(__name__)

client = AzureOpenAI(
    api_key=os.environ.get("AZURE_OPENAI_KEY"),
    api_version="2024-02-01",
    azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
)

PROMPT_TEMPLATE = """
You are a recruitment consultant. Given a CV/resume, create an anonymised candidate spec email.

RULES:
- Anonymise all company names (e.g., "RE Mega Fund", "Big 4 Accountancy Firm", "Global Investment Bank", "Leading Asset Manager")
- Include company size/AUM where relevant (e.g., "RE Fund > $20bn AUM")
- Only include the last 2 roles
- Include 3-4 bullet points per role
- Anonymise university names (e.g., "Top 100 College", "Russell Group University")
- Do not include candidate name, contact details, or any identifying information
- Do not include gender

FORMAT (follow exactly):

Subject: Candidate Spec - [Seniority] [Function] - [Location]

Hi

I am working with an exceptional [Function] professional who has a solid background within [Industry/Sector]. They are actively seeking a new opportunity in [Location].

I have highlighted some of their career below; let me know if you would be interested in seeing a full resume or would be interested in having a chat about the general market.

[Company Description] | [Location]
[Role Title] ([Dates])
[Role Title if promoted] ([Dates])
- [Achievement/responsibility]
- [Achievement/responsibility]
- [Achievement/responsibility]

[Company Description] | [Location]
[Role Title] ([Dates])
- [Achievement/responsibility]
- [Achievement/responsibility]
- [Achievement/responsibility]

Education
[University Description] - [Degree], [Specialization] ([Year])
"""

@app.route("/")
def home():
    return "Bot is running!"

@app.route("/api/messages", methods=["POST"])
def messages():
    try:
        body = request.get_json()
        
        if body.get("type") == "message":
            text = body.get("text", "")
            
            if text:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a helpful recruitment assistant."},
                        {"role": "user", "content": text}
                    ]
                )
                reply = response.choices[0].message.content
            else:
                reply = "Send me a CV and I'll create an anonymised spec email."
            
            return jsonify({"type": "message", "text": reply})
        
        return jsonify({"type": "message", "text": "Hello!"})
    
    except Exception as e:
        return jsonify({"type": "message", "text": f"Error: {str(e)}"})

if __name__ == "__main__":
    app.run()
```