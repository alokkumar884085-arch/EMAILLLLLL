import logging
import random
import string
import time
import re
import json
import os
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

# ============ DATABASE FILES ============
DATA_FILE = "bot_data.json"

# ============ DATABASE STRUCTURE ============
def load_data():
    """Load data from JSON file"""
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
        "withdraw_requests": []
    }

def save_data(data):
    """Save data to JSON file"""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4, default=str)

# ============ LOAD DATA ============
data = load_data()

# ============ LOGGING ============
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ MAINTENANCE MODE CHECK ============
def is_maintenance_mode():
    now = datetime.now()
    current_hour = now.hour
    if current_hour >= MAINTENANCE_START or current_hour < MAINTENANCE_END:
        return True
    return False

# ============ COMMAND HANDLERS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    
    if is_maintenance_mode():
        await update.message.reply_text(
            "🛠️ **MAINTENANCE MODE** 🛠️\n\n"
            "Bot is under maintenance.\n"
            "⏰ Timing: 10 PM - 10 AM IST\n\n"
            "Please try again after 10 AM.",
            parse_mode='Markdown'
        )
        return
    
    if user_id not in data["users"]:
        data["users"][user_id] = {
            "gmail": "", "password": "", "recovery": "",
            "timestamp": "", "upi": "", "balance": 0,
            "username": user.first_name, "completed": False
        }
        save_data(data)
    
    welcome_text = f"""
📧 **GMAIL 2FA VERIFICATION BOT** 📧

👋 Hello {user.first_name}!

💰 **EARN ₹15 BY VERIFYING GMAIL!**

📋 **STEPS:**
1️⃣ /new - Start new verification
2️⃣ Upload 2FA QR Code or /skip2fa
3️⃣ Enter OTP (if 2FA enabled)
4️⃣ Submit screenshot proof
5️⃣ Get ₹15 on hold
6️⃣ Release after 5 days moderation

⚡ **COMMANDS:**
/new - Start verification
/status - Check status
/balance - Check balance
/withdraw - Withdraw earnings
/setupi [UPI_ID] - Set UPI ID
/cancel - Cancel process
/help - Show help

👑 **Admin:** {ESCROW_USER}
"""
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if is_maintenance_mode():
        await update.message.reply_text("🛠️ Bot is under maintenance. Try after 10 AM.", parse_mode='Markdown')
        return
    
    if user_id in data["users"] and data["users"][user_id].get("completed", False):
        await update.message.reply_text(
            "❌ Already Completed! Only one Gmail per user.\n"
            f"📧 Gmail: `{data['users'][user_id]['gmail']}`\n"
            f"💰 Balance: ₹{data['users'][user_id]['balance']}",
            parse_mode='Markdown'
        )
        return
    
    if not data["email_stock"]:
        await update.message.reply_text("❌ No Email Stock Available! Admin notified.", parse_mode='Markdown')
        await context.bot.send_message(OWNER_ID, "⚠️ EMAIL STOCK EMPTY! Please upload new stock using /upload.")
        return
    
    if user_id in data["pending"]:
        await update.message.reply_text("⏳ You have a pending verification! Use /cancel to cancel.", parse_mode='Markdown')
        return
    
    email_data = data["email_stock"].pop(0)
    gmail, password, recovery = email_data.split("|")
    
    data["pending"][user_id] = {
        "gmail": gmail, "password": password, "recovery": recovery,
        "timestamp": str(datetime.now()), "status": "pending", "username": username
    }
    save_data(data)
    
    await update.message.reply_text(
        f"📧 **GMAIL ASSIGNED!**\n\n"
        f"📧 Gmail: `{gmail}`\n🔑 Password: `{password}`\n📧 Recovery: `{recovery}`\n\n"
        "📌 Next Steps:\n1️⃣ Login to this Gmail\n2️⃣ Enable 2FA or /skip2fa\n3️⃣ Upload QR Code\n4️⃣ Enter OTP\n5️⃣ Submit screenshot\n\n"
        "⚡ Commands: /skip2fa - Submit without 2FA | /cancel - Cancel",
        parse_mode='Markdown'
    )

async def skip2fa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in data["pending"]:
        await update.message.reply_text("❌ No pending verification! Use /new to start.", parse_mode='Markdown')
        return
    
    data["pending"][user_id]["skip_2fa"] = True
    data["pending"][user_id]["step"] = "waiting_screenshot"
    save_data(data)
    
    await update.message.reply_text(
        "✅ 2FA SKIPPED!\n\n"
        "📸 Send screenshot showing:\n1. Gmail inbox\n2. Account creation proof\n3. Gmail settings page",
        parse_mode='Markdown'
    )

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
    
    await update.message.reply_text(
        f"✅ QR Code Received!\n\n📱 Your 2FA OTP is: `{otp}`\n\n📝 Enter this OTP below:\n⚠️ OTP expires in 5 minutes!",
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text
    if not text or user_id not in data["pending"]:
        return
    
    step = data["pending"][user_id].get("step", "")
    if step == "waiting_otp":
        await handle_otp_input(update, context)

async def handle_otp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    
    if not text.isdigit() or len(text) != 6:
        await update.message.reply_text("❌ Invalid OTP! Must be 6 digits. Try again.", parse_mode='Markdown')
        return
    
    if user_id not in data["pending"]:
        return
    
    stored_otp = data["pending"][user_id].get("otp")
    if int(text) != stored_otp:
        await update.message.reply_text("❌ Invalid OTP! Try again.", parse_mode='Markdown')
        return
    
    data["pending"][user_id]["otp_verified"] = True
    data["pending"][user_id]["step"] = "waiting_screenshot"
    save_data(data)
    
    await update.message.reply_text(
        "✅ OTP Verified!\n\n📸 Send screenshot showing:\n1. Gmail inbox\n2. 2FA enabled (if enabled)\n3. Recovery email\n4. Account creation proof",
        parse_mode='Markdown'
    )

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if user_id not in data["pending"]:
        return
    
    if not update.message.photo and not update.message.document:
        await update.message.reply_text("❌ Please send a screenshot!", parse_mode='Markdown')
        return
    
    file_id = update.message.photo[-1].file_id if update.message.photo else update.message.document.file_id
    
    pending = data["pending"][user_id]
    gmail, password, recovery = pending["gmail"], pending["password"], pending["recovery"]
    
    data["users"][user_id] = {
        "gmail": gmail, "password": password, "recovery": recovery,
        "timestamp": str(datetime.now()),
        "upi": data["users"].get(user_id, {}).get("upi", ""),
        "balance": 15, "username": username, "completed": True,
        "screenshot": file_id,
        "skip_2fa": pending.get("skip_2fa", False),
        "otp_verified": pending.get("otp_verified", False)
    }
    
    data["used_emails"].append(gmail)
    del data["pending"][user_id]
    save_data(data)
    
    # Send to owner
    await context.bot.send_message(
        OWNER_ID,
        f"✅ NEW GMAIL VERIFIED!\n\n"
        f"👤 User: @{username}\n🆔 ID: `{user_id}`\n"
        f"📧 Gmail: `{gmail}`\n🔑 Pass: `{password}`\n📧 Recovery: `{recovery}`\n"
        f"📸 2FA: {'✅' if not pending.get('skip_2fa') else '❌ Skipped'}\n"
        f"💰 Payment: ₹15 (On Hold - 5 Days)\n"
        f"📌 UPI: {data['users'][user_id].get('upi', 'Not set')}"
    )
    
    # Send to escrow
    try:
        await context.bot.send_message(
            "escrow2929",
            f"✅ NEW GMAIL VERIFIED!\n\n"
            f"👤 User: @{username}\n📧 Gmail: `{gmail}`\n🔑 Pass: `{password}`\n"
            f"📸 2FA: {'✅' if not pending.get('skip_2fa') else '❌'}\n"
            f"💰 Payment: ₹15 (On Hold - 5 Days)"
        )
    except:
        pass
    
    # Check stock
    if not data["email_stock"]:
        await context.bot.send_message(OWNER_ID, "⚠️ EMAIL STOCK EMPTY! Please upload new stock.")
    
    await update.message.reply_text(
        f"🎉 GMAIL VERIFIED SUCCESSFULLY!\n\n"
        f"✅ Gmail: `{gmail}`\n💰 Balance: ₹15 (On Hold - 5 Days)\n\n"
        f"📌 Payment will be released after 5 days moderation.\n"
        f"📧 You have been logged out!\n\n"
        f"📧 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in data["pending"]:
        pending = data["pending"][user_id]
        data["email_stock"].append(f"{pending['gmail']}|{pending['password']}|{pending['recovery']}")
        del data["pending"][user_id]
        save_data(data)
        await update.message.reply_text("❌ Verification Cancelled! Gmail returned to stock.", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ No active session to cancel.", parse_mode='Markdown')

async def setupi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if len(context.args) < 1:
        await update.message.reply_text("❌ Usage: /setupi [UPI_ID]\nExample: /setupi example@upi", parse_mode='Markdown')
        return
    
    upi = context.args[0]
    if user_id not in data["users"]:
        data["users"][user_id] = {"gmail": "", "password": "", "recovery": "", "timestamp": "", "upi": upi, "balance": 0, "username": update.effective_user.first_name, "completed": False}
    else:
        data["users"][user_id]["upi"] = upi
    save_data(data)
    await update.message.reply_text(f"✅ UPI ID SET: `{upi}`", parse_mode='Markdown')

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in data["users"]:
        await update.message.reply_text("❌ No account found! Use /start.", parse_mode='Markdown')
        return
    user = data["users"][user_id]
    await update.message.reply_text(
        f"💰 YOUR BALANCE\n\n📧 Gmail: `{user.get('gmail', 'Not set')}`\n💰 Balance: ₹{user.get('balance', 0)}\n📌 UPI: `{user.get('upi', 'Not set')}`\n\n📌 Withdraw: /withdraw [amount]",
        parse_mode='Markdown'
    )

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in data["users"]:
        await update.message.reply_text("❌ No account found!", parse_mode='Markdown')
        return
    
    user = data["users"][user_id]
    balance = user.get("balance", 0)
    upi = user.get("upi", "")
    
    if not upi:
        await update.message.reply_text("❌ UPI ID not set! Use /setupi [UPI_ID]", parse_mode='Markdown')
        return
    if balance <= 0:
        await update.message.reply_text(f"❌ Insufficient Balance! Balance: ₹{balance}", parse_mode='Markdown')
        return
    if len(context.args) < 1:
        await update.message.reply_text(f"💰 Withdraw Amount\nBalance: ₹{balance}\nUsage: /withdraw [amount]", parse_mode='Markdown')
        return
    
    try:
        amount = int(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid Amount!", parse_mode='Markdown')
        return
    
    if amount > balance:
        await update.message.reply_text(f"❌ Insufficient Balance! Balance: ₹{balance}", parse_mode='Markdown')
        return
    if amount < 15:
        await update.message.reply_text("❌ Minimum Withdrawal is ₹15!", parse_mode='Markdown')
        return
    
    withdraw_data = {"user_id": user_id, "username": update.effective_user.first_name, "upi": upi, "amount": amount, "timestamp": str(datetime.now()), "status": "pending"}
    if "withdraw_requests" not in data:
        data["withdraw_requests"] = []
    data["withdraw_requests"].append(withdraw_data)
    save_data(data)
    
    await context.bot.send_message(OWNER_ID, f"💰 NEW WITHDRAWAL REQUEST!\n\n👤 User: @{update.effective_user.username}\n🆔 ID: `{user_id}`\n📌 UPI: `{upi}`\n💰 Amount: ₹{amount}\n📌 Action: /approve {user_id} {amount}")
    await update.message.reply_text(f"✅ WITHDRAWAL REQUEST SENT!\n💰 Amount: ₹{amount}\n📌 Status: Pending\n👑 Admin: {ESCROW_USER}", parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in data["pending"]:
        pending = data["pending"][user_id]
        await update.message.reply_text(f"⏳ PENDING VERIFICATION\n📧 Gmail: `{pending['gmail']}`\n📌 Status: In Progress\n\nUse /cancel to cancel.", parse_mode='Markdown')
    elif user_id in data["users"] and data["users"][user_id].get("completed", False):
        user = data["users"][user_id]
        await update.message.reply_text(f"✅ VERIFIED\n📧 Gmail: `{user['gmail']}`\n💰 Balance: ₹{user.get('balance', 0)}\n📌 UPI: `{user.get('upi', 'Not set')}`", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ No active verification. Use /new to start.", parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📧 GMAIL 2FA VERIFICATION BOT - HELP\n\n"
        "📋 COMMANDS:\n"
        "/new - Start verification\n/status - Check status\n/balance - Check balance\n"
        "/withdraw - Withdraw earnings\n/setupi [UPI_ID] - Set UPI ID\n/cancel - Cancel\n/help - This help\n\n"
        "💰 EARN ₹15:\n1️⃣ /new - Get a Gmail\n2️⃣ Login to Gmail\n3️⃣ Enable 2FA or /skip2fa\n4️⃣ Upload QR Code\n5️⃣ Enter OTP\n6️⃣ Submit screenshot\n7️⃣ Get ₹15 on hold\n8️⃣ Release after 5 days\n\n"
        f"📧 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )

# ============ ADMIN COMMANDS ============

async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if not context.args:
        await update.message.reply_text("📤 UPLOAD EMAIL STOCK\nUsage: /upload [gmail1|pass1|rec1,gmail2|pass2|rec2]", parse_mode='Markdown')
        return
    
    emails = context.args[0].split(",")
    count = 0
    for email in emails:
        if "|" in email:
            data["email_stock"].append(email.strip())
            count += 1
    save_data(data)
    await update.message.reply_text(f"✅ EMAIL STOCK UPDATED!\n📤 Added: {count}\n📦 Total: {len(data['email_stock'])}", parse_mode='Markdown')

async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    await update.message.reply_text(
        f"📊 STOCK STATUS\n\n📦 Available: {len(data['email_stock'])}\n✅ Used: {len(data['used_emails'])}\n⏳ Pending: {len(data['pending'])}\n👥 Total Users: {len(data['users'])}\n📌 Status: {'✅ Active' if data['email_stock'] else '⚠️ Empty'}",
        parse_mode='Markdown'
    )

async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Usage: /approve [user_id] [amount]", parse_mode='Markdown')
        return
    
    target_id = context.args[0]
    amount = int(context.args[1])
    if target_id not in data["users"]:
        await update.message.reply_text(f"❌ User `{target_id}` not found.", parse_mode='Markdown')
        return
    
    data["users"][target_id]["balance"] -= amount
    for req in data.get("withdraw_requests", []):
        if req["user_id"] == target_id and req["amount"] == amount and req["status"] == "pending":
            req["status"] = "approved"
            req["approved_at"] = str(datetime.now())
            break
    save_data(data)
    
    await context.bot.send_message(int(target_id), f"💰 WITHDRAWAL APPROVED!\n✅ Amount: ₹{amount}\n📌 Status: Approved", parse_mode='Markdown')
    await update.message.reply_text(f"✅ Withdrawal approved for user `{target_id}`", parse_mode='Markdown')

# ============ ERROR HANDLER ============
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

# ============ MAIN ============
def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new_command))
    app.add_handler(CommandHandler("skip2fa", skip2fa_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CommandHandler("setupi", setupi_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("help", help_command))
    
    app.add_handler(CommandHandler("upload", upload_command))
    app.add_handler(CommandHandler("stock", stock_command))
    app.add_handler(CommandHandler("approve", approve_command))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_screenshot))
    app.add_error_handler(error_handler)
    
    print("🚀 Gmail 2FA Verification Bot started!")
    print(f"👑 Owner ID: {OWNER_ID}")
    print(f"📦 Stock: {len(data['email_stock'])}")
    
    # SIMPLE - BINA ASYNCIO KE
    app.run_polling()

if __name__ == "__main__":
    main()
