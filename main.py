import logging
import random
import string
import time
import re
import json
import os
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# ============ CONFIGURATION ============
TOKEN = "8875994072:AAHUbwcMmabM5UmsDKivRH1C6rj1mIQbpvM"
OWNER_ID = 8785590284
ESCROW_USER = "@escrow2929"

# ============ TIME CONFIGURATION ============
MAINTENANCE_START = 22  # 10 PM
MAINTENANCE_END = 10    # 10 AM
TASK_TIMEOUT_MINUTES = 15  # 15 minute task timeout
COOLDOWN_MINUTES = 2  # 2 minute cooldown

# ============ DATABASE ============
DATA_FILE = "bot_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except:
            return default_data()
    return default_data()

def default_data():
    return {
        "users": {},
        "pending": {},
        "email_stock": [],
        "used_emails": [],
        "withdraw_requests": [],
        "cooldowns": {}  # user_id -> cooldown_end_time
    }

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4, default=str)

data = load_data()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def is_maintenance_mode():
    now = datetime.now()
    return now.hour >= MAINTENANCE_START or now.hour < MAINTENANCE_END

# ============ SELF PING (HAR 3 MINUTE) ============
async def self_ping(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"🔄 **BOT IS ALIVE!**\n\n"
                 f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                 f"📦 Stock: {len(data['email_stock'])}\n"
                 f"👥 Users: {len(data['users'])}\n"
                 f"⏳ Pending: {len(data['pending'])}\n\n"
                 f"✅ All systems working!"
        )
        logger.info("Self-ping sent successfully")
    except Exception as e:
        logger.error(f"Self-ping failed: {e}")

# ============ CHECK TIMEOUT ============
def check_pending_timeout():
    """Check if any pending task has timed out (15 minutes)"""
    now = datetime.now()
    to_remove = []
    
    for user_id, pending in data["pending"].items():
        if "timestamp" in pending:
            start_time = datetime.fromisoformat(pending["timestamp"])
            if (now - start_time).total_seconds() > TASK_TIMEOUT_MINUTES * 60:
                to_remove.append(user_id)
    
    for user_id in to_remove:
        pending = data["pending"][user_id]
        # Return email to stock
        name = pending.get("name", pending.get("username", "User"))
        email_data = f"{name}|{pending['gmail']}|{pending['password']}|{pending['recovery']}"
        data["email_stock"].append(email_data)
        
        # Set cooldown for user
        data["cooldowns"][user_id] = (datetime.now() + timedelta(minutes=COOLDOWN_MINUTES)).isoformat()
        
        del data["pending"][user_id]
        save_data(data)
        
        logger.info(f"Task timeout for user {user_id}, email returned to stock, cooldown set")
        
        # Notify owner
        try:
            context.bot.send_message(
                OWNER_ID,
                f"⏰ **TASK TIMEOUT!**\n\n"
                f"👤 User ID: `{user_id}`\n"
                f"📧 Gmail: `{pending['gmail']}`\n"
                f"⏰ Timeout after {TASK_TIMEOUT_MINUTES} minutes\n"
                f"⏳ Cooldown: {COOLDOWN_MINUTES} minutes"
            )
        except:
            pass

async def check_timeout_job(context: ContextTypes.DEFAULT_TYPE):
    """Job to check pending timeouts every minute"""
    if data["pending"]:
        check_pending_timeout()

# ============ COMMAND HANDLERS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    
    if is_maintenance_mode():
        await update.message.reply_text("🛠️ Maintenance Mode (10 PM - 10 AM IST). Try after 10 AM.", parse_mode='Markdown')
        return
    
    if user_id not in data["users"]:
        data["users"][user_id] = {"gmail": "", "password": "", "recovery": "", "timestamp": "", "upi": "", "balance": 0, "username": user.first_name, "completed": False}
        save_data(data)
    
    await update.message.reply_text(
        f"📧 **GMAIL VERIFICATION BOT**\n\n👋 Hello {user.first_name}!\n💰 **Earn ₹15 per Gmail!**\n\n"
        "📋 **Commands:**\n/new - Start\n/status - Check status\n/balance - Check balance\n/withdraw - Withdraw\n/setupi [UPI] - Set UPI\n/cancel - Cancel\n/help - Help\n\n"
        f"👑 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )

async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start new Gmail verification with timeout and cooldown"""
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if is_maintenance_mode():
        await update.message.reply_text("🛠️ Maintenance Mode. Try after 10 AM.", parse_mode='Markdown')
        return
    
    # Check cooldown
    if user_id in data["cooldowns"]:
        cooldown_end = datetime.fromisoformat(data["cooldowns"][user_id])
        if datetime.now() < cooldown_end:
            remaining = (cooldown_end - datetime.now()).seconds // 60
            await update.message.reply_text(
                f"⏳ **COOLDOWN ACTIVE!**\n\n"
                f"Please wait {remaining + 1} minutes before trying again.\n"
                f"You timed out on your last task.",
                parse_mode='Markdown'
            )
            return
        else:
            del data["cooldowns"][user_id]
            save_data(data)
    
    if user_id in data["users"] and data["users"][user_id].get("completed", False):
        await update.message.reply_text(f"❌ Already completed! Gmail: `{data['users'][user_id]['gmail']}`", parse_mode='Markdown')
        return
    
    if not data["email_stock"]:
        await update.message.reply_text("❌ No stock! Admin notified.", parse_mode='Markdown')
        await context.bot.send_message(OWNER_ID, "⚠️ STOCK EMPTY! Use /upload")
        return
    
    if user_id in data["pending"]:
        await update.message.reply_text("⏳ Pending verification! Use /cancel", parse_mode='Markdown')
        return
    
    # Assign email from stock
    email_data = data["email_stock"].pop(0)
    parts = email_data.split("|")
    
    if len(parts) == 4:
        name, gmail, password, recovery = parts
    else:
        gmail, password, recovery = parts
        name = username
    
    data["pending"][user_id] = {
        "gmail": gmail, 
        "password": password, 
        "recovery": recovery,
        "name": name,
        "timestamp": datetime.now().isoformat(), 
        "username": username
    }
    save_data(data)
    
    # ============ SEND TO OWNER ============
    await context.bot.send_message(
        OWNER_ID,
        f"📧 **GMAIL ASSIGNED!**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 **Username:** @{username}\n"
        f"🆔 **User ID:** `{user_id}`\n"
        f"📧 **Gmail:** `{gmail}`\n"
        f"🔑 **Password:** `{password}`\n"
        f"📧 **Recovery:** `{recovery}`\n"
        f"⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"⏳ **Task Timeout:** {TASK_TIMEOUT_MINUTES} minutes\n"
        f"📌 **Stock Left:** {len(data['email_stock'])}"
    )
    
    # ============ SEND TO USER ============
    message_text = (
        f"📧 **GMAIL ASSIGNED!**\n\n"
        f"👤 Name: `{name}`\n"
        f"📧 Email: `{gmail}`\n"
        f"🔑 Password: `{password}`\n"
        f"📧 Recovery: `{recovery}`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 **Next Steps:**\n"
        "1️⃣ Login to this Gmail\n"
        "2️⃣ Enable 2FA or /skip2fa\n"
        "3️⃣ Upload QR Code\n"
        "4️⃣ Enter OTP\n"
        "5️⃣ Submit screenshot\n\n"
        f"⏰ **You have {TASK_TIMEOUT_MINUTES} minutes to complete!**\n"
        f"⚠️ After timeout, email returns to stock\n\n"
        "⚡ **Commands:**\n"
        "/skip2fa - Skip 2FA\n"
        "/cancel - Cancel"
    )
    
    try:
        await update.message.reply_text(message_text, parse_mode='Markdown')
        logger.info(f"Email assigned to {user_id}: {gmail}")
    except Exception as e:
        logger.error(f"Failed to send message to {user_id}: {e}")
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=message_text,
                parse_mode='Markdown'
            )
            logger.info(f"Email sent via DM to {user_id}: {gmail}")
        except Exception as e2:
            logger.error(f"DM also failed for {user_id}: {e2}")
            data["email_stock"].insert(0, email_data)
            del data["pending"][user_id]
            save_data(data)
            await context.bot.send_message(
                OWNER_ID,
                f"⚠️ **DELIVERY FAILED!**\n\n"
                f"User: {username} (ID: {user_id})\n"
                f"Email returned to stock."
            )

async def skip2fa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in data["pending"]:
        await update.message.reply_text("❌ No pending!", parse_mode='Markdown')
        return
    
    data["pending"][user_id]["skip_2fa"] = True
    data["pending"][user_id]["step"] = "waiting_screenshot"
    save_data(data)
    
    await update.message.reply_text("✅ 2FA Skipped!\n\n📸 Send screenshot of Gmail inbox & settings.", parse_mode='Markdown')

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in data["pending"]:
        return
    
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    
    data["pending"][user_id]["qr_file_id"] = photo.file_id
    otp = random.randint(100000, 999999)
    data["pending"][user_id]["otp"] = otp
    data["pending"][user_id]["step"] = "waiting_otp"
    save_data(data)
    
    await update.message.reply_text(f"✅ QR Received!\n\n📱 OTP: `{otp}`\n\nEnter the OTP:", parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text
    if not text or user_id not in data["pending"]:
        return
    
    if data["pending"][user_id].get("step") == "waiting_otp":
        await handle_otp_input(update, context)

async def handle_otp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    
    if not text.isdigit() or len(text) != 6:
        await update.message.reply_text("❌ Enter 6-digit OTP!", parse_mode='Markdown')
        return
    
    stored_otp = data["pending"][user_id].get("otp")
    if int(text) != stored_otp:
        await update.message.reply_text("❌ Wrong OTP! Try again.", parse_mode='Markdown')
        return
    
    data["pending"][user_id]["otp_verified"] = True
    data["pending"][user_id]["step"] = "waiting_screenshot"
    save_data(data)
    
    await update.message.reply_text("✅ OTP Verified!\n\n📸 Send screenshot of Gmail inbox & settings.", parse_mode='Markdown')

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if user_id not in data["pending"]:
        return
    
    if not update.message.photo and not update.message.document:
        await update.message.reply_text("❌ Send screenshot!", parse_mode='Markdown')
        return
    
    file_id = update.message.photo[-1].file_id if update.message.photo else update.message.document.file_id
    
    pending = data["pending"][user_id]
    gmail, password, recovery = pending["gmail"], pending["password"], pending["recovery"]
    name = pending.get("name", username)
    
    data["users"][user_id] = {
        "gmail": gmail, 
        "password": password, 
        "recovery": recovery,
        "name": name,
        "timestamp": datetime.now().isoformat(),
        "upi": data["users"].get(user_id, {}).get("upi", ""),
        "balance": 15, 
        "username": username, 
        "completed": True,
        "screenshot": file_id,
        "skip_2fa": pending.get("skip_2fa", False)
    }
    
    data["used_emails"].append(gmail)
    
    # Remove cooldown if exists
    if user_id in data["cooldowns"]:
        del data["cooldowns"][user_id]
    
    del data["pending"][user_id]
    save_data(data)
    
    # Send to owner
    await context.bot.send_message(
        OWNER_ID,
        f"✅ **NEW VERIFIED!**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 **Name:** {name}\n"
        f"👤 **User:** @{username}\n"
        f"🆔 **ID:** `{user_id}`\n"
        f"📧 **Gmail:** `{gmail}`\n"
        f"🔑 **Pass:** `{password}`\n"
        f"📧 **Recovery:** `{recovery}`\n"
        f"📸 **2FA:** {'✅' if not pending.get('skip_2fa') else '❌ Skipped'}\n"
        f"💰 **Payment:** ₹15 (Hold 5 Days)\n"
        f"⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"📦 **Stock Left:** {len(data['email_stock'])}"
    )
    
    # Send to escrow
    try:
        await context.bot.send_message(
            "escrow2929",
            f"✅ **NEW GMAIL!**\n"
            f"👤 @{username}\n"
            f"📧 `{gmail}`\n"
            f"💰 ₹15 (5 Days Hold)"
        )
    except:
        pass
    
    if not data["email_stock"]:
        await context.bot.send_message(OWNER_ID, "⚠️ STOCK EMPTY! Upload new.")
    
    await update.message.reply_text(
        f"🎉 **VERIFIED!** 🎉\n\n"
        f"✅ Gmail: `{gmail}`\n"
        f"💰 ₹15 (5 Days Hold)\n\n"
        f"📧 Logged out!\n"
        f"👑 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in data["pending"]:
        pending = data["pending"][user_id]
        name = pending.get("name", pending.get("username", "User"))
        email_data = f"{name}|{pending['gmail']}|{pending['password']}|{pending['recovery']}"
        data["email_stock"].append(email_data)
        del data["pending"][user_id]
        save_data(data)
        
        await context.bot.send_message(
            OWNER_ID,
            f"❌ **CANCELLED!**\n\n"
            f"👤 User: @{pending.get('username', 'Unknown')}\n"
            f"🆔 ID: `{user_id}`\n"
            f"📧 Gmail: `{pending['gmail']}`\n"
            f"⏰ Cancelled manually"
        )
        
        await update.message.reply_text("❌ Cancelled! Gmail returned to stock.", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ No active session.", parse_mode='Markdown')

async def setupi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if len(context.args) < 1:
        await update.message.reply_text("❌ Usage: /setupi [UPI_ID]", parse_mode='Markdown')
        return
    
    upi = context.args[0]
    if user_id not in data["users"]:
        data["users"][user_id] = {"gmail": "", "password": "", "recovery": "", "timestamp": "", "upi": upi, "balance": 0, "username": update.effective_user.first_name, "completed": False}
    else:
        data["users"][user_id]["upi"] = upi
    save_data(data)
    await update.message.reply_text(f"✅ UPI Set: `{upi}`", parse_mode='Markdown')

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in data["users"]:
        await update.message.reply_text("❌ No account!", parse_mode='Markdown')
        return
    user = data["users"][user_id]
    await update.message.reply_text(
        f"💰 **Balance:** ₹{user.get('balance', 0)}\n"
        f"📧 Gmail: `{user.get('gmail', 'Not set')}`\n"
        f"📌 UPI: `{user.get('upi', 'Not set')}`",
        parse_mode='Markdown'
    )

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    withdraw_data = {"user_id": user_id, "username": update.effective_user.first_name, "upi": upi, "amount": amount, "timestamp": datetime.now().isoformat(), "status": "pending"}
    if "withdraw_requests" not in data:
        data["withdraw_requests"] = []
    data["withdraw_requests"].append(withdraw_data)
    save_data(data)
    
    await context.bot.send_message(OWNER_ID, f"💰 **WITHDRAWAL!**\n👤 @{update.effective_user.username}\n📌 `{upi}`\n💰 ₹{amount}\n/approve {user_id} {amount}")
    await update.message.reply_text(f"✅ Request Sent!\n💰 ₹{amount}\n📌 Pending\n👑 Admin: {ESCROW_USER}", parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in data["pending"]:
        pending = data["pending"][user_id]
        # Check remaining time
        start_time = datetime.fromisoformat(pending["timestamp"])
        elapsed = (datetime.now() - start_time).seconds // 60
        remaining = max(0, TASK_TIMEOUT_MINUTES - elapsed)
        
        await update.message.reply_text(
            f"⏳ **PENDING VERIFICATION**\n\n"
            f"📧 Gmail: `{pending['gmail']}`\n"
            f"🔑 Password: `{pending['password']}`\n"
            f"📧 Recovery: `{pending['recovery']}`\n\n"
            f"⏰ **Time Left:** {remaining} minutes\n"
            f"📌 Complete verification or /cancel",
            parse_mode='Markdown'
        )
    elif user_id in data["users"] and data["users"][user_id].get("completed", False):
        user = data["users"][user_id]
        await update.message.reply_text(
            f"✅ **VERIFIED**\n\n"
            f"📧 Gmail: `{user['gmail']}`\n"
            f"💰 Balance: ₹{user.get('balance', 0)}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ No active verification. Use /new", parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📧 **HELP**\n\n"
        "/new - Start verification\n"
        "/status - Check status\n"
        "/balance - Check balance\n"
        "/withdraw - Withdraw earnings\n"
        "/setupi [UPI] - Set UPI ID\n"
        "/cancel - Cancel process\n"
        "/help - This help\n\n"
        f"👑 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )

# ============ ADMIN COMMANDS ============

async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if not context.args:
        await update.message.reply_text(
            "📤 **UPLOAD FORMAT**\n\n"
            "With Name:\n"
            "/upload Name|Email|Pass|Recovery\n\n"
            "Multiple:\n"
            "/upload Name1|Email1|Pass1|Rec1,Name2|Email2|Pass2|Rec2",
            parse_mode='Markdown'
        )
        return
    
    emails = context.args[0].split(",")
    count = 0
    for email in emails:
        if "|" in email:
            data["email_stock"].append(email.strip())
            count += 1
    save_data(data)
    
    await update.message.reply_text(
        f"✅ **EMAIL STOCK UPDATED!**\n\n"
        f"📤 Added: {count}\n"
        f"📦 Total: {len(data['email_stock'])}",
        parse_mode='Markdown'
    )

async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    await update.message.reply_text(
        f"📊 **STOCK STATUS**\n\n"
        f"📦 Available: {len(data['email_stock'])}\n"
        f"✅ Used: {len(data['used_emails'])}\n"
        f"⏳ Pending: {len(data['pending'])}\n"
        f"👥 Users: {len(data['users'])}\n"
        f"📌 Cooldowns: {len(data.get('cooldowns', {}))}\n"
        f"📌 Status: {'✅ Active' if data['email_stock'] else '⚠️ Empty'}",
        parse_mode='Markdown'
    )

async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /approve [user_id] [amount]", parse_mode='Markdown')
        return
    
    target_id = context.args[0]
    amount = int(context.args[1])
    if target_id not in data["users"]:
        await update.message.reply_text(f"❌ User not found.", parse_mode='Markdown')
        return
    
    data["users"][target_id]["balance"] -= amount
    for req in data.get("withdraw_requests", []):
        if req["user_id"] == target_id and req["amount"] == amount and req["status"] == "pending":
            req["status"] = "approved"
            req["approved_at"] = datetime.now().isoformat()
            break
    save_data(data)
    
    await context.bot.send_message(int(target_id), f"💰 ₹{amount} Approved!", parse_mode='Markdown')
    await update.message.reply_text(f"✅ Approved ₹{amount} for `{target_id}`", parse_mode='Markdown')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

# ============ MAIN ============
def main():
    app = Application.builder().token(TOKEN).build()
    
    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new_command))
    app.add_handler(CommandHandler("skip2fa", skip2fa_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CommandHandler("setupi", setupi_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("help", help_command))
    
    # Admin commands
    app.add_handler(CommandHandler("upload", upload_command))
    app.add_handler(CommandHandler("stock", stock_command))
    app.add_handler(CommandHandler("approve", approve_command))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_screenshot))
    app.add_error_handler(error_handler)
    
    # ============ JOB QUEUE ============
    job_queue = app.job_queue
    if job_queue:
        # Self ping every 3 minutes
        job_queue.run_repeating(self_ping, interval=180, first=10)
        # Check timeout every minute
        job_queue.run_repeating(check_timeout_job, interval=60, first=30)
        print("🔄 Self-ping scheduled (every 3 minutes)")
        print("⏰ Timeout check scheduled (every minute)")
    
    print("🚀 Gmail 2FA Verification Bot started!")
    print(f"👑 Owner ID: {OWNER_ID}")
    print(f"📦 Stock: {len(data['email_stock'])}")
    print(f"⏰ Task Timeout: {TASK_TIMEOUT_MINUTES} minutes")
    print(f"⏳ Cooldown: {COOLDOWN_MINUTES} minutes")
    print(f"🔄 Maintenance: {MAINTENANCE_START}:00 - {MAINTENANCE_END}:00 IST")
    
    app.run_polling()

if __name__ == "__main__":
    main()
