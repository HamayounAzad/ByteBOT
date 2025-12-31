import os
import re
import html
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from openai import AsyncOpenAI

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Clean keys if they exist
if TELEGRAM_TOKEN:
    TELEGRAM_TOKEN = TELEGRAM_TOKEN.strip()
if OPENROUTER_API_KEY:
    OPENROUTER_API_KEY = OPENROUTER_API_KEY.strip()

OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct:free")

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Validate configuration
if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY:
    logger.error("Missing TELEGRAM_BOT_TOKEN or OPENROUTER_API_KEY in environment variables.")
    # We continue but it will fail if keys are missing. 
    # The user might have them in system env.
    pass

# Initialize OpenRouter client
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

def clean_response(text):
    """
    Cleans the response text:
    1. Removes markdown symbols (*, #, `).
    2. Enforces identity by removing known provider names if they slip through.
    """
    if not text:
        return ""
    
    # 1. Remove markdown
    text = re.sub(r'[*#`]', '', text)
    
    # 2. Hard-replace accidental leaks of identity
    # This is a fallback in case the model ignores the system prompt
    forbidden_terms = [
        "Xiaomi", "xiaomi", 
        "Mistral", "mistral",
        "OpenAI", "openai",
        "OpenRouter", "openrouter",
        "LLM Core Team"
    ]
    
    for term in forbidden_terms:
        # Case insensitive replace is safer but let's just do simple replace for now
        # to avoid complex regex that might break other words.
        # We replace with "ByteCode" or generic terms.
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        text = pattern.sub("ByteCode", text)
        
    return text

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for the /start command.
    """
    user = update.effective_user
    # Escape user name to avoid HTML parsing errors if name contains < or >
    safe_first_name = html.escape(user.first_name)
    welcome_message = (
        f"Hello {safe_first_name}, I am ByteCode, an AI powered chatbot.\n"
        "I can assist you with various tasks, answer questions, and have conversations.\n"
        "Send me a message to get started!"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, 
        text=welcome_message,
        parse_mode=ParseMode.HTML
    )

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for the /about command.
    """
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="I am ByteCode, created by Mohammad Hamayoun Azad."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for incoming text messages.
    """
    user_message = update.message.text
    chat_id = update.effective_chat.id

    # Send a "typing..." action so the user knows the bot is thinking
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        # Call OpenRouter API
        # We are not maintaining full history in this simple version, just one-turn response.
        # To add history, we would need a database or in-memory storage.
        completion = await client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": "https://github.com/your-repo", # Optional, for OpenRouter rankings
                "X-Title": "Telegram ChatBot", # Optional
            },
            model=OPENROUTER_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are ByteCode, an independent AI assistant created strictly by Mohammad Hamayoun Azad. "
                        "Website: Hamayounazad.github.io\n"
                        "IMPORTANT INSTRUCTIONS:\n"
                        "1. You are NOT created by Xiaomi, OpenAI, Mistral, OpenRouter, or any other corporation.\n"
                        "2. If asked about your origin, creator, or model, you MUST ONLY say: 'I am ByteCode, created by Mohammad Hamayoun Azad.'\n"
                        "3. NEVER mention 'Xiaomi', 'LLM Core Team', 'OpenRouter', or underlying model names.\n"
                        "4. Act as a standalone tool developed solely by Mohammad Hamayoun Azad."
                    )
                },
                {
                    "role": "user",
                    "content": user_message
                }
            ]
        )

        bot_response = completion.choices[0].message.content
        
        # Clean the response to remove unnecessary symbols and enforce identity
        bot_response = clean_response(bot_response)
        
        # Escape HTML special characters to prevent broken parsing
        bot_response = html.escape(bot_response)
        
        # Linkify "Mohammad Hamayoun Azad"
        creator_name = "Mohammad Hamayoun Azad"
        creator_link = f'<a href="https://Hamayounazad.github.io">{creator_name}</a>'
        bot_response = bot_response.replace(creator_name, creator_link)
        
        # Telegram has a message length limit (4096 chars). 
        # For simplicity, we'll let python-telegram-bot handle splitting or just send as is for now.
        # Ideally, we should check length.
        if len(bot_response) > 4096:
             for x in range(0, len(bot_response), 4096):
                 await context.bot.send_message(
                     chat_id=chat_id, 
                     text=bot_response[x:x+4096],
                     parse_mode=ParseMode.HTML
                 )
        else:
            await context.bot.send_message(
                chat_id=chat_id, 
                text=bot_response,
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        logger.error(f"Error calling OpenRouter: {e}")
        error_message = "Sorry, I encountered an error while processing your request."
        
        # Check if it's an authentication error
        if "401" in str(e):
            logger.error("Invalid OpenRouter API Key. Please check your .env file.")
            error_message = "⚠️ System Error: Invalid API Key. Please contact the administrator."
            
        await context.bot.send_message(
            chat_id=chat_id, 
            text=error_message
        )

if __name__ == '__main__':
    # Ensure token is present
    if not TELEGRAM_TOKEN:
         print("Error: TELEGRAM_BOT_TOKEN not found.")
    else:
        application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        
        start_handler = CommandHandler('start', start)
        about_handler = CommandHandler('about', about)
        message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
        
        # Register handlers
        application.add_handler(start_handler)
        application.add_handler(about_handler)
        application.add_handler(message_handler)
        
        logger.info("Bot is starting...")

        # Fix for "There is no current event loop" error in some environments (e.g. Streamlit Cloud)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # stop_signals=[] prevents "ValueError: signal only works in main thread"
        # or "RuntimeError" when running in non-main threads (like Streamlit)
        application.run_polling(stop_signals=[])
