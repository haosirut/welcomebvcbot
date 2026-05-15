"""
Telegram Welcome Bot для BVC — БЕЗ внешних зависимостей.
Webhook-режим для Amvera.

Переменные окружения:
  BOT_TOKEN       — токен Telegram бота (от @BotFather)
  MANAGER_CHAT_ID — ID чата куда отправлять заявки (с минусом для групп)
  WEBHOOK_URL     — публичный URL приложения в Amvera (напр. https://welcomebvcbot-valeriinovikov.amvera.io)
  PORT            — порт (по умолчанию 8080)
"""

import os
import json
import ssl
import logging
import threading
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
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

logger.info(f"BOT_TOKEN: {'set' if BOT_TOKEN else 'NOT SET'}")
logger.info(f"MANAGER_CHAT_ID: {MANAGER_CHAT_ID or 'NOT SET'}")
logger.info(f"WEBHOOK_URL: {WEBHOOK_URL or 'NOT SET'}")
logger.info(f"PORT: {PORT}")

# -----------------------------------------------------------------------------
# SSL context
# -----------------------------------------------------------------------------
ssl_ctx = ssl.create_default_context()

# -----------------------------------------------------------------------------
# Telegram API helper (pure stdlib)
# -----------------------------------------------------------------------------
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def tg_request(method, params=None):
    """Вызов Telegram Bot API через urllib."""
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
                logger.error(f"TG API error ({method}): {result}")
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


def get_user_step(chat_id):
    """Получить текущий шаг пользователя."""
    return user_data.get(chat_id, {}).get("step")


def set_user_step(chat_id, step):
    """Установить шаг пользователя."""
    if chat_id not in user_data:
        user_data[chat_id] = {}
    user_data[chat_id]["step"] = step


def save_user_info(chat_id, from_user):
    """Сохранить информацию о пользователе Telegram."""
    if chat_id not in user_data:
        user_data[chat_id] = {}
    user_data[chat_id]["user_info"] = {
        "id": from_user.get("id"),
        "username": from_user.get("username", ""),
        "full_name": from_user.get("first_name", "")
        + (" " + from_user.get("last_name", "") if from_user.get("last_name") else ""),
    }


# -----------------------------------------------------------------------------
# Message handlers
# -----------------------------------------------------------------------------
def handle_start(chat_id):
    """Приветствие + выбор типа тренировки."""
    user_data[chat_id] = {"step": STEP_TRAINING}
    logger.info(f"User {chat_id} started registration")

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


def handle_training_callback(chat_id, callback_data, callback_id):
    """Обработка выбора типа тренировки."""
    if get_user_step(chat_id) != STEP_TRAINING:
        answer_callback_query(callback_id, "Начните заново: /start")
        return

    training_map = {
        "training_adult": "Взрослые",
        "training_kids": "Детские",
    }
    training_type = training_map.get(callback_data, "Неизвестно")
    user_data[chat_id]["training_type"] = training_type
    set_user_step(chat_id, STEP_BRANCH)
    logger.info(f"User {chat_id} chose training: {training_type}")

    kb = inline_keyboard([
        [("Песок", "branch_pesok"), ("Спот", "branch_spot")]
    ])
    send_message(
        chat_id,
        f"Вы выбрали: {training_type}\n\nВ каком филиале?",
        reply_markup=kb,
    )
    answer_callback_query(callback_id)


def handle_branch_callback(chat_id, callback_data, callback_id):
    """Обработка выбора филиала."""
    if get_user_step(chat_id) != STEP_BRANCH:
        answer_callback_query(callback_id, "Начните заново: /start")
        return

    branch_map = {
        "branch_pesok": "Песок",
        "branch_spot": "Спот",
    }
    branch = branch_map.get(callback_data, "Неизвестно")
    user_data[chat_id]["branch"] = branch
    set_user_step(chat_id, STEP_NAME)
    logger.info(f"User {chat_id} chose branch: {branch}")

    send_message(
        chat_id,
        f"Филиал: {branch}\n\nКак вас зовут?",
    )
    answer_callback_query(callback_id)


def handle_name_text(chat_id, text):
    """Обработка ввода имени."""
    if get_user_step(chat_id) != STEP_NAME:
        return False

    name = text.strip()
    if len(name) < 1 or len(name) > 100:
        send_message(chat_id, "Пожалуйста, введите корректное имя.")
        return True

    user_data[chat_id]["name"] = name
    set_user_step(chat_id, STEP_PHONE)
    logger.info(f"User {chat_id} entered name: {name}")

    send_message(
        chat_id,
        "Укажите номер телефона для связи",
        reply_markup=reply_keyboard_contact(),
    )
    return True


def handle_phone_text(chat_id, text):
    """Обработка номера телефона введённого вручную."""
    if get_user_step(chat_id) != STEP_PHONE:
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
    if get_user_step(chat_id) != STEP_PHONE:
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
            result = send_message(int(MANAGER_CHAT_ID), manager_text)
            if result and result.get("ok"):
                logger.info(f"SUCCESS: Registration info sent to manager chat {MANAGER_CHAT_ID}")
            else:
                logger.error(f"ERROR: Failed to send to manager chat {MANAGER_CHAT_ID}. "
                           f"API response: {result}")
        except Exception as e:
            logger.error(f"ERROR: Exception sending to manager chat {MANAGER_CHAT_ID}: {e}")
    else:
        logger.warning("MANAGER_CHAT_ID not set, skipping manager notification")

    # Помечаем шаг как завершённый
    user_data[chat_id] = {"step": None}
    logger.info(f"User {chat_id} completed registration")


# -----------------------------------------------------------------------------
# Update processor
# -----------------------------------------------------------------------------
def process_update(update):
    """Обработка одного обновления от Telegram."""
    # Callback query (нажатие на inline кнопку)
    if "callback_query" in update:
        cb = update["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        callback_data = cb.get("data", "")
        callback_id = cb.get("id", "")

        save_user_info(chat_id, cb.get("from", {}))

        if callback_data.startswith("training_"):
            handle_training_callback(chat_id, callback_data, callback_id)
        elif callback_data.startswith("branch_"):
            handle_branch_callback(chat_id, callback_data, callback_id)
        else:
            answer_callback_query(callback_id, "Начните заново: /start")
        return

    # Обычное сообщение
    if "message" not in update:
        return

    msg = update["message"]
    chat_id = msg["chat"]["id"]

    save_user_info(chat_id, msg.get("from", {}))

    # Контакт (номер телефона через кнопку)
    if "contact" in msg:
        contact = msg["contact"]
        phone = contact.get("phone_number", "")
        logger.info(f"User {chat_id} shared contact (phone)")
        handle_phone_contact(chat_id, phone)
        return

    text = msg.get("text", "")

    # Команда /start
    if text and text.startswith("/start"):
        logger.info(f"User {chat_id} sent /start")
        handle_start(chat_id)
        return

    # Шаг ввода имени
    if handle_name_text(chat_id, text):
        return

    # Шаг ввода телефона
    if handle_phone_text(chat_id, text):
        return

    # Если пользователь не в процессе регистрации — подсказка
    if get_user_step(chat_id) is None:
        send_message(
            chat_id,
            "Чтобы записаться на тренировку, нажмите /start",
        )


# -----------------------------------------------------------------------------
# Multithreaded Webhook HTTP server
# -----------------------------------------------------------------------------
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Многопоточный HTTP сервер для обработки webhook."""
    daemon_threads = True
    allow_reuse_address = True


class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP сервер: принимает webhook от Telegram + health check от Amvera."""

    def do_GET(self):
        """Health check для Amvera."""
        logger.info(f"GET {self.path}")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_POST(self):
        """Получение обновлений от Telegram webhook."""
        logger.info(f"POST {self.path}")

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # Telegram отправляет webhook на любой путь — обрабатываем везде
        try:
            update = json.loads(body.decode("utf-8"))
            update_summary = json.dumps(update, ensure_ascii=False)[:300]
            logger.info(f"Webhook update: {update_summary}")

            # Обрабатываем в отдельном потоке, чтобы быстро ответить 200
            threading.Thread(
                target=process_update,
                args=(update,),
                daemon=True,
            ).start()
        except Exception as e:
            logger.error(f"Error parsing webhook update: {e}")

        # Telegram ожидает 200 OK — отвечаем быстро
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, format, *args):
        pass  # заглушаем стандартные логи HTTP, используем свои


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is not set!")
        exit(1)

    # Сначала удаляем старый вебхук
    logger.info("Deleting old webhook...")
    tg_request("deleteWebhook", {"drop_pending_updates": False})

    # Устанавливаем webhook
    if WEBHOOK_URL:
        # Amvera маршрутизирует /webhook на порт 8080
        webhook_endpoint = f"{WEBHOOK_URL.rstrip('/')}/webhook"
        logger.info(f"Setting webhook to: {webhook_endpoint}")

        result = tg_request("setWebhook", {
            "url": webhook_endpoint,
            "allowed_updates": ["message", "callback_query"],
        })
        if result and result.get("ok"):
            logger.info(f"Webhook set successfully to: {webhook_endpoint}")
            # Проверяем информацию о вебхуке
            info = tg_request("getWebhookInfo")
            if info and info.get("ok"):
                wh_info = info.get("result", {})
                logger.info(f"Webhook info: url={wh_info.get('url')}, "
                           f"has_custom_cert={wh_info.get('has_custom_certificate')}, "
                           f"pending_update_count={wh_info.get('pending_update_count')}, "
                           f"last_error_date={wh_info.get('last_error_date')}, "
                           f"last_error_message={wh_info.get('last_error_message')}")
        else:
            logger.error(f"Failed to set webhook: {result}")
    else:
        logger.error(
            "WEBHOOK_URL not set! Bot will not receive updates. "
            "Set WEBHOOK_URL to your Amvera app public URL."
        )

    # Запускаем многопоточный HTTP сервер
    server = ThreadingHTTPServer(("0.0.0.0", PORT), WebhookHandler)
    logger.info(f"Webhook server started on 0.0.0.0:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        server.shutdown()
