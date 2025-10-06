from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)
client = OpenAI()  # OPENAI_API_KEY from environment

@app.post("/webhook/on_message")
def on_message():
    data = request.get_json()
    caller = data.get("caller")
    text = data.get("text")

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Antworte kurz und klar."},
            {"role": "user", "content": text}
        ]
    )

    reply = completion.choices[0].message.content
    return jsonify({"caller": caller, "reply": reply})

if __name__ == "__main__":
    app.run(port=5678)