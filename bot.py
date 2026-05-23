"""
VPN Telegram Bot
A bot for managing VPN services through Telegram
"""
import logging
import random
import string
import time
import uuid
from datetime import timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from telegram import MenuButtonCommands


from client_management import show_all_clients, confirm_delete_client, delete_client_handler, cancel_delete_client
# Import our modules
from config import BOT_TOKEN, ADMIN_IDS, IPDOMAIN, PORT, HOST, SNI, DB_FILE, ALLOW_BUY, payment_msg
from database import (
    init_db, get_or_create_user, get_user_configs, save_new_config,
    update_config_active_status, get_client_id_by_email, check_trial_usage,
    save_payment_request, get_all_users,
    create_ticket, add_ticket_message, close_ticket, update_ticket_status, verify_ticket_access,
    get_formatted_user_tickets, get_ticket_conversation, get_payment_info, update_payment_status,
    get_pending_payments, update_config_total_gb, get_all_configs_with_users,
    get_service_policy
)
from menus import (
    VPN_PLANS, get_main_menu_keyboard, get_free_trial_keyboard, get_vpn_plans_keyboard,
    get_back_to_main_button, get_configs_keyboard, get_config_status_keyboard,
    get_admin_approval_keyboard, get_support_keyboard, get_admin_menu_keyboard, get_vpn_extend_plans_keyboard,
    get_buy_allow_keyboard, get_extend_all_client_day
)
from xui_api import get_client_status, create_client, extend_client
from notification_service import start_notification_service

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def random_suffix(length=6):
    """Generate a random suffix for email addresses"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def generate_vless_link(client_id, email):
    """Generate a VLESS link for the client"""
    return (
        f"vless://{client_id}@{IPDOMAIN}:{PORT}"
        f"?type=ws&path=%2F&host={HOST}&security=tls&fp=firefox&alpn=h3%2Ch2%2Chttp%2F1.1&sni={SNI}"
        f"#{email}"
    )


def _parse_plan_gb(plan_name):
    """Extract the plan size in GB from a plan name."""
    import re

    if plan_name is None:
        return 0.0

    if isinstance(plan_name, (int, float)):
        return float(plan_name)

    text = str(plan_name)
    if not text:
        return 0.0

    persian_digits = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    arabic_digits = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    text = text.translate(persian_digits).translate(arabic_digits)

    match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:گیگابایت|گیگاب|گیگ|GB|G)\b', text, re.IGNORECASE)
    if match:
        return float(match.group(1).replace(',', '.'))

    match = re.search(r'(\d+(?:[.,]\d+)?)', text)
    if match:
        return float(match.group(1).replace(',', '.'))

    return 0.0

# Command handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command"""
    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name, user.last_name)

    await update.message.reply_text(
        "گزینه مورد نظر را انتخاب کنید\n "
        "این سرویس به تازگی راه اندازی شده است و درحال حاضر صرفا جهت تست قرار داده شده . "
        "امیدوارم کیفیت لطفا نظرات خود را با ما در میان بگذارید.",
        reply_markup=get_main_menu_keyboard()
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /admin command"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("شما اجازه دسترسی به این بخش را ندارید.")
        return

    await update.message.reply_text(
        "🔐 پنل مدیریت\n\nلطفا یک گزینه را انتخاب کنید:",
        reply_markup=get_admin_menu_keyboard()
    )

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /broadcast command"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("دسترسی رد شد.")
        return

    if not context.args:
        await update.message.reply_text("لطفاً پیام خود را بعد از دستور /broadcast وارد کنید.")
        return

    message = ' '.join(context.args)
    users = get_all_users()

    success = 0
    failed = 0

    for user_id in users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📢 اطلاعیه:\n\n{message}"
            )
            success += 1
        except Exception as e:
            logger.error(f"Error sending broadcast to {user_id}: {e}")
            failed += 1

    await update.message.reply_text(
        f"پیام به {success} کاربر ارسال شد.\n"
        f"ارسال به {failed} کاربر ناموفق بود."
    )

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /support command"""
    await update.message.reply_text(
        "🔧 بخش پشتیبانی\n\nلطفا یکی از گزینه ها را انتخاب کنید:",
        reply_markup=get_support_keyboard()
    )

# Callback query handlers
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback queries"""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    # Main menu options
    if data == "check_status":
        await handle_check_status(query, user_id)
    elif data == "buy_service":
        await handle_buy_service(query, user_id)
    elif data == "buy_service_gift":
        await handle_buy_service_gift(query, user_id)
    elif data == "support":
        await handle_support(query, context)
    elif data == "back_to_main":
        await show_main_menu(query)

    # VPN status and configuration
    elif data == "refresh_status":
        await refresh_config_status(query, context)
    elif data == "extend_config":
        await show_extend_options(query, context)
    elif data.startswith("extend_gb_"):
        await handle_extend_selection(query, data, user_id, context)
    elif data.startswith("status_"):
        await handle_show_status(query, data[7:], user_id)
    elif data.startswith("gb_"):
        await handle_plan_selection(query, data, user_id, context)
    elif data.startswith("free_"):
        await handle_free_trial(query, data, user_id, context)

    # Admin functions
    elif data.startswith("admin_"):
        await handle_admin_callback(query, data, user_id, context)
    elif data.startswith("approve_") or data.startswith("reject_"):
        await handle_admin_decision(query, data, user_id, context)
    elif data.startswith("view_receipt_"):
        await handle_view_receipt(query, data, user_id, context)

    # Support system
    elif data.startswith("support_"):
        await handle_support_callback(query, data, user_id, context)

    else:
        logger.warning(f"Unhandled callback data: {data}")
        await query.edit_message_text("گزینه نامعت��ر.")

async def show_main_menu(query):
    """Show the main menu"""
    await query.edit_message_text(
        "پلن مورد نظر خود را انتخاب کنید:",
        reply_markup=get_main_menu_keyboard()
    )

# Handler functions for various actions
async def handle_check_status(query, user_id):
    """Handle the check status option"""
    configs = get_user_configs(user_id)

    if not configs:
        keyboard = get_back_to_main_button()
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("سرویسی برای شما یافت نشد.", reply_markup=reply_markup)
        return

    reply_markup = get_configs_keyboard(configs)
    await query.edit_message_text("لطفا سرویس مورد نظر را انتخاب کنید:", reply_markup=reply_markup)

async def handle_show_status(query, email, user_id):
    """Show the status of a specific configuration"""
    client_id = get_client_id_by_email(email, user_id)

    if not client_id:
        await query.edit_message_text("خطا در دریافت اطلاعات سر��یس." ,
                                      reply_markup=InlineKeyboardMarkup(get_back_to_main_button()))
        return

    status = get_client_status(email)
    if not status:
        await query.edit_message_text("خطا در دریافت اطلاعات سرویس.", reply_markup=InlineKeyboardMarkup(get_back_to_main_button()))
        return

    update_config_active_status(email, user_id, status['is_active'])

    vless_link = generate_vless_link(client_id, email)

    status_icon = "✅" if status['is_active'] else "❌"
    message = (
        f"{status_icon} وضعیت سرویس:\n"
        f"📧 نام: `{email}`\n"
        f"📊 حجم باقیمانده: {status['remaining_gb']} گیگابایت از {status['total_gb']} گیگابایت\n"
        f"⏳ زمان باقیمانده: {status['remaining_time_display']} (تا {status['expiry_date']})\n"
        f"🔌 وضعیت: {'فعال' if status['is_active'] else 'غیرفعال'}\n\n"
        f"🔗 لینک کانفیگ:\n`{vless_link}`"
    )

    reply_markup = get_config_status_keyboard()
    await query.edit_message_text(message, parse_mode="Markdown", reply_markup=reply_markup)

async def handle_buy_service(query, user_id):
    """Handle the buy service option"""
    policy = get_service_policy()
    keyboard = get_vpn_plans_keyboard(policy) + get_back_to_main_button()
    reply_markup = InlineKeyboardMarkup(keyboard)
    max_config_gb = policy.get("max_config_gb", 0)
    max_config_label = "نامحدود" if not max_config_gb else f"{int(max_config_gb) if float(max_config_gb).is_integer() else max_config_gb}GB"

    await query.edit_message_text(f"لطفاً پلن مورد نظر خود را انتخاب کنید.\n هر کانفیگ حداکثر به مقدار {max_config_label} قابل شارژ است", reply_markup=reply_markup)

async def handle_buy_service_gift(query, user_id):
    """Handle the buy gift service option"""
    keyboard = get_free_trial_keyboard() + get_back_to_main_button()
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("لطفاً پلن مورد نظر خود را انتخاب کنید.", reply_markup=reply_markup)

async def handle_support(query, context: ContextTypes.DEFAULT_TYPE):
    """Handle the support option"""
    await query.edit_message_text(
        "🔧 بخش پشتیبانی\n\nلطفا یکی از گزینه ها را انتخاب کنید:",
        reply_markup=get_support_keyboard()
    )

async def handle_plan_selection(query, plan_data, user_id, context: ContextTypes.DEFAULT_TYPE):
    """Handle the selection of a VPN plan"""
    import config
    if not config.ALLOW_BUY :
        reply_markup = InlineKeyboardMarkup(get_back_to_main_button())
        await query.edit_message_text("فروش فعال نیست.", reply_markup=reply_markup)
        return
    plan = VPN_PLANS.get(plan_data)
    if not plan:
        reply_markup = InlineKeyboardMarkup(get_back_to_main_button())
        await query.edit_message_text("پلن نامعتبر است.", reply_markup=reply_markup)
        return

    policy = get_service_policy()
    if policy['max_config_gb'] > 0 and float(plan.get('gb', 0)) > policy['max_config_gb']:
        reply_markup = InlineKeyboardMarkup(get_back_to_main_button())
        await query.edit_message_text(
            f"❗ حجم این پلن از محدودیت {policy['max_config_gb']}GB بیشتر است.",
            reply_markup=reply_markup,
        )
        return

    context.user_data['selected_plan'] = plan
    keyboard = get_back_to_main_button()
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"لطفاً فیش پرداخت برای پلن {plan['name']} را ارسال کنید.\n\n"
        "در صورت وقوع شرایط خاص در کشور کانفیگ شما تمدید خواهد شد\n"
        "پس از تأیید ادمین، کانفیگ برای شما ارسال خواهد شد.\n"
        + payment_msg,
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def handle_free_trial(query, data, user_id, context: ContextTypes.DEFAULT_TYPE):
    """Handle the free trial option"""
    keyboard = get_back_to_main_button()
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Determine trial size
    if data == "free_1gb":
        gb_amount = 1
    elif data == "free_5gb":
        gb_amount = 5
    else:
        await query.edit_message_text("گزینه نامعتبر.", reply_markup=reply_markup)
        return

    # Check if user has already used this trial
    if check_trial_usage(user_id, gb_amount):
        await query.edit_message_text(
            f"❗ شما قبلاً از هدیه {gb_amount}GB استفاده کرده‌اید.",
            reply_markup=reply_markup
        )
        return

    # Prepare client parameters
    client_id = str(uuid.uuid4())
    suffix = random_suffix()
    user = query.from_user

    email = f"{user.username or 'user'}_{suffix}@free"
    if len(email) > 50:
        email = f"u{user_id}_{suffix}@free_{gb_amount}_gb"

    total_bytes = gb_amount * 1024 ** 3
    policy = get_service_policy()

    if policy['max_config_gb'] > 0 and gb_amount > policy['max_config_gb']:
        await query.edit_message_text(
            f"❗ حجم این هدیه از محدودیت {policy['max_config_gb']}GB بیشتر است.",
            reply_markup=reply_markup
        )
        return

    # Set expiry time based on trial type
    expiry_time = policy['global_expiry_time_ms']

    try:
        client_id, error = create_client(email, total_bytes, expiry_time)
        if error:
            raise Exception(error)

        save_new_config(user_id, email, client_id, gb_amount)
        vless_link = generate_vless_link(client_id, email)

        await query.edit_message_text(
            f"🎉 هدیه شما آماده شد!\n\n🔗 لینک کانفیگ:\n`{vless_link}`",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Free trial error: {e}")
        await query.edit_message_text(
            "⚠️ خطا در ایجاد هدیه. لطفاً دوباره تلاش کنید.",
            reply_markup=reply_markup
        )

async def handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle receipt photos sent by users"""
    keyboard = get_back_to_main_button()
    if 'selected_plan' not in context.user_data:
        await update.message.reply_text("لطفاً ابتدا یک پلن انتخاب کنید.", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if not update.message.photo:
        await update.message.reply_text("لطفاً یک تصویر از فیش پرداخت ارسال کنید.")
        return

    photo = update.message.photo[-1]
    plan = context.user_data['selected_plan']
    user_id = update.effective_user.id

    # Get additional info if this is an extension
    is_extension = plan.get('is_extension', False)
    extension_email = plan.get('email', None) if is_extension else None

    # Save payment request
    payment_id = save_payment_request(user_id, plan['name'], photo.file_id)

    # Notify admins
    for admin_id in ADMIN_IDS:
        try:
            # Include extension info in the caption if applicable
            extension_info = f"\nتمدید برای: {extension_email}" if is_extension else ""

            await context.bot.send_photo(
                chat_id=admin_id,
                photo=photo.file_id,
                caption=f"درخواست پرداخت جدید:\n"
                        f"کاربر: {update.effective_user.full_name}\n"
                        f"پلن: {plan['name']}{extension_info}\n"
                        f"شناسه پرداخت: {payment_id}",
                reply_markup=get_admin_approval_keyboard(payment_id)
            )
        except Exception as e:
            logger.error(f"Error notifying admin {admin_id}: {e}")

    # Send confirmation message based on request type
    if is_extension:
        message = "فیش پرداخت شما برای تمدید سرویس دریافت شد و در انتظار تأیید ادمین است.\n" \
                 "پس از تأیید، سرویس شما تمدید خواهد شد."
    else:
        message = "فیش پرداخت شما دریافت شد و در انتظار تأیید ادمین است.\n" \
                 "پس از تأیید، کانفیگ برای شما ارسال خواهد شد."

    await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard))

    # Store extension details in the database or in a persistent context
    if is_extension:
        import json
        if not hasattr(context.bot_data, 'extension_requests'):
            context.bot_data['extension_requests'] = {}

        # Store extension details with payment_id as key
        context.bot_data['extension_requests'][str(payment_id)] = {
            'email': extension_email,
            'gb_amount': plan['gb'],
            'client_id': context.user_data.get('extension_details', {}).get('client_id', '')
        }

    # Clean up user data
    del context.user_data['selected_plan']
    if 'extension_details' in context.user_data:
        del context.user_data['extension_details']

# Admin handling functions
async def handle_admin_extend_all(query, context, data):

    if query.from_user.id not in ADMIN_IDS:
        await query.answer("دسترسی رد شد.")
        return
    if data == "admin_extend_all":
        await query.edit_message_text("تعداد روز را انتخاب کنید" , reply_markup= get_extend_all_client_day())
    else:
        day = int (data.replace("admin_extend_all_",""))

        configs = get_all_configs_with_users()
        c = 0
        for config in configs:
            config_id = config['client_id']
            user_id = config['user_id']
            email = config['email']
            success, err = extend_client(email, config_id,0,timedelta(days=day))
            sucDB = update_config_total_gb(email, user_id, 0)
            if sucDB and success:
                c = c + 1
        key =  InlineKeyboardMarkup([[InlineKeyboardButton("برگشت", callback_data="admin_menu")]])
        await query.edit_message_text(f"{c} کلاینت افزایش داده شدند", reply_markup=key)


async def handle_admin_callback(query, data, user_id, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin panel callbacks"""
    if user_id not in ADMIN_IDS:
        await query.answer("دسترسی رد شد.")
        return

    if data == "admin_pending":
        await show_pending_approvals(query)
    elif data == "admin_users":
        await show_all_users(query)
    elif data == "admin_tickets":
        await show_all_tickets(query)
    elif data == "admin_manage_clients":
        await show_all_clients(query, context)
    elif data == "admin_broadcast":
        context.user_data['awaiting_broadcast'] = True
        await query.edit_message_text(
            "لطفا پیام خود را برای ارسال به همه کاربران وارد کنید:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ انصراف", callback_data="admin_menu")]
            ])
        )
    elif data.startswith("admin_view_ticket_"):
        ticket_id = int(data.split("_")[3])
        await show_ticket_messages_admin(query, ticket_id)
    elif data == "admin_menu":
        await show_admin_menu(query)
    # Client management callbacks
    elif data.startswith("admin_clients_page_"):
        page = int(data.split("_")[-1])
        await show_all_clients(query, context, page)
    elif data.startswith("admin_delete_client_"):
        client_id = data.split("_")[3]
        await confirm_delete_client(query, client_id)
    elif data.startswith("admin_confirm_delete_"):
        client_id = data.split("_")[3]
        await delete_client_handler(query, client_id)
    elif data.startswith("admin_cancel_delete_"):
        client_id = data.split("_")[3]
        await cancel_delete_client(query, client_id, context)
    elif data.startswith("admin_buy_allow"):
        await show_buy_allow(query, data)
    elif data.startswith("admin_extend_all"):
        await handle_admin_extend_all(query, context , data)

async def show_admin_menu(query):
    """Show the admin menu"""
    await query.edit_message_text(
        "🔐 پنل مدیریت\n\nلطفا یک گزینه را انتخاب کنید:",
        reply_markup=get_admin_menu_keyboard()
    )
async def show_buy_allow(query , data):
    """Show the admin menu"""
    import config
    if data.replace("admin_buy_allow","") == "":
        status_icon = "است ✅" if config.ALLOW_BUY else "نیست ❌"
        await query.edit_message_text(
            "فروش فعال "+status_icon+"\n\n",
            reply_markup=get_buy_allow_keyboard()
        )
    elif data.replace("admin_buy_allow_","") == "yes":
        config.ALLOW_BUY = True
        status_icon = "است ✅" if config.ALLOW_BUY else "نیست ❌"
        await query.edit_message_text(
            "فروش فعال " + status_icon + "\n\n",
            reply_markup=get_buy_allow_keyboard()
        )
    else:
        config.ALLOW_BUY = False
        status_icon = "است ✅" if config.ALLOW_BUY else "نیست ❌"
        await query.edit_message_text(
            "فروش فعال " + status_icon + "\n\n",
            reply_markup=get_buy_allow_keyboard()
        )
async def show_pending_approvals(query, context: ContextTypes.DEFAULT_TYPE = None):
    """Show all pending payment approvals"""
    # Use the database function instead of direct SQL queries
    from database import get_pending_payments

    pending_payments = get_pending_payments()


    if not pending_payments:
        await query.edit_message_text(
            "هیچ درخواست در انتظار تأییدی وجود ندارد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_menu")]
            ])
        )
        return

    # Store receipt file IDs in context.user_data if context is provided
    if context and not hasattr(context.bot_data, 'receipt_file_ids'):
        context.bot_data['receipt_file_ids'] = {}

    message = "درخواست‌های در انتظار تأیید:\n\n"
    keyboard = []

    for payment in pending_payments:
        payment_id, user_id, plan, first_name, username, receipt_file_id = payment
        user_display = f"{first_name} (@{username})" if username else f"{first_name} (بدون یوزرنیم)"

        # Store the file_id in context for later retrieval if context is provided
        if context:
            context.bot_data['receipt_file_ids'][str(payment_id)] = receipt_file_id

        message += (
            f"🆔 {payment_id}\n"
            f"👤 کاربر: {user_display}\n"
            f"📝 پلن: {plan}\n\n"
        )

        # Add approval/rejection buttons
        keyboard.append([
            InlineKeyboardButton(f"تأیید {payment_id}", callback_data=f"approve_{payment_id}"),
            InlineKeyboardButton(f"رد {payment_id}", callback_data=f"reject_{payment_id}")
        ])

        # Add button to view receipt again with a simpler callback data
        if receipt_file_id:
            keyboard.append([
                InlineKeyboardButton(f"🧾 مشاهده رسید {payment_id}", callback_data=f"view_receipt_{payment_id}")
            ])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_menu")])

    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_all_users(query):
    """Show all users"""
    import sqlite3
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT u.user_id, u.first_name, u.username, COUNT(c.config_id), MAX(c.created_at)
    FROM users u
    LEFT JOIN configs c ON u.user_id = c.user_id
    GROUP BY u.user_id
    ORDER BY MAX(c.created_at) DESC NULLS LAST
    LIMIT 50
    ''')

    users = cursor.fetchall()
    conn.close()

    if not users:
        await query.edit_message_text(
            "هیچ کارب��ی یافت نشد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_menu")]
            ])
        )
        return

    message = "👥 لیست کاربران:\n\n"

    for user in users:
        user_id, first_name, username, config_count, last_created = user
        username_display = f"@{username}" if username else "بدون یوزرنیم"
        last_config = last_created if last_created else "ندارد"

        message += (
            f"👤 {first_name} ({username_display})\n"
            f"🆔 {user_id}\n"
            f"🔢 تعداد کانفیگ: {config_count}\n"
            f"📅 آخرین کانفیگ: {last_config}\n\n"
        )

    # Add navigation
    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_menu")]
        ])
    )

async def show_all_tickets(query):
    """Show all support tickets"""
    import sqlite3
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT t.ticket_id, t.subject, t.status, u.first_name, u.username 
    FROM tickets t
    JOIN users u ON t.user_id = u.user_id
    ORDER BY 
        CASE 
            WHEN t.status = 'open' THEN 1
            WHEN t.status = 'answered' THEN 2
            ELSE 3
        END,
        t.created_at DESC
    LIMIT 50
    ''')

    tickets = cursor.fetchall()
    conn.close()

    if not tickets:
        await query.edit_message_text(
            "هیچ تیکتی وجود ندارد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_menu")]
            ])
        )
        return

    keyboard = []

    for ticket in tickets:
        ticket_id, subject, status, first_name, username = ticket

        # Format subject to fit on button
        if len(subject) > 25:
            subject = subject[:22] + "..."

        # Status icon
        status_icon = "🟢" if status == 'open' else "🟡" if status == 'answered' else "🔴"

        # User info
        user_display = f"{first_name}" + (f" (@{username})" if username else "")

        keyboard.append([
            InlineKeyboardButton(
                f"{status_icon} #{ticket_id}: {subject}",
                callback_data=f"admin_view_ticket_{ticket_id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_menu")])

    await query.edit_message_text(
        "🎫 تیکت‌های پشتیبانی:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_ticket_messages_admin(query, ticket_id):
    """Show messages in a ticket for admin"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    import sqlite3

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Get ticket info
    cursor.execute('''
    SELECT t.subject, t.status, t.user_id, u.first_name, u.username
    FROM tickets t
    JOIN users u ON t.user_id = u.user_id
    WHERE t.ticket_id = ?
    ''', (ticket_id,))

    ticket_info = cursor.fetchone()

    if not ticket_info:
        await query.edit_message_text(
            "تیکت یافت نشد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_tickets")]
            ])
        )
        conn.close()
        return

    subject, status, user_id, first_name, username = ticket_info

    # Get messages
    cursor.execute('''
    SELECT message, is_admin, created_at, sender_id
    FROM ticket_messages 
    WHERE ticket_id = ?
    ORDER BY created_at
    ''', (ticket_id,))

    messages = cursor.fetchall()
    conn.close()

    message_text = f"📋 تیکت #{ticket_id}\n\n"
    message_text += f"📝 موضوع: {subject}\n"
    message_text += f"👤 کاربر: {first_name}" + (f" (@{username})" if username else "") + f"\n"
    message_text += f"📊 وضعیت: {status}\n\n"
    message_text += "📨 پیام ها:\n\n"

    for msg in messages:
        text, is_admin, timestamp, sender_id = msg
        sender = "👤 پشتیبانی" if is_admin else f"👤 کاربر"
        message_text += f"{sender} ({timestamp}):\n{text}\n\n"

    keyboard = [
        [InlineKeyboardButton("✏️ پاسخ به تیکت", callback_data=f"support_reply_{ticket_id}")],
        [InlineKeyboardButton("🔙 بازگشت به تیکت‌ها", callback_data="admin_tickets")],
        [InlineKeyboardButton("🔙 بازگشت به منوی ادمین", callback_data="admin_menu")]
    ]

    if status != "closed":
        keyboard.insert(1, [InlineKeyboardButton("🔒 بستن تیکت", callback_data=f"support_close_{ticket_id}")])

    await query.edit_message_text(
        message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def send_broadcast_message(message, context):
    """Send a broadcast message to all users"""
    users = get_all_users()

    success = 0
    failed = 0

    for user_id in users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📢 اطلاعیه مهم:\n\n{message}"
            )
            success += 1
        except Exception as e:
            logger.error(f"Error sending broadcast to {user_id}: {e}")
            failed += 1

    return success, failed

async def handle_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages for support tickets"""
    user_id = update.effective_user.id
    message_text = update.message.text

    # Check if admin is sending a broadcast message
    if user_id in ADMIN_IDS and context.user_data.get('awaiting_broadcast'):
        del context.user_data['awaiting_broadcast']

        # Send broadcast message to all users
        success, failed = await send_broadcast_message(message_text, context)

        # Notify admin about broadcast result
        await update.message.reply_text(
            f"📢 اطلاعیه به {success} کاربر ارسال شد.\n"
            f"ارسال به {failed} کاربر ناموفق بود."
        )
        return

    # Creating a new ticket
    if 'creating_ticket' in context.user_data:
        # Create new ticket
        ticket_id = create_ticket(user_id, message_text)

        # Add first message as the ticket subject
        add_ticket_message(ticket_id, user_id, message_text, False)

        # Clear the creating_ticket flag
        del context.user_data['creating_ticket']

        # Notify user
        await update.message.reply_text(
            f"✅ تیکت شما با شماره #{ticket_id} ایجاد شد.\n\n"
            "پشتیبانی به زودی پاسخ خواهد داد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📨 مشاهده تیکت", callback_data=f"support_ticket_{ticket_id}")]
            ])
        )

        # Notify admins
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"📩 تیکت جدید #{ticket_id}\n"
                         f"👤 کاربر: {update.effective_user.full_name}\n"
                         f"📝 موضوع: {message_text}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✏️ پاسخ به تیکت", callback_data=f"support_reply_{ticket_id}")],
                        [InlineKeyboardButton("📋 مشاهده تیکت", callback_data=f"admin_view_ticket_{ticket_id}")]
                    ])
                )
            except Exception as e:
                logger.error(f"Error notifying admin: {e}")

    # Replying to a ticket
    elif 'replying_to' in context.user_data:
        ticket_id = context.user_data['replying_to']
        is_admin = user_id in ADMIN_IDS

        # Add the message to the ticket
        add_ticket_message(ticket_id, user_id, message_text, is_admin)

        # Update ticket status if admin replied
        if is_admin:
            update_ticket_status(ticket_id, 'answered')
        else:
            update_ticket_status(ticket_id, 'open')

        # Get ticket owner for notifications
        import sqlite3
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM tickets WHERE ticket_id = ?', (ticket_id,))
        ticket_owner_id = cursor.fetchone()[0]
        conn.close()

        del context.user_data['replying_to']

        # Notify the other party
        if is_admin and ticket_owner_id != user_id:
            try:
                await context.bot.send_message(
                    chat_id=ticket_owner_id,
                    text=f"📬 پاسخ جدید به تیکت شما #{ticket_id}\n\n"
                         f"{message_text}\n\n",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 مشاهده تیکت", callback_data=f"support_ticket_{ticket_id}")]
                    ])
                )
            except Exception as e:
                logger.error(f"Error notifying ticket owner: {e}")
        elif not is_admin:
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"📬 پاسخ کاربر به تیکت #{ticket_id}\n\n"
                             f"{message_text}\n\n",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✏️ پاسخ", callback_data=f"support_reply_{ticket_id}")],
                            [InlineKeyboardButton("📋 مشاهده تیکت", callback_data=f"admin_view_ticket_{ticket_id}")]
                        ])
                    )
                except Exception as e:
                    logger.error(f"Error notifying admin: {e}")

        await update.message.reply_text(
            "✅ پاسخ شما ارسال شد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📨 بازگشت به تیکت", callback_data=f"support_ticket_{ticket_id}")]
            ])
        )
async def create_new_ticket(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['creating_ticket'] = True
    await query.edit_message_text(
        "لطفا موضوع تیکت خود را ارسال کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ انصراف", callback_data="support")]
        ])
    )
async def show_user_tickets(query, user_id):
    """Show all tickets for a user"""
    # Get formatted user tickets from database
    formatted_tickets = get_formatted_user_tickets(user_id)

    # Handle case when user has no tickets
    if not formatted_tickets:
        keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="support")]]
        await query.edit_message_text(
            "شما هیچ تیکتی ندارید.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Build keyboard with status icons and truncated subjects
    keyboard = []
    for ticket in formatted_tickets:
        keyboard.append([
            InlineKeyboardButton(
                f"{ticket['status_icon']} #{ticket['id']}: {ticket['display_subject']}",
                callback_data=f"support_ticket_{ticket['id']}"
            )
        ])

    # Add back button
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="support")])

    # Show the tickets list
    await query.edit_message_text(
        "تیکت های شما:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
async def show_ticket_messages(query, ticket_id, user_id):
    """Show messages in a ticket for user"""
    # Get ticket conversation from database
    ticket_data = get_ticket_conversation(ticket_id, user_id, ADMIN_IDS)

    if not ticket_data['access']:
        await query.answer("دسترسی denied.")
        return

    if 'error' in ticket_data and not ticket_data.get('ticket_info'):
        await query.edit_message_text(
            "تیکت یافت نشد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="support_my_tickets")]
            ])
        )
        return

    # Use the formatted message text from the database function
    message_text = ticket_data['formatted_text']
    status = ticket_data['status']

    # Create keyboard
    keyboard = [
        [InlineKeyboardButton("✏️ پاسخ", callback_data=f"support_reply_{ticket_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="support_my_tickets")]
    ]

    if status != 'closed':
        keyboard.insert(1, [InlineKeyboardButton("🔒 بستن تیکت", callback_data=f"support_close_{ticket_id}")])

    await query.edit_message_text(
        message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
async def close_user_ticket(query, ticket_id, user_id):
    """Close a ticket and show updated ticket view"""
    # Check access permission
    has_access, ticket_owner_id = verify_ticket_access(ticket_id, user_id, ADMIN_IDS)
    if not has_access:
        await query.answer("دسترسی رد شد.")
        return

    # Close the ticket in database
    close_ticket(ticket_id)
    await query.answer("تیکت بسته شد.")

    # Show updated ticket view
    if user_id in ADMIN_IDS:
        await show_ticket_messages_admin(query, ticket_id)
    else:
        await show_ticket_messages(query, ticket_id, user_id)


# Support system handlers
async def handle_support_callback(query, data, user_id, context: ContextTypes.DEFAULT_TYPE):
    """Handle support system callbacks"""
    if data == "support_new":
        await create_new_ticket(query, context)
    elif data == "support_my_tickets":
        await show_user_tickets(query, user_id)
    elif data.startswith("support_ticket_"):
        ticket_id = int(data.split("_")[2])
        await show_ticket_messages(query, ticket_id, user_id)
    elif data.startswith("support_reply_"):
        ticket_id = int(data.split("_")[2])
        context.user_data['replying_to'] = ticket_id
        await query.edit_message_text(
            "لطفا پیام پاسخ خود را ارسال کنید:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ انصراف", callback_data=f"support_ticket_{ticket_id}")]
            ])
        )
    elif data.startswith("support_close_"):
        ticket_id = int(data.split("_")[2])
        await close_user_ticket(query, ticket_id, user_id)

async def handle_admin_decision(query, data, user_id, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin decisions on payment approvals/rejections"""
    if user_id not in ADMIN_IDS:
        await query.answer("دسترسی رد شد.")
        return

    if data.startswith("approve_"):
        payment_id = int(data[8:])
        await approve_payment(query, payment_id, context)
    elif data.startswith("reject_"):
        payment_id = int(data[7:])
        await reject_payment(query, payment_id, context)

async def approve_payment(query, payment_id, context: ContextTypes.DEFAULT_TYPE):
    """Approve a payment and create VPN configuration for the user or extend existing one"""
    # Get payment info including user_id, plan details and username
    payment_info = get_payment_info(payment_id)

    if not payment_info:
        await query.answer("پرداخت یافت نشد یا قبلاً پردازش ��ده است.")
        return

    user_id, plan_name, username = payment_info
    plan_gb = _parse_plan_gb(plan_name)
    policy = get_service_policy()

    # Check if this is an extension request
    is_extension = False
    extension_email = None
    extension_client_id = None

    if 'extension_requests' in context.bot_data and str(payment_id) in context.bot_data['extension_requests']:
        is_extension = True
        extension_data = context.bot_data['extension_requests'][str(payment_id)]
        extension_email = extension_data.get('email')
        extension_client_id = extension_data.get('client_id')
    elif "تمدید" in query.message.caption:
        update_payment_status(payment_id, 'rejected')
        await context.bot.send_message(
            chat_id=user_id,
            text=f"مشکلی پیش آمد مجدد برای تمدید را درخواست کنید!\n\n",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(get_back_to_main_button())
        )
        return
    try:
        if is_extension and extension_email and extension_client_id:
            # Handle extension of existing service

            # Get current status to obtain expiry date
            status = get_client_status(extension_email)
            if not status:
                raise Exception("خطا در دریافت اطلاعات سرویس فعلی")

            if policy['max_config_gb'] > 0 and status['total_gb'] + plan_gb > policy['max_config_gb']:
                raise Exception(f"تمدید از محدودیت {policy['max_config_gb']} گیگابایت بیشتر می‌شود")

            # Extend the client service
            success, error_msg = extend_client(extension_email, extension_client_id, plan_gb, policy['global_expiry_time_ms'])

            if not success:
                raise Exception(f"خطا در تمدید سرویس: {error_msg}")

            # Update the database with the new total GB amount
            db_update_success = update_config_total_gb(extension_email, user_id, plan_gb)
            if not db_update_success:
                logger.warning(f"Failed to update database for config {extension_email} after extension")

            # Update payment status to approved
            update_payment_status(payment_id, 'approved')

            # Generate VLESS link
            vless_link = generate_vless_link(extension_client_id, extension_email)

            # Notify the user about their approved extension
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ درخواست تمدید شما تأیید شد!\n\n"
                     f"حجم {plan_gb} گیگابایت به سرویس شما اضافه شد\n"
                     f"تاریخ انقضا به تاریخ سراسری تنظیم شد\n\n"
                     f"🔗 لینک کانفیگ شما:\n`{vless_link}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(get_back_to_main_button())
            )

            # Clean up extension request data
            del context.bot_data['extension_requests'][str(payment_id)]

            # Confirm successful approval to admin
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"تمدید سرویس {extension_email} با {plan_gb} گیگابایت تأیید شد."
            )
        else:
            # Handle new service creation (existing logic)
            if policy['max_config_gb'] > 0 and plan_gb > policy['max_config_gb']:
                raise Exception(f"پلن از محدودیت {policy['max_config_gb']} گیگابایت بیشتر است")

            # Create unique identifiers for the new client
            client_id = str(uuid.uuid4())
            suffix = random_suffix()

            # Create email identifier for the client
            user_identifier = username if username else str(user_id)
            email = f"{user_identifier}_{suffix}@vpn"

            # Ensure email is not too long
            if len(email) > 50:
                email = f"u{user_id}_{suffix}@vpn"

            # Calculate configuration details
            total_bytes = int(round(plan_gb * (1024 ** 3)))  # Convert GB to bytes
            expiry_time = policy['global_expiry_time_ms']

            # Create the client on the VPN server
            client_id, error = create_client(email, total_bytes, expiry_time)

            if error:
                raise Exception(f"خطا در ایجاد کانفیگ: {error}")

            # Save the new configuration in the database
            save_new_config(user_id, email, client_id, plan_gb)

            # Update payment status to approved
            update_payment_status(payment_id, 'approved')

            # Generate VPN connection link
            vless_link = generate_vless_link(client_id, email)

            # Notify the user about their approved payment and send config
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ پرداخت شما تأیید شد!\n\n"
                     f"🔗 لینک کانفیگ:\n`{vless_link}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(get_back_to_main_button())
            )

            # Confirm successful approval to admin
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"پرداخت {payment_id} تأیید شد و کانفیگ برای کاربر ارسال شد."
            )

    except Exception as e:
        logger.error(f"Error approving payment: {str(e)}")
        # Notify admin about the error
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"خطا در پردازش پرداخت: {str(e)}",
            reply_markup=get_admin_menu_keyboard(),
        )

async def reject_payment(query, payment_id, context: ContextTypes.DEFAULT_TYPE):
    """Reject a payment and notify the user"""
    try:
        # Get user ID and plan information associated with the payment
        payment_info = get_payment_info(payment_id)

        if not payment_info:
            await query.answer("پرداخت یافت نشد یا قبلاً پردازش شده است.")
            return

        user_id, plan_name, username = payment_info

        # Check if this is an extension request
        is_extension = False
        extension_email = None

        if hasattr(context.bot_data, 'extension_requests') and str(payment_id) in context.bot_data['extension_requests']:
            is_extension = True
            extension_data = context.bot_data['extension_requests'][str(payment_id)]
            extension_email = extension_data.get('email')

        # Update payment status to rejected
        update_payment_status(payment_id, 'rejected')

        # Notify user about the rejection with details
        try:
            # Customize message based on request type
            if is_extension:
                message = (f"❌ فیش پرداخت شما برای تمدید سرویس {plan_name} رد شد.\n\n"
                         f"سرویس: {extension_email}\n"
                         f"شناسه پرداخت: {payment_id}\n"
                         f"اگر فکر می‌کنید این اشتباه است یا سوالی دارید، "
                         f"لطفاً با ایجاد یک تیکت پشتیبانی با ما تماس بگیرید.")
            else:
                message = (f"❌ فیش پرداخت شما برای پلن {plan_name} رد شد.\n\n"
                         f"شناسه پرداخت: {payment_id}\n"
                         f"اگر فکر می‌کنید این اشتباه است یا سوالی دارید، "
                         f"لطفاً با ایجاد یک تیکت پشتیبانی با ما تماس بگیرید.")

            await context.bot.send_message(
                chat_id=user_id,
                text=message,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎫 ایجاد تیکت پشتیبانی", callback_data="support_new")]
                ])
            )

            # Log successful notification
            logger.info(f"User {user_id} notified about rejected payment {payment_id}")

            # Confirm rejection to admin with notification status
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"پرداخت {payment_id} رد شد و کاربر با موفقیت مطلع شد."
            )

            # Clean up extension request data if it exists
            if is_extension and hasattr(context.bot_data, 'extension_requests'):
                if str(payment_id) in context.bot_data['extension_requests']:
                    del context.bot_data['extension_requests'][str(payment_id)]

        except Exception as e:
            logger.error(f"Error notifying user {user_id} about rejected payment: {e}")

            # Inform admin about failed notification
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"پرداخت {payment_id} رد شد اما اعلان به کاربر با خطا مواجه شد: {str(e)}"
                ,reply_markup=get_admin_menu_keyboard()
            )

    except Exception as e:
        logger.error(f"Error rejecting payment {payment_id}: {e}")

        # Notify admin about the error
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"خطا در رد پرداخت {payment_id}: {str(e)}",
            reply_markup=get_admin_menu_keyboard(),
        )
async def handle_view_receipt(query, data, user_id, context: ContextTypes.DEFAULT_TYPE):
    """Handle the view receipt button click to show the receipt image to admin"""
    if user_id not in ADMIN_IDS:
        await query.answer("دسترسی رد شد.")
        return

    try:
        # Extract payment ID from callback data
        payment_id = int(data.split('_')[2])

        # Get receipt file ID from database
        import sqlite3
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT receipt_file_id FROM payments WHERE payment_id = ?', (payment_id,))
        result = cursor.fetchone()
        conn.close()

        if not result or not result[0]:
            await query.answer("رسید یافت نشد!")
            return

        file_id = result[0]

        # Send the receipt image
        await context.bot.send_photo(
            chat_id=user_id,
            photo=file_id,
            caption=f"🧾 رسید پرداخت #{payment_id}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأیید", callback_data=f"approve_{payment_id}")],
                [InlineKeyboardButton("❌ رد", callback_data=f"reject_{payment_id}")]
            ])
        )

        # Inform admin that the receipt is sent
        await query.answer("رسید برای شما ارسال شد.")

    except Exception as e:
        logger.error(f"Error viewing receipt: {e}")
        await query.answer("خطا در نمایش رسید!")

async def refresh_config_status(query, context: ContextTypes.DEFAULT_TYPE):
    """Refresh the status of the current config"""
    # Extract email from the previous message
    message_text = query.message.text
    email_lines = [line for line in message_text.split('\n') if '📧 نام:' in line]

    if not email_lines:
        await query.edit_message_text("خطا در بازیابی اطلاعات کانفیگ.", reply_markup=InlineKeyboardMarkup(get_back_to_main_button()))
        return

    # Extract email from the line (format: "📧 نام: `email`")
    email_line = email_lines[0]
    email = email_line.split(':')[1]
    email = email.strip()
    # Get user_id and show status
    user_id = query.from_user.id
    await handle_show_status(query, email, user_id)

async def show_extend_options(query, context: ContextTypes.DEFAULT_TYPE):
    """Show options for extending a config"""
    # Extract email from the previous message
    message_text = query.message.text
    email_lines = [line for line in message_text.split('\n') if '📧 نام:' in line]

    if not email_lines:
        await query.edit_message_text("خطا در بازیابی اطلاعات کانفیگ.", reply_markup=InlineKeyboardMarkup(get_back_to_main_button()))
        return

    # Extract email from the line (format: "📧 نام: `email`")
    email_line = email_lines[0]
    email = email_line.split(':')[1]
    email = email.strip()
    # Store the email in context for the extend handler
    context.user_data['extending_email'] = email

    # Create keyboard with extension options
    keyboard = get_vpn_extend_plans_keyboard(email)

    await query.edit_message_text(
        "لطفاً میزان افزایش حجم را انتخاب کنید:\n\n"
        "بعد از انتخاب، فیش پرداخت خود را ارسال کنید.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_extend_selection(query, data, user_id, context: ContextTypes.DEFAULT_TYPE):
    """Handle the selection of an extension amount"""
    # Extract GB amount from callback data
    gb_amount = int(data.split('_')[2])
    policy = get_service_policy()

    if policy['max_config_gb'] > 0:
        current_total_gb = None

        for config in get_user_configs(user_id):
            if config[1] == context.user_data.get('extending_email'):
                current_total_gb = float(config[3])
                break

        if current_total_gb is not None and current_total_gb + gb_amount > policy['max_config_gb']:
            reply_markup = InlineKeyboardMarkup(get_back_to_main_button())
            await query.edit_message_text(
                f"❗ این تمدید از محدودیت {policy['max_config_gb']}GB بیشتر می‌شود.",
                reply_markup=reply_markup,
            )
            return

    # Check if we have the email in context
    if 'extending_email' not in context.user_data:
        await query.edit_message_text("خطا در بازیابی اطلاعات کانفیگ.", reply_markup=InlineKeyboardMarkup(get_back_to_main_button()))
        return

    email = context.user_data['extending_email']
    email = email.strip()

    # Get client_id for the email
    client_id = get_client_id_by_email(email, user_id)
    if not client_id:
        await query.edit_message_text("خطا در بازیابی اطلاعات کانفیگ.", reply_markup=InlineKeyboardMarkup(get_back_to_main_button()))
        return

    # Store extension details in context for later use
    context.user_data['extension_details'] = {
        'email': email,
        'gb_amount': gb_amount,
        'client_id': client_id,
        'type': 'extension'  # Mark this as an extension request
    }

    # Create a "plan" object similar to what's used for new service purchases
    context.user_data['selected_plan'] = {
        'name': f"تمدید {gb_amount}GB",
        'gb': gb_amount,
        'is_extension': True,
        'email': email  # Store email to identify which config to extend
    }

    keyboard = get_back_to_main_button()
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"لطفاً فیش پرداخت برای تمدید سرویس با {gb_amount} گیگابایت را ارسال کنید.\n\n"
        f"پس از تأیید ادمین، تمدید برای شما اعمال خواهد شد.\n"
        + payment_msg,
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

    # Log the extension request
    logger.info(f"User {user_id} requested extension for {email} by {gb_amount}GB")

async def set_bot_commands(application):
    await application.bot.set_my_commands([
        ("start", "شروع کار با ربات"),
        ("support", "پشتیبانی"),
        ("admin", "پنل مدیریت (برای ادمین)")
    ])

async def set_chat_menu_button(application):
    await application.bot.set_chat_menu_button(
        menu_button=MenuButtonCommands()
    )

def main():
    """Main function to start the bot"""
    # Initialize database
    init_db()

    # Create application
    # application = ApplicationBuilder().token(BOT_TOKEN).build()
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(set_bot_commands).post_init(set_chat_menu_button).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("support", support_command))

    application.add_handler(CallbackQueryHandler(callback_handler))

    application.add_handler(MessageHandler(filters.PHOTO, handle_receipt))
    # Add handler for text messages to process support tickets
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_support_message))

    # Start the notification service
    logger.info("Starting notification service...")
    start_notification_service(application)

    # Start the Bot
    logger.info("Bot started successfully!")
    application.run_polling()

if __name__ == '__main__':
    main()
