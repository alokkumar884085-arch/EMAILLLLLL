import logging
import random
import string
import time
import re
import json
import os
import asyncio
import pytz
import threading
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.request import HTTPXRequest
from flask import Flask

# ============ FLASK WEB SERVER (KEEP ALIVE) ============
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "🟢 Bot is alive and running!"

@flask_app.route('/ping')
def ping():
    return "PONG"

def run_flask():
    flask_app.run(host='0.0.0.0', port=10000)

# ============ CONFIGURATION ============
TOKEN = "8875994072:AAFAgBRvDOmw1KrZZ0Ku0hW5h8nbA0otcKw"
OWNER_ID = 8785590284
ESCROW_USER = "@escrow2929"

ADMINS = [OWNER_ID]

# ============ TIME CONFIGURATION ============
MAINTENANCE_START_HOUR = 22
MAINTENANCE_END_HOUR = 8

# ============ LIMITS ============
MAX_EMAIL_UPLOAD = 1000
MAX_QR_UPLOAD = 100
MAX_REVIEW_UPLOAD = 500

# ============ TIMEOUT CONFIGURATION ============
# Ye timeout values badha diye gaye hain
HTTPX_TIMEOUT = 120.0  # 2 minutes
TASK_TIMEOUT_MINUTES = 15
QR_EXPIRE_MINUTES = 5
REVIEW_EXPIRE_MINUTES = 10
COOLDOWN_MINUTES = 2

# ============ IST TIMEZONE ============
IST = pytz.timezone('Asia/Kolkata')

def get_ist_now():
    return datetime.now(IST)

def is_maintenance_mode():
    now = get_ist_now()
    current_hour = now.hour
    if current_hour >= MAINTENANCE_START_HOUR or current_hour < MAINTENANCE_END_HOUR:
        return True
    return False

def get_next_start_time():
    now = get_ist_now()
    current_hour = now.hour
    if current_hour >= MAINTENANCE_START_HOUR:
        next_start = now.replace(hour=MAINTENANCE_END_HOUR, minute=0, second=0, microsecond=0) + timedelta(days=1)
    elif current_hour < MAINTENANCE_END_HOUR:
        next_start = now.replace(hour=MAINTENANCE_END_HOUR, minute=0, second=0, microsecond=0)
    else:
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
                    "pending_qr": {}, "pending_review": {}, "pending_approvals": {}
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
        "pending_qr": {}, "pending_review": {}, "pending_approvals": {}
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

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
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
                 f"⏰ IST: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
                 f"📦 Email: {len(data['email_stock'])}\n"
                 f"📱 QR: {len(data['qr_stock'])}\n"
                 f"📝 Review: {len(data['review_stock'])}\n"
                 f"👥 Users: {len(data['users'])}\n"
                 f"⏳ Pending Approvals: {len(data.get('pending_approvals', {}))}"
        )
        logger.info(f"Self ping #{PING_COUNT} sent")
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
            "💡 Use 'skip' for no recovery:\n"
            "/upload Name|Email|Pass|skip\n\n"
            "Multiple:\n"
            "/upload Name1|Email1|Pass1|Rec1,Name2|Email2|Pass2|skip\n\n"
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
            parts = email.split("|")
            if len(parts) == 4:
                name = parts[0].strip()
                gmail = parts[1].strip()
                password = parts[2].strip()
                recovery = parts[3].strip().lower()
                
                if recovery == "skip":
                    recovery = "No Recovery"
                
                processed_email = f"{name}|{gmail}|{password}|{recovery}"
                data["email_stock"].append(processed_email)
                data["upload_counter"] = data.get("upload_counter", 0) + 1
                data["upload_history"].append({
                    "id": data["upload_counter"], 
                    "raw": processed_email,
                    "status": "pending", 
                    "timestamp": get_ist_now().isoformat()
                })
                count += 1
            else:
                await update.message.reply_text(
                    f"❌ Invalid format: {email}\n\n"
                    "Use: Name|Email|Pass|Recovery\n"
                    "Or: Name|Email|Pass|skip",
                    parse_mode='Markdown'
                )
                return
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
                f"Bot will be back at **{time_str}**\n\n"
                f"⏰ Timing: 10 PM - 8 AM IST",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "🛠️ **MAINTENANCE MODE**\n\n"
                "⏰ Timing: 10 PM - 8 AM IST\n\n"
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
        name = parts[0].strip()
        gmail = parts[1].strip()
        password = parts[2].strip()
        recovery = parts[3].strip()
    else:
        gmail, password, recovery = parts[0].strip(), parts[1].strip(), parts[2].strip()
        name = username
    
    data["pending"][user_id] = {
        "type": "email", 
        "gmail": gmail, 
        "password": password,
        "recovery": recovery,
        "name": name,
        "username": username,
        "timestamp": get_ist_now().isoformat()
    }
    save_data(data)
    
    for admin in ADMINS:
        try:
            await context.bot.send_message(
                admin,
                f"📧 **EMAIL ASSIGNED!**\n"
                f"👤 @{username} (ID: `{user_id}`)\n"
                f"📧 `{gmail}`\n"
                f"📦 Left: {len(data['email_stock'])}"
            )
        except:
            pass
    
    await update.message.reply_text(
        f"📧 **EMAIL ASSIGNED!**\n\n"
        f"👤 Name: `{name}`\n"
        f"📧 Email: `{gmail}`\n"
        f"🔑 Pass: `{password}`\n"
        f"📧 Recovery: `{recovery}`\n\n"
        "📌 Login → /skip2fa → Upload QR → OTP → Screenshot\n\n"
        f"⏰ {TASK_TIMEOUT_MINUTES} min timeout!\n"
        "/cancel - Cancel",
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
                f"Bot will be back at **{time_str}**",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "🛠️ **MAINTENANCE MODE**\n\n"
                "⏰ Timing: 10 PM - 8 AM IST",
                parse_mode='Markdown'
            )
        return
    
    if user_id in data.get("pending_qr", {}):
        await update.message.reply_text("⏳ You already have a QR!", parse_mode='Markdown')
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
        f"📸 Send screenshot proof\n"
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
                f"Bot will be back at **{time_str}**",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "🛠️ **MAINTENANCE MODE**\n\n"
                "⏰ Timing: 10 PM - 8 AM IST",
                parse_mode='Markdown'
            )
        return
    
    if user_id in data.get("pending_review", {}):
        await update.message.reply_text("⏳ You already have a review!", parse_mode='Markdown')
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
        f"📸 Send screenshot proof\n"
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
            "📸 Send screenshot of Gmail inbox & settings as proof.",
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
                f"👤 Name: `{pending.get('name', '')}`\n"
                f"📧 Email: `{pending.get('gmail', '')}`\n"
                f"🔑 Pass: `{pending.get('password', '')}`\n"
                f"📧 Recovery: `{pending.get('recovery', '')}`\n\n"
                "📌 /skip2fa - Skip 2FA\n"
                "/cancel - Cancel work",
                parse_mode='Markdown'
            )
        return
    
    if user_id in data.get("pending_qr", {}):
        await update.message.reply_text(
            "📱 **QR PENDING**\n\n"
            "Send a PHOTO as proof.",
            parse_mode='Markdown'
        )
        return
    
    if user_id in data.get("pending_review", {}):
        await update.message.reply_text(
            "📝 **REVIEW PENDING**\n\n"
            "Send a PHOTO as proof.",
            parse_mode='Markdown'
        )
        return
    
    await update.message.reply_text(
        "❌ **Unknown command**\n\n"
        "📌 Commands:\n"
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
        
        approval_id = f"qr_{user_id}_{int(get_ist_now().timestamp())}"
        data["pending_approvals"][approval_id] = {
            "type": "qr",
            "user_id": user_id,
            "username": username,
            "data": pending["qr_data"],
            "screenshot": file_id,
            "timestamp": get_ist_now().isoformat(),
            "status": "pending"
        }
        
        for qr in data.get("qr_history", []):
            if qr["data"] == pending["qr_data"] and qr["status"] == "pending":
                qr["status"] = "pending_approval"
                break
        
        del data["pending_qr"][user_id]
        save_data(data)
        
        for admin in ADMINS:
            try:
                await context.bot.send_photo(
                    chat_id=admin,
                    photo=file_id,
                    caption=f"📱 **QR PENDING APPROVAL!**\n\n"
                            f"👤 User: @{username}\n"
                            f"🆔 ID: `{user_id}`\n"
                            f"📱 QR: `{pending['qr_data']}`\n"
                            f"⏰ Time: {get_ist_now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                            f"📌 Approve: `/approve {approval_id}`\n"
                            f"❌ Deny: `/deny {approval_id}`",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Failed to send QR approval to admin {admin}: {e}")
        
        await update.message.reply_text(
            f"✅ **QR SUBMITTED FOR APPROVAL!**\n\n"
            f"📱 QR: `{pending['qr_data']}`\n"
            f"📸 Screenshot sent to admins\n"
            f"⏳ Waiting for admin approval\n\n"
            f"💰 You will get ₹15 after approval.\n"
            f"👑 Admin: {ESCROW_USER}",
            parse_mode='Markdown'
        )
        return
    
    # Check for Review pending
    if user_id in data.get("pending_review", {}):
        pending = data["pending_review"][user_id]
        photo = update.message.photo[-1]
        file_id = photo.file_id
        
        approval_id = f"review_{user_id}_{int(get_ist_now().timestamp())}"
        data["pending_approvals"][approval_id] = {
            "type": "review",
            "user_id": user_id,
            "username": username,
            "data": pending["review_data"],
            "screenshot": file_id,
            "timestamp": get_ist_now().isoformat(),
            "status": "pending"
        }
        
        for rev in data.get("review_history", []):
            if rev["data"] == pending["review_data"] and rev["status"] == "pending":
                rev["status"] = "pending_approval"
                break
        
        del data["pending_review"][user_id]
        save_data(data)
        
        for admin in ADMINS:
            try:
                await context.bot.send_photo(
                    chat_id=admin,
                    photo=file_id,
                    caption=f"📝 **REVIEW PENDING APPROVAL!**\n\n"
                            f"👤 User: @{username}\n"
                            f"🆔 ID: `{user_id}`\n"
                            f"📝 Review: `{pending['review_data']}`\n"
                            f"⏰ Time: {get_ist_now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                            f"📌 Approve: `/approve {approval_id}`\n"
                            f"❌ Deny: `/deny {approval_id}`",
                    parse_mode='Markdown'
                )
