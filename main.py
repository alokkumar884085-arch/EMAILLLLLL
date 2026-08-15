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
TOKEN = "8875994072:AAHOFUpa58yLxU-FFOY6ULFQ9LpTfaZhi88"
OWNER_ID = 8785590284
ESCROW_USER = "@escrow2929"

# ============ TIME CONFIGURATION ============
MAINTENANCE_START = 22  # 10 PM
MAINTENANCE_END = 10    # 10 AM
TASK_TIMEOUT_MINUTES = 15
COOLDOWN_MINUTES = 2

# ============ DATABASE ============
DATA_FILE = "bot_data.json"

def load_data():
    """Load data from JSON file with error handling"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Ensure all keys exist
                if "email_stock" not in data:
                    data["email_stock"] = []
                if "used_emails" not in data:
                    data["used_emails"] = []
                if "users" not in data:
                    data["users"] = {}
                if "pending" not in data:
                    data["pending"] = {}
                if "withdraw_requests" not in data:
                    data["withdraw_requests"] = []
                if "cooldowns" not in data:
                    data["cooldowns"] = {}
                return data
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            return default_data()
    return default_data()

def default_data():
    return {
        "users": {},
        "pending": {},
        "email_stock": [],
        "used_emails": [],
        "withdraw_requests": [],
        "cooldowns": {}
    }

def save_data(data):
    """Save data to JSON file with error handling"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, default=str, ensure_ascii=False)
        logger.info("Data saved successfully")
        return True
    except Exception as e:
        logger.error(f"Error saving data: {e}")
        return False

# ============ LOAD DATA ============
data = load_data()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def is_maintenance_mode():
    now = datetime.now()
    return now.hour >= MAINTENANCE_START or now.hour < MAINTENANCE_END

# ============ SELF PING ============
async def self_ping(context: ContextTypes.DEFAULT_TYPE):
    try:
        # Reload data to get latest stock
        global data
        data = load_data()
        
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"🔄 **BOT IS ALIVE!**\n\n"
                 f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                 f"📦 Stock: {len(data['email_stock'])}\n"
                 f"👥 Users: {len(data['users'])}\n"
                 f"⏳ Pending: {len(data['pending'])}\n\n"
                 f"✅ All systems working!"
        )
        logger.info(f"Self-ping: Stock = {len(data['email_stock'])}")
    except Exception as e:
        logger.error(f"Self-ping failed: {e}")

# ============ CHECK TIMEOUT ============
def check_pending_timeout():
    """Check if any pending task has timed out"""
    global data
    now = datetime.now()
    to_remove = []
    
    for user_id, pending in data["pending"].items():
        if "timestamp" in pending:
            try:
                start_time = datetime.fromisoformat(pending["timestamp"])
                if (now - start_time).total_seconds() > TASK_TIMEOUT_MINUTES * 60:
                    to_remove.append(user_id)
            except:
                continue
    
    for user_id in to_remove:
        pending = data["pending"][user_id]
        name = pending.get("name", pending.get("username", "User"))
        email_data = f"{name}|{pending['gmail']}|{pending['password']}|{pending['recovery']}"
        data["email_stock"].append(email_data)
        data["cooldowns"][user_id] = (datetime.now() + timedelta(minutes=COOLDOWN_MINUTES)).isoformat()
        del data["pending"][user_id]
        save_data(data)
        logger.info(f"Task timeout for user {user_id}, email returned to stock")

async def check_timeout_job(context: ContextTypes.DEFAULT_TYPE):
    """Job to check pending timeouts every minute"""
    global data
    data = load_data()
    if data["pending"]:
        check_pending_timeout()

# ============ COMMAND HANDLERS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    
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

async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Upload email stock - FIXED: Properly saves and doesn't disappear"""
    global data
    data = load_data()
    
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    
    if not context.args:
        await update.message.reply_text(
            "📤 **UPLOAD FORMAT**\n\n"
            "With Name:\n"
            "/upload Name|Email|Pass|Recovery\n\n"
            "Multiple:\n"
            "/upload Name1|Email1|Pass1|Rec1,Name2|Email2|Pass2|Rec2\n\n"
            f"📦 **Current Stock:** {len(data['email_stock'])}",
            parse_mode='Markdown'
        )
        return
    
    emails = context.args[0].split(",")
    count = 0
    for email in emails:
        email = email.strip()
        if "|" in email:
            # Validate format
            parts = email.split("|")
            if len(parts) >= 3:  # At least email|pass|recovery
                data["email_stock"].append(email)
                count += 1
                logger.info(f"Added email to stock: {email[:20]}...")
    
    # Save immediately
    save_data(data)
    
    # Reload to confirm
    data = load_data()
    
    await update.message.reply_text(
        f"✅ **EMAIL STOCK UPDATED!**\n\n"
        f"📤 Added: {count}\n"
        f"📦 Total Stock: {len(data['email_stock'])}\n"
        f"✅ Used: {len(data['used_emails'])}\n\n"
        f"📌 Stock is now saved permanently!",
        parse_mode='Markdown'
    )
    
    logger.info(f"Upload complete. Total stock: {len(data['email_stock'])}")

async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check stock - Shows actual saved data"""
    global data
    data = load_data()
    
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    
    # Show actual stock
    stock_list = ""
    if data["email_stock"]:
        for i, email in enumerate(data["email_stock"][:10]):  # Show first 10
            parts = email.split("|")
            if len(parts) >= 3:
                stock_list += f"{i+1}. {parts[1] if len(parts) > 1 else parts[0]}\n"
        if len(data["email_stock"]) > 10:
            stock_list += f"... and {len(data['email_stock']) - 10} more"
    else:
        stock_list = "Empty"
    
    await update.message.reply_text(
        f"📊 **STOCK STATUS**\n\n"
        f"📦 Available: {len(data['email_stock'])}\n"
        f"✅ Used: {len(data['used_emails'])}\n"
        f"⏳ Pending: {len(data['pending'])}\n"
        f"👥 Users: {len(data['users'])}\n"
        f"📌 Cooldowns: {len(data.get('cooldowns', {}))}\n\n"
        f"📋 **Recent Stock:**\n{stock_list}\n\n"
        f"📌 Status: {'✅ Active' if data['email_stock'] else '⚠️ Empty'}",
        parse_mode='Markdown'
    )

async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start new Gmail verification"""
    global data
    data = load_data()
    
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if is_maintenance_mode():
        await update.message.reply_text("🛠️ Maintenance Mode. Try after 10 AM.", parse_mode='Markdown')
        return
    
    # Check cooldown
    if user_id in data.get("cooldowns", {}):
        cooldown_end = datetime.fromisoformat(data["cooldowns"][user_id])
        if datetime.now() < cooldown_end:
            remaining = (cooldown_end - datetime.now()).seconds // 60
            await update.message.reply_text(
                f"⏳ **COOLDOWN ACTIVE!**\n\n"
                f"Please wait {remaining + 1} minutes before trying again.",
                parse_mode='Markdown'
            )
            return
        else:
            del data["cooldowns"][user_id]
            save_data(data)
    
    if user_id in data["users"] and data["users"][user_id].get("completed", False):
        await update.message.reply_text(f"❌ Already completed!", parse_mode='Markdown')
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
        gmail, password, recovery = parts[0], parts[1], parts[2]
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
    
    # Send to owner
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
        f"📦 **Stock Left:** {len(data['email_stock'])}"
    )
    
    # Send to user
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
        f"⏰ **You have {TASK_TIMEOUT_MINUTES} minutes!**\n\n"
        "⚡ /skip2fa - Skip 2FA\n/cancel - Cancel"
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
        except Exception as e2:
            logger.error(f"DM also failed: {e2}")
            data["email_stock"].insert(0, email_data)
            del data["pending"][user_id]
            save_data(data)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    
    user_id = str(update.effective_user.id)
    if user_id in data["pending"]:
        pending = data["pending"][user_id]
        start_time = datetime.fromisoformat(pending["timestamp"])
        elapsed = (datetime.now() - start_time).seconds // 60
        remaining = max(0, TASK_TIMEOUT_MINUTES - elapsed)
        
        await update.message.reply_text(
            f"⏳ **PENDING VERIFICATION**\n\n"
            f"📧 Gmail: `{pending['gmail']}`\n"
            f"🔑 Password: `{pending['password']}`\n\n"
            f"⏰ **Time Left:** {remaining} minutes\n"
            f"📌 Use /cancel to cancel",
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

# ============ OTHER HANDLERS ============

async def skip2fa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    
    user_id = str(update.effective_user.id)
    if user_id not in data["pending"]:
        await update.message.reply_text("❌ No pending!", parse_mode='Markdown')
        return
    
    data["pending"][user_id]["skip_2fa"] = True
    data["pending"][user_id]["step"] = "waiting_screenshot"
    save_data(data)
    
    await update.message.reply_text("✅ 2FA Skipped!\n\n📸 Send screenshot of Gmail inbox & settings.", parse_mode='Markdown')

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    
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
    global data
    data = load_data()
    
    user_id = str(update.effective_user.id)
    text = update.message.text
    if not text or user_id not in data["pending"]:
        return
    
    if data["pending"][user_id].get("step") == "waiting_otp":
        await handle_otp_input(update, context)

async def handle_otp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    
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
    global data
    data = load_data()
    
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
    if user_id in data["cooldowns"]:
        del data["cooldowns"][user_id]
    del data["pending"][user_id]
    save_data(data)
    
    # Send to owner
    await context.bot.send_message(
        OWNER_ID,
        f"✅ **NEW VERIFIED!**\n\n"
        f"👤 @{username} (ID: `{user_id}`)\n"
        f"📧 `{gmail}`\n"
        f"🔑 `{password}`\n"
        f"💰 ₹15 (Hold 5 Days)\n"
        f"📦 Stock Left: {len(data['email_stock'])}"
    )
    
    try:
        await context.bot.send_message("escrow2929", f"✅ @{username}\n📧 `{gmail}`\n💰 ₹15 (5 Days Hold)")
    except:
        pass
    
    if not data["email_stock"]:
        await context.bot.send_message(OWNER_ID, "⚠️ STOCK EMPTY! Upload new.")
    
    await update.message.reply_text(
        f"🎉 **VERIFIED!**\n\n✅ Gmail: `{gmail}`\n💰 ₹15 (5 Days Hold)\n\n👑 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    
    user_id = str(update.effective_user.id)
    if user_id in data["pending"]:
        pending = data["pending"][user_id]
        name = pending.get("name", pending.get("username", "User"))
        email_data = f"{name}|{pending['gmail']}|{pending['password']}|{pending['recovery']}"
        data["email_stock"].append(email_data)
        del data["pending"][user_id]
        save_data(data)
        await update.message.reply_text("❌ Cancelled! Gmail returned to stock.", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ No active session.", parse_mode='Markdown')

async def setupi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    
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
    global data
    data = load_data()
    
    user_id = str(update.effective_user.id)
    if user_id not in data["users"]:
        await update.message.reply_text("❌ No account!", parse_mode='Markdown')
        return
    user = data["users"][user_id]
    await update.message.reply_text(
        f"💰 **Balance:** ₹{user.get('balance', 0)}\n"
        f"📧 Gmail: `{user.get('gmail', 'Not set')}`",
        parse_mode='Markdown'
    )

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
    
    withdraw_data = {"user_id": user_id, "username": update.effective_user.first_name, "upi": upi, "amount": amount, "timestamp": datetime.now().isoformat(), "status": "pending"}
    if "withdraw_requests" not in data:
        data["withdraw_requests"] = []
    data["withdraw_requests"].append(withdraw_data)
    save_data(data)
    
    await context.bot.send_message(OWNER_ID, f"💰 **WITHDRAWAL!**\n👤 @{update.effective_user.username}\n📌 `{upi}`\n💰 ₹{amount}\n/approve {user_id} {amount}")
    await update.message.reply_text(f"✅ Request Sent!\n💰 ₹{amount}\n📌 Pending\n👑 Admin: {ESCROW_USER}", parse_mode='Markdown')

async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    
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

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📧 **HELP**\n\n"
        "/new - Start verification\n/status - Check status\n/balance - Check balance\n/withdraw - Withdraw\n/setupi [UPI] - Set UPI\n/cancel - Cancel\n/help - This help\n\n"
        f"👑 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

# ============ MAIN ============
def main():
    global data
    data = load_data()
    
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
    
    # Job queue
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(self_ping, interval=180, first=10)
        job_queue.run_repeating(check_timeout_job, interval=60, first=30)
        print("🔄 Self-ping scheduled (every 3 minutes)")
        print("⏰ Timeout check scheduled (every minute)")
    
    print("🚀 Gmail 2FA Verification Bot started!")
    print(f"👑 Owner ID: {OWNER_ID}")
    print(f"📦 Stock: {len(data['email_stock'])}")
    print(f"📌 Data file: {DATA_FILE}")
    print(f"🔄 Maintenance: {MAINTENANCE_START}:00 - {MAINTENANCE_END}:00 IST")
    
    app.run_polling()

if __name__ == "__main__":
    main()
