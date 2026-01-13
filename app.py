from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

@app.route("/api/messages", methods=["POST"])
def messages():
    return jsonify({"type": "message", "text": "Hello from bot!"})

if __name__ == "__main__":
    app.run()
