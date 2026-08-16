import logging
import random
import string
import time
import re
import json
import os
import asyncio
import pytz
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.request import HTTPXRequest

# ============ CONFIGURATION ============
TOKEN = "8875994072:AAFEw8QGWPrfIOw6SGoVo6H-bk3ioLI9uEk"
OWNER_ID = 8785590284
ESCROW_USER = "@escrow2929"

ADMINS = [OWNER_ID]

# ============ TIME CONFIGURATION (INDIAN TIME - IST) ============
# Bot ON: 8 AM to 10 PM IST
# Bot OFF (Maintenance): 10 PM to 8 AM IST
MAINTENANCE_START_HOUR = 22  # 10 PM
MAINTENANCE_END_HOUR = 8     # 8 AM

# ============ LIMITS ============
MAX_EMAIL_UPLOAD = 1000
MAX_QR_UPLOAD = 100
MAX_REVIEW_UPLOAD = 500

# ============ TASK TIMEOUTS ============
TASK_TIMEOUT_MINUTES = 15
QR_EXPIRE_MINUTES = 5
REVIEW_EXPIRE_MINUTES = 10
COOLDOWN_MINUTES = 2

# ============ IST TIMEZONE ============
IST = pytz.timezone('Asia/Kolkata')

def get_ist_now():
    """Get current time in IST"""
    return datetime.now(IST)

def is_maintenance_mode():
    """Check if current IST time is in maintenance window (10 PM - 8 AM)"""
    now = get_ist_now()
    current_hour = now.hour
    
    # Maintenance: 10 PM (22) to 8 AM (8)
    if current_hour >= MAINTENANCE_START_HOUR or current_hour < MAINTENANCE_END_HOUR:
        return True
    return False

def get_next_start_time():
    """Get next bot start time in IST"""
    now = get_ist_now()
    current_hour = now.hour
    
    if current_hour >= MAINTENANCE_START_HOUR:  # After 10 PM
        # Next start is tomorrow 8 AM
        next_start = now.replace(hour=MAINTENANCE_END_HOUR, minute=0, second=0, microsecond=0) + timedelta(days=1)
    elif current_hour < MAINTENANCE_END_HOUR:  # Before 8 AM
        # Next start is today 8 AM
        next_start = now.replace(hour=MAINTENANCE_END_HOUR, minute=0, second=0, microsecond=0)
    else:
        # Bot is currently running
        next_start = None
    
    return next_start

# ============ DATABASE ============
DATA_FILE = "bot_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                default_keys = {
                    "users": {}, "pending": {}, "email_stock": [], "used_emails": [],
                    "withdraw_requests": [], "cooldowns": {}, "admins": [OWNER_ID],
                    "upload_counter": 0, "upload_history": [],
                    "qr_stock": [], "qr_used": [], "qr_upload_counter": 0, "qr_history": [],
                    "review_stock": [], "review_used": [], "review_upload_counter": 0, "review_history": [],
                    "pending_qr": {}, "pending_review": {}
                }
                for key, default_val in default_keys.items():
                    if key not in data:
                        data[key] = default_val
                return data
        except Exception as e:
            logging.error(f"Error loading data: {e}")
            return default_data()
    return default_data()

def default_data():
    return {
        "users": {}, "pending": {}, "email_stock": [], "used_emails": [],
        "withdraw_requests": [], "cooldowns": {}, "admins": [OWNER_ID],
        "upload_counter": 0, "upload_history": [],
        "qr_stock": [], "qr_used": [], "qr_upload_counter": 0, "qr_history": [],
        "review_stock": [], "review_used": [], "review_upload_counter": 0, "review_history": [],
        "pending_qr": {}, "pending_review": {}
    }

def save_data(data):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, default=str, ensure_ascii=False)
        return True
    except Exception as e:
        logging.error(f"Error saving data: {e}")
        return False

data = load_data()
ADMINS = data.get("admins", [OWNER_ID])

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def is_admin(user_id):
    return user_id in ADMINS or user_id == OWNER_ID

# ============ SELF PING ============
PING_COUNT = 0

async def self_ping(context: ContextTypes.DEFAULT_TYPE):
    global PING_COUNT, data
    PING_COUNT += 1
    data = load_data()
    now = get_ist_now()
    
    try:
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"🔄 **BOT ALIVE** #{PING_COUNT}\n\n"
                 f"⏰ IST Time: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
                 f"📦 Email Stock: {len(data['email_stock'])}\n"
                 f"📱 QR Stock: {len(data['qr_stock'])}\n"
                 f"📝 Review Stock: {len(data['review_stock'])}\n"
                 f"👥 Users: {len(data['users'])}\n"
                 f"⏳ Pending: {len(data['pending'])}\n"
                 f"🔄 Status: {'🟢 ONLINE' if not is_maintenance_mode() else '🔴 MAINTENANCE'}"
        )
    except Exception as e:
        logger.error(f"Self ping failed: {e}")

# ============ CHECK TIMEOUT ============
def check_pending_timeout():
    global data
    now = get_ist_now()
    to_remove = []
    for user_id, pending in data["pending"].items():
        if "timestamp" in pending:
            try:
                start_time = datetime.fromisoformat(pending["timestamp"])
                # Convert to IST if naive
                if start_time.tzinfo is None:
                    start_time = IST.localize(start_time)
                if (now - start_time).total_seconds() > TASK_TIMEOUT_MINUTES * 60:
                    to_remove.append(user_id)
            except:
                continue
    for user_id in to_remove:
        pending = data["pending"][user_id]
        name = pending.get("name", pending.get("username", "User"))
        
        if pending.get("type") == "email":
            email_data = f"{name}|{pending['gmail']}|{pending['password']}|{pending['recovery']}"
            data["email_stock"].append(email_data)
        elif pending.get("type") == "qr":
            data["qr_stock"].append(pending.get("qr_data"))
        elif pending.get("type") == "review":
            data["review_stock"].append(pending.get("review_data"))
        
        data["cooldowns"][user_id] = (now + timedelta(minutes=COOLDOWN_MINUTES)).isoformat()
        del data["pending"][user_id]
        save_data(data)

async def check_timeout_job(context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    if data["pending"]:
        check_pending_timeout()

# ============ CHECK QR EXPIRE ============
def check_qr_expire():
    global data
    now = get_ist_now()
    to_remove = []
    for user_id, pending in data.get("pending_qr", {}).items():
        if "timestamp" in pending:
            try:
                start_time = datetime.fromisoformat(pending["timestamp"])
                if start_time.tzinfo is None:
                    start_time = IST.localize(start_time)
                if (now - start_time).total_seconds() > QR_EXPIRE_MINUTES * 60:
                    to_remove.append(user_id)
            except:
                continue
    for user_id in to_remove:
        pending = data["pending_qr"][user_id]
        data["qr_stock"].append(pending.get("qr_data"))
        del data["pending_qr"][user_id]
        save_data(data)

async def check_qr_expire_job(context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    if data.get("pending_qr"):
        check_qr_expire()

# ============ CHECK REVIEW EXPIRE ============
def check_review_expire():
    global data
    now = get_ist_now()
    to_remove = []
    for user_id, pending in data.get("pending_review", {}).items():
        if "timestamp" in pending:
            try:
                start_time = datetime.fromisoformat(pending["timestamp"])
                if start_time.tzinfo is None:
                    start_time = IST.localize(start_time)
                if (now - start_time).total_seconds() > REVIEW_EXPIRE_MINUTES * 60:
                    to_remove.append(user_id)
            except:
                continue
    for user_id in to_remove:
        pending = data["pending_review"][user_id]
        data["review_stock"].append(pending.get("review_data"))
        del data["pending_review"][user_id]
        save_data(data)

async def check_review_expire_job(context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    if data.get("pending_review"):
        check_review_expire()

# ============ NEW ADMIN ============
async def newadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data, ADMINS
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only Owner can add admins!", parse_mode='Markdown')
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: `/newadmin [user_id]`", parse_mode='Markdown')
        return
    try:
        new_admin_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid ID!", parse_mode='Markdown')
        return
    if new_admin_id in ADMINS:
        await update.message.reply_text(f"⚠️ Already admin!", parse_mode='Markdown')
        return
    ADMINS.append(new_admin_id)
    data["admins"] = ADMINS
    save_data(data)
    await update.message.reply_text(f"✅ New admin added: `{new_admin_id}`", parse_mode='Markdown')
    try:
        await context.bot.send_message(new_admin_id, "👑 You are now an Admin!", parse_mode='Markdown')
    except:
        pass

# ============ UPLOAD EMAIL ============
async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if not context.args:
        await update.message.reply_text(
            "📤 **UPLOAD EMAIL**\n\n"
            "/upload Name|Email|Pass|Recovery\n\n"
            f"📦 Stock: {len(data['email_stock'])}/{MAX_EMAIL_UPLOAD}",
            parse_mode='Markdown'
        )
        return
    
    if len(data["email_stock"]) >= MAX_EMAIL_UPLOAD:
        await update.message.reply_text(f"❌ Max limit {MAX_EMAIL_UPLOAD} reached!", parse_mode='Markdown')
        return
    
    emails = context.args[0].split(",")
    count = 0
    for email in emails:
        email = email.strip()
        if "|" in email and len(data["email_stock"]) < MAX_EMAIL_UPLOAD:
            data["email_stock"].append(email)
            data["upload_counter"] = data.get("upload_counter", 0) + 1
            data["upload_history"].append({
                "id": data["upload_counter"], "raw": email,
                "status": "pending", "timestamp": get_ist_now().isoformat()
            })
            count += 1
    save_data(data)
    await update.message.reply_text(
        f"✅ **EMAIL UPLOADED!**\n\n📤 Added: {count}\n📦 Total: {len(data['email_stock'])}/{MAX_EMAIL_UPLOAD}",
        parse_mode='Markdown'
    )

# ============ UPLOAD QR ============
async def uploadqr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if len(data["qr_stock"]) >= MAX_QR_UPLOAD:
        await update.message.reply_text(f"❌ Max {MAX_QR_UPLOAD} QR limit reached!", parse_mode='Markdown')
        return
    if not context.args:
        await update.message.reply_text(
            "📤 **UPLOAD QR**\n\n"
            "/uploadqr [qr_name_or_id]\n\n"
            f"📱 Stock: {len(data['qr_stock'])}/{MAX_QR_UPLOAD}",
            parse_mode='Markdown'
        )
        return
    qr_data = " ".join(context.args)
    data["qr_stock"].append(qr_data)
    data["qr_upload_counter"] = data.get("qr_upload_counter", 0) + 1
    data["qr_history"].append({
        "id": data["qr_upload_counter"], "data": qr_data,
        "status": "pending", "timestamp": get_ist_now().isoformat()
    })
    save_data(data)
    await update.message.reply_text(
        f"✅ **QR UPLOADED!**\n\n📱 Added: {qr_data}\n📦 Total: {len(data['qr_stock'])}/{MAX_QR_UPLOAD}",
        parse_mode='Markdown'
    )

# ============ UPLOAD REVIEW ============
async def uploadr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if not context.args:
        await update.message.reply_text(
            "📝 **UPLOAD REVIEW**\n\n"
            "/uploadr [review_message]\n\n"
            f"📝 Stock: {len(data['review_stock'])}",
            parse_mode='Markdown'
        )
        return
    review_data = " ".join(context.args)
    data["review_stock"].append(review_data)
    data["review_upload_counter"] = data.get("review_upload_counter", 0) + 1
    data["review_history"].append({
        "id": data["review_upload_counter"], "data": review_data,
        "status": "pending", "timestamp": get_ist_now().isoformat()
    })
    save_data(data)
    await update.message.reply_text(
        f"✅ **REVIEW UPLOADED!**\n\n📝 Added: {review_data[:50]}...\n📦 Total: {len(data['review_stock'])}",
        parse_mode='Markdown'
    )

# ============ EMAIL COMMAND ============
async def email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if is_maintenance_mode():
        next_start = get_next_start_time()
        if next_start:
            time_str = next_start.strftime('%I:%M %p')
            await update.message.reply_text(
                f"🛠️ **MAINTENANCE MODE**\n\n"
                f"Bot is currently in maintenance.\n"
                f"⏰ **Timing:** 10 PM - 8 AM IST\n"
                f"🔄 Bot will be back at **{time_str}**\n\n"
                f"Please try again later!",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "🛠️ **MAINTENANCE MODE**\n\n"
                "Bot is currently in maintenance.\n"
                "⏰ **Timing:** 10 PM - 8 AM IST\n\n"
                "Please try again after 8 AM!",
                parse_mode='Markdown'
            )
        return
    
    if user_id in data.get("cooldowns", {}):
        cooldown_end = datetime.fromisoformat(data["cooldowns"][user_id])
        if cooldown_end.tzinfo is None:
            cooldown_end = IST.localize(cooldown_end)
        if get_ist_now() < cooldown_end:
            remaining = (cooldown_end - get_ist_now()).seconds // 60
            await update.message.reply_text(f"⏳ Cooldown: {remaining + 1} min", parse_mode='Markdown')
            return
        else:
            del data["cooldowns"][user_id]
            save_data(data)
    
    if user_id in data["users"] and data["users"][user_id].get("completed", False):
        await update.message.reply_text("❌ Already completed!", parse_mode='Markdown')
        return
    
    if not data["email_stock"]:
        await update.message.reply_text("❌ No stock!", parse_mode='Markdown')
        return
    
    if user_id in data["pending"]:
        await update.message.reply_text("⏳ Pending! Use /cancel", parse_mode='Markdown')
        return
    
    email_data = data["email_stock"].pop(0)
    parts = email_data.split("|")
    if len(parts) == 4:
        name, gmail, password, recovery = parts
    else:
        gmail, password, recovery = parts[0], parts[1], parts[2]
        name = username
    
    data["pending"][user_id] = {
        "type": "email", "gmail": gmail, "password": password,
        "recovery": recovery, "name": name, "username": username,
        "timestamp": get_ist_now().isoformat()
    }
    save_data(data)
    
    for admin in ADMINS:
        try:
            await context.bot.send_message(
                admin,
                f"📧 **EMAIL ASSIGNED!**\n👤 @{username} (ID: `{user_id}`)\n📧 `{gmail}`\n📦 Left: {len(data['email_stock'])}"
            )
        except:
            pass
    
    await update.message.reply_text(
        f"📧 **EMAIL ASSIGNED!**\n\n👤 Name: `{name}`\n📧 Email: `{gmail}`\n🔑 Pass: `{password}`\n📧 Recovery: `{recovery}`\n\n"
        "📌 Login → /skip2fa → Upload QR → OTP → Screenshot\n\n"
        f"⏰ {TASK_TIMEOUT_MINUTES} min timeout!\n/cancel - Cancel",
        parse_mode='Markdown'
    )

# ============ QR COMMAND ============
async def qr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if is_maintenance_mode():
        next_start = get_next_start_time()
        if next_start:
            time_str = next_start.strftime('%I:%M %p')
            await update.message.reply_text(
                f"🛠️ **MAINTENANCE MODE**\n\n"
                f"Bot is currently in maintenance.\n"
                f"⏰ **Timing:** 10 PM - 8 AM IST\n"
                f"🔄 Bot will be back at **{time_str}**",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "🛠️ **MAINTENANCE MODE**\n\n"
                "Bot is currently in maintenance.\n"
                "⏰ **Timing:** 10 PM - 8 AM IST\n\n"
                "Please try again after 8 AM!",
                parse_mode='Markdown'
            )
        return
    
    if user_id in data.get("pending_qr", {}):
        await update.message.reply_text("⏳ You already have a QR! Complete or wait.", parse_mode='Markdown')
        return
    
    if not data["qr_stock"]:
        await update.message.reply_text("❌ No QR available!", parse_mode='Markdown')
        return
    
    qr_data = data["qr_stock"].pop(0)
    data["pending_qr"][user_id] = {
        "qr_data": qr_data, "username": username,
        "timestamp": get_ist_now().isoformat()
    }
    save_data(data)
    
    await update.message.reply_text(
        f"📱 **YOUR QR CODE**\n\n"
        f"`{qr_data}`\n\n"
        f"💰 **1 QR = ₹15**\n\n"
        f"📸 Send screenshot proof (QR scanned/used)\n"
        f"⏰ Expires in {QR_EXPIRE_MINUTES} minutes!",
        parse_mode='Markdown'
    )

# ============ REVIVE/REVIEW COMMAND ============
async def revive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if is_maintenance_mode():
        next_start = get_next_start_time()
        if next_start:
            time_str = next_start.strftime('%I:%M %p')
            await update.message.reply_text(
                f"🛠️ **MAINTENANCE MODE**\n\n"
                f"Bot is currently in maintenance.\n"
                f"⏰ **Timing:** 10 PM - 8 AM IST\n"
                f"🔄 Bot will be back at **{time_str}**",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "🛠️ **MAINTENANCE MODE**\n\n"
                "Bot is currently in maintenance.\n"
                "⏰ **Timing:** 10 PM - 8 AM IST\n\n"
                "Please try again after 8 AM!",
                parse_mode='Markdown'
            )
        return
    
    if user_id in data.get("pending_review", {}):
        await update.message.reply_text("⏳ You already have a review! Complete or wait.", parse_mode='Markdown')
        return
    
    if not data["review_stock"]:
        await update.message.reply_text("❌ No review available!", parse_mode='Markdown')
        return
    
    review_data = data["review_stock"].pop(0)
    data["pending_review"][user_id] = {
        "review_data": review_data, "username": username,
        "timestamp": get_ist_now().isoformat()
    }
    save_data(data)
    
    await update.message.reply_text(
        f"📝 **REVIEW WORK**\n\n"
        f"`{review_data}`\n\n"
        f"📸 Send screenshot proof of review completion\n"
        f"⏰ Expires in {REVIEW_EXPIRE_MINUTES} minutes!",
        parse_mode='Markdown'
    )

# ============ GET REVIEW ============
async def getr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await revive_command(update, context)

# ============ SKIP 2FA ============
async def skip2fa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    if user_id not in data["pending"]:
        await update.message.reply_text("❌ No pending email!", parse_mode='Markdown')
        return
    data["pending"][user_id]["skip_2fa"] = True
    data["pending"][user_id]["step"] = "waiting_screenshot"
    save_data(data)
    await update.message.reply_text("✅ 2FA Skipped!\n📸 Send screenshot proof.", parse_mode='Markdown')

# ============ HANDLE OTP INPUT ============
async def handle_otp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    
    if not text.isdigit() or len(text) != 6:
        await update.message.reply_text("❌ Enter 6-digit OTP!", parse_mode='Markdown')
        return
    
    if user_id not in data["pending"]:
        await update.message.reply_text("❌ No pending email work!", parse_mode='Markdown')
        return
    
    stored_otp = data["pending"][user_id].get("otp")
    if stored_otp and int(text) == stored_otp:
        data["pending"][user_id]["otp_verified"] = True
        data["pending"][user_id]["step"] = "waiting_screenshot"
        save_data(data)
        await update.message.reply_text(
            "✅ **OTP Verified!**\n\n"
            "📸 Now send a screenshot of Gmail inbox & settings as proof.",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ Wrong OTP! Try again.", parse_mode='Markdown')

# ============ HANDLE MESSAGE ============
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    text = update.message.text
    
    if not text:
        return
    
    if user_id in data.get("pending", {}):
        pending = data["pending"][user_id]
        if pending.get("step") == "waiting_otp":
            await handle_otp_input(update, context)
            return
        
        if pending.get("type") == "email":
            await update.message.reply_text(
                f"📧 **EMAIL WORK**\n\n"
                f"📧 Email: `{pending.get('gmail', '')}`\n"
                f"🔑 Pass: `{pending.get('password', '')}`\n\n"
                "📌 **Next Steps:**\n"
                "1. Login to Gmail\n"
                "2. Enable 2FA or use /skip2fa\n"
                "3. Upload QR code (photo)\n"
                "4. Enter OTP (6 digits)\n"
                "5. Send screenshot proof\n\n"
                "⚡ Commands:\n"
                "/skip2fa - Skip 2FA\n"
                "/cancel - Cancel work",
                parse_mode='Markdown'
            )
        return
    
    if user_id in data.get("pending_qr", {}):
        await update.message.reply_text(
            "📱 **QR PENDING**\n\n"
            "Please send a screenshot of the QR being used/scanned.\n"
            "Send a PHOTO as proof.",
            parse_mode='Markdown'
        )
        return
    
    if user_id in data.get("pending_review", {}):
        await update.message.reply_text(
            "📝 **REVIEW PENDING**\n\n"
            "Please send a screenshot of the review completion.\n"
            "Send a PHOTO as proof.",
            parse_mode='Markdown'
        )
        return
    
    await update.message.reply_text(
        "❌ **Unknown command**\n\n"
        "📌 Available commands:\n"
        "/email - Get email work\n"
        "/qr - Get QR work\n"
        "/revive - Get review work\n"
        "/status - Check status\n"
        "/balance - Check balance\n"
        "/help - Show all commands",
        parse_mode='Markdown'
    )

# ============ HANDLE PHOTO ============
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    # Check for QR pending
    if user_id in data.get("pending_qr", {}):
        pending = data["pending_qr"][user_id]
        photo = update.message.photo[-1]
        file_id = photo.file_id
        
        data["qr_used"].append(pending["qr_data"])
        
        if user_id not in data["users"]:
            data["users"][user_id] = {"balance": 0, "username": username, "completed": False}
        data["users"][user_id]["balance"] = data["users"][user_id].get("balance", 0) + 15
        data["users"][user_id]["qr_done"] = True
        
        for qr in data.get("qr_history", []):
            if qr["data"] == pending["qr_data"] and qr["status"] == "pending":
                qr["status"] = "approved"
                qr["approved_by"] = "auto"
                break
        
        del data["pending_qr"][user_id]
        save_data(data)
        
        for admin in ADMINS:
            try:
                await context.bot.send_message(
                    admin,
                    f"📱 **QR VERIFIED!**\n👤 @{username}\n💰 ₹15 added\n📸 Screenshot received"
                )
            except:
                pass
        
        await update.message.reply_text(
            f"✅ **QR VERIFIED!**\n\n💰 ₹15 added to your balance!\n👑 Admin: {ESCROW_USER}",
            parse_mode='Markdown'
        )
        return
    
    # Check for Review pending
    if user_id in data.get("pending_review", {}):
        pending = data["pending_review"][user_id]
        photo = update.message.photo[-1]
        file_id = photo.file_id
        
        data["review_used"].append(pending["review_data"])
        
        if user_id not in data["users"]:
            data["users"][user_id] = {"balance": 0, "username": username, "completed": False}
        data["users"][user_id]["balance"] = data["users"][user_id].get("balance", 0) + 15
        data["users"][user_id]["review_done"] = True
        
        for rev in data.get("review_history", []):
            if rev["data"] == pending["review_data"] and rev["status"] == "pending":
                rev["status"] = "approved"
                rev["approved_by"] = "auto"
                break
        
        del data["pending_review"][user_id]
        save_data(data)
        
        for admin in ADMINS:
            try:
                await context.bot.send_message(
                    admin,
                    f"📝 **REVIEW VERIFIED!**\n👤 @{username}\n💰 ₹15 added\n📸 Screenshot received"
                )
            except:
                pass
        
        await update.message.reply_text(
            f"✅ **REVIEW VERIFIED!**\n\n💰 ₹15 added to your balance!\n👑 Admin: {ESCROW_USER}",
            parse_mode='Markdown'
        )
        return
    
    # Check for Email pending
    if user_id in data.get("pending", {}):
        pending = data["pending"][user_id]
        if pending.get("step") == "waiting_screenshot" or pending.get("step") == "waiting_otp":
            photo = update.message.photo[-1]
            file_id = photo.file_id
            
            gmail = pending.get("gmail")
            password = pending.get("password")
            recovery = pending.get("recovery")
            
            if user_id not in data["users"]:
                data["users"][user_id] = {"balance": 0, "username": username, "completed": False}
            data["users"][user_id]["balance"] = data["users"][user_id].get("balance", 0) + 15
            data["users"][user_id]["email_done"] = True
            data["users"][user_id]["gmail"] = gmail
            data["users"][user_id]["password"] = password
            data["users"][user_id]["recovery"] = recovery
            data["users"][user_id]["completed"] = True
            
            data["used_emails"].append(gmail)
            
            for upload in data.get("upload_history", []):
                if upload["raw"].find(gmail) != -1 and upload["status"] == "pending":
                    upload["status"] = "approved"
                    break
            
            del data["pending"][user_id]
            save_data(data)
            
            for admin in ADMINS:
                try:
                    await context.bot.send_message(
                        admin,
                        f"📧 **EMAIL VERIFIED!**\n👤 @{username}\n📧 `{gmail}`\n💰 ₹15 added"
                    )
                except:
                    pass
            
            await update.message.reply_text(
                f"🎉 **EMAIL VERIFIED!**\n\n✅ Gmail: `{gmail}`\n💰 ₹15 added!\n👑 Admin: {ESCROW_USER}",
                parse_mode='Markdown'
            )
            return
    
    await update.message.reply_text("❌ No pending work found!", parse_mode='Markdown')

# ============ CANCEL COMMAND ============
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    
    if user_id in data["pending"]:
        pending = data["pending"][user_id]
        if pending.get("type") == "email":
            name = pending.get("name", "User")
            email_data = f"{name}|{pending['gmail']}|{pending['password']}|{pending['recovery']}"
            data["email_stock"].append(email_data)
        elif pending.get("type") == "qr":
            data["qr_stock"].append(pending.get("qr_data"))
        elif pending.get("type") == "review":
            data["review_stock"].append(pending.get("review_data"))
        del data["pending"][user_id]
        save_data(data)
        await update.message.reply_text("❌ Cancelled! Work returned.", parse_mode='Markdown')
    elif user_id in data.get("pending_qr", {}):
        pending = data["pending_qr"][user_id]
        data["qr_stock"].append(pending["qr_data"])
        del data["pending_qr"][user_id]
        save_data(data)
        await update.message.reply_text("❌ QR cancelled!", parse_mode='Markdown')
    elif user_id in data.get("pending_review", {}):
        pending = data["pending_review"][user_id]
        data["review_stock"].append(pending["review_data"])
        del data["pending_review"][user_id]
        save_data(data)
        await update.message.reply_text("❌ Review cancelled!", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ No active session!", parse_mode='Markdown')

# ============ CANCEL UPLOAD (ADMIN) ============
async def cancel_upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: `/cancel #id`", parse_mode='Markdown')
        return
    
    upload_id = int(context.args[0].replace("#", ""))
    
    # Check email history
    for upload in data.get("upload_history", []):
        if upload["id"] == upload_id and upload["status"] == "pending":
            data["email_stock"].remove(upload["raw"])
            upload["status"] = "cancelled"
            save_data(data)
            await update.message.reply_text(f"✅ Upload `#{upload_id}` cancelled!", parse_mode='Markdown')
            return
    
    # Check QR history
    for qr in data.get("qr_history", []):
        if qr["id"] == upload_id and qr["status"] == "pending":
            data["qr_stock"].remove(qr["data"])
            qr["status"] = "cancelled"
            save_data(data)
            await update.message.reply_text(f"✅ QR `#{upload_id}` cancelled!", parse_mode='Markdown')
            return
    
    await update.message.reply_text(f"❌ Upload `#{upload_id}` not found!", parse_mode='Markdown')

# ============ RESET ALL ============
async def reset_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only Owner!", parse_mode='Markdown')
        return
    if len(context.args) < 1 or context.args[0].lower() != "confirm":
        await update.message.reply_text("⚠️ Type: `/reset all confirm`", parse_mode='Markdown')
        return
    
    data["email_stock"] = []
    data["qr_stock"] = []
    data["review_stock"] = []
    data["upload_history"] = []
    data["qr_history"] = []
    data["review_history"] = []
    data["upload_counter"] = 0
    data["qr_upload_counter"] = 0
    data["review_upload_counter"] = 0
    save_data(data)
    await update.message.reply_text("✅ **All reset!**", parse_mode='Markdown')

# ============ APPROVE COMMAND ============
async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/approve [user_id] [amount]`\n\n"
            "Example: `/approve 123456789 15`",
            parse_mode='Markdown'
        )
        return
    
    target_id = context.args[0]
    amount = int(context.args[1])
    
    data = load_data()
    if target_id not in data["users"]:
        await update.message.reply_text(f"❌ User not found!", parse_mode='Markdown')
        return
    
    data["users"][target_id]["balance"] -= amount
    
    for req in data.get("withdraw_requests", []):
        if req["user_id"] == target_id and req["amount"] == amount and req["status"] == "pending":
            req["status"] = "approved"
            req["approved_at"] = get_ist_now().isoformat()
            break
    save_data(data)
    
    await context.bot.send_message(
        int(target_id),
        f"💰 **PAYMENT APPROVED!**\n\n✅ ₹{amount} approved\n📌 We are paying in 4 days as fastest as possible.\n\n👑 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )
    await update.message.reply_text(f"✅ Approved ₹{amount} for `{target_id}`", parse_mode='Markdown')

# ============ STOCK COMMAND ============
async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    data = load_data()
    await update.message.reply_text(
        f"📊 **STOCK STATUS**\n\n"
        f"📦 Email: {len(data['email_stock'])}/{MAX_EMAIL_UPLOAD}\n"
        f"📱 QR: {len(data['qr_stock'])}/{MAX_QR_UPLOAD}\n"
        f"📝 Review: {len(data['review_stock'])}\n"
        f"👥 Users: {len(data['users'])}\n"
        f"⏳ Pending: {len(data['pending'])}",
        parse_mode='Markdown'
    )

# ============ BALANCE COMMAND ============
async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    if user_id not in data["users"]:
        await update.message.reply_text("❌ No account!", parse_mode='Markdown')
        return
    user = data["users"][user_id]
    await update.message.reply_text(
        f"💰 **BALANCE**\n\n"
        f"💵 Balance: ₹{user.get('balance', 0)}\n"
        f"📧 Email: {'✅' if user.get('email_done') else '❌'}\n"
        f"📱 QR: {'✅' if user.get('qr_done') else '❌'}\n"
        f"📝 Review: {'✅' if user.get('review_done') else '❌'}\n\n"
        f"📌 Withdraw: /withdraw [amount]",
        parse_mode='Markdown'
    )

# ============ WITHDRAW COMMAND ============
async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    if user_id not in data["users"]:
        await update.message.reply_text("❌ No account!", parse_mode='Markdown')
        return
    user = data["users"][user_id]
    balance = user.get("balance", 0)
    upi = user.get("upi", "")
    if not upi:
        await update.message.reply_text("❌ Set UPI: /setupi [UPI]", parse_mode='Markdown')
        return
    if balance <= 0:
        await update.message.reply_text(f"❌ Balance: ₹{balance}", parse_mode='Markdown')
        return
    if len(context.args) < 1:
        await update.message.reply_text(f"💰 Balance: ₹{balance}\nUsage: /withdraw [amount]", parse_mode='Markdown')
        return
    try:
        amount = int(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid amount!", parse_mode='Markdown')
        return
    if amount > balance:
        await update.message.reply_text(f"❌ Balance: ₹{balance}", parse_mode='Markdown')
        return
    if amount < 15:
        await update.message.reply_text("❌ Minimum ₹15!", parse_mode='Markdown')
        return
    
    withdraw_data = {"user_id": user_id, "username": update.effective_user.first_name, "upi": upi, "amount": amount, "timestamp": get_ist_now().isoformat(), "status": "pending"}
    if "withdraw_requests" not in data:
        data["withdraw_requests"] = []
    data["withdraw_requests"].append(withdraw_data)
    save_data(data)
    
    for admin in ADMINS:
        try:
            await context.bot.send_message(
                admin,
                f"💰 **WITHDRAWAL!**\n👤 @{update.effective_user.username}\n📌 `{upi}`\n💰 ₹{amount}\n/approve {user_id} {amount}"
            )
        except:
            pass
    
    await update.message.reply_text(f"✅ Request Sent!\n💰 ₹{amount}\n📌 Pending", parse_mode='Markdown')

# ============ SETUPI COMMAND ============
async def setupi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    if len(context.args) < 1:
        await update.message.reply_text("❌ Usage: /setupi [UPI_ID]", parse_mode='Markdown')
        return
    upi = context.args[0]
    if user_id not in data["users"]:
        data["users"][user_id] = {"balance": 0, "username": update.effective_user.first_name, "completed": False}
    data["users"][user_id]["upi"] = upi
    save_data(data)
    await update.message.reply_text(f"✅ UPI Set: `{upi}`", parse_mode='Markdown')

# ============ STATUS COMMAND ============
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    
    if user_id in data["pending"]:
        pending = data["pending"][user_id]
        start_time = datetime.fromisoformat(pending["timestamp"])
        if start_time.tzinfo is None:
            start_time = IST.localize(start_time)
        elapsed = (get_ist_now() - start_time).seconds // 60
        remaining = max(0, TASK_TIMEOUT_MINUTES - elapsed)
        await update.message.reply_text(
            f"⏳ **PENDING**\n📧 `{pending.get('gmail', '')}`\n⏰ Time Left: {remaining} min",
            parse_mode='Markdown'
        )
        return
    
    if user_id in data.get("pending_qr", {}):
        pending = data["pending_qr"][user_id]
        start_time = datetime.fromisoformat(pending["timestamp"])
        if start_time.tzinfo is None:
            start_time = IST.localize(start_time)
        elapsed = (get_ist_now() - start_time).seconds // 60
        remaining = max(0, QR_EXPIRE_MINUTES - elapsed)
        await update.message.reply_text(
            f"⏳ **QR PENDING**\n📱 QR assigned\n⏰ Expires in: {remaining} min",
            parse_mode='Markdown'
        )
        return
    
    if user_id in data.get("pending_review", {}):
        pending = data["pending_review"][user_id]
        start_time = datetime.fromisoformat(pending["timestamp"])
        if start_time.tzinfo is None:
            start_time = IST.localize(start_time)
        elapsed = (get_ist_now() - start_time).seconds // 60
        remaining = max(0, REVIEW_EXPIRE_MINUTES - elapsed)
        await update.message.reply_text(
            f"⏳ **REVIEW PENDING**\n📝 Review assigned\n⏰ Expires in: {remaining} min",
            parse_mode='Markdown'
        )
        return
    
    if user_id in data["users"] and data["users"][user_id].get("completed", False):
        user = data["users"][user_id]
        await update.message.reply_text(
            f"✅ **VERIFIED**\n📧 `{user.get('gmail', '')}`\n💰 ₹{user.get('balance', 0)}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ No active work.\n\n"
            "📌 Commands:\n"
            "/email - Get email work\n"
            "/qr - Get QR work\n"
            "/revive - Get review work",
            parse_mode='Markdown'
        )

# ============ HELP COMMAND ============
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin_user = is_admin(update.effective_user.id)
    
    help_text = (
        "📧 **HELP**\n\n"
        "**User Commands:**\n"
        "/email - Get email work (₹15)\n"
        "/qr - Get QR work (₹15)\n"
        "/revive - Get review work (₹15)\n"
        "/status - Check status\n"
        "/balance - Check balance\n"
        "/withdraw [amount] - Withdraw\n"
        "/setupi [UPI] - Set UPI\n"
        "/cancel - Cancel current\n"
        "/help - This help\n\n"
        "⏰ **Bot Timings:**\n"
        "🟢 8 AM - 10 PM IST (Online)\n"
        "🔴 10 PM - 8 AM IST (Maintenance)\n"
    )
    
    if is_admin_user:
        help_text += (
            "\n**Admin Commands:**\n"
            "/upload Name|Email|Pass|Rec - Add email\n"
            "/uploadqr [qr_data] - Add QR\n"
            "/uploadr [review] - Add review\n"
            "/stock - Check all stock\n"
            "/cancel #id - Cancel upload\n"
            "/reset all - Reset all (Owner)\n"
            "/approve [user_id] [amount] - Approve payment\n"
            "/newadmin [user_id] - Add admin (Owner)\n"
        )
    
    help_text += f"\n\n👑 Admin: {ESCROW_USER}"
    await update.message.reply_text(help_text, parse_mode='Markdown')

# ============ START COMMAND ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user = update.effective_user
    user_id = str(user.id)
    
    if is_maintenance_mode():
        next_start = get_next_start_time()
        if next_start:
            time_str = next_start.strftime('%I:%M %p')
            await update.message.reply_text(
                f"🛠️ **MAINTENANCE MODE**\n\n"
                f"Bot is currently in maintenance.\n"
                f"⏰ **Timing:** 10 PM - 8 AM IST\n"
                f"🔄 Bot will be back at **{time_str}**\n\n"
                f"⏳ Time remaining: {(next_start - get_ist_now()).seconds // 60} minutes\n\n"
                f"Please try again later!",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "🛠️ **MAINTENANCE MODE**\n\n"
                "Bot is currently in maintenance.\n"
                "⏰ **Timing:** 10 PM - 8 AM IST\n\n"
                "Please try again after 8 AM!",
                parse_mode='Markdown'
            )
        return
    
    if user_id not in data["users"]:
        data["users"][user_id] = {"balance": 0, "username": user.first_name, "completed": False}
        save_data(data)
    
    await update.message.reply_text(
        f"📧 **GMAIL VERIFICATION BOT**\n\n👋 Hello {user.first_name}!\n💰 **Earn ₹15 per work!**\n\n"
        "📌 **Available Work:**\n"
        "/email - Email verification\n"
        "/qr - QR verification\n"
        "/revive - Review work\n\n"
        f"⏰ **Timings:** 8 AM - 10 PM IST\n"
        f"👑 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )

# ============ ERROR HANDLER ============
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

# ============ MAIN ============
def main():
    global data, ADMINS
    data = load_data()
    ADMINS = data.get("admins", [OWNER_ID])
    
    request = HTTPXRequest(
        connect_timeout=60.0,
        read_timeout=60.0,
        write_timeout=60.0,
        pool_timeout=60.0,
    )
    
    app = Application.builder().token(TOKEN).request(request).build()
    
    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("email", email_command))
    app.add_handler(CommandHandler("qr", qr_command))
    app.add_handler(CommandHandler("revive", revive_command))
    app.add_handler(CommandHandler("getr", getr_command))
    app.add_handler(CommandHandler("skip2fa", skip2fa_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CommandHandler("setupi", setupi_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("help", help_command))
    
    # Admin commands
    app.add_handler(CommandHandler("upload", upload_command))
    app.add_handler(CommandHandler("uploadqr", uploadqr_command))
    app.add_handler(CommandHandler("uploadr", uploadr_command))
    app.add_handler(CommandHandler("stock", stock_command))
    app.add_handler(CommandHandler("approve", approve_command))
    app.add_handler(CommandHandler("newadmin", newadmin_command))
    app.add_handler(CommandHandler("reset", reset_all_command))
    app.add_handler(CommandHandler("cancel", cancel_upload_command))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_photo))
    app.add_error_handler(error_handler)
    
    # Job Queue
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(self_ping, interval=300, first=30)
        job_queue.run_repeating(check_timeout_job, interval=60, first=60)
        job_queue.run_repeating(check_qr_expire_job, interval=60, first=30)
        job_queue.run_repeating(check_review_expire_job, interval=60, first=30)
        print("🔄 All jobs scheduled")
    
    print("🚀 Bot started!")
    print(f"📦 Email: {len(data['email_stock'])}/{MAX_EMAIL_UPLOAD}")
    print(f"📱 QR: {len(data['qr_stock'])}/{MAX_QR_UPLOAD}")
    print(f"📝 Review: {len(data['review_stock'])}")
    print(f"⏰ Bot Timings: 8 AM - 10 PM IST")
    print(f"🔴 Maintenance: 10 PM - 8 AM IST")
    
    app.run_polling()

if __name__ == "__main__":
    main()
