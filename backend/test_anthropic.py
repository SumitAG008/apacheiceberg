import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

key = os.environ.get("ANTHROPIC_API_KEY")
print(f"Loaded Key length: {len(key) if key else 0}")
if key:
    print(f"Key starts with: {key[:15]}... and ends with: ...{key[-5:]}")

client = Anthropic(api_key=key)

models = [
    "claude-sonnet-5",
    "claude-haiku-4.5",
    "claude-opus-4.8",
    "claude-fable-5",
    "claude-3-5-sonnet"
]

for model in models:
    try:
        print(f"\nTesting model: {model}...")
        message = client.messages.create(
            model=model,
            max_tokens=10,
            messages=[
                {"role": "user", "content": "Hello"}
            ]
        )
        print(f"✅ Success! Response: {message.content[0].text}")
    except Exception as e:
        print(f"❌ Error: {e}")
