import os
import discord
import requests
from discord.ext import commands
from dotenv import load_dotenv
import asyncio

# Load environment variables
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "gemma2-3b")  # default model
MAX_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", 180))
TEMPERATURE = float(os.getenv("TEMPERATURE", 0.7))
OWNER_ID = os.getenv("OWNER_ID")  # optional

# Discord intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Simple rate limiter per user
cooldown = {}
COOLDOWN_SECONDS = 5


def is_in_cooldown(user_id):
    if user_id not in cooldown:
        return False
    return (asyncio.get_event_loop().time() - cooldown[user_id]) < COOLDOWN_SECONDS


def update_cooldown(user_id):
    cooldown[user_id] = asyncio.get_event_loop().time()


# --------------------------
# GROQ CHAT FUNCTION
# --------------------------
def groq_generate(message_content):
    url = "https://api.groq.com/openai/v1/chat/completions"

    prompt = f"""
You are MANZAR, a savage but poetic Urdu/Hindi chatbot. 
Your style = roasted + witty + shayari + Jaun Elia tone.
Always respond like a cool dost, with 1–2 lines of shayari sometimes.

User said: {message_content}
Respond naturally.
"""

    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    r = requests.post(url, json=payload, headers=headers)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# --------------------------
# DISCORD EVENTS
# --------------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} — using model: {GROQ_MODEL}")
    await bot.change_presence(activity=discord.Game("Manzar is alive 😎🔥"))


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    # Rate limit
    if is_in_cooldown(message.author.id):
        await message.channel.send("Bhai thoda ruk ja… CPU bhi insaan hai 😭")
        return

    update_cooldown(message.author.id)

    # Trigger on bot mention
    if bot.user.mention in message.content or message.content.lower().startswith("!manzar"):
        user_prompt = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if user_prompt == "":
            user_prompt = "Bol bhai?"

        try:
            reply = await asyncio.to_thread(groq_generate, user_prompt)
            await message.channel.send(reply)
        except Exception as e:
            await message.channel.send("Abe kuch gadbad ho gayi… fir try kar 😂")
            print("ERROR:", e)

    await bot.process_commands(message)


# --------------------------
# BASIC COMMANDS
# --------------------------
@bot.command()
async def ping(ctx):
    await ctx.send("Pong bhai 😎")


@bot.command()
async def owner(ctx):
    if OWNER_ID:
        await ctx.send(f"Mera malik: <@{OWNER_ID}>")
    else:
        await ctx.send("Owner not set.")


# --------------------------
# RUN BOT
# --------------------------
bot.run(DISCORD_TOKEN)
