import logging
import sqlite3
import json
import requests
from datetime import datetime, timedelta
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id
from icalendar import Calendar
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import re
import random
import uuid

# ========== CONFIGURATION ==========
VK_TOKEN = "vk1.a.eZvEbyVQo2aLD4K-r_7DxudJLQ4iNke42CLOnxo-ewzkJhDCjgY-FFImW2JeNulCAByv9bzkSuo_VXZFEV1GbMGoTfjD_TlDUV_pfIIfXU2eJvNsYIVFvVRa7OQxAhzGJPle69aDCxH7jYlu-LbbfSLM-9ZVDiOkmo3zSdgiWYegoSqKJqtGAGoyldsJYC79Fc9up1aNsvk3uJ3NZaE6Xg"
GROUP_ID = 237363984
TIMEZONE = pytz.timezone("Asia/Novosibirsk")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ========== DATABASE SETUP ==========
def init_db():
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        vk_id INTEGER PRIMARY KEY,
        name TEXT DEFAULT '',
        language TEXT DEFAULT 'en',
        reminder_offset INTEGER DEFAULT 75,
        join_date DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS schedule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        subject TEXT,
        day INTEGER,
        start_time TEXT,
        end_time TEXT,
        location TEXT,
        teacher TEXT
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        task TEXT,
        due_date TEXT,
        remind_days INTEGER,
        priority TEXT DEFAULT 'normal',
        category TEXT DEFAULT 'general',
        done INTEGER DEFAULT 0,
        completed_date DATETIME
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS study_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        subject TEXT,
        duration INTEGER,
        date TEXT,
        notes TEXT DEFAULT ''
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS pomodoro_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        subject TEXT,
        duration INTEGER,
        completed_cycles INTEGER,
        date TEXT
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        goal TEXT,
        target INTEGER,
        current INTEGER DEFAULT 0,
        unit TEXT DEFAULT 'hours',
        deadline TEXT,
        created_date TEXT
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE,
        sent INTEGER DEFAULT 1,
        reminder_time DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS time_blocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        title TEXT,
        start_time TEXT,
        end_time TEXT,
        date TEXT,
        type TEXT DEFAULT 'study'
    )""")
    
    conn.commit()
    conn.close()
    logging.info("Database initialized with all tables")

init_db()

# ========== LANGUAGE SYSTEM (EN, RU, ZH) ==========
RESPONSES = {
    'en': {
        'ask_name': "👋 Hello! I'm your study assistant bot. What's your name?",
        'got_name': "Nice to meet you, {name}! 🎉\n\nI can help you with:\n📅 Schedule management\n📝 Task tracking\n⏱️ Time management\n📊 Progress statistics\n📥 Calendar import\n\nUse /help to see all commands!",
        'help': """🤖 *BOT COMMANDS*

📅 *SCHEDULE*
• "Today" - Today's classes
• "Tomorrow" - Tomorrow's classes
• /add [subj] [day] [start] [end] - Add class
• /ics [url] - Import calendar

📝 *TASKS*
• "Tasks" - View your tasks
• /task [name] [date] [priority] - Add task
• /done [task] - Complete task
• /deadlines - Upcoming deadlines

⏱️ *TIME MANAGEMENT*
• /focus [subj] [min] - Start focus timer
• /pomodoro [subj] - Start Pomodoro
• /stop - Stop timer
• /timeblock - Schedule time block
• /todayplan - Today's plan
• /weekplan - Weekly plan

📊 *STATS & GOALS*
• /stats - Your statistics
• /goal [text] [target] - Set goal
• /goals - View your goals
• /progress - Goal progress

⚙️ *OTHER*
• /language [en/ru/zh] - Change language
• /time - Current time
• /joke - Random joke""",
        'today': "📅 *Today's Schedule*\n\n{classes}",
        'tomorrow': "📅 *Tomorrow's Schedule*\n\n{classes}",
        'no_classes': "🎉 No classes today! Time to study or relax!",
        'tasks_empty': "✅ No pending tasks! Great job!",
        'tasks_list': "📝 *Your Tasks*\n\n{tasks}",
        'task_added': "✅ Task added: {task}\n📅 Due: {due}\n⚡ Priority: {priority}",
        'task_completed': "🎉 Task '{task}' completed! Keep it up!",
        'focus_start': "⏱️ *Focus Mode ON*\n\n📖 {subject}\n⏰ {duration} min\n\nStay focused! I'll notify you when done.",
        'focus_done': "🎉 *Focus Complete!*\n\n📖 {subject}\n⏰ {duration} min\n\nGreat work! Take a 5-min break.",
        'focus_stop': "⏹️ Focus stopped.\nCompleted {elapsed} min.",
        'pomodoro_start': "🍅 *Pomodoro Started!*\n\n{cycles} cycles (25min work + 5min break)\n\nSubject: {subject}",
        'pomodoro_break': "☕ Break time! 5 minutes.",
        'pomodoro_long_break': "☕ Long break! 15 minutes.",
        'pomodoro_done': "🎉 Pomodoro complete! {cycles} cycles done!",
        'stats': """📊 *YOUR STATISTICS*

📝 Tasks: {completed}/{total} completed ({rate}%)
⏱️ Study time: {study_hours}h {study_min}min
📚 Classes: {class_count}
🎯 Goals: {goals_completed}/{goals_total} achieved

📈 Productivity Score: {productivity}%""",
        'goal_set': "🎯 Goal set: {goal}\nTarget: {target} {unit}",
        'no_goals': "No goals set yet. Use /goal to create one!",
        'import_success': "✅ Imported {count} classes!",
        'import_fail': "❌ Import failed: {error}",
        'time': "🕐 Current time: {time}",
        'language_changed': "✅ Language changed to {language}",
        'weekdays': ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        'error': "❌ Something went wrong. Please try again.",
        'importing': "⏳ Importing calendar...",
        'focus_usage': "Usage: /focus [subject] [minutes]\nExample: /focus Math 30\n\nOr use /pomodoro [subject] for Pomodoro technique (4 cycles of 25min)",
        'delete_usage': "Usage: /delete [class_id]\nFind IDs in schedule",
        'class_deleted': "✅ Class deleted!",
        'follow_help': "Try /help for available commands! 🚀"
    },
    'ru': {
        'ask_name': "👋 Привет! Я твой учебный помощник. Как тебя зовут?",
        'got_name': "Приятно познакомиться, {name}! 🎉\n\nЯ помогу с:\n📅 Расписанием\n📝 Задачами\n⏱️ Управлением временем\n📊 Статистикой\n📥 Импортом календаря\n\nИспользуй /help для команд!",
        'help': """🤖 *КОМАНДЫ БОТА*

📅 *РАСПИСАНИЕ*
• "Сегодня" - Пары сегодня
• "Завтра" - Пары завтра
• /add [предмет] [день] [начало] [конец]
• /ics [ссылка] - Импорт календаря

📝 *ЗАДАЧИ*
• "Задачи" - Список задач
• /task [имя] [дата] [приоритет]
• /done [задача] - Выполнить
• /deadlines - Ближайшие сроки

⏱️ *ТАЙМ-МЕНЕДЖМЕНТ*
• /focus [предмет] [мин] - Фокус
• /pomodoro [предмет] - Помодоро
• /stop - Стоп таймер
• /timeblock - Блок времени
• /todayplan - План на сегодня
• /weekplan - План на неделю

📊 *СТАТИСТИКА*
• /stats - Статистика
• /goal [текст] [цель] - Цель
• /goals - Мои цели
• /progress - Прогресс целей

⚙️ *ПРОЧЕЕ*
• /language [en/ru/zh] - Сменить язык
• /time - Время
• /joke - Шутка""",
        'today': "📅 *Расписание на сегодня*\n\n{classes}",
        'tomorrow': "📅 *Расписание на завтра*\n\n{classes}",
        'no_classes': "🎉 Сегодня нет пар! Время учиться или отдыхать!",
        'tasks_empty': "✅ Нет задач! Отличная работа!",
        'tasks_list': "📝 *Твои задачи*\n\n{tasks}",
        'task_added': "✅ Задача добавлена: {task}\n📅 Срок: {due}\n⚡ Приоритет: {priority}",
        'task_completed': "🎉 Задача '{task}' выполнена! Так держать!",
        'focus_start': "⏱️ *Фокус ВКЛ*\n\n📖 {subject}\n⏰ {duration} мин\n\nСосредоточься! Сообщу когда закончишь.",
        'focus_done': "🎉 *Фокус завершён!*\n\n📖 {subject}\n⏰ {duration} мин\n\nОтлично! Сделай перерыв 5 мин.",
        'focus_stop': "⏹️ Фокус остановлен.\nСделано {elapsed} мин.",
        'pomodoro_start': "🍅 *Помодоро запущен!*\n\n{cycles} циклов (25мин работа + 5мин отдых)\n\nПредмет: {subject}",
        'pomodoro_break': "☕ Перерыв! 5 минут.",
        'pomodoro_long_break': "☕ Длинный перерыв! 15 минут.",
        'pomodoro_done': "🎉 Помодоро завершён! {cycles} циклов сделано!",
        'stats': """📊 *ТВОЯ СТАТИСТИКА*

📝 Задачи: {completed}/{total} выполнено ({rate}%)
⏱️ Учёба: {study_hours}ч {study_min}мин
📚 Пары: {class_count}
🎯 Цели: {goals_completed}/{goals_total} достигнуто

📈 Продуктивность: {productivity}%""",
        'goal_set': "🎯 Цель поставлена: {goal}\nЦель: {target} {unit}",
        'no_goals': "Целей пока нет. Используй /goal чтобы создать!",
        'import_success': "✅ Импортировано {count} пар!",
        'import_fail': "❌ Ошибка импорта: {error}",
        'time': "🕐 Текущее время: {time}",
        'language_changed': "✅ Язык изменён на {language}",
        'weekdays': ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
        'error': "❌ Что-то пошло не так. Попробуй снова.",
        'importing': "⏳ Импортирую календарь...",
        'focus_usage': "Использование: /focus [предмет] [минуты]\nПример: /focus Математика 30\n\nИли /pomodoro [предмет] для техники Помодоро (4 цикла по 25 мин)",
        'delete_usage': "Использование: /delete [id_пары]\nНайди ID в расписании",
        'class_deleted': "✅ Пара удалена!",
        'follow_help': "Попробуй /help для списка команд! 🚀"
    },
    'zh': {
        'ask_name': "👋 你好！我是你的学习助手机器人。你叫什么名字？",
        'got_name': "很高兴认识你, {name}! 🎉\n\n我可以帮助你：\n📅 课程表管理\n📝 任务跟踪\n⏱️ 时间管理\n📊 进度统计\n📥 日历导入\n\n使用 /help 查看所有命令！",
        'help': """🤖 *机器人命令*

📅 *课程表*
• "今天" - 今日课程
• "明天" - 明日课程
• /add [科目] [星期] [开始] [结束] - 添加课程
• /ics [链接] - 导入日历

📝 *任务*
• "任务" - 查看任务
• /task [名称] [日期] [优先级] - 添加任务
• /done [任务] - 完成任务
• /deadlines - 即将截止

⏱️ *时间管理*
• /focus [科目] [分钟] - 开始专注
• /pomodoro [科目] - 番茄工作法
• /stop - 停止计时
• /timeblock - 安排时间块
• /todayplan - 今日计划
• /weekplan - 周计划

📊 *统计与目标*
• /stats - 你的统计
• /goal [文字] [目标] - 设定目标
• /goals - 查看目标
• /progress - 目标进度

⚙️ *其他*
• /language [en/ru/zh] - 切换语言
• /time - 当前时间
• /joke - 随机笑话""",
        'today': "📅 *今日课程*\n\n{classes}",
        'tomorrow': "📅 *明日课程*\n\n{classes}",
        'no_classes': "🎉 今天没课！学习或放松的时间！",
        'tasks_empty': "✅ 没有待办任务！做得好！",
        'tasks_list': "📝 *你的任务*\n\n{tasks}",
        'task_added': "✅ 任务已添加: {task}\n📅 截止: {due}\n⚡ 优先级: {priority}",
        'task_completed': "🎉 任务 '{task}' 已完成！继续加油！",
        'focus_start': "⏱️ *专注模式开启*\n\n📖 {subject}\n⏰ {duration} 分钟\n\n保持专注！完成后我会通知你。",
        'focus_done': "🎉 *专注完成！*\n\n📖 {subject}\n⏰ {duration} 分钟\n\n做得好！休息5分钟。",
        'focus_stop': "⏹️ 专注已停止。\n完成 {elapsed} 分钟。",
        'pomodoro_start': "🍅 *番茄工作法开始！*\n\n{cycles} 个周期 (25分钟工作 + 5分钟休息)\n\n科目: {subject}",
        'pomodoro_break': "☕ 休息时间！5分钟。",
        'pomodoro_long_break': "☕ 长时间休息！15分钟。",
        'pomodoro_done': "🎉 番茄工作法完成！{cycles} 个周期完成！",
        'stats': """📊 *你的统计*

📝 任务: {completed}/{total} 已完成 ({rate}%)
⏱️ 学习时间: {study_hours}小时 {study_min}分钟
📚 课程: {class_count}
🎯 目标: {goals_completed}/{goals_total} 已达成

📈 效率评分: {productivity}%""",
        'goal_set': "🎯 目标已设定: {goal}\n目标: {target} {unit}",
        'no_goals': "还没有设定目标。使用 /goal 创建一个！",
        'import_success': "✅ 已导入 {count} 门课程！",
        'import_fail': "❌ 导入失败: {error}",
        'time': "🕐 当前时间: {time}",
        'language_changed': "✅ 语言已切换到{language}",
        'weekdays': ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
        'error': "❌ 出了点问题。请重试。",
        'importing': "⏳ 正在导入日历...",
        'focus_usage': "用法: /focus [科目] [分钟]\n示例: /focus 数学 30\n\n或使用 /pomodoro [科目] 进行番茄工作法 (4个周期，每个25分钟)",
        'delete_usage': "用法: /delete [课程ID]\n在课程表中查找ID",
        'class_deleted': "✅ 课程已删除！",
        'follow_help': "尝试 /help 查看可用命令！🚀"
    }
}

def get_response(user_id, key, **kwargs):
    lang = get_user_language(user_id)
    responses = RESPONSES.get(lang, RESPONSES['en'])
    template = responses.get(key, RESPONSES['en'].get(key, key))
    try:
        return template.format(**kwargs)
    except:
        return template

# ========== HELPER FUNCTIONS ==========
def detect_language(text):
    if not text:
        return 'en'
    # Check for Cyrillic (Russian)
    cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    if cyrillic > len(text) * 0.1:
        return 'ru'
    # Check for Chinese characters
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')
    if chinese > len(text) * 0.1:
        return 'zh'
    return 'en'

def get_user_name(user_id):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("SELECT name FROM users WHERE vk_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else None

def set_user_name(user_id, name):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (vk_id, name) VALUES (?, ?)", (user_id, name))
    conn.commit()
    conn.close()

def get_user_language(user_id):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("SELECT language FROM users WHERE vk_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 'en'

def set_user_language(user_id, lang):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("UPDATE users SET language = ? WHERE vk_id = ?", (lang, user_id))
    conn.commit()
    conn.close()

# ========== SCHEDULE FUNCTIONS ==========
def add_class(user_id, subject, day, start, end, location='', teacher=''):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("INSERT INTO schedule (user_id, subject, day, start_time, end_time, location, teacher) VALUES (?,?,?,?,?,?,?)",
              (user_id, subject, day, start, end, location, teacher))
    conn.commit()
    conn.close()

def get_today_classes(user_id):
    today = datetime.now(TIMEZONE).weekday()
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("SELECT id, subject, start_time, end_time, location FROM schedule WHERE user_id = ? AND day = ? ORDER BY start_time", (user_id, today))
    rows = c.fetchall()
    conn.close()
    return rows

def get_tomorrow_classes(user_id):
    tomorrow = (datetime.now(TIMEZONE).weekday() + 1) % 7
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("SELECT id, subject, start_time, end_time, location FROM schedule WHERE user_id = ? AND day = ? ORDER BY start_time", (user_id, tomorrow))
    rows = c.fetchall()
    conn.close()
    return rows

def get_next_class(user_id):
    now = datetime.now(TIMEZONE)
    current_day = now.weekday()
    current_time = now.strftime("%H:%M")
    
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("SELECT subject, day, start_time, id FROM schedule WHERE user_id = ? ORDER BY day, start_time", (user_id,))
    classes = c.fetchall()
    conn.close()
    
    for subject, day, start, cid in classes:
        if day > current_day or (day == current_day and start > current_time):
            return subject, start, day
    if classes:
        return classes[0][0], classes[0][2], classes[0][1]
    return None, None, None

def get_class_count(user_id):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM schedule WHERE user_id = ?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def delete_class(user_id, class_id):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("DELETE FROM schedule WHERE id = ? AND user_id = ?", (class_id, user_id))
    conn.commit()
    conn.close()

def get_all_classes(user_id):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("SELECT id, subject, day, start_time, end_time FROM schedule WHERE user_id = ? ORDER BY day, start_time", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

# ========== TASK FUNCTIONS ==========
def add_task(user_id, task, due_date, remind_days=1, priority='normal'):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("INSERT INTO tasks (user_id, task, due_date, remind_days, priority, done) VALUES (?,?,?,?,?,0)",
              (user_id, task, due_date, remind_days, priority))
    conn.commit()
    conn.close()

def get_tasks(user_id):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("SELECT id, task, due_date, remind_days, priority FROM tasks WHERE user_id = ? AND done = 0 ORDER BY due_date", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def complete_task(user_id, task_id):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    completed_date = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE tasks SET done = 1, completed_date = ? WHERE id = ? AND user_id = ?", (completed_date, task_id, user_id))
    conn.commit()
    conn.close()

def get_task_stats(user_id):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ? AND done = 0", (user_id,))
    pending = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ? AND done = 1", (user_id,))
    completed = c.fetchone()[0]
    conn.close()
    return pending, completed

# ========== STUDY FUNCTIONS ==========
def add_study_session(user_id, subject, duration, notes=''):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    c.execute("INSERT INTO study_sessions (user_id, subject, duration, date, notes) VALUES (?,?,?,?,?)",
              (user_id, subject, duration, today, notes))
    conn.commit()
    conn.close()

def get_study_stats(user_id):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("SELECT COALESCE(SUM(duration), 0) FROM study_sessions WHERE user_id = ?", (user_id,))
    total = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(duration), 0) FROM study_sessions WHERE user_id = ? AND date >= date('now', '-7 days')", (user_id,))
    weekly = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(duration), 0) FROM study_sessions WHERE user_id = ? AND date = date('now')", (user_id,))
    today = c.fetchone()[0]
    conn.close()
    return total, weekly, today

# ========== GOAL FUNCTIONS ==========
def add_goal(user_id, goal, target, unit='hours', deadline=None):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    today = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    c.execute("INSERT INTO goals (user_id, goal, target, unit, deadline, created_date) VALUES (?,?,?,?,?,?)",
              (user_id, goal, target, unit, deadline, today))
    conn.commit()
    conn.close()

def get_goals(user_id):
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("SELECT id, goal, target, current, unit FROM goals WHERE user_id = ? ORDER BY created_date DESC", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

# ========== ICS IMPORT ==========
def import_ics_from_link(user_id, url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        
        cal = Calendar.from_ical(response.text)
        count = 0
        
        for component in cal.walk():
            if component.name == "VEVENT":
                subject = str(component.get('SUMMARY', 'Class'))
                dtstart = component.get('DTSTART')
                dtend = component.get('DTEND')
                
                if dtstart and dtend:
                    start = dtstart.dt
                    end = dtend.dt
                    
                    if not isinstance(start, datetime):
                        start = datetime.combine(start, datetime.min.time())
                    if not isinstance(end, datetime):
                        end = datetime.combine(end, datetime.min.time())
                    
                    location = str(component.get('LOCATION', ''))
                    day_of_week = start.weekday()
                    start_time = start.strftime("%H:%M")
                    end_time = end.strftime("%H:%M")
                    
                    add_class(user_id, subject, day_of_week, start_time, end_time, location)
                    count += 1
        
        return count, None
    except Exception as e:
        return -1, str(e)

# ========== BOT FUNCTIONS ==========
def send_message(vk, user_id, text, keyboard=None):
    try:
        if not keyboard:
            keyboard = VkKeyboard().get_empty_keyboard()
        vk.messages.send(user_id=user_id, message=text[:4096], random_id=get_random_id(), keyboard=keyboard)
    except Exception as e:
        logging.error(f"Send error: {e}")

def get_keyboard(lang='en'):
    keyboard = VkKeyboard(one_time=False)
    
    labels = {
        'en': {
            'today': "📅 Today", 'tomorrow': "📅 Tomorrow", 'tasks': "📝 Tasks",
            'focus': "⏱️ Focus", 'stats': "📊 Stats", 'import': "📥 Import", 'help': "❓ Help"
        },
        'ru': {
            'today': "📅 Сегодня", 'tomorrow': "📅 Завтра", 'tasks': "📝 Задачи",
            'focus': "⏱️ Фокус", 'stats': "📊 Статистика", 'import': "📥 Импорт", 'help': "❓ Помощь"
        },
        'zh': {
            'today': "📅 今天", 'tomorrow': "📅 明天", 'tasks': "📝 任务",
            'focus': "⏱️ 专注", 'stats': "📊 统计", 'import': "📥 导入", 'help': "❓ 帮助"
        }
    }
    
    l = labels.get(lang, labels['en'])
    
    keyboard.add_button(l['today'], color=VkKeyboardColor.PRIMARY)
    keyboard.add_button(l['tomorrow'], color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button(l['tasks'], color=VkKeyboardColor.SECONDARY)
    keyboard.add_button(l['focus'], color=VkKeyboardColor.SECONDARY)
    keyboard.add_line()
    keyboard.add_button(l['stats'], color=VkKeyboardColor.POSITIVE)
    keyboard.add_button(l['import'], color=VkKeyboardColor.POSITIVE)
    keyboard.add_line()
    keyboard.add_button(l['help'], color=VkKeyboardColor.PRIMARY)
    
    return keyboard.get_keyboard()

# ========== FOCUS/POMODORO TIMER ==========
active_timers = {}

def start_focus_timer(vk, user_id, subject, duration):
    if user_id in active_timers:
        active_timers[user_id]['cancel'] = True
    
    timer_id = str(uuid.uuid4())[:8]
    active_timers[user_id] = {
        'id': timer_id,
        'subject': subject,
        'duration': duration,
        'start_time': datetime.now(TIMEZONE),
        'cancel': False
    }
    
    lang = get_user_language(user_id)
    
    scheduler.add_job(
        complete_focus,
        'date',
        run_date=datetime.now(TIMEZONE) + timedelta(minutes=duration),
        args=[vk, user_id, timer_id, subject, duration],
        id=timer_id
    )
    
    send_message(vk, user_id, get_response(user_id, 'focus_start', subject=subject, duration=duration), get_keyboard(lang))

def start_pomodoro(vk, user_id, subject, cycles=4):
    if user_id in active_timers:
        active_timers[user_id]['cancel'] = True
    
    timer_id = str(uuid.uuid4())[:8]
    active_timers[user_id] = {
        'id': timer_id,
        'subject': subject,
        'cycles': cycles,
        'current_cycle': 0,
        'cancel': False,
        'type': 'pomodoro'
    }
    
    total_duration = cycles * 30
    lang = get_user_language(user_id)
    
    send_message(vk, user_id, get_response(user_id, 'pomodoro_start', subject=subject, cycles=cycles), get_keyboard(lang))
    
    for i in range(cycles):
        break_time = datetime.now(TIMEZONE) + timedelta(minutes=i * 30 + 25)
        
        scheduler.add_job(
            pomodoro_break_reminder,
            'date',
            run_date=break_time,
            args=[vk, user_id, timer_id, i + 1, cycles],
            id=f"{timer_id}_break_{i}"
        )
    
    scheduler.add_job(
        complete_pomodoro,
        'date',
        run_date=datetime.now(TIMEZONE) + timedelta(minutes=total_duration),
        args=[vk, user_id, timer_id, subject, cycles],
        id=f"{timer_id}_complete"
    )

def pomodoro_break_reminder(vk, user_id, timer_id, cycle, total_cycles):
    if user_id not in active_timers or active_timers[user_id].get('cancel'):
        return
    
    current = active_timers[user_id]
    if current['id'] != timer_id:
        return
    
    current['current_cycle'] = cycle
    lang = get_user_language(user_id)
    
    if cycle % 4 == 0:
        send_message(vk, user_id, get_response(user_id, 'pomodoro_long_break'), get_keyboard(lang))
    else:
        send_message(vk, user_id, get_response(user_id, 'pomodoro_break'), get_keyboard(lang))

def complete_focus(vk, user_id, timer_id, subject, duration):
    if user_id not in active_timers:
        return
    
    current = active_timers[user_id]
    if current.get('cancel') or current['id'] != timer_id:
        return
    
    add_study_session(user_id, subject, duration)
    del active_timers[user_id]
    
    send_message(vk, user_id, get_response(user_id, 'focus_done', subject=subject, duration=duration))

def complete_pomodoro(vk, user_id, timer_id, subject, cycles):
    if user_id not in active_timers:
        return
    
    current = active_timers[user_id]
    if current.get('cancel') or current['id'] != timer_id:
        return
    
    total_duration = cycles * 25
    add_study_session(user_id, subject, total_duration, f"Pomodoro: {cycles} cycles")
    del active_timers[user_id]
    
    send_message(vk, user_id, get_response(user_id, 'pomodoro_done', cycles=cycles))

def stop_timer(vk, user_id):
    if user_id not in active_timers:
        return False
    
    current = active_timers[user_id]
    elapsed = int((datetime.now(TIMEZONE) - current['start_time']).total_seconds() / 60)
    current['cancel'] = True
    del active_timers[user_id]
    
    if elapsed > 0:
        add_study_session(user_id, current.get('subject', 'Study'), elapsed, "Stopped early")
    
    send_message(vk, user_id, get_response(user_id, 'focus_stop', elapsed=elapsed))
    return True

# ========== MAIN MESSAGE HANDLER ==========
def handle_message(vk, user_id, text, attachments=[]):
    if not text:
        return
    
    text = text.strip()
    lang = detect_language(text)
    set_user_language(user_id, lang)
    name = get_user_name(user_id)
    text_lower = text.lower()
    
    # First time user
    if not name and not any(word in text_lower for word in ['my name is', 'call me', 'меня зовут', 'зовут', '我叫', '我的名字是']):
        send_message(vk, user_id, get_response(user_id, 'ask_name'), get_keyboard(lang))
        return
    
    # Extract name (EN, RU, ZH)
    name_match = re.search(r'(?:my name is|call me|меня зовут|зовут|我叫|我的名字是|我是)\s+([A-Za-zА-Яа-я\u4e00-\u9fff]+)', text, re.IGNORECASE)
    if name_match and not name:
        name = name_match.group(1).capitalize()
        set_user_name(user_id, name)
        send_message(vk, user_id, get_response(user_id, 'got_name', name=name), get_keyboard(lang))
        return
    
    # ICS link in text
    if '.ics' in text and ('http://' in text or 'https://' in text):
        url_match = re.search(r'(https?://[^\s]+\.ics)', text)
        if url_match:
            send_message(vk, user_id, get_response(user_id, 'importing'))
            count, error = import_ics_from_link(user_id, url_match.group(1))
            if count > 0:
                send_message(vk, user_id, get_response(user_id, 'import_success', count=count), get_keyboard(lang))
            else:
                send_message(vk, user_id, get_response(user_id, 'import_fail', error=error), get_keyboard(lang))
        return
    
    # File attachments
    ics_files = [att for att in attachments if att.get("type") == "doc" and att["doc"]["title"].endswith(".ics")]
    if ics_files:
        url = ics_files[0]["doc"]["url"]
        send_message(vk, user_id, get_response(user_id, 'importing'))
        count, error = import_ics_from_link(user_id, url)
        if count > 0:
            send_message(vk, user_id, get_response(user_id, 'import_success', count=count), get_keyboard(lang))
        else:
            send_message(vk, user_id, get_response(user_id, 'import_fail', error=error), get_keyboard(lang))
        return
    
    # Help
    help_triggers = {
        'en': ['help', '❓ help'],
        'ru': ['помощь', '❓ помощь'],
        'zh': ['帮助', '❓ 帮助']
    }
    
    if any(text in help_triggers.get(lang, []) or w in text_lower for w in ['help', 'помощь', '帮助']):
        send_message(vk, user_id, get_response(user_id, 'help'), get_keyboard(lang))
        return
    
    # Today button triggers
    today_buttons = {'en': '📅 today', 'ru': '📅 сегодня', 'zh': '📅 今天'}
    tomorrow_buttons = {'en': '📅 tomorrow', 'ru': '📅 завтра', 'zh': '📅 明天'}
    tasks_buttons = {'en': '📝 tasks', 'ru': '📝 задачи', 'zh': '📝 任务'}
    focus_buttons = {'en': '⏱️ focus', 'ru': '⏱️ фокус', 'zh': '⏱️ 专注'}
    stats_buttons = {'en': '📊 stats', 'ru': '📊 статистика', 'zh': '📊 统计'}
    import_buttons = {'en': '📥 import', 'ru': '📥 импорт', 'zh': '📥 导入'}
    
    # Today
    if text == today_buttons.get(lang, '') or any(w in text_lower for w in ['today', 'сегодня', '今天']):
        classes = get_today_classes(user_id)
        if classes:
            weekdays = RESPONSES[lang]['weekdays']
            today_name = weekdays[datetime.now(TIMEZONE).weekday()]
            class_list = "\n".join([f"#{cid} ⏰ {s}-{e} • **{subj}**" + (f" ({loc})" if loc else "") for cid, subj, s, e, loc in classes])
            send_message(vk, user_id, f"📅 *{today_name}*\n\n{class_list}", get_keyboard(lang))
        else:
            send_message(vk, user_id, get_response(user_id, 'no_classes'), get_keyboard(lang))
        return
    
    # Tomorrow
    if text == tomorrow_buttons.get(lang, '') or any(w in text_lower for w in ['tomorrow', 'завтра', '明天']):
        classes = get_tomorrow_classes(user_id)
        if classes:
            weekdays = RESPONSES[lang]['weekdays']
            tomorrow_idx = (datetime.now(TIMEZONE).weekday() + 1) % 7
            tomorrow_name = weekdays[tomorrow_idx]
            class_list = "\n".join([f"#{cid} ⏰ {s}-{e} • **{subj}**" for cid, subj, s, e, loc in classes])
            send_message(vk, user_id, f"📅 *{tomorrow_name}*\n\n{class_list}", get_keyboard(lang))
        else:
            send_message(vk, user_id, get_response(user_id, 'no_classes'), get_keyboard(lang))
        return
    
    # Tasks
    if text == tasks_buttons.get(lang, '') or any(w in text_lower for w in ['tasks', 'задачи', '任务']):
        tasks = get_tasks(user_id)
        if tasks:
            priority_icons = {'high': '🔴', 'medium': '🟡', 'low': '🟢', 'normal': '⚪'}
            task_list = "\n".join([f"{priority_icons.get(p, '⚪')} #{tid} **{task}**\n   📅 {due}" for tid, task, due, r, p in tasks[:10]])
            send_message(vk, user_id, get_response(user_id, 'tasks_list', tasks=task_list), get_keyboard(lang))
        else:
            send_message(vk, user_id, get_response(user_id, 'tasks_empty'), get_keyboard(lang))
        return
    
    # Stats
    if text == stats_buttons.get(lang, '') or 'stats' in text_lower or 'статистика' in text_lower or '统计' in text_lower:
        pending, completed = get_task_stats(user_id)
        total = pending + completed
        rate = round((completed / total * 100)) if total > 0 else 0
        total_study, weekly_study, today_study = get_study_stats(user_id)
        study_hours = total_study // 60
        study_min = total_study % 60
        class_count = get_class_count(user_id)
        goals = get_goals(user_id)
        goals_total = len(goals)
        goals_completed = sum(1 for g in goals if g[3] >= g[2])
        productivity = round((rate * 0.5 + min(total_study / 6000 * 100, 100) * 0.3 + min(class_count / 20 * 100, 100) * 0.2))
        
        send_message(vk, user_id, get_response(user_id, 'stats', 
            completed=completed, total=total, rate=rate,
            study_hours=study_hours, study_min=study_min,
            class_count=class_count,
            goals_completed=goals_completed, goals_total=goals_total,
            productivity=productivity
        ), get_keyboard(lang))
        return
    
    # Focus button
    if text == focus_buttons.get(lang, ''):
        send_message(vk, user_id, get_response(user_id, 'focus_usage'), get_keyboard(lang))
        return
    
    # Import button
    if text == import_buttons.get(lang, ''):
        send_message(vk, user_id, "📥 Send me an .ics file or use /ics [url]", get_keyboard(lang))
        return
    
    # /focus command
    if text_lower.startswith('/focus'):
        parts = text.split()
        if len(parts) >= 3:
            subject = parts[1]
            duration = int(parts[2]) if parts[2].isdigit() else 25
            start_focus_timer(vk, user_id, subject, min(duration, 180))
        elif len(parts) == 2:
            start_focus_timer(vk, user_id, parts[1], 25)
        else:
            send_message(vk, user_id, get_response(user_id, 'focus_usage'), get_keyboard(lang))
        return
    
    # /pomodoro command
    if text_lower.startswith('/pomodoro'):
        parts = text.split()
        subject = parts[1] if len(parts) > 1 else 'Study'
        cycles = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 4
        start_pomodoro(vk, user_id, subject, min(cycles, 8))
        return
    
    # /stop command
    if text_lower.startswith('/stop'):
        stop_timer(vk, user_id)
        return
    
    # /task command
    if text_lower.startswith('/task'):
        match = re.match(r'/task\s+"([^"]+)"\s+(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)(?:\s+(high|medium|low))?', text)
        if match:
            task_name = match.group(1)
            due_date = match.group(2)
            priority = match.group(3) or 'normal'
            add_task(user_id, task_name, due_date, 1, priority)
            send_message(vk, user_id, get_response(user_id, 'task_added', task=task_name, due=due_date, priority=priority), get_keyboard(lang))
        else:
            send_message(vk, user_id, 'Format: /task "Task name" 2026-12-31 [priority]', get_keyboard(lang))
        return
    
    # /done command
    if text_lower.startswith('/done'):
        task_id = int(text.split()[1]) if len(text.split()) > 1 and text.split()[1].isdigit() else None
        if task_id:
            complete_task(user_id, task_id)
            send_message(vk, user_id, get_response(user_id, 'task_completed', task=f"#{task_id}"), get_keyboard(lang))
        else:
            send_message(vk, user_id, "Usage: /done [task_id]\nFind IDs in /tasks", get_keyboard(lang))
        return
    
    # /add command
    if text_lower.startswith('/add'):
        parts = text.split()
        if len(parts) >= 5:
            subject = parts[1]
            day = int(parts[2]) if parts[2].isdigit() and 0 <= int(parts[2]) <= 6 else None
            start = parts[3]
            end = parts[4]
            location = ' '.join(parts[5:]) if len(parts) > 5 else ''
            if day is not None:
                add_class(user_id, subject, day, start, end, location)
                send_message(vk, user_id, f"✅ Added: {subject} on day {day} at {start}-{end}", get_keyboard(lang))
            else:
                send_message(vk, user_id, "Day must be 0-6 (0=Mon)", get_keyboard(lang))
        else:
            send_message(vk, user_id, "Format: /add Subject Day StartTime EndTime\nExample: /add Math 0 09:00 10:30", get_keyboard(lang))
        return
    
    # /delete command
    if text_lower.startswith('/delete'):
        parts = text.split()
        if len(parts) > 1 and parts[1].isdigit():
            delete_class(user_id, int(parts[1]))
            send_message(vk, user_id, get_response(user_id, 'class_deleted'), get_keyboard(lang))
        else:
            send_message(vk, user_id, get_response(user_id, 'delete_usage'), get_keyboard(lang))
        return
    
    # /ics command
    if text_lower.startswith('/ics'):
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            send_message(vk, user_id, get_response(user_id, 'importing'))
            count, error = import_ics_from_link(user_id, parts[1].strip())
            if count > 0:
                send_message(vk, user_id, get_response(user_id, 'import_success', count=count), get_keyboard(lang))
            else:
                send_message(vk, user_id, get_response(user_id, 'import_fail', error=error), get_keyboard(lang))
        else:
            send_message(vk, user_id, "Usage: /ics [url]", get_keyboard(lang))
        return
    
    # /goal command
    if text_lower.startswith('/goal'):
        parts = text.split(maxsplit=2)
        if len(parts) >= 3:
            goal = parts[1]
            target = int(parts[2]) if parts[2].isdigit() else 10
            add_goal(user_id, goal, target)
            send_message(vk, user_id, get_response(user_id, 'goal_set', goal=goal, target=target, unit='hours'), get_keyboard(lang))
        else:
            send_message(vk, user_id, "Usage: /goal [description] [target_hours]", get_keyboard(lang))
        return
    
    # /goals command
    if text_lower == '/goals':
        goals = get_goals(user_id)
        if goals:
            msg = "🎯 *Goals*\n\n"
            for gid, goal, target, current, unit in goals:
                pct = round(current / target * 100) if target > 0 else 0
                bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
                msg += f"*{goal}*\n  {current}/{target} {unit} | {pct}%\n  [{bar}]\n\n"
            send_message(vk, user_id, msg, get_keyboard(lang))
        else:
            send_message(vk, user_id, get_response(user_id, 'no_goals'), get_keyboard(lang))
        return
    
    # /language command
    if text_lower.startswith('/language'):
        parts = text.split()
        if len(parts) > 1 and parts[1].lower() in ['en', 'ru', 'zh']:
            set_user_language(user_id, parts[1].lower())
            lang_names = {'en': 'English', 'ru': 'Русский', 'zh': '中文'}
            send_message(vk, user_id, get_response(user_id, 'language_changed', language=lang_names[parts[1].lower()]), get_keyboard(parts[1].lower()))
        return
    
    # /time command
    if text_lower == '/time':
        now = datetime.now(TIMEZONE)
        send_message(vk, user_id, get_response(user_id, 'time', time=now.strftime("%H:%M")), get_keyboard(lang))
        return
    
    # /joke command
    if text_lower == '/joke':
        jokes = {
            'en': ["Why don't scientists trust atoms? They make up everything!", "Parallel lines have so much in common. It's a shame they'll never meet."],
            'ru': ["Почему программисты путают Хэллоуин с Рождеством? 31 Oct = 25 Dec!", "Колобок повесился."],
            'zh': ["为什么科学家不相信原子？因为它们构成一切！", "平行线有那么多共同点。可惜它们永远不会相遇。"]
        }
        send_message(vk, user_id, f"😂 {random.choice(jokes.get(lang, jokes['en']))}", get_keyboard(lang))
        return
    
    # Greeting
    greetings = {'en': ['hello', 'hi', 'hey'], 'ru': ['привет', 'здравствуй'], 'zh': ['你好', '嗨', '嘿']}
    if any(w in text_lower for w in greetings.get(lang, [])):
        msg = {
            'en': f"👋 Hey {name}! How can I help you today?" if name else "👋 Hello! What's your name?",
            'ru': f"👋 Привет {name}! Чем могу помочь?" if name else "👋 Привет! Как тебя зовут?",
            'zh': f"👋 你好 {name}！今天我能帮你什么？" if name else "👋 你好！你叫什么名字？"
        }
        send_message(vk, user_id, msg.get(lang, msg['en']), get_keyboard(lang))
        return
    
    # Default
    if name:
        responses_list = {
            'en': [f"How can I help, {name}?", f"Hey {name}! Check /stats!", f"What would you like to do?"],
            'ru': [f"Чем помочь, {name}?", f"Привет {name}! Проверь /stats!", f"Что хочешь сделать?"],
            'zh': [f"需要帮助吗, {name}？", f"嘿 {name}！查看 /stats！", f"你想做什么？"]
        }
        send_message(vk, user_id, random.choice(responses_list.get(lang, responses_list['en'])), get_keyboard(lang))
    else:
        send_message(vk, user_id, get_response(user_id, 'ask_name'), get_keyboard(lang))

# ========== REMINDER SYSTEM ==========
def check_reminders(vk):
    try:
        conn = sqlite3.connect("assistant.db")
        c = conn.cursor()
        now = datetime.now(TIMEZONE)
        current_day = now.weekday()
        
        c.execute("SELECT DISTINCT user_id FROM schedule")
        users = c.fetchall()
        
        for (user_id,) in users:
            name = get_user_name(user_id) or "student"
            lang = get_user_language(user_id)
            
            c.execute("SELECT subject, start_time FROM schedule WHERE user_id = ? AND day = ?", (user_id, current_day))
            classes = c.fetchall()
            
            for subject, start_time in classes:
                hour, minute = map(int, start_time.split(':'))
                class_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                minutes_until = (class_time - now).total_seconds() / 60
                
                if 60 <= minutes_until <= 90:
                    key = f"reminder_{user_id}_{current_day}_{start_time}"
                    c.execute("SELECT sent FROM reminders WHERE key = ?", (key,))
                    if not c.fetchone():
                        msgs = {
                            'en': f"⏰ {name}, reminder! {subject} in {int(minutes_until)} min at {start_time}!",
                            'ru': f"⏰ {name}, напоминание! {subject} через {int(minutes_until)} мин в {start_time}!",
                            'zh': f"⏰ {name}，提醒！{subject} 在 {int(minutes_until)} 分钟后 ({start_time})！"
                        }
                        send_message(vk, user_id, msgs.get(lang, msgs['en']))
                        c.execute("INSERT OR IGNORE INTO reminders (key, sent) VALUES (?, 1)", (key,))
                        conn.commit()
        
        conn.close()
    except Exception as e:
        logging.error(f"Reminder error: {e}")

# ========== MAIN ==========
scheduler = BackgroundScheduler()

def main():
    print("=" * 60)
    print("🤖 VITA BOT - Multilingual Study Assistant")
    print("=" * 60)
    print("✅ Features:")
    print("   • Schedule management with reminders")
    print("   • Task tracking with priorities")
    print("   • Focus/Pomodoro timers")
    print("   • Goal setting & tracking")
    print("   • ICS calendar import")
    print("   • Languages: English, Русский, 中文")
    print("=" * 60)
    
    try:
        vk_session = vk_api.VkApi(token=VK_TOKEN)
        vk = vk_session.get_api()
        
        scheduler.add_job(lambda: check_reminders(vk), 'interval', minutes=5)
        scheduler.start()
        
        print("✅ Bot is running!")
        print("💬 Listening for messages...\n")
        
        longpoll = VkBotLongPoll(vk_session, GROUP_ID)
        
        for event in longpoll.listen():
            if event.type == VkBotEventType.MESSAGE_NEW:
                try:
                    msg = event.object.message
                    user_id = msg["from_id"]
                    text = msg.get("text", "").strip()
                    attachments = msg.get("attachments", [])
                    
                    if text or attachments:
                        handle_message(vk, user_id, text, attachments)
                        
                except Exception as e:
                    logging.error(f"Error processing message: {e}")
                    
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped")
        scheduler.shutdown()
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        scheduler.shutdown()

if __name__ == "__main__":
    main()
