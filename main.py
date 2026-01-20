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
from garant import GarantDB

# =================== КОНФИГУРАЦИЯ ===================
TOKEN = "8449402978:AAHzm8IOWivnDUlCMxlngUtAnHEWeH_Ohz0"
ADMIN_IDS = [1007247805]  # Замени на ID админов
REPORT_ADMIN_ID = 1007247805  # Твой ID для получения репортов

# Настройки антиспама
ANTISPAM_ENABLED = True  # Включить/выключить антиспам
ANTISPAM_WINDOW = 30  # Секунды для отслеживания флуда
ANTISPAM_WARN_LIMIT = 2  # Сообщений для предупреждения
ANTISPAM_MUTE_LIMIT = 3  # Сообщений для мута

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


# =================== АНТИСПАМ СИСТЕМА ===================

class AntispamDB:
    """База данных для антиспама"""
    
    def __init__(self):
        self.user_messages = {}  # {user_id: [timestamp1, timestamp2]}
        self.muted_users = {}  # {user_id: unmute_time}
        self.warned_users = {}  # {user_id: warn_time}
    
    def add_message(self, user_id: int):
        """Добавить запись о сообщении пользователя"""
        current_time = time.time()
        
        if user_id not in self.user_messages:
            self.user_messages[user_id] = []
        
        # Удаляем старые записи (старше 30 секунд)
        self.user_messages[user_id] = [
            t for t in self.user_messages[user_id] 
            if current_time - t < ANTISPAM_WINDOW
        ]
        
        # Добавляем текущее время
        self.user_messages[user_id].append(current_time)
        
        # Проверяем, не истекло ли предупреждение
        if user_id in self.warned_users and current_time - self.warned_users[user_id] > 300:  # 5 минут
            del self.warned_users[user_id]
    
    def check_spam(self, user_id: int) -> tuple:
        """
        Проверяет, является ли активность спамом
        Возвращает: (is_spam, messages_count, action)
        action: "warn", "mute", "ok"
        """
        if user_id not in self.user_messages:
            return False, 0, "ok"
        
        messages_count = len(self.user_messages[user_id])
        
        if messages_count >= ANTISPAM_MUTE_LIMIT:
            return True, messages_count, "mute"
        elif messages_count >= ANTISPAM_WARN_LIMIT:
            return True, messages_count, "warn"
        else:
            return False, messages_count, "ok"
    
    def mute_user(self, user_id: int, duration: int = 3600):
        """Замутить пользователя"""
        self.muted_users[user_id] = time.time() + duration
        # Очищаем историю сообщений
        if user_id in self.user_messages:
            self.user_messages[user_id] = []
    
    def is_muted(self, user_id: int) -> tuple:
        """Проверяет, замучен ли пользователь"""
        if user_id in self.muted_users:
            mute_until = self.muted_users[user_id]
            if time.time() < mute_until:
                time_left = int(mute_until - time.time())
                return True, time_left
            else:
                del self.muted_users[user_id]
        return False, 0
    
    def warn_user(self, user_id: int):
        """Выдать предупреждение пользователю"""
        self.warned_users[user_id] = time.time()


# =================== ИНИЦИАЛИЗАЦИЯ ===================

bot = Bot(token=TOKEN)
dp = Dispatcher()
rep_db = ReputationDB()
bans_db = BansDB()
antispam_db = AntispamDB()
garant_db = GarantDB()


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


# =================== АНТИСПАМ ХЕНДЛЕР ===================

async def check_antispam(message: types.Message):
    """Проверка сообщения на спам"""
    # Пропускаем команды и админов
    if message.text and message.text.startswith('/'):
        return False
    
    if is_admin(message.from_user.id):
        return False
    
    user_id = message.from_user.id
    
    # Проверяем, не замучен ли пользователь
    is_muted, time_left = antispam_db.is_muted(user_id)
    if is_muted:
        try:
            # Удаляем сообщение
            await message.delete()
            
            # Отправляем уведомление в ЛС
            hours = time_left // 3600
            minutes = (time_left % 3600) // 60
            seconds = time_left % 60
            
            time_str = ""
            if hours > 0:
                time_str += f"{hours}ч "
            if minutes > 0:
                time_str += f"{minutes}м "
            time_str += f"{seconds}с"
            
            await bot.send_message(
                user_id,
                f"⏸ <b>Вы замучены!</b>\n\n"
                f"Вы отправляете сообщения слишком часто.\n"
                f"🔇 Мут истечет через: <b>{time_str}</b>\n\n"
                f"<i>Соблюдайте правила чата</i>",
                parse_mode="HTML"
            )
        except:
            pass
        return True
    
    # Добавляем запись о сообщении
    if ANTISPAM_ENABLED:
        antispam_db.add_message(user_id)
        
        # Проверяем на спам
        is_spam, count, action = antispam_db.check_spam(user_id)
        
        if is_spam:
            if action == "warn" and user_id not in antispam_db.warned_users:
                # Первое предупреждение
                antispam_db.warn_user(user_id)
                
                try:
                    warning_msg = await message.reply(
                        f"⚠️ <b>ПРЕДУПРЕЖДЕНИЕ</b>\n\n"
                        f"@{message.from_user.username or message.from_user.first_name}, "
                        f"вы отправляете сообщения слишком часто!\n"
                        f"📊 Сообщений за 30 сек: <b>{count}</b>\n\n"
                        f"<i>Следующее нарушение → мут на 1 час</i>",
                        parse_mode="HTML"
                    )
                    
                    # Удаляем предупреждение через 10 секунд
                    await asyncio.sleep(10)
                    await warning_msg.delete()
                    
                except:
                    pass
            
            elif action == "mute":
                # Выдаем мут
                antispam_db.mute_user(user_id, 3600)  # 1 час
                
                try:
                    # Удаляем сообщение
                    await message.delete()
                    
                    # Отправляем уведомление о муте
                    mute_msg = await message.answer(
                        f"🔇 <b>ПОЛЬЗОВАТЕЛЬ ЗАМУЧЕН</b>\n\n"
                        f"👤 Пользователь: @{message.from_user.username or message.from_user.first_name}\n"
                        f"⏰ Мут на: <b>1 час</b>\n"
                        f"📊 Нарушение: <b>флуд ({count} сообщений за 30 сек)</b>\n\n"
                        f"<i>Автоматическая система антиспама</i>",
                        parse_mode="HTML"
                    )
                    
                    # Уведомляем пользователя в ЛС
                    try:
                        await bot.send_message(
                            user_id,
                            f"🔇 <b>Вы получили мут!</b>\n\n"
                            f"Причина: <b>Флуд ({count} сообщений за 30 секунд)</b>\n"
                            f"Длительность: <b>1 час</b>\n"
                            f"Чат: <b>{message.chat.title if hasattr(message.chat, 'title') else 'личные сообщения'}</b>\n\n"
                            f"<i>Соблюдайте правила общения</i>",
                            parse_mode="HTML"
                        )
                    except:
                        pass
                    
                    # Удаляем уведомление через 15 секунд
                    await asyncio.sleep(15)
                    await mute_msg.delete()
                    
                except Exception as e:
                    logger.error(f"Ошибка при муте: {e}")
    
    return False


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

         "🛡 <b>Гарант</b>\n"
        "├ /garant @продавец @покупатель сумма\n"
        "└ /deal [ID] – проверка сделки\n\n"
        
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
    # Проверяем антиспам перед обработкой команды
    if await check_antispam(message):
        return
    
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
    # Проверяем антиспам перед обработкой команды
    if await check_antispam(message):
        return
    
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


# =================== КОМАНДЫ ДЛЯ УПРАВЛЕНИЯ АНТИСПАМОМ ===================

@dp.message(Command("mute"))
async def cmd_mute(message: types.Message, command: CommandObject):
    """Замутить пользователя вручную"""
    if not is_admin(message.from_user.id):
        return
    
    if not message.reply_to_message:
        await message.answer(
            "❗ <b>Использование:</b>\n"
            "Ответьте на сообщение пользователя:\n"
            "<code>/mute время_в_секундах причина</code>\n\n"
            "<b>Примеры:</b>\n"
            "├ <code>/mute 3600 флуд</code> (1 час)\n"
            "├ <code>/mute 300 спам</code> (5 минут)\n"
            "└ <code>/mute 86400 нарушение правил</code> (1 день)",
            parse_mode="HTML"
        )
        return
    
    target_user = message.reply_to_message.from_user
    
    if not command.args:
        duration = 3600  # 1 час по умолчанию
        reason = "Нарушение правил"
    else:
        args = command.args.strip().split(' ', 1)
        try:
            duration = int(args[0])
            reason = args[1] if len(args) > 1 else "Нарушение правил"
        except:
            duration = 3600
            reason = command.args
    
    # Мьют через антиспам систему
    antispam_db.mute_user(target_user.id, duration)
    
    # Удаляем сообщение пользователя
    try:
        await message.reply_to_message.delete()
    except:
        pass
    
    # Уведомление в чат
    hours = duration // 3600
    minutes = (duration % 3600) // 60
    
    time_str = ""
    if hours > 0:
        time_str += f"{hours}ч "
    if minutes > 0:
        time_str += f"{minutes}м"
    if not time_str:
        time_str = f"{duration}с"
    
    await message.answer(
        f"🔇 <b>ПОЛЬЗОВАТЕЛЬ ЗАМУЧЕН</b>\n\n"
        f"👤 Пользователь: @{target_user.username or target_user.first_name}\n"
        f"🆔 ID: <code>{target_user.id}</code>\n"
        f"⏰ Длительность: <b>{time_str}</b>\n"
        f"📝 Причина: <b>{reason}</b>\n"
        f"👮 Администратор: <b>{message.from_user.first_name}</b>\n\n"
        f"#USER_MUTED",
        parse_mode="HTML"
    )

@dp.message(Command("unmute"))
async def cmd_unmute(message: types.Message, command: CommandObject):
    """Размутить пользователя"""
    if not is_admin(message.from_user.id):
        return
    
    if not command.args and not message.reply_to_message:
        await message.answer(
            "❗ <b>Использование:</b>\n"
            "1. <code>/unmute @username</code>\n"
            "2. Ответить на сообщение: <code>/unmute</code>",
            parse_mode="HTML"
        )
        return
    
    target_user_id = None
    
    if message.reply_to_message:
        target_user_id = message.reply_to_message.from_user.id
    elif command.args and command.args.startswith('@'):
        # Поиск по юзернейму в базе репутации
        username = command.args[1:]
        user_id, _ = rep_db.find_by_username(username)
        if user_id:
            target_user_id = int(user_id)
        else:
            await message.answer(f"❌ Пользователь @{username} не найден.")
            return
    
    if target_user_id:
        # Удаляем из списка замученных
        if target_user_id in antispam_db.muted_users:
            del antispam_db.muted_users[target_user_id]
            await message.answer(f"✅ Пользователь размучен")
        else:
            await message.answer("ℹ️ Пользователь не был замучен")
    else:
        await message.answer("❌ Не удалось определить пользователя")

@dp.message(Command("antispam"))
async def cmd_antispam(message: types.Message):
    """Информация о системе антиспама"""
    if not is_admin(message.from_user.id):
        return
    
    muted_count = len(antispam_db.muted_users)
    warned_count = len(antispam_db.warned_users)
    
    # Список замученных пользователей
    muted_list = ""
    for user_id, mute_time in list(antispam_db.muted_users.items()):
        time_left = int(mute_time - time.time())
        if time_left > 0:
            user_data = rep_db.get_user(str(user_id))
            username = user_data.get("username", "")
            name = user_data.get("first_name", f"ID: {user_id}")
            
            hours = time_left // 3600
            minutes = (time_left % 3600) // 60
            
            time_str = ""
            if hours > 0:
                time_str += f"{hours}ч "
            if minutes > 0:
                time_str += f"{minutes}м"
            if not time_str:
                time_str = f"{time_left}с"
            
            muted_list += f"├ 👤 {name} (@{username}) - осталось: {time_str}\n"
    
    await message.answer(
        f"🛡 <b>СИСТЕМА АНТИСПАМА</b>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"├ Статус: {'🟢 ВКЛЮЧЕН' if ANTISPAM_ENABLED else '🔴 ВЫКЛЮЧЕН'}\n"
        f"├ Замучено: <b>{muted_count}</b> пользователей\n"
        f"├ Предупреждений: <b>{warned_count}</b>\n"
        f"└ Окно проверки: <b>{ANTISPAM_WINDOW}</b> секунд\n\n"
        f"⚙️ <b>Настройки:</b>\n"
        f"├ Предупреждение: {ANTISPAM_WARN_LIMIT} сообщ./{ANTISPAM_WINDOW}сек\n"
        f"└ Мут: {ANTISPAM_MUTE_LIMIT} сообщ./{ANTISPAM_WINDOW}сек\n\n"
        f"📋 <b>Замученные сейчас:</b>\n"
        f"{muted_list if muted_list else '├ Нет замученных пользователей'}\n\n"
        f"<i>Команды: /mute, /unmute</i>",
        parse_mode="HTML"
    )

def calculate_commission(amount_str: str) -> str:
    """Рассчитывает комиссию 5% от суммы"""
    try:
        # Убираем все нецифровые символы, кроме точки и запятой
        clean_amount = re.sub(r'[^\d.,]', '', amount_str)
        clean_amount = clean_amount.replace(',', '.')
        
        if not clean_amount:
            return "не удалось рассчитать"
        
        amount = float(clean_amount)
        commission = amount * 0.05
        
        # Форматируем обратно
        if '₽' in amount_str:
            return f"{commission:.2f}₽"
        elif '$' in amount_str:
            return f"{commission:.2f}$"
        elif '€' in amount_str:
            return f"{commission:.2f}€"
        else:
            return f"{commission:.2f}"
            
    except:
        return "не удалось рассчитать"

def format_status(status: str) -> str:
    """Форматирует статус сделки"""
    status_map = {
        "pending": "⏳ Ожидание гаранта",
        "active": "🟢 Активна (гарант подключен)",
        "completed": "✅ Завершена успешно",
        "cancelled": "❌ Отменена"
    }
    return status_map.get(status, "Неизвестно")


@dp.message(Command("garant"))
async def cmd_garant(message: types.Message, command: CommandObject):
    """Команда /garant - вызов гаранта для сделки"""
    
    if not command.args:
        await message.answer(
            "🛡 <b>Система Гаранта NOTOSCAM</b>\n\n"
            "📝 <b>Формат команды:</b>\n"
            "<code>/garant @продавец @покупатель сумма</code>\n\n"
            "📋 <b>Примеры:</b>\n"
            "├ <code>/garant @seller @buyer 1000₽</code>\n"
            "├ <code>/garant @user1 @user2 500₽</code>\n"
            "└ <code>/garant @username1 @username2 2500₽</code>\n\n"
            "⚠️ <b>Важно:</b>\n"
            "- Гарант нужен для безопасной сделки\n"
            "- Администратор выступит посредником\n"
            "<i>#гарант #безопасность #notoscam</i>",
            parse_mode="HTML"
        )
        return
    
    args = command.args.strip().split()
    
    if len(args) < 3:
        await message.answer(
            "❌ <b>Недостаточно аргументов</b>\n\n"
            "<b>Правильный формат:</b>\n"
            "<code>/garant @продавец @покупатель сумма</code>\n\n"
            "<b>Пример:</b>\n"
            "<code>/garant @seller123 @buyer456 1500₽</code>",
            parse_mode="HTML"
        )
        return
    
    seller_username = args[0]
    buyer_username = args[1]
    amount = " ".join(args[2:])
    
    # Проверяем, что указаны юзернеймы с @
    if not seller_username.startswith('@') or not buyer_username.startswith('@'):
        await message.answer(
            "❌ <b>Некорректные юзернеймы</b>\n\n"
            "Укажите юзернеймы с символом @:\n"
            "<code>/garant @username1 @username2 сумма</code>",
            parse_mode="HTML"
        )
        return
    
    # Проверяем, что пользователи существуют в базе
    seller_id, seller_data = rep_db.find_by_username(seller_username[1:])
    buyer_id, buyer_data = rep_db.find_by_username(buyer_username[1:])
    
    if not seller_id:
        await message.answer(f"❌ Продавец {seller_username} не найден в базе.\nИспользуйте /rep {seller_username} для проверки.")
        return
    
    if not buyer_id:
        await message.answer(f"❌ Покупатель {buyer_username} не найден в базе.\nИспользуйте /rep {buyer_username} для проверки.")
        return
    
    # Создаем сделку
    try:
        deal = garant_db.create_deal(
            seller_username=seller_username,
            buyer_username=buyer_username,
            amount=amount,
            initiator_id=message.from_user.id,
            chat_id=message.chat.id,
            message_id=message.message_id
        )
        
        # Обновляем информацию о пользователях
        rep_db.update_user_info(seller_id, seller_data.get("username"), seller_data.get("first_name"))
        rep_db.update_user_info(buyer_id, buyer_data.get("username"), buyer_data.get("first_name"))
        
        # Получаем информацию о репутации
        seller_plus = seller_data.get("plus", 0)
        seller_minus = seller_data.get("minus", 0)
        buyer_plus = buyer_data.get("plus", 0)
        buyer_minus = buyer_data.get("minus", 0)
        
        # Рассчитываем комиссию
        commission = calculate_commission(amount)
        
        # Формируем сообщение для админа
        admin_message = (
            f"🛡 <b>НОВАЯ СДЕЛКА С ГАРАНТОМ</b>\n\n"
            f"🆔 <b>ID сделки:</b> <code>{deal['deal_id']}</code>\n"
            f"⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
            
            f"👤 <b>Продавец:</b>\n"
            f"├ {seller_username}\n"
            f"├ Имя: {seller_data.get('first_name', 'Неизвестно')}\n"
            f"├ Репутация: ✅{seller_plus} ❌{seller_minus}\n"
            f"└ ID: <code>{seller_id}</code>\n\n"
            
            f"👤 <b>Покупатель:</b>\n"
            f"├ {buyer_username}\n"
            f"├ Имя: {buyer_data.get('first_name', 'Неизвестно')}\n"
            f"├ Репутация: ✅{buyer_plus} ❌{buyer_minus}\n"
            f"└ ID: <code>{buyer_id}</code>\n\n"
            
            f"💰 <b>Сумма сделки:</b> <code>{amount}</code>\n"
            
            f"👥 <b>Инициатор вызова:</b>\n"
            f"├ @{message.from_user.username or message.from_user.first_name}\n"
            f"└ ID: <code>{message.from_user.id}</code>\n\n"
            
            f"💬 <b>Чат:</b> {message.chat.title if hasattr(message.chat, 'title') else 'Личные сообщения'}\n"
            f"🆔 ID чата: <code>{message.chat.id}</code>\n\n"
            
            f"🔗 <b>Ссылки:</b>\n"
            f"├ Продавец: https://t.me/{seller_username[1:]}\n"
            f"├ Покупатель: https://t.me/{buyer_username[1:]}\n"
            f"└ Сообщение: https://t.me/c/{str(message.chat.id)[4:]}/{message.message_id}\n\n"
            
            f"<i>Сделка ожидает подтверждения</i>\n"
            f"#ГАРАНТ_СДЕЛКА #{deal['deal_id']}"
        )
        
        # Отправляем уведомление админу
        try:
            await bot.send_message(
                chat_id=REPORT_ADMIN_ID,
                text=admin_message,
                parse_mode="HTML",
                disable_web_page_preview=False
            )
            
            # Отмечаем что админ уведомлен
            garant_db.set_admin_notified(deal['deal_id'])
            
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления гаранта админу: {e}")
        
        # Отвечаем пользователю
        response = (
            f"🛡 <b>ГАРАНТ ВЫЗВАН!</b>\n\n"
            f"✅ <b>Сделка создана:</b>\n"
            f"├ Продавец: {seller_username}\n"
            f"├ Покупатель: {buyer_username}\n"
            f"└ Сумма: <code>{amount}</code>\n\n"
            
            f"📋 <b>Детали:</b>\n"
            f"├ ID сделки: <code>{deal['deal_id']}</code>\n"
            f"└ Статус: ⏳ <b>Ожидание гаранта</b>\n\n"
            
            f"👮 <b>Администратор уведомлен</b>\n"
            f"В ближайшее время с вами свяжутся для подтверждения сделки.\n\n"
            
            f"⚠️ <b>Внимание:</b>\n"
            f"- Не переводите деньги до подтверждения гаранта\n"
            f"- Общайтесь вежливо и четко\n"
            f"- Сохраните ID сделки для связи\n\n"
            
            f"<i>#гарант #{deal['deal_id']}</i>"
        )
        
        await message.answer(response, parse_mode="HTML")
        
        logger.info(f"Создана сделка с гарантом: {deal['deal_id']}")
        
    except Exception as e:
        logger.error(f"Ошибка создания сделки с гарантом: {e}")
        await message.answer(
            "❌ <b>Ошибка создания сделки</b>\n\n"
            f"<i>Техническая информация: {str(e)}</i>\n\n"
            "Попробуйте позже или обратитесь к администратору.",
            parse_mode="HTML"
        )


@dp.message(Command("deal"))
async def cmd_deal(message: types.Message, command: CommandObject = None):
    """Проверить статус сделки"""
    if not command or not command.args:
        # Показываем активные сделки пользователя
        username = f"@{message.from_user.username}" if message.from_user.username else None
        
        if not username:
            await message.answer("❌ У вас нет юзернейма в Telegram.")
            return
        
        user_deals = garant_db.get_user_deals(username)
        
        if not user_deals:
            await message.answer(
                "📭 <b>У вас нет активных сделок</b>\n\n"
                "Чтобы создать сделку с гарантом:\n"
                "<code>/garant @продавец @покупатель сумма</code>",
                parse_mode="HTML"
            )
            return
        
        response = "📋 <b>ВАШИ СДЕЛКИ</b>\n\n"
        
        for deal in user_deals[:5]:  # Показываем только 5 последних сделок
            status_emoji = {
                "pending": "⏳",
                "active": "🟢",
                "completed": "✅",
                "cancelled": "❌"
            }.get(deal["status"], "❓")
            
            response += (
                f"{status_emoji} <b>Сделка {deal['deal_id']}</b>\n"
                f"├ Продавец: {deal['seller_username']}\n"
                f"├ Покупатель: {deal['buyer_username']}\n"
                f"├ Сумма: <code>{deal['amount']}</code>\n"
                f"└ Статус: <b>{format_status(deal['status'])}</b>\n\n"
            )
        
        if len(user_deals) > 5:
            response += f"<i>... и еще {len(user_deals) - 5} сделок</i>\n\n"
        
        response += "ℹ️ Для деталей конкретной сделки: <code>/deal ID_сделки</code>"
        
        await message.answer(response, parse_mode="HTML")
        return
    
    # Проверка конкретной сделки по ID
    deal_id = command.args.strip()
    deal = garant_db.find_deal(deal_id)
    
    if not deal:
        await message.answer(
            f"❌ <b>Сделка не найдена</b>\n\n"
            f"Сделка с ID <code>{deal_id}</code> не существует.\n"
            f"Проверьте ID или используйте <code>/deal</code> для просмотра ваших сделок.",
            parse_mode="HTML"
        )
        return
    
    # Форматируем статус
    status_text = format_status(deal["status"])
    status_emoji = {
        "pending": "⏳",
        "active": "🟢",
        "completed": "✅",
        "cancelled": "❌"
    }.get(deal["status"], "❓")
    
    response = (
        f"🛡 <b>ИНФОРМАЦИЯ О СДЕЛКЕ</b>\n\n"
        f"{status_emoji} <b>Статус:</b> {status_text}\n"
        f"🆔 <b>ID сделки:</b> <code>{deal['deal_id']}</code>\n"
        f"⏰ <b>Создана:</b> {datetime.fromisoformat(deal['created_at']).strftime('%d.%m.%Y %H:%M')}\n\n"
        
        f"👤 <b>Продавец:</b> {deal['seller_username']}\n"
        f"👤 <b>Покупатель:</b> {deal['buyer_username']}\n"
        f"💰 <b>Сумма:</b> <code>{deal['amount']}</code>\n\n"
    )
    
    if deal["status"] == "completed" and deal.get("completed_at"):
        response += f"✅ <b>Завершена:</b> {datetime.fromisoformat(deal['completed_at']).strftime('%d.%m.%Y %H:%M')}\n\n"
    elif deal["status"] == "cancelled" and deal.get("cancelled_at"):
        reason = deal.get("cancelled_reason", "Причина не указана")
        response += f"❌ <b>Отменена:</b> {datetime.fromisoformat(deal['cancelled_at']).strftime('%d.%m.%Y %H:%M')}\n"
        response += f"📝 <b>Причина:</b> {reason}\n\n"
    
    if is_admin(message.from_user.id) and deal["status"] == "pending":
        response += (
            "⚡ <b>Команды для админа:</b>\n"
            f"├ <code>/accept {deal['deal_id']}</code> - принять сделку\n"
            f"├ <code>/complete {deal['deal_id']}</code> - завершить сделку\n"
            f"└ <code>/cancel {deal['deal_id']} причина</code> - отменить\n"
        )
    
    await message.answer(response, parse_mode="HTML")


# =================== АДМИН КОМАНДЫ ДЛЯ УПРАВЛЕНИЯ СДЕЛКАМИ ===================

@dp.message(Command("accept"))
async def cmd_accept(message: types.Message, command: CommandObject):
    """Принять сделку как гарант (только для админов)"""
    if not is_admin(message.from_user.id):
        return
    
    if not command.args:
        await message.answer("Использование: /accept ID_сделки")
        return
    
    deal_id = command.args.strip()
    deal = garant_db.find_deal(deal_id)
    
    if not deal:
        await message.answer(f"❌ Сделка {deal_id} не найдена.")
        return
    
    if deal["status"] != "pending":
        await message.answer(f"❌ Сделка уже в статусе: {deal['status']}")
        return
    
    # Обновляем статус сделки
    if garant_db.update_deal_status(deal_id, "active", message.from_user.id):
        # Уведомляем в исходном чате
        try:
            notification = (
                f"🟢 <b>ГАРАНТ ПОДКЛЮЧЕН!</b>\n\n"
                f"Сделка <code>{deal_id}</code> принята администратором.\n"
                f"👮 <b>Гарант:</b> @{message.from_user.username or message.from_user.first_name}\n\n"
                f"ℹ️ <b>Дальнейшие действия:</b>\n"
                f"1. Свяжитесь с гарантом в ЛС\n"
                f"2. Обсудите детали перевода\n"
                f"3. Следуйте инструкциям гаранта\n\n"
                f"<i>Не переводите деньги до подтверждения гаранта!</i>"
            )
            
            await bot.send_message(
                chat_id=deal["chat_id"],
                text=notification,
                parse_mode="HTML"
            )
        except:
            pass
        
        await message.answer(f"✅ Сделка {deal_id} принята. Статус изменен на 'active'.")
    else:
        await message.answer("❌ Ошибка обновления статуса сделки.")


@dp.message(Command("complete"))
async def cmd_complete(message: types.Message, command: CommandObject):
    """Завершить сделку (только для админов)"""
    if not is_admin(message.from_user.id):
        return
    
    if not command.args:
        await message.answer("Использование: /complete ID_сделки")
        return
    
    deal_id = command.args.strip()
    deal = garant_db.find_deal(deal_id)
    
    if not deal:
        await message.answer(f"❌ Сделка {deal_id} не найдена.")
        return
    
    if deal["status"] != "active":
        await message.answer(f"❌ Сделка не активна. Текущий статус: {deal['status']}")
        return
    
    # Обновляем статус сделки
    if garant_db.update_deal_status(deal_id, "completed"):
        # Уведомляем в исходном чате
        try:
            notification = (
                f"✅ <b>СДЕЛКА ЗАВЕРШЕНА!</b>\n\n"
                f"Сделка <code>{deal_id}</code> успешно завершена.\n"
                f"💰 <b>Сумма:</b> {deal['amount']}\n"
                f"👮 <b>Гарант:</b> @{message.from_user.username or message.from_user.first_name}\n\n"
                f"⭐ <b>Не забудьте оценить друг друга:</b>\n"
                f"├ <code>+rep</code> - если все прошло хорошо\n"
                f"└ <code>-rep</code> - если были проблемы\n\n"
                f"<i>Спасибо за использование NOTOSCAM Гаранта!</i>"
            )
            
            await bot.send_message(
                chat_id=deal["chat_id"],
                text=notification,
                parse_mode="HTML"
            )
        except:
            pass
        
        await message.answer(f"✅ Сделка {deal_id} завершена. Статус изменен на 'completed'.")
    else:
        await message.answer("❌ Ошибка обновления статуса сделки.")


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, command: CommandObject):
    """Отменить сделку (только для админов)"""
    if not is_admin(message.from_user.id):
        return
    
    if not command.args:
        await message.answer("Использование: /cancel ID_сделки причина")
        return
    
    args = command.args.strip().split(' ', 1)
    if len(args) < 2:
        await message.answer("Укажите причину отмены: /cancel ID_сделки причина")
        return
    
    deal_id = args[0]
    reason = args[1]
    deal = garant_db.find_deal(deal_id)
    
    if not deal:
        await message.answer(f"❌ Сделка {deal_id} не найдена.")
        return
    
    if deal["status"] not in ["pending", "active"]:
        await message.answer(f"❌ Сделка уже в статусе: {deal['status']}")
        return
    
    # Обновляем статус сделки с причиной
    if garant_db.update_deal_status(deal_id, "cancelled"):
        # Добавляем причину отмены
        for d in garant_db.data:
            if d["deal_id"] == deal_id:
                d["cancelled_reason"] = reason
                break
        garant_db._save_data()
        
        # Уведомляем в исходном чате
        try:
            notification = (
                f"❌ <b>СДЕЛКА ОТМЕНЕНА</b>\n\n"
                f"Сделка <code>{deal_id}</code> отменена администратором.\n"
                f"📝 <b>Причина:</b> {reason}\n"
                f"👮 <b>Гарант:</b> @{message.from_user.username or message.from_user.first_name}\n\n"
                f"⚠️ <b>Внимание:</b>\n"
                f"Не проводите перевод по отмененной сделке!\n\n"
                f"<i>Если есть вопросы - обратитесь к администратору</i>"
            )
            
            await bot.send_message(
                chat_id=deal["chat_id"],
                text=notification,
                parse_mode="HTML"
            )
        except:
            pass
        
        await message.answer(f"✅ Сделка {deal_id} отменена. Статус изменен на 'cancelled'.")
    else:
        await message.answer("❌ Ошибка обновления статуса сделки.")

# =================== ОБРАБОТЧИК ВСЕХ СООБЩЕНИЙ (АНТИСПАМ) ===================

@dp.message()
async def handle_all_messages(message: types.Message):
    """Обработчик всех сообщений для антиспама"""
    # Пропускаем команды (они обрабатываются отдельными хендлерами)
    if message.text and message.text.startswith('/'):
        # Проверяем антиспам даже для команд
        if await check_antispam(message):
            return
        
        # Сообщение не является известной командой - показываем помощь
        await message.answer(
            "❓ <b>Неизвестная команда</b>\n\n"
            "Используйте <code>/help</code> для просмотра всех доступных команд.",
            parse_mode="HTML"
        )
        return
    
    # Проверяем обычные сообщения на антиспам
    await check_antispam(message)


# =================== ЗАПУСК БОТА ===================

async def main():
    """Основная функция запуска бота"""
    logger.info("=" * 50)
    logger.info("NOTOSCAM РЕПУТАЦИИ запущен!")
    logger.info(f"Пользователей в базе: {len(rep_db.data)}")
    logger.info(f"Забанено пользователей: {len(bans_db.data)}")
    logger.info(f"Авто-сообщения каждые {AUTO_MESSAGES_INTERVAL} сек")
    logger.info(f"Антиспам: {'ВКЛ' if ANTISPAM_ENABLED else 'ВЫКЛ'}")
    logger.info(f"  - Окно: {ANTISPAM_WINDOW} сек")
    logger.info(f"  - Лимиты: {ANTISPAM_WARN_LIMIT}/{ANTISPAM_MUTE_LIMIT}")
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