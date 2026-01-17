import asyncio
import logging
import json
import os
import re
import time
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject
from aiogram.types import ChatPermissions
from aiogram.enums import ChatMemberStatus

# =================== КОНФИГУРАЦИЯ ===================
TOKEN = "8449402978:AAHzm8IOWivnDUlCMxlngUtAnHEWeH_Ohz0"
ADMIN_IDS = [1007247805]  # Замени на ID админов
REPORT_ADMIN_ID = 1007247805  # Твой ID для получения репортов

# Файлы базы данных
REPUTATION_FILE = "reputation.json"
BANS_FILE = "bans.json"

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# =================== АВТО-СООБЩЕНИЯ КОНФИГ ===================
AUTO_MESSAGES_INTERVAL = 10800  # Секунды между сообщениями (180 сек = 3 минуты)
AUTO_MESSAGES_CHAT_ID = -1003404332093  # ЗАМЕНИ на ID твоего чата/канала

AUTO_MESSAGES = [
    "💡 <b>Напоминание</b>\nОценивайте участников после сделок — это помогает поддерживать честную среду. #notoscam\n\n<code>[АВТОПОСТИНГ]</code>",
    "📊 <b>Статистика сегодня</b>\nПроверьте /stats — посмотрите, как растёт сообщество.\n\n<code>[АВТОПОСТИНГ]</code>",
    "⭐ <b>Как работает репутация?</b>\nПоложительные оценки повышают репутацию, отрицательные — понижают.\n\n<code>[АВТОПОСТИНГ]</code>",
    "👥 <b>Проверяйте профили</b>\nПеред сделкой используйте /rep @username — убедитесь в надёжности.\n\n<code>[АВТОПОСТИНГ]</code>",
    "🔒 <b>Безопасность</b>\nСообщество NOTOSCAM создано для минимизации рисков обмана.\n\n<code>[АВТОПОСТИНГ]</code>",
    "⏰ <b>Кулдаун 1 час</b>\nВы можете ставить репутацию одному пользователю раз в час.\n\n<code>[АВТОПОСТИНГ]</code>",
    "📈 <b>Повышайте рейтинг</b>\nЧем больше положительных оценок, тем выше доверие к вам.\n\n<code>[АВТОПОСТИНГ]</code>"
]

# =================== ФУНКЦИЯ АВТО-СООБЩЕНИЙ ===================

async def send_auto_messages(bot: Bot):
    """Функция для отправки авто-сообщений"""
    logger.info(f"Запущена функция авто-сообщений. Интервал: {AUTO_MESSAGES_INTERVAL} секунд")
    
    # Для теста - отправка каждые 30 секунд
    # AUTO_MESSAGES_INTERVAL = 30  # Раскомментируй для теста
    
    while True:
        try:
            # Ждем указанное время
            await asyncio.sleep(AUTO_MESSAGES_INTERVAL)
            
            # Выбираем случайное сообщение
            message = random.choice(AUTO_MESSAGES)
            
            # Отправляем сообщение
            await bot.send_message(
                chat_id=AUTO_MESSAGES_CHAT_ID,
                text=message,
                parse_mode="HTML"
            )
            
            logger.info(f"[АВТО] Отправлено сообщение в чат {AUTO_MESSAGES_CHAT_ID}")
            
        except Exception as e:
            logger.error(f"[АВТО] Ошибка отправки: {e}")
            # Ждем перед следующей попыткой
            await asyncio.sleep(60)  # 1 минута при ошибке


# =================== БАЗА ДАННЫХ ===================

class ReputationDB:
    """База данных для хранения репутации"""
    
    def __init__(self):
        self.data = self._load_data()
        self.fix_old_data()
    
    def _load_data(self):
        """Загружаем данные из файла"""
        if os.path.exists(REPUTATION_FILE):
            try:
                with open(REPUTATION_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_data(self):
        """Сохраняем данные в файл"""
        with open(REPUTATION_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def get_user(self, user_id: str):
        """Получаем данные пользователя"""
        if user_id not in self.data:
            self.data[user_id] = {
                "plus": 0,      # Положительные оценки
                "minus": 0,     # Отрицательные оценки
                "username": None,
                "first_name": None,
                "last_update": datetime.now().isoformat(),
                "last_given_rep": {}  # Храним время последней выданной репутации
            }
        else:
            # Гарантируем, что у существующих пользователей есть все ключи
            user = self.data[user_id]
            if "plus" not in user:
                user["plus"] = 0
            if "minus" not in user:
                user["minus"] = 0
            if "username" not in user:
                user["username"] = None
            if "first_name" not in user:
                user["first_name"] = None
            if "last_update" not in user:
                user["last_update"] = datetime.now().isoformat()
            if "last_given_rep" not in user:
                user["last_given_rep"] = {}
        
        return self.data[user_id]
    
    def can_give_rep(self, from_user_id: str, to_user_id: str) -> tuple:
        """
        Проверяем, может ли пользователь дать репутацию другому
        Возвращает: (может_дать, оставшееся_время_в_секундах, последнее_время)
        """
        user = self.get_user(from_user_id)
        last_given = user.get("last_given_rep", {})
        
        # Получаем время последней выданной репутации этому пользователю
        last_time = last_given.get(to_user_id, 0)
        current_time = time.time()
        
        # КД 1 час = 3600 секунд
        cooldown = 3600
        
        if last_time == 0:  # Никогда не давал репутацию этому пользователю
            return True, 0, last_time
        
        time_passed = current_time - last_time
        
        if time_passed >= cooldown:
            return True, 0, last_time
        else:
            time_left = cooldown - time_passed
            return False, time_left, last_time
    
    def update_rep_time(self, from_user_id: str, to_user_id: str):
        """Обновляем время последней выданной репутации"""
        user = self.get_user(from_user_id)
        if "last_given_rep" not in user:
            user["last_given_rep"] = {}
        
        user["last_given_rep"][to_user_id] = time.time()
        self._save_data()
    
    def update_user_info(self, user_id: str, username: str = None, first_name: str = None):
        """Обновляем информацию о пользователе"""
        user = self.get_user(user_id)
        if username:
            user["username"] = username
        if first_name:
            user["first_name"] = first_name
        user["last_update"] = datetime.now().isoformat()
        self._save_data()
    
    def add_plus(self, user_id: str):
        """Добавляем +rep"""
        user = self.get_user(user_id)
        current_plus = user.get("plus", 0)
        current_minus = user.get("minus", 0)
        
        user["plus"] = current_plus + 1
        user["last_update"] = datetime.now().isoformat()
        self._save_data()
        
        return user["plus"], user["minus"]
    
    def add_minus(self, user_id: str):
        """Добавляем -rep"""
        user = self.get_user(user_id)
        current_plus = user.get("plus", 0)
        current_minus = user.get("minus", 0)
        
        user["minus"] = current_minus + 1
        user["last_update"] = datetime.now().isoformat()
        self._save_data()
        
        return user["plus"], user["minus"]
    
    def find_by_username(self, username: str):
        """Ищем пользователя по username"""
        username = username.lower().replace('@', '')
        for user_id, user_data in self.data.items():
            if user_data.get("username") and user_data["username"].lower() == username:
                return user_id, user_data
        return None, None
    
    def fix_old_data(self):
        """Исправляем старые данные, если они в неправильном формате"""
        fixed = False
        for user_id, user_data in list(self.data.items()):
            if not isinstance(user_data, dict):
                self.data[user_id] = {
                    "plus": 0,
                    "minus": 0,
                    "username": None,
                    "first_name": None,
                    "last_update": datetime.now().isoformat(),
                    "last_given_rep": {}
                }
                fixed = True
            else:
                if "plus" not in user_data:
                    user_data["plus"] = 0
                    fixed = True
                if "minus" not in user_data:
                    user_data["minus"] = 0
                    fixed = True
                if "username" not in user_data:
                    user_data["username"] = None
                    fixed = True
                if "first_name" not in user_data:
                    user_data["first_name"] = None
                    fixed = True
                if "last_update" not in user_data:
                    user_data["last_update"] = datetime.now().isoformat()
                    fixed = True
                if "last_given_rep" not in user_data:
                    user_data["last_given_rep"] = {}
                    fixed = True
        
        if fixed:
            self._save_data()
            logger.info("Исправлены старые данные в базе репутации")
        
        return fixed


class BansDB:
    """База данных для хранения банов"""
    
    def __init__(self):
        self.data = self._load_data()
    
    def _load_data(self):
        """Загружаем данные из файла"""
        if os.path.exists(BANS_FILE):
            try:
                with open(BANS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_data(self):
        """Сохраняем данные в файл"""
        with open(BANS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def ban_user(self, user_id: str, admin_id: str, reason: str):
        """Бан пользователя"""
        self.data[user_id] = {
            "admin_id": admin_id,
            "reason": reason,
            "banned_at": datetime.now().isoformat()
        }
        self._save_data()
    
    def unban_user(self, user_id: str):
        """Разбан пользователя"""
        if user_id in self.data:
            del self.data[user_id]
            self._save_data()
            return True
        return False
    
    def is_banned(self, user_id: str):
        """Проверяем, забанен ли пользователь"""
        return user_id in self.data, self.data.get(user_id)


# =================== ИНИЦИАЛИЗАЦИЯ ===================

bot = Bot(token=TOKEN)
dp = Dispatcher()
rep_db = ReputationDB()
bans_db = BansDB()



# =================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===================

def is_admin(user_id: int) -> bool:
    """Проверяем, является ли пользователь администратором"""
    return user_id in ADMIN_IDS

async def check_bot_permissions(chat_id: int) -> bool:
    """Проверяем права бота в чате"""
    try:
        bot_member = await bot.get_chat_member(chat_id, (await bot.get_me()).id)
        return bot_member.status == ChatMemberStatus.ADMINISTRATOR
    except:
        return False

def get_reputation_emoji(plus: int, minus: int) -> str:
    """Получаем эмодзи для репутации"""
    total = plus - minus
    
    if total >= 50:
        return "🏆"
    elif total >= 20:
        return "⭐️⭐️⭐️"
    elif total >= 10:
        return "⭐️⭐️"
    elif total >= 5:
        return "⭐️"
    elif total >= 0:
        return "👍"
    elif total >= -5:
        return "⚠️"
    elif total >= -10:
        return "👎"
    else:
        return "💀"

def get_reputation_level(plus: int, minus: int) -> str:
    """Получаем уровень репутации"""
    total = plus - minus
    
    if total >= 50:
        return "ЛЕГЕНДА"
    elif total >= 20:
        return "ЭЛИТА"
    elif total >= 10:
        return "ПРОВЕРЕННЫЙ"
    elif total >= 5:
        return "АКТИВНЫЙ"
    elif total >= 0:
        return "НОВИЧОК"
    elif total >= -5:
        return "ПОДОЗРИТЕЛЬНЫЙ"
    elif total >= -10:
        return "НЕНАДЕЖНЫЙ"
    else:
        return "ИЗГОЙ"

def format_profile(user_id: str, user_data: dict) -> str:
    """Форматируем профиль пользователя"""
    plus = user_data.get("plus", 0)
    minus = user_data.get("minus", 0)
    total = plus - minus
    
    username = user_data.get("username")
    first_name = user_data.get("first_name", "Пользователь")
    
    username_display = f" @{username}" if username else ""
    emoji = get_reputation_emoji(plus, minus)
    level = get_reputation_level(plus, minus)
    
    # Создаем прогресс-бар
    total_votes = plus + minus
    if total_votes > 0:
        plus_percent = int((plus / total_votes) * 100)
        progress_bar = "🟩" * (plus_percent // 10) + "🟥" * ((100 - plus_percent) // 10)
        if len(progress_bar) < 10:
            progress_bar += "⬜" * (10 - len(progress_bar))
    else:
        progress_bar = "⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜"
        plus_percent = 0
    
    return (
        f"👤 <b>Профиль</b>\n"
        f"├ Имя: {first_name}\n"
        f"├ Юзернейм: @{username if username else '—'}\n"
        f"├ ID: <code>{user_id}</code>\n\n"
        f"⭐ <b>Репутация</b>\n"
        f"├ +{plus} положительных\n"
        f"├ -{minus} отрицательных\n"
        f"└ Всего: {plus + minus}\n\n"
        f"<i>#notoscam #профиль</i>"
    )


def format_cooldown_time(from_user_id: str, to_user_id: str) -> str:
    """Форматирует информацию о кулдауне"""
    can_give, time_left, last_time = rep_db.can_give_rep(from_user_id, to_user_id)
    
    if can_give:
        return "✅ Можно дать репутацию"
    else:
        hours = int(time_left // 3600)
        minutes = int((time_left % 3600) // 60)
        seconds = int(time_left % 60)
        
        time_str = ""
        if hours > 0:
            time_str += f"{hours}ч "
        if minutes > 0:
            time_str += f"{minutes}м "
        time_str += f"{seconds}с"
        
        return f"⏳ Кулдаун: {time_str}"


# =================== ОБРАБОТЧИКИ КОМАНД ===================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start"""
    user = message.from_user
    user_id = str(user.id)
    
    rep_db.update_user_info(user_id, user.username, user.first_name)
    
    await message.answer(
        "🔰 <b>Добро пожаловать в NOTOSCAM РЕПУТАЦИИ!</b>\n\n"
        "Я помогу отслеживать репутацию пользователей и предотвращать мошенничество.\n\n"
        "ℹ️ Используйте <b>/help</b> для просмотра всех команд.",
        parse_mode="HTML"
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Команда /help - минималистичная справочная информация"""
    help_text = (
        "🔍 <b>Справка по командам</b>\n"
        "└─ • • • ─┘\n\n"  # Легкий разделитель
        
        "👤 <b>Профиль</b>\n"
        "├ /rep – ваш рейтинг\n"
        "└ /rep @user – профиль другого\n\n"
        
        "⭐ <b>Оценки</b> (ответом на сообщение)\n"
        "├ +rep или +реп – положительная\n"
        "├ -rep или +реп – отрицательная\n"
        "└ ⏱ Кулдаун: 1 час на пользователя\n\n"
        
        "📊 <b>Информация</b>\n"
        "├ /report – жалоба на пользователя\n"
        "├ /start – приветствие\n"
        "├ /stats – статистика\n"
        "└ /help – эта справка"
    )
    
    await message.answer(help_text, parse_mode="HTML")


@dp.message(Command("report"))
async def cmd_report(message: types.Message, command: CommandObject):
    """Команда /report - отправить жалобу на пользователя"""
    
    # Проверяем, отвечает ли на сообщение
    if not message.reply_to_message:
        await message.answer(
            "❗ <b>Как отправить жалобу:</b>\n\n"
            "1. <b>Ответьте на сообщение</b> пользователя, на которого жалуетесь\n"
            "2. Напишите <code>/report причина</code>\n\n"
            "<b>Пример:</b>\n"
            "├ <code>/report спам</code>\n"
            "├ <code>/report мошенничество</code>\n"
            "└ <code>/report оскорбления</code>",
            parse_mode="HTML"
        )
        return
    
    # Получаем пользователя, на которого жалуются
    reported_user = message.reply_to_message.from_user
    reporter_user = message.from_user
    
    # Получаем причину из аргументов
    reason = command.args.strip() if command.args else "Причина не указана"
    
    # Сохраняем информацию о пользователях в базу
    rep_db.update_user_info(str(reported_user.id), reported_user.username, reported_user.first_name)
    rep_db.update_user_info(str(reporter_user.id), reporter_user.username, reporter_user.first_name)
    
    # Формируем информацию о чате
    chat_info = ""
    if message.chat.type in ["group", "supergroup"]:
        chat_info = (
            f"💬 <b>Чат:</b> {message.chat.title}\n"
            f"🆔 ID чата: <code>{message.chat.id}</code>\n"
        )
    
    # Формируем ссылку на сообщение
    message_link = f"https://t.me/c/{str(message.chat.id)[4:]}/{message.reply_to_message.message_id}" if message.chat.type in ["group", "supergroup"] else ""
    
    # Формируем полное сообщение для админа
    report_message = (
        f"🚨 <b>НОВАЯ ЖАЛОБА</b>\n\n"
        
        f"👤 <b>На кого жалуются:</b>\n"
        f"├ Имя: {reported_user.first_name}\n"
        f"├ Юзернейм: @{reported_user.username if reported_user.username else '—'}\n"
        f"└ ID: <code>{reported_user.id}</code>\n\n"
        
        f"👥 <b>Кто пожаловался:</b>\n"
        f"├ Имя: {reporter_user.first_name}\n"
        f"├ Юзернейм: @{reporter_user.username if reporter_user.username else '—'}\n"
        f"└ ID: <code>{reporter_user.id}</code>\n\n"
        
        f"{chat_info}"
        
        f"📝 <b>Причина:</b> {reason}\n\n"
        
        f"⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
    )
    
    # Добавляем ссылку на сообщение, если есть
    if message_link:
        report_message += f"\n🔗 <a href='{message_link}'>Ссылка на сообщение</a>\n"
    
    report_message += "\n#REPORT"
    
    try:
        # Отправляем жалобу админу в ЛС
        await bot.send_message(
            chat_id=REPORT_ADMIN_ID,
            text=report_message,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        
        # Подтверждаем пользователю, что жалоба отправлена
        await message.reply(
            f"✅ <b>Жалоба отправлена администратору</b>\n\n"
            f"👤 На пользователя: {reported_user.first_name}\n"
            f"📝 Причина: {reason}\n\n"
            f"<i>Спасибо за бдительность!</i>",
            parse_mode="HTML"
        )
        
        logger.info(f"Отправлена жалоба от {reporter_user.id} на {reported_user.id}")
        
    except Exception as e:
        logger.error(f"Ошибка отправки жалобы: {e}")
        await message.reply(
            "❌ <b>Не удалось отправить жалобу</b>\n\n"
            "<i>Попробуйте позже или свяжитесь с администратором напрямую.</i>",
            parse_mode="HTML"
        )


@dp.message(Command("rep"))
async def cmd_rep(message: types.Message, command: CommandObject = None):
    """Команда /rep - просмотр репутации"""
    args = command.args if command else None
    
    # Обновляем информацию об отправителе
    user = message.from_user
    rep_db.update_user_info(str(user.id), user.username, user.first_name)
    
    # Определяем целевого пользователя
    target_user_id = None
    target_user_data = None
    
    if not args:
        # Показать свой профиль
        target_user_id = str(user.id)
        target_user_data = rep_db.get_user(target_user_id)
    
    elif args:
        # Поиск по username
        if args.startswith('@'):
            username = args[1:]
            found_id, found_data = rep_db.find_by_username(username)
            if found_id:
                target_user_id = found_id
                target_user_data = found_data
            else:
                await message.answer(f"❌ Пользователь {args} не найден.")
                return
        
        # Поиск по ID
        elif args.isdigit():
            target_user_id = args
            target_user_data = rep_db.get_user(target_user_id)
        
        else:
            await message.answer("❌ Неверный формат. Используйте:\n/rep - ваш профиль\n/rep @username")
            return
    
    # Если ответ на сообщение
    elif message.reply_to_message:
        target_user = message.reply_to_message.from_user
        target_user_id = str(target_user.id)
        rep_db.update_user_info(target_user_id, target_user.username, target_user.first_name)
        target_user_data = rep_db.get_user(target_user_id)
    
    else:
        await message.answer("❌ Неверный формат. Используйте:\n/rep - ваш профиль\n/rep @username")
        return
    
    # Показываем профиль
    if target_user_data:
        profile_text = format_profile(target_user_id, target_user_data)
        
        # Проверяем, забанен ли пользователь
        is_banned, ban_data = bans_db.is_banned(target_user_id)
        if is_banned:
            profile_text += f"\n\n🚫 <b>ЗАБАНЕН</b>\nПричина: {ban_data.get('reason', 'Не указана')}"
        
        await message.answer(profile_text, parse_mode="HTML")
    else:
        await message.answer("❌ Пользователь не найден в базе данных.")


@dp.message(lambda m: m.text and (m.text.lower().startswith('+rep') or m.text.lower().startswith('+реп')))
async def add_plus_rep(message: types.Message):
    """Обработчик +rep / +реп"""
    if not message.reply_to_message:
        await message.reply("❗ <b>Ответьте на сообщение пользователя</b>, которому хотите дать +rep.", parse_mode="HTML")
        return
    
    target_user = message.reply_to_message.from_user
    sender_user = message.from_user
    
    # Проверяем, не самому ли себе
    if target_user.id == sender_user.id:
        await message.reply("❗ <b>Нельзя изменять репутацию самому себе.</b>", parse_mode="HTML")
        return
    
    # Проверяем КД
    can_give, time_left, last_time = rep_db.can_give_rep(str(sender_user.id), str(target_user.id))
    
    if not can_give:
        # Форматируем оставшееся время
        hours = int(time_left // 3600)
        minutes = int((time_left % 3600) // 60)
        seconds = int(time_left % 60)
        
        time_str = ""
        if hours > 0:
            time_str += f"{hours}ч "
        if minutes > 0:
            time_str += f"{minutes}м "
        if seconds > 0 or (hours == 0 and minutes == 0):
            time_str += f"{seconds}с"
        
        await message.reply(
            f"⏳ <b>Кулдаун!</b>\n\n"
            f"Вы уже давали репутацию этому пользователю.\n"
            f"Следующую репутацию можно будет дать через:\n"
            f"<b>{time_str}</b>\n\n"
            f"⏰ Кулдаун: 1 час",
            parse_mode="HTML"
        )
        return
    
    # Обновляем информацию о пользователях
    target_id = str(target_user.id)
    sender_id = str(sender_user.id)
    
    rep_db.update_user_info(target_id, target_user.username, target_user.first_name)
    rep_db.update_user_info(sender_id, sender_user.username, sender_user.first_name)
    
    # Добавляем +rep и обновляем время
    plus, minus = rep_db.add_plus(target_id)
    rep_db.update_rep_time(sender_id, target_id)  # Обновляем время КД
    
    total = plus - minus
    
    # Формируем ответ
    target_name = target_user.first_name or "Пользователь"
    target_username = f" @{target_user.username}" if target_user.username else ""
    emoji = get_reputation_emoji(plus, minus)
    
    await message.reply(
        f"✅ <b>+1 репутация добавлена!</b>\n\n"
        f"👤 Пользователь: <b>{target_name}{target_username}</b>\n"
        f"📊 Новая статистика:\n"
        f"   ✅ +rep: <b>{plus}</b>\n"
        f"   ❌ -rep: <b>{minus}</b>\n"
        f"   📈 Рейтинг: <b>{total}</b>\n"
        f"   {emoji} Уровень: <b>{get_reputation_level(plus, minus)}</b>\n\n"
        f"⏰ Следующую репутацию этому пользователю можно будет дать через 1 час.\n"
        f"#PLUS_REP",
        parse_mode="HTML"
    )


@dp.message(lambda m: m.text and (m.text.lower().startswith('-rep') or m.text.lower().startswith('-реп')))
async def add_minus_rep(message: types.Message):
    """Обработчик -rep / -реп"""
    if not message.reply_to_message:
        await message.reply("❗ <b>Ответьте на сообщение пользователя</b>, которому хотите дать -rep.", parse_mode="HTML")
        return
    
    target_user = message.reply_to_message.from_user
    sender_user = message.from_user
    
    # Проверяем, не самому ли себе
    if target_user.id == sender_user.id:
        await message.reply("❗ <b>Нельзя изменять репутацию самому себе.</b>", parse_mode="HTML")
        return
    
    # Проверяем КД
    can_give, time_left, last_time = rep_db.can_give_rep(str(sender_user.id), str(target_user.id))
    
    if not can_give:
        # Форматируем оставшееся время
        hours = int(time_left // 3600)
        minutes = int((time_left % 3600) // 60)
        seconds = int(time_left % 60)
        
        time_str = ""
        if hours > 0:
            time_str += f"{hours}ч "
        if minutes > 0:
            time_str += f"{minutes}м "
        if seconds > 0 or (hours == 0 and minutes == 0):
            time_str += f"{seconds}с"
        
        await message.reply(
            f"⏳ <b>Кулдаун!</b>\n\n"
            f"Вы уже давали репутацию этому пользователю.\n"
            f"Следующую репутацию можно будет дать через:\n"
            f"<b>{time_str}</b>\n\n"
            f"⏰ Кулдаун: 1 час",
            parse_mode="HTML"
        )
        return
    
    # Обновляем информацию о пользователях
    target_id = str(target_user.id)
    sender_id = str(sender_user.id)
    
    rep_db.update_user_info(target_id, target_user.username, target_user.first_name)
    rep_db.update_user_info(sender_id, sender_user.username, sender_user.first_name)
    
    # Добавляем -rep и обновляем время
    plus, minus = rep_db.add_minus(target_id)
    rep_db.update_rep_time(sender_id, target_id)  # Обновляем время КД
    
    total = plus - minus
    
    # Формируем ответ
    target_name = target_user.first_name or "Пользователь"
    target_username = f" @{target_user.username}" if target_user.username else ""
    emoji = get_reputation_emoji(plus, minus)
    
    await message.reply(
        f"❌ <b>-1 репутация добавлена!</b>\n\n"
        f"👤 Пользователь: <b>{target_name}{target_username}</b>\n"
        f"📊 Новая статистика:\n"
        f"   ✅ +rep: <b>{plus}</b>\n"
        f"   ❌ -rep: <b>{minus}</b>\n"
        f"   📈 Рейтинг: <b>{total}</b>\n"
        f"   {emoji} Уровень: <b>{get_reputation_level(plus, minus)}</b>\n\n"
        f"⏰ Следующую репутацию этому пользователю можно будет дать через 1 час.\n"
        f"#MINUS_REP",
        parse_mode="HTML"
    )


@dp.message(Command("ban"))
async def cmd_ban(message: types.Message, command: CommandObject):
    """Команда /ban - бан пользователя"""
    # Проверяем права
    if not is_admin(message.from_user.id):
        await message.answer("❌ <b>Эта команда только для администраторов.</b>", parse_mode="HTML")
        return
    
    # Проверяем, что в группе
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("❌ <b>Эта команда работает только в группах.</b>", parse_mode="HTML")
        return
    
    # Проверяем права бота
    if not await check_bot_permissions(message.chat.id):
        await message.answer("❌ <b>Мне нужны права администратора для этой команды.</b>", parse_mode="HTML")
        return
    
    # Если это ответ на сообщение
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
        
        # Получаем причину из аргументов или используем по умолчанию
        reason = command.args.strip() if command.args else "Нарушение правил"
        
        try:
            # Баним пользователя
            await bot.ban_chat_member(
                chat_id=message.chat.id,
                user_id=target_user.id,
                revoke_messages=True
            )
            
            # Сохраняем в нашу базу
            bans_db.ban_user(
                user_id=str(target_user.id),
                admin_id=str(message.from_user.id),
                reason=reason
            )
            
            # Обновляем информацию в базе репутации
            rep_db.update_user_info(
                str(target_user.id),
                target_user.username,
                target_user.first_name
            )
            
            # Формируем сообщение
            username_display = f" @{target_user.username}" if target_user.username else ""
            
            await message.answer(
                f"🚫 <b>ПОЛЬЗОВАТЕЛЬ ЗАБАНЕН</b>\n\n"
                f"👤 Пользователь: <b>{target_user.first_name}{username_display}</b>\n"
                f"🆔 ID: <code>{target_user.id}</code>\n"
                f"📝 Причина: <b>{reason}</b>\n"
                f"👮 Администратор: <b>{message.from_user.first_name}</b>\n\n"
                f"#USER_BANNED",
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при бане: {e}")
            await message.answer(f"❌ <b>Ошибка при бане:</b> {str(e)}", parse_mode="HTML")
    
    else:
        # Если не ответ на сообщение, показываем инструкцию
        await message.answer(
            "❗ <b>Как использовать команду /ban:</b>\n\n"
            "1. <b>Ответьте на сообщение пользователя</b>, которого хотите забанить\n"
            "2. Напишите: <code>/ban причина</code>\n\n"
            "<b>Пример:</b>\n"
            "├ <code>/ban спам в чате</code>\n"
            "└ <code>/ban мошенничество</code>\n\n"
            "<i>Для бана по юзернейму боту нужен реальный ID пользователя из Telegram.</i>",
            parse_mode="HTML"
        )


@dp.message(Command("unban"))
async def cmd_unban(message: types.Message, command: CommandObject):
    """Команда /unban - разбан пользователя"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ <b>Эта команда только для администраторов.</b>", parse_mode="HTML")
        return
    
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("❌ <b>Эта команда работает только в группах.</b>", parse_mode="HTML")
        return
    
    if not await check_bot_permissions(message.chat.id):
        await message.answer("❌ <b>Мне нужны права администратора для этой команды.</b>", parse_mode="HTML")
        return
    
    if not command.args:
        await message.answer(
            "❗ <b>Использование:</b> <code>/unban ID_пользователя</code>\n\n"
            "<b>Пример:</b> <code>/unban 123456789</code>\n\n"
            "<i>ID можно узнать командой /rep @username</i>",
            parse_mode="HTML"
        )
        return
    
    args = command.args.strip()
    
    # Проверяем, является ли аргумент числом (ID пользователя)
    if args.isdigit():
        user_id = int(args)
        
        try:
            # Пытаемся разбанить пользователя по ID
            await bot.unban_chat_member(
                chat_id=message.chat.id,
                user_id=user_id,
                only_if_banned=True
            )
            
            # Удаляем из нашей базы
            bans_db.unban_user(str(user_id))
            
            # Пытаемся найти имя пользователя в базе репутации
            user_data = rep_db.get_user(str(user_id))
            first_name = user_data.get("first_name", "Пользователь") if user_data else "Пользователь"
            username = user_data.get("username") if user_data else None
            username_display = f" @{username}" if username else ""
            
            await message.answer(
                f"✅ <b>ПОЛЬЗОВАТЕЛЬ РАЗБАНЕН</b>\n\n"
                f"👤 Пользователь: <b>{first_name}{username_display}</b>\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"👮 Администратор: <b>{message.from_user.first_name}</b>\n\n"
                f"#USER_UNBANNED",
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при разбане: {e}")
            await message.answer(f"❌ <b>Ошибка при разбане:</b> {str(e)}", parse_mode="HTML")
    
    else:
        await message.answer(
            "❗ <b>Укажите ID пользователя:</b> <code>/unban 123456789</code>\n\n"
            "<i>ID можно узнать командой /rep @username</i>",
            parse_mode="HTML"
        )


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """Команда /stats - статистика бота"""
    total_users = len(rep_db.data)
    total_bans = len(bans_db.data)
    
    # Подсчитываем общую статистику
    total_plus = sum(user.get("plus", 0) for user in rep_db.data.values())
    total_minus = sum(user.get("minus", 0) for user in rep_db.data.values())
    
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        
        f"👥 <b>Пользователи</b>\n"
        f"├ Всего: <code>{total_users}</code>\n"
        f"├ Забанено: <code>{total_bans}</code>\n"
        f"└ Активных: <code>{total_users - total_bans}</code>\n\n"
        
        f"⭐ <b>Оценки</b>\n"
        f"├ Положительных: <code>+{total_plus}</code>\n"
        f"├ Отрицательных: <code>-{total_minus}</code>\n"
        f"└ Всего: <code>{total_plus + total_minus}</code>\n\n"
        
        f"🏆 <b>Топ-5 по репутации</b>\n"
        f"{get_top_users(rep_db.data)}\n\n"
        
        f"<i>#notoscam #статистика</i>",
        parse_mode="HTML"
    )


def get_top_users(data: dict, limit: int = 5) -> str:
    """Получаем топ пользователей по репутации"""
    users_with_score = []
    
    for user_id, user_data in data.items():
        plus = user_data.get("plus", 0)
        minus = user_data.get("minus", 0)
        score = plus - minus
        username = user_data.get("username")
        first_name = user_data.get("first_name", "Пользователь")
        
        users_with_score.append({
            "id": user_id,
            "score": score,
            "name": first_name,
            "username": username
        })
    
    # Сортируем по репутации
    users_with_score.sort(key=lambda x: x["score"], reverse=True)
    
    # Форматируем вывод
    result = ""
    for i, user in enumerate(users_with_score[:limit], 1):
        username_display = f" @{user['username']}" if user['username'] else ""
        medal = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i-1]
        result += f"├ {medal} {user['name']}{username_display}: <b>{user['score']}</b>\n"
    
    return result


# =================== ЗАПУСК БОТА ===================

async def main():
    """Основная функция запуска бота"""
    logger.info("=" * 50)
    logger.info("NOTOSCAM РЕПУТАЦИИ запущен!")
    logger.info(f"Пользователей в базе: {len(rep_db.data)}")
    logger.info(f"Забанено пользователей: {len(bans_db.data)}")
    logger.info(f"Авто-сообщения каждые {AUTO_MESSAGES_INTERVAL} сек")
    logger.info("=" * 50)
    
    # Создаем фоновую задачу для авто-сообщений
    auto_messages_task = asyncio.create_task(send_auto_messages(bot))
    
    try:
        # Запускаем поллинг
        await dp.start_polling(bot)
    finally:
        # Отменяем задачу при остановке бота
        auto_messages_task.cancel()
        try:
            await auto_messages_task
        except asyncio.CancelledError:
            pass
        logger.info("Авто-сообщения остановлены")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем.")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")