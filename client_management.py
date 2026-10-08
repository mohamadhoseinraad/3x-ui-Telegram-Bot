"""
Client management functions for VPN Telegram Bot - Multi-server support
"""
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

import config

logger = logging.getLogger(__name__)

async def show_all_clients(query, context, page=0, admin_ids=config.ADMIN_IDS):
    """Show all clients across all servers with pagination."""
    if admin_ids is None:
        admin_ids = []

    if query.from_user.id not in admin_ids:
        await query.answer("دسترسی رد شد.")
        return

    from xui_api import get_all_clients_multi_server
    from db_utils import get_all_db_configs

    xui_clients = get_all_clients_multi_server() or []
    db_clients = get_all_db_configs() or []

    all_clients = {}

    for client in xui_clients:
        client_id = client.get('id')
        if client_id:
            client['in_xui'] = True
            all_clients[client_id] = client

    for client in db_clients:
        client_id = client.get('client_id')
        if client_id:
            if client_id in all_clients:
                all_clients[client_id].update({
                    'user_id': client.get('user_id'),
                    'username': client.get('username'),
                    'first_name': client.get('first_name'),
                    'db_total_gb': client.get('total_gb'),
                    'created_at': client.get('created_at'),
                    'server_id': client.get('server_id'),
                    'in_db': True
                })
            else:
                all_clients[client_id] = {
                    'id': client_id,
                    'email': client.get('email'),
                    'total_gb': client.get('total_gb'),
                    'is_active': client.get('is_active', False),
                    'user_id': client.get('user_id'),
                    'username': client.get('username'),
                    'first_name': client.get('first_name'),
                    'created_at': client.get('created_at'),
                    'server_id': client.get('server_id'),
                    'in_db': True,
                    'in_xui': False
                }

    clients = list(all_clients.values())

    if not clients:
        await query.edit_message_text(
            "⚠️ هیچ کلاینتی یافت نشد.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_menu")]])
        )
        return

    def get_sort_key(client):
        created_at = client.get('created_at')
        if created_at:
            if isinstance(created_at, str):
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    return int(dt.timestamp())
                except (ValueError, TypeError):
                    return 0
            return created_at

        expiry_time = client.get('expiryTime', 0)
        if isinstance(expiry_time, str):
            try:
                return int(expiry_time)
            except (ValueError, TypeError):
                return 0
        return expiry_time or 0

    clients.sort(key=get_sort_key, reverse=True)

    items_per_page = 5
    total_pages = (len(clients) + items_per_page - 1) // items_per_page
    page = max(0, min(page, total_pages - 1))
    start_index = page * items_per_page
    end_index = min(start_index + items_per_page, len(clients))
    current_page_clients = clients[start_index:end_index]

    message = f"👨‍💻 لیست کلاینت ها (صفحه {page + 1} از {total_pages}):\n"
    message += f"📊 تعداد کل: {len(clients)} | 🔌 پنل: {len(xui_clients)} | 💾 دیتابیس: {len(db_clients)}\n\n"

    for i, client in enumerate(current_page_clients, start=1):
        email = client.get('email', 'بدون نام')
        total_gb = client.get('total_gb', client.get('totalGB', 0) / (1024 ** 3))
        remaining_gb = client.get('remaining_gb', 0)
        expiry_date = client.get('expiry_date', 'نامشخص')
        active_status = "✅ فعال" if client.get('is_active', client.get('enable', False)) else "❌ غیرفعال"
        remaining_time = client.get('remaining_time_display', 'نامشخص')
        server_name = client.get('server_name', client.get('server_id', '?'))

        location = ""
        if client.get('in_xui', False) and client.get('in_db', False):
            location = "📱💾"
        elif client.get('in_xui', False):
            location = "📱"
        elif client.get('in_db', False):
            location = "💾"

        user_info = ""
        if client.get('username') or client.get('first_name'):
            user_info = f"👤 کاربر: {client.get('first_name', '')} (@{client.get('username', '')})\n   "

        message += (
            f"{i}. {location} {email}\n"
            f"   🖥️ سرور: {server_name}\n"
            f"   {user_info}📊 حجم: {remaining_gb}/{total_gb} GB\n"
            f"   ⏳ زمان: {remaining_time} (تا {expiry_date})\n"
            f"   🔌 وضعیت: {active_status}\n"
            f"   🆔 شناسه: {client.get('id', 'نامشخص')[:8]}...\n\n"
        )

    keyboard = []

    for i, client in enumerate(current_page_clients, start=1):
        client_id = client.get('id', '')
        email = client.get('email', 'بدون نام')
        if client_id:
            keyboard.append([
                InlineKeyboardButton(f"❌ حذف {email}", callback_data=f"admin_delete_client_{client_id}")
            ])

    navigation_buttons = []
    if page > 0:
        navigation_buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"admin_clients_page_{page - 1}"))
    if page < total_pages - 1:
        navigation_buttons.append(InlineKeyboardButton("➡️ بعدی", callback_data=f"admin_clients_page_{page + 1}"))
    if navigation_buttons:
        keyboard.append(navigation_buttons)

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_menu")])

    context.user_data['client_list'] = clients

    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def confirm_delete_client(query, client_id, admin_ids=config.ADMIN_IDS):
    """Ask for confirmation before deleting a client."""
    if admin_ids is None:
        admin_ids = []

    if query.from_user.id not in admin_ids:
        await query.answer("دسترسی رد شد.")
        return

    await query.edit_message_text(
        f"⚠️ آیا از حذف کلاینت با شناسه {client_id[:8]}... اطمینان دارید؟\n"
        "این عملیات غیرقابل بازگشت است!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ بله، حذف شود", callback_data=f"admin_confirm_delete_{client_id}")],
            [InlineKeyboardButton("❌ خیر، انصراف", callback_data=f"admin_cancel_delete_{client_id}")]
        ])
    )


async def delete_client_handler(query, client_id, admin_ids=config.ADMIN_IDS):
    """Handle client deletion after confirmation - searches all servers."""
    if admin_ids is None:
        admin_ids = []

    if query.from_user.id not in admin_ids:
        await query.answer("دسترسی رد شد.")
        return

    from xui_api import _legacy_delete_client  # searches all servers
    from db_utils import delete_config_by_client_id

    success, error_message = _legacy_delete_client(client_id)

    if success:
        db_success = delete_config_by_client_id(client_id)

        message = f"✅ کلاینت با شناسه {client_id[:8]}... با موفقیت حذف شد."
        if db_success:
            message += "\n✅ اطلاعات مربوطه از دیتابیس نیز حذف شد."
        else:
            message += "\n⚠️ حذف از دیتابیس ناموفق بود."

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت به لیست کلاینت ها", callback_data="admin_manage_clients")],
                [InlineKeyboardButton("🔙 بازگشت به منوی ادمین", callback_data="admin_menu")]
            ])
        )
    else:
        await query.edit_message_text(
            f"❌ خطا در حذف کلاینت:\n{error_message}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 تلاش مجدد", callback_data=f"admin_delete_client_{client_id}")],
                [InlineKeyboardButton("🔙 بازگشت به لیست کلاینت ها", callback_data="admin_manage_clients")],
                [InlineKeyboardButton("🔙 بازگشت به منوی ادمین", callback_data="admin_menu")]
            ])
        )


async def cancel_delete_client(query, client_id, context, admin_ids=config.ADMIN_IDS):
    """Cancel client deletion and return to client list."""
    if admin_ids is None:
        admin_ids = []

    if query.from_user.id not in admin_ids:
        await query.answer("دسترسی رد شد.")
        return

    await show_all_clients(query, context, admin_ids=admin_ids)