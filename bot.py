import os
import asyncio
import logging
from datetime import datetime

from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Contact,
)
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# -----------------------------------------------------------------------------
# Environment Variables
# -----------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID")
PORT = int(os.getenv("PORT", "8080"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # опционально, для webhook режима

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("welcomebvcbot")

# -----------------------------------------------------------------------------
# FSM States
# -----------------------------------------------------------------------------
class Registration(StatesGroup):
    training_type = State()
    branch = State()
    name = State()
    phone = State()


# -----------------------------------------------------------------------------
# Router & Handlers
# -----------------------------------------------------------------------------
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Приветствие нового пользователя и выбор типа тренировки."""
    await state.clear()

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Взрослые", callback_data="training_adult"),
                InlineKeyboardButton(text="Детские", callback_data="training_kids"),
            ]
        ]
    )

    await message.answer(
        "Привет! 👋 Добро пожаловать!\n\n"
        "Давайте запишем вас на тренировку. "
        "Какие тренировки вас интересуют?",
        reply_markup=keyboard,
    )
    await state.set_state(Registration.training_type)


@router.callback_query(Registration.training_type, F.data.startswith("training_"))
async def process_training_type(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора типа тренировки, переход к выбору филиала."""
    training_map = {
        "training_adult": "Взрослые",
        "training_kids": "Детские",
    }
    training_type = training_map.get(callback.data, "Неизвестно")
    await state.update_data(training_type=training_type)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Песок", callback_data="branch_pesok"),
                InlineKeyboardButton(text="Спот", callback_data="branch_spot"),
            ]
        ]
    )

    await callback.message.edit_text(
        f"Вы выбрали: {training_type}\n\nВ каком филиале?",
        reply_markup=keyboard,
    )
    await state.set_state(Registration.branch)
    await callback.answer()


@router.callback_query(Registration.branch, F.data.startswith("branch_"))
async def process_branch(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора филиала, запрос имени."""
    branch_map = {
        "branch_pesok": "Песок",
        "branch_spot": "Спот",
    }
    branch = branch_map.get(callback.data, "Неизвестно")
    await state.update_data(branch=branch)

    await callback.message.edit_text(
        f"Филиал: {branch}\n\nКак вас зовут?",
        reply_markup=None,
    )
    await state.set_state(Registration.name)
    await callback.answer()


@router.message(Registration.name, F.text)
async def process_name(message: Message, state: FSMContext):
    """Обработка ввода имени, запрос номера телефона."""
    name = message.text.strip()
    if len(name) < 1 or len(name) > 100:
        await message.answer("Пожалуйста, введите корректное имя.")
        return

    await state.update_data(name=name)

    # Клавиатура с кнопкой "Поделиться номером" + ручной ввод
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Поделиться номером телефона", request_contact=True)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    await message.answer(
        "Укажите номер телефона для связи",
        reply_markup=keyboard,
    )
    await state.set_state(Registration.phone)


@router.message(Registration.phone, F.contact)
async def process_phone_contact(message: Message, state: FSMContext):
    """Обработка номера телефона через кнопку 'Поделиться номером'."""
    phone = message.contact.phone_number
    await _finish_registration(message, state, phone)


@router.message(Registration.phone, F.text)
async def process_phone_text(message: Message, state: FSMContext):
    """Обработка номера телефона введённого вручную."""
    phone = message.text.strip()
    # Простая валидация — убираем пробелы и дефисы
    cleaned = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    if len(cleaned) < 8:
        await message.answer(
            "Похоже, номер слишком короткий. "
            "Пожалуйста, введите корректный номер телефона."
        )
        return

    await _finish_registration(message, state, cleaned)


async def _finish_registration(message: Message, state: FSMContext, phone: str):
    """Завершение регистрации: показ сообщения об успехе + отправка менеджерам."""
    data = await state.get_data()
    training_type = data.get("training_type", "Не указано")
    branch = data.get("branch", "Не указано")
    name = data.get("name", "Не указано")

    # Информация о пользователе Telegram
    user = message.from_user
    username = f"@{user.username}" if user.username else "нет username"
    full_name = user.full_name
    user_id = user.id

    # --- Сообщение пользователю ---
    await message.answer(
        "✅ Вы успешно записались!\n\n"
        "С вами скоро свяжутся для подтверждения записи. "
        "Спасибо за обращение!",
        reply_markup=ReplyKeyboardRemove(),
    )

    # --- Сообщение менеджерам ---
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

    bot = message.bot
    if MANAGER_CHAT_ID:
        try:
            await bot.send_message(chat_id=MANAGER_CHAT_ID, text=manager_text)
            logger.info(f"Registration info sent to manager chat {MANAGER_CHAT_ID}")
        except Exception as e:
            logger.error(f"Failed to send message to manager chat: {e}")
    else:
        logger.warning("MANAGER_CHAT_ID not set, skipping manager notification")

    await state.clear()


# Обработка некорректных сообщений в состоянии ожидания имени
@router.message(Registration.name)
async def process_name_invalid(message: Message):
    await message.answer("Пожалуйста, введите ваше имя текстом.")


# Обработка некорректных сообщений в состоянии ожидания телефона
@router.message(Registration.phone)
async def process_phone_invalid(message: Message):
    await message.answer(
        "Пожалуйста, отправьте номер телефона — "
        "воспользуйтесь кнопкой «Поделиться номером телефона» или введите номер вручную."
    )


# -----------------------------------------------------------------------------
# Application entry point
# -----------------------------------------------------------------------------
async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is not set!")
        return

    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)

    # Запуск aiohttp для health check (требуется Amvera)
    app = web.Application()

    async def health(request):
        return web.Response(text="OK")

    app.router.add_get("/health", health)

    # Запускаем polling бота и веб-сервер параллельно
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health check server started on 0.0.0.0:{PORT}")

    logger.info("Starting Telegram bot (polling mode)...")
    try:
        # Удаляем вебхук на всякий случай
        await bot.delete_webhook(drop_pending_updates=True)
        # Запускаем polling
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await dp.stop_polling()
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
