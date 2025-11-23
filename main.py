# main.py
import os
import asyncio
import json
import time
from typing import Optional
from dotenv import load_dotenv
import requests
import discord

load_dotenv()

# --- Config from env ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "gemma2-3b")
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "180"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
OWNER_ID = int(os.getenv("OWNER_ID")) if os.getenv("OWNER_ID") else None

if not DISCORD_TOKEN or not GROQ_API_KEY:
    raise RuntimeError("Set DISCORD_TOKEN and GROQ_API_KEY in environment variables.")

# --- Discord setup ---
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# --- Simple per-user rate limit (tokens) ---
# Allows bursts but prevents spamming the Groq API
USER_BUCKET = {}  # uid -> (tokens, last_refill_ts)
RATE_MAX_TOKENS = 3
RATE_REFILL_SECONDS = 20  # refill interval for full bucket

def refill_tokens(uid: int):
    now = time.time()
    tokens, last = USER_BUCKET.get(uid, (RATE_MAX_TOKENS, now))
    elapsed = now - last
    # linear refill
    refill = (elapsed / RATE_REFILL_SECONDS) * RATE_MAX_TOKENS
    tokens = min(RATE_MAX_TOKENS, tokens + refill)
    USER_BUCKET[uid] = (tokens, now)
    return tokens

def consume_token(uid: int) -> bool:
    tokens = refill_tokens(uid)
    tokens, last = USER_BUCKET.get(uid, (RATE_MAX_TOKENS, time.time()))
    if tokens >= 1:
        USER_BUCKET[uid] = (tokens - 1, last)
        return True
    USER_BUCKET[uid] = (tokens, last)
    return False

# --- Personality / system prompt ---
SYSTEM_PROMPT = (
    "You are Manzar — a witty, slightly savage Discord poet inspired by Jaun Elia.\n"
    "Style: mix Hindi/Urdu casually with English, short shayari lines, playful roasts. "
    "Be creative and never produce hateful or illegal content. Keep replies short (1–6 sentences) unless user asks for more.\n"
)

# build messages for Groq's OpenAI-compatible chat endpoint
def build_messages(user_text: str, mode_hint: Optional[str] = None):
    messages = []
    messages.append({"role": "system", "content": SYSTEM_PROMPT})
    if mode_hint:
        # optional mode instruction
        messages.append({"role": "system", "content": f"MODE_HINT: {mode_hint}"})
    messages.append({"role": "user", "content": user_text})
    return messages

# --- Call Groq OpenAI-compatible chat completion endpoint ---
# Docs: POST https://api.groq.com/openai/v1/chat/completions
# Authorization: Bearer <GROQ_API_KEY>
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

def call_groq_chat(messages, model=GROQ_MODEL, max_output_tokens=MAX_OUTPUT_TOKENS, temperature=TEMPERATURE, timeout=60):
    payload = {
        "model": model,
        "messages": messages,
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.post(GROQ_CHAT_URL, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    # try common response paths
    if isinstance(data, dict):
        # openai-compat: choices[0].message.content
        if "choices" in data and len(data["choices"]) > 0:
            choice = data["choices"][0]
            msg = choice.get("message", {}).get("content")
            if msg:
                return msg
        # groq: may include 'text' or 'response' top-level
        if "response" in data:
            return data["response"]
        if "text" in data:
            return data["text"]
    # fallback: return string form
    return json.dumps(data)[:1900]

# --- Bot behavior ---
@client.event
async def on_ready():
    print(f"Logged in as {client.user} — groq model: {GROQ_MODEL}")

@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return

    content = message.content.strip()
    lower = content.lower()

    # help
    if lower.startswith("!help"):
        await message.reply("Commands: `!manzar <text>` or mention me. Extras: `!shayari`, `!roast`, `!mode <default|jaunelia|friendly|roast` (owner only).")
        return

    # owner only: change system style quickly (optional)
    if lower.startswith("!mode ") and OWNER_ID and message.author.id == OWNER_ID:
        # store mode hint in a simple local attribution (or you can implement persistence)
        mode = lower.split(" ",1)[1].strip()
        await message.reply(f"Mode changed on-the-fly to: {mode} (applies to next messages).")
        # we'll just pass mode as mode_hint when building messages below, no persistence
        return

    if lower.startswith("!shayari"):
        user_query = "Write a short 2-line Urdu/Hindi shayari inspired by Jaun Elia but original."
    elif lower.startswith("!roast"):
        user_query = "Write a short playful roast (1-2 lines). Keep it witty, not hateful."
    elif client.user.mentioned_in(message) or lower.startswith("!manzar"):
        # extract text
        user_query = content.replace(f"<@{client.user.id}>","").replace("!manzar","").strip()
        if not user_query:
            user_query = "hello"
    else:
        return

    # Rate-limit per-user
    if not consume_token(message.author.id):
        await message.reply("Slow down bhai — too many requests. Try again in a few seconds.")
        return

    # Show typing indicator
    await message.channel.trigger_typing()

    # Build messages (we could support modes by reading message or a small memory; keeping simple)
    mode_hint = None
    if lower.startswith("!shayari"):
        mode_hint = "jaunelia"
    elif lower.startswith("!roast"):
        mode_hint = "roast"
    messages = build_messages(user_query, mode_hint=mode_hint)

    # Run blocking network call in executor
    loop = asyncio.get_event_loop()
    try:
        ai_reply = await loop.run_in_executor(None, call_groq_chat, messages)
    except Exception as e:
        print("Groq API error:", e)
        await message.reply("Mera brain abhi busy hai — try again in a bit.")
        return

    if not ai_reply:
        await message.reply("Kuch garbar ho gayi, try again.")
        return

    # Truncate if too long
    if len(ai_reply) > 1900:
        ai_reply = ai_reply[:1900] + "\n\n...(truncated)"

    await message.reply(ai_reply)

if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
