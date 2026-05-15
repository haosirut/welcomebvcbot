import os
import logging
import threading
from datetime import datetime

import telebot
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from aiohttp import web

# -----------------------------------------------------------------------------
# Environment Variables
# -----------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID")
PORT = int(os.getenv("PORT", "8080"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("welcomebvcbot")

# -----------------------------------------------------------------------------
# Bot instance
# -----------------------------------------------------------------------------
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# Хранилище данных пользователя (в памяти)
user_data = {}

# Шаги диалога
STEP_TRAINING = "training"
STEP_BRANCH = "branch"
STEP_NAME = "name"
STEP_PHONE = "phone"


# -----------------------------------------------------------------------------
# /start
# -----------------------------------------------------------------------------
@bot.message_handler(commands=["start"])
def cmd_start(message):
    chat_id = message.chat.id
    user_data[chat_id] = {"step": STEP_TRAINING}

    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("Взрослые", callback_data="training_adult"),
        InlineKeyboardButton("Детские", callback_data="training_kids"),
    )

    bot.send_message(
        chat_id,
        "Привет! 👋 Добро пожаловать!\n\n"
        "Давайте запишем вас на тренировку. "
        "Какие тренировки вас интересуют?",
        reply_markup=keyboard,
    )


# -----------------------------------------------------------------------------
# Выбор типа тренировки
# -----------------------------------------------------------------------------
@bot.callback_query_handler(func=lambda call: call.data.startswith("training_"))
def process_training_type(call):
    chat_id = call.message.chat.id

    # Проверяем, что пользователь на нужном шаге
    if chat_id not in user_data or user_data[chat_id].get("step") != STEP_TRAINING:
        bot.answer_callback_query(call.id, "Начните заново: /start")
        return

    training_map = {
        "training_adult": "Взрослые",
        "training_kids": "Детские",
    }
    training_type = training_map.get(call.data, "Неизвестно")
    user_data[chat_id]["training_type"] = training_type
    user_data[chat_id]["step"] = STEP_BRANCH

    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("Песок", callback_data="branch_pesok"),
        InlineKeyboardButton("Спот", callback_data="branch_spot"),
    )

    bot.edit_message_text(
        f"Вы выбрали: {training_type}\n\nВ каком филиале?",
        chat_id=chat_id,
        message_id=call.message.message_id,
        reply_markup=keyboard,
    )
    bot.answer_callback_query(call.id)


# -----------------------------------------------------------------------------
# Выбор филиала
# -----------------------------------------------------------------------------
@bot.callback_query_handler(func=lambda call: call.data.startswith("branch_"))
def process_branch(call):
    chat_id = call.message.chat.id

    if chat_id not in user_data or user_data[chat_id].get("step") != STEP_BRANCH:
        bot.answer_callback_query(call.id, "Начните заново: /start")
        return

    branch_map = {
        "branch_pesok": "Песок",
        "branch_spot": "Спорт",
    }
    branch = branch_map.get(call.data, "Неизвестно")
    user_data[chat_id]["branch"] = branch
    user_data[chat_id]["step"] = STEP_NAME

    bot.edit_message_text(
        f"Филиал: {branch}\n\nКак вас зовут?",
        chat_id=chat_id,
        message_id=call.message.message_id,
    )
    bot.answer_callback_query(call.id)


# -----------------------------------------------------------------------------
# Ввод имени
# -----------------------------------------------------------------------------
@bot.message_handler(func=lambda message: _is_step(message, STEP_NAME))
def process_name(message):
    chat_id = message.chat.id
    name = message.text.strip()

    if len(name) < 1 or len(name) > 100:
        bot.send_message(chat_id, "Пожалуйста, введите корректное имя.")
        return

    user_data[chat_id]["name"] = name
    user_data[chat_id]["step"] = STEP_PHONE

    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add(KeyboardButton("Поделиться номером телефона", request_contact=True))

    bot.send_message(
        chat_id,
        "Укажите номер телефона для связи",
        reply_markup=keyboard,
    )


# -----------------------------------------------------------------------------
# Номер телефона через кнопку «Поделиться»
# -----------------------------------------------------------------------------
@bot.message_handler(content_types=["contact"])
def process_phone_contact(message):
    chat_id = message.chat.id

    if chat_id not in user_data or user_data[chat_id].get("step") != STEP_PHONE:
        return

    phone = message.contact.phone_number
    _finish_registration(message, phone)


# -----------------------------------------------------------------------------
# Номер телефона текстом
# -----------------------------------------------------------------------------
@bot.message_handler(func=lambda message: _is_step(message, STEP_PHONE))
def process_phone_text(message):
    chat_id = message.chat.id
    phone = message.text.strip()

    cleaned = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    if len(cleaned) < 8:
        bot.send_message(
            chat_id,
            "Похоже, номер слишком короткий. "
            "Пожалуйста, введите корректный номер телефона.",
        )
        return

    _finish_registration(message, cleaned)


# -----------------------------------------------------------------------------
# Завершение регистрации
# -----------------------------------------------------------------------------
def _finish_registration(message, phone):
    chat_id = message.chat.id
    data = user_data.get(chat_id, {})

    training_type = data.get("training_type", "Не указано")
    branch = data.get("branch", "Не указано")
    name = data.get("name", "Не указано")

    user = message.from_user
    username = f"@{user.username}" if user.username else "нет username"
    full_name = user.full_name
    user_id = user.id

    # Сообщение пользователю
    bot.send_message(
        chat_id,
        "✅ Вы успешно записались!\n\n"
        "С вами скоро свяжутся для подтверждения записи. "
        "Спасибо за обращение!",
        reply_markup=ReplyKeyboardRemove(),
    )

    # Сообщение менеджерам
    manager_text = (
        f"📥 Новая запись на тренировку!\n\n"
        f"🏋️ Тип тренировки: {training_type}\n"
        f"🏢 Филиал: {branch}\n"
        f"👤 Имя: {name}\n"
        f"📞 Телефон: {phone}\n\n"
        f"💬 Telegram: {username}\n"
        f"📋 Имя в TG: {full_name}\n"
        f"🆔 ID: {user_id}\n"
        f"🕐 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )

    if MANAGER_CHAT_ID:
        try:
            bot.send_message(chat_id=MANAGER_CHAT_ID, text=manager_text)
            logger.info(f"Registration info sent to manager chat {MANAGER_CHAT_ID}")
        except Exception as e:
            logger.error(f"Failed to send message to manager chat: {e}")
    else:
        logger.warning("MANAGER_CHAT_ID not set, skipping manager notification")

    # Очищаем данные
    user_data.pop(chat_id, None)


# -----------------------------------------------------------------------------
# Helper
# -----------------------------------------------------------------------------
def _is_step(message, step):
    chat_id = message.chat.id
    return chat_id in user_data and user_data[chat_id].get("step") == step


# -----------------------------------------------------------------------------
# Health check web server (для Amvera)
# -----------------------------------------------------------------------------
async def health_handler(request):
    return web.Response(text="OK")


def run_web_server():
    app = web.Application()
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    loop.run_until_complete(site.start())
    logger.info(f"Health check server started on 0.0.0.0:{PORT}")
    loop.run_forever()


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is not set!")
        exit(1)

    # Запускаем веб-сервер health check в отдельном потоке
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    # Запускаем бота (polling)
    logger.info("Starting Telegram bot (polling mode)...")
    bot.infinity_polling()
