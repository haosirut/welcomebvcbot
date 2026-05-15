"""
Telegram Welcome Bot для BVC — БЕЗ внешних зависимостей.
Webhook-режим для Amvera (polling не работает из-за блокировки исходящих long-polling).

Переменные окружения:
  BOT_TOKEN       — токен Telegram бота (от @BotFather)
  MANAGER_CHAT_ID — ID чата куда отправлять заявки (с минусом для групп)
  WEBHOOK_URL     — публичный URL приложения в Amvera (напр. https://welcomebvcbot.amvera.io)
  PORT            — порт (по умолчанию 8080)
"""

import os
import json
import ssl
import logging
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# -----------------------------------------------------------------------------
# Environment Variables
# -----------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORT = int(os.getenv("PORT", "8080"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("welcomebvcbot")

# -----------------------------------------------------------------------------
# SSL context для исходящих запросов к Telegram API
# -----------------------------------------------------------------------------
ssl_ctx = ssl.create_default_context()

# -----------------------------------------------------------------------------
# Telegram API helper (pure stdlib)
# -----------------------------------------------------------------------------
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def tg_request(method, params=None):
    """Вызов Telegram Bot API через urllib (короткие запросы, не long-polling)."""
    url = f"{API_BASE}/{method}"
    data = None
    if params:
        data = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if not result.get("ok"):
                logger.error(f"TG API error: {result}")
            return result
    except Exception as e:
        logger.error(f"TG API request failed ({method}): {e}")
        return None


def send_message(chat_id, text, reply_markup=None):
    """Отправка сообщения."""
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return tg_request("sendMessage", params)


def edit_message_text(chat_id, message_id, text, reply_markup=None):
    """Редактирование сообщения."""
    params = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        params["reply_markup"] = reply_markup
    return tg_request("editMessageText", params)


def answer_callback_query(callback_query_id, text=None):
    """Ответ на callback query."""
    params = {"callback_query_id": callback_query_id}
    if text:
        params["text"] = text
    return tg_request("answerCallbackQuery", params)


# -----------------------------------------------------------------------------
# Keyboard builders
# -----------------------------------------------------------------------------
def inline_keyboard(buttons):
    """buttons: list of list of (text, callback_data) tuples"""
    kb = {
        "inline_keyboard": [
            [{"text": t, "callback_data": d} for t, d in row]
            for row in buttons
        ]
    }
    return json.dumps(kb)


def reply_keyboard_contact():
    """Клавиатура с кнопкой «Поделиться номером»."""
    kb = {
        "keyboard": [[{"text": "Поделиться номером телефона", "request_contact": True}]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }
    return json.dumps(kb)


def reply_keyboard_remove():
    """Убрать клавиатуру."""
    kb = {"remove_keyboard": True}
    return json.dumps(kb)


# -----------------------------------------------------------------------------
# User state management
# -----------------------------------------------------------------------------
STEP_TRAINING = "training"
STEP_BRANCH = "branch"
STEP_NAME = "name"
STEP_PHONE = "phone"

user_data = {}


# -----------------------------------------------------------------------------
# Message handlers
# -----------------------------------------------------------------------------
def handle_start(chat_id):
    """Приветствие + выбор типа тренировки."""
    user_data[chat_id] = {"step": STEP_TRAINING}

    kb = inline_keyboard([
        [("Взрослые", "training_adult"), ("Детские", "training_kids")]
    ])
    send_message(
        chat_id,
        "Привет! 👋 Добро пожаловать!\n\n"
        "Давайте запишем вас на тренировку. "
        "Какие тренировки вас интересуют?",
        reply_markup=kb,
    )


def handle_training_callback(chat_id, message_id, callback_data, callback_id):
    """Обработка выбора типа тренировки."""
    if chat_id not in user_data or user_data[chat_id].get("step") != STEP_TRAINING:
        answer_callback_query(callback_id, "Начните заново: /start")
        return

    training_map = {
        "training_adult": "Взрослые",
        "training_kids": "Детские",
    }
    training_type = training_map.get(callback_data, "Неизвестно")
    user_data[chat_id]["training_type"] = training_type
    user_data[chat_id]["step"] = STEP_BRANCH

    kb = inline_keyboard([
        [("Песок", "branch_pesok"), ("Спот", "branch_spot")]
    ])
    # Отправляем новое сообщение, не редактируем старое — история сохраняется
    send_message(
        chat_id,
        f"Вы выбрали: {training_type}\n\nВ каком филиале?",
        reply_markup=kb,
    )
    answer_callback_query(callback_id)


def handle_branch_callback(chat_id, message_id, callback_data, callback_id):
    """Обработка выбора филиала."""
    if chat_id not in user_data or user_data[chat_id].get("step") != STEP_BRANCH:
        answer_callback_query(callback_id, "Начните заново: /start")
        return

    branch_map = {
        "branch_pesok": "Песок",
        "branch_spot": "Спот",
    }
    branch = branch_map.get(callback_data, "Неизвестно")
    user_data[chat_id]["branch"] = branch
    user_data[chat_id]["step"] = STEP_NAME

    # Отправляем новое сообщение, не редактируем старое — история сохраняется
    send_message(
        chat_id,
        f"Филиал: {branch}\n\nКак вас зовут?",
    )
    answer_callback_query(callback_id)


def handle_name_text(chat_id, text):
    """Обработка ввода имени."""
    if chat_id not in user_data or user_data[chat_id].get("step") != STEP_NAME:
        return False

    name = text.strip()
    if len(name) < 1 or len(name) > 100:
        send_message(chat_id, "Пожалуйста, введите корректное имя.")
        return True

    user_data[chat_id]["name"] = name
    user_data[chat_id]["step"] = STEP_PHONE

    send_message(
        chat_id,
        "Укажите номер телефона для связи",
        reply_markup=reply_keyboard_contact(),
    )
    return True


def handle_phone_text(chat_id, text):
    """Обработка номера телефона введённого вручную."""
    if chat_id not in user_data or user_data[chat_id].get("step") != STEP_PHONE:
        return False

    phone = text.strip()
    cleaned = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    if len(cleaned) < 8:
        send_message(
            chat_id,
            "Похоже, номер слишком короткий. "
            "Пожалуйста, введите корректный номер телефона.",
        )
        return True

    finish_registration(chat_id, cleaned)
    return True


def handle_phone_contact(chat_id, phone):
    """Обработка номера телефона через кнопку «Поделиться»."""
    if chat_id not in user_data or user_data[chat_id].get("step") != STEP_PHONE:
        return False

    finish_registration(chat_id, phone)
    return True


def finish_registration(chat_id, phone):
    """Завершение регистрации."""
    data = user_data.get(chat_id, {})
    training_type = data.get("training_type", "Не указано")
    branch = data.get("branch", "Не указано")
    name = data.get("name", "Не указано")
    user_info = data.get("user_info", {})

    # Сообщение пользователю
    send_message(
        chat_id,
        "✅ Вы успешно записались!\n\n"
        "С вами скоро свяжутся для подтверждения записи. "
        "Спасибо за обращение!\n\n"
        "Если хотите записаться ещё раз — нажмите /start",
        reply_markup=reply_keyboard_remove(),
    )

    # Сообщение менеджерам
    username = user_info.get("username", "")
    tg_username = f"@{username}" if username else "нет username"
    full_name = user_info.get("full_name", "Неизвестно")
    user_id = user_info.get("id", "Неизвестно")

    manager_text = (
        f"📥 Новая запись на тренировку!\n\n"
        f"🏋️ Тип тренировки: {training_type}\n"
        f"🏢 Филиал: {branch}\n"
        f"👤 Имя: {name}\n"
        f"📞 Телефон: {phone}\n\n"
        f"💬 Telegram: {tg_username}\n"
        f"📋 Имя в TG: {full_name}\n"
        f"🆔 ID: {user_id}\n"
        f"🕐 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )

    if MANAGER_CHAT_ID:
        try:
            send_message(int(MANAGER_CHAT_ID), manager_text)
            logger.info(f"Registration info sent to manager chat {MANAGER_CHAT_ID}")
        except Exception as e:
            logger.error(f"Failed to send message to manager chat: {e}")
    else:
        logger.warning("MANAGER_CHAT_ID not set, skipping manager notification")

    # Помечаем шаг как завершённый, но не удаляем данные полностью
    # чтобы подсказка о /start работала корректно
    user_data[chat_id] = {"step": None}


# -----------------------------------------------------------------------------
# Update processor
# -----------------------------------------------------------------------------
def process_update(update):
    """Обработка одного обновления от Telegram."""
    # Callback query (нажатие на inline кнопку)
    if "callback_query" in update:
        cb = update["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        message_id = cb["message"]["message_id"]
        callback_data = cb.get("data", "")
        callback_id = cb.get("id", "")

        if chat_id not in user_data:
            user_data[chat_id] = {}
        from_user = cb.get("from", {})
        user_data[chat_id]["user_info"] = {
            "id": from_user.get("id"),
            "username": from_user.get("username", ""),
            "full_name": from_user.get("first_name", "")
            + (" " + from_user.get("last_name", "") if from_user.get("last_name") else ""),
        }

        if callback_data.startswith("training_"):
            handle_training_callback(chat_id, message_id, callback_data, callback_id)
        elif callback_data.startswith("branch_"):
            handle_branch_callback(chat_id, message_id, callback_data, callback_id)
        return

    # Обычное сообщение
    if "message" not in update:
        return

    msg = update["message"]
    chat_id = msg["chat"]["id"]

    if chat_id not in user_data:
        user_data[chat_id] = {}
    from_user = msg.get("from", {})
    user_data[chat_id]["user_info"] = {
        "id": from_user.get("id"),
        "username": from_user.get("username", ""),
        "full_name": from_user.get("first_name", "")
        + (" " + from_user.get("last_name", "") if from_user.get("last_name") else ""),
    }

    # Контакт (номер телефона через кнопку)
    if "contact" in msg:
        contact = msg["contact"]
        phone = contact.get("phone_number", "")
        handle_phone_contact(chat_id, phone)
        return

    text = msg.get("text", "")

    if text.startswith("/start"):
        handle_start(chat_id)
        return

    if handle_name_text(chat_id, text):
        return

    if handle_phone_text(chat_id, text):
        return

    # Если пользователь не в процессе регистрации — подсказка
    if chat_id not in user_data or user_data[chat_id].get("step") is None:
        send_message(
            chat_id,
            "Чтобы записаться на тренировку, нажмите /start",
        )


# -----------------------------------------------------------------------------
# Webhook HTTP server
# -----------------------------------------------------------------------------
class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP сервер: принимает webhook от Telegram + health check от Amvera."""

    def do_GET(self):
        """Health check для Amvera."""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_POST(self):
        """Получение обновлений от Telegram webhook."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            update = json.loads(body.decode("utf-8"))
            logger.info(f"Received update: {json.dumps(update, ensure_ascii=False)[:200]}")
            process_update(update)
        except Exception as e:
            logger.error(f"Error processing webhook update: {e}")

        # Telegram ожидает 200 OK
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, format, *args):
        logger.info(f"HTTP: {format % args}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is not set!")
        exit(1)

    # Устанавливаем webhook
    if WEBHOOK_URL:
        webhook_endpoint = f"{WEBHOOK_URL.rstrip('/')}/webhook"
        result = tg_request("setWebhook", {
            "url": webhook_endpoint,
            "allowed_updates": json.dumps(["message", "callback_query"]),
        })
        if result and result.get("ok"):
            logger.info(f"Webhook set to: {webhook_endpoint}")
        else:
            logger.error(f"Failed to set webhook: {result}")
    else:
        logger.warning(
            "WEBHOOK_URL not set! Bot will not receive updates via webhook. "
            "Set WEBHOOK_URL to your Amvera app public URL."
        )

    # Запускаем HTTP сервер
    server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    logger.info(f"Webhook server started on 0.0.0.0:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()
