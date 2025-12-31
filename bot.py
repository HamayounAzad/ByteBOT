import os
import re
import html
import logging
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, Application
from telegram.request import HTTPXRequest
from openai import AsyncOpenAI
import database  # Import our new database module

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")  # Channel ID for logs

# Clean keys if they exist
if TELEGRAM_TOKEN:
    TELEGRAM_TOKEN = TELEGRAM_TOKEN.strip()
if OPENROUTER_API_KEY:
    OPENROUTER_API_KEY = OPENROUTER_API_KEY.strip()

# Try to convert LOG_CHANNEL_ID to int (safer for negative IDs like -100...)
if LOG_CHANNEL_ID:
    try:
        LOG_CHANNEL_ID = int(LOG_CHANNEL_ID)
    except ValueError:
        pass # Keep as string if it's a username (e.g. @mychannel)

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
    timeout=60.0, # 60 seconds timeout
    max_retries=3, # Retry up to 3 times on connection error
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

async def log_to_channel(context: ContextTypes.DEFAULT_TYPE, message: str):
    """
    Sends a log message to the configured channel.
    """
    if LOG_CHANNEL_ID:
        try:
            await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=message, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Failed to log to channel {LOG_CHANNEL_ID}: {e}")

async def post_init(application: Application):
    """
    Called after the bot application is initialized.
    Sends a startup message to the log channel.
    """
    if LOG_CHANNEL_ID:
        try:
            await application.bot.send_message(
                chat_id=LOG_CHANNEL_ID, 
                text="<b>🚀 ByteCode Bot Started!</b>\nI am now online and ready to serve users.",
                parse_mode=ParseMode.HTML
            )
            logger.info(f"Startup message sent to channel {LOG_CHANNEL_ID}")
        except Exception as e:
            logger.error(f"Failed to send startup message to channel {LOG_CHANNEL_ID}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for the /start command.
    """
    user = update.effective_user
    
    # Track user in database
    is_new = database.update_user(
        user.id, 
        user.username, 
        user.first_name, 
        user.language_code
    )
    
    # If new user, notify admin channel
    if is_new:
        log_msg = (
            f"<b>🆕 New User Joined!</b>\n"
            f"<b>Name:</b> {html.escape(user.first_name)}\n"
            f"<b>Username:</b> @{user.username if user.username else 'N/A'}\n"
            f"<b>ID:</b> {user.id}\n"
            f"<b>Lang:</b> {user.language_code}"
        )
        await log_to_channel(context, log_msg)

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

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for the /stats command. Sends stats to the chat and the log channel.
    """
    stats_data = database.get_statistics()
    
    top_users_text = ""
    for u in stats_data['top_users']:
        username = f"@{u[0]}" if u[0] else u[1]  # Username or First Name
        top_users_text += f"• {html.escape(str(username))}: {u[2]} msgs\n"
    
    stats_msg = (
        f"<b>📊 ByteCode Statistics</b>\n\n"
        f"<b>👥 Total Users:</b> {stats_data['total_users']}\n"
        f"<b>🔥 Active (24h):</b> {stats_data['active_24h']}\n\n"
        f"<b>🏆 Top Active Users:</b>\n{top_users_text}"
    )
    
    # Send to the user who requested it
    await context.bot.send_message(chat_id=update.effective_chat.id, text=stats_msg, parse_mode=ParseMode.HTML)
    
    # Also log to channel that stats were requested
    await log_to_channel(context, f"📈 Stats requested by {update.effective_user.first_name}\n\n{stats_msg}")

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
    user = update.effective_user
    
    # Track user activity (update last_seen and increment message count)
    database.update_user(
        user.id, 
        user.username, 
        user.first_name, 
        user.language_code
    )

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
        # Initialize Database
        database.init_db()
        
        # Optimization:
        # 1. concurrent_updates(True): Processes messages in parallel (AsyncIO) instead of one-by-one.
        # 2. HTTPXRequest: Increases connection pool size to handle more simultaneous requests to Telegram.
        t_request = HTTPXRequest(
            connection_pool_size=20,  # Handle up to 20 concurrent connections to Telegram
            read_timeout=20.0,
            write_timeout=20.0,
            connect_timeout=20.0
        )
        
        application = ApplicationBuilder().token(TELEGRAM_TOKEN).request(t_request).concurrent_updates(True).post_init(post_init).build()
        
        start_handler = CommandHandler('start', start)
        about_handler = CommandHandler('about', about)
        stats_handler = CommandHandler('stats', stats)
        message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
        
        # Register handlers
        application.add_handler(start_handler)
        application.add_handler(about_handler)
        application.add_handler(stats_handler)
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
        # drop_pending_updates=True can help resolve conflicts if the previous session didn't close cleanly
        logger.info("Dropping pending updates to resolve conflicts...")
        # Note: drop_pending_updates is not a direct argument for run_polling in v20+
        # We handle conflict resilience by just starting polling.
        # If a conflict error occurs, the library will retry or we need to ensure old instances are dead.
        
        # However, to be robust against "Conflict" errors, we can't do much from code if another instance IS actually running.
        # But if it's a "zombie" connection, sometimes just restarting helps.
        
        application.run_polling(stop_signals=[], drop_pending_updates=True)
