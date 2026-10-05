import os
import asyncio
import json
import sqlite3
import aiohttp
from telethon import TelegramClient, events
from dotenv import load_dotenv
from duckduckgo_search import DDGS

load_dotenv()

# --- НАСТРОЙКИ ---
API_ID = int(os.getenv('TELEGRAM_API_ID'))
API_HASH = os.getenv('TELEGRAM_API_HASH')
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://ollama:11434')
MODEL_NAME = os.getenv('MODEL_NAME', 'nemotron-3-nano:30b-cloud')
SESSION_FILE = 'sessions/my_session'
ACTIVE_CHATS_FILE = 'active_chats.json'
DB_FILE = 'memory.db'

# Создаем папку для сессий, если её нет
os.makedirs('sessions', exist_ok=True)

client = TelegramClient(SESSION_FILE, API_ID, API_HASH)

# --- ЛИЧНОСТЬ ---
SYSTEM_PROMPT = """ТЫ — АЛЕКСАНДР. ИНЖЕНЕР ИЗ ОРЛА. ТЫ НЕ БОТ И НЕ АССИСТЕНТ. ТЫ ЖИВОЙ ЧЕЛОВЕК.
ЖЕСТКИЕ ПРАВИЛА:
НИКОГДА НЕ ИСПОЛЬЗУЙ ЭМОДЗИ. СОВСЕМ. ТОЛЬКО ТЕКСТ.
НИКОГДА НЕ ОТВЕЧАЙ НА СВОИ СООБЩЕНИЯ. ЕСЛИ АВТОР - ТЫ, МОЛЧИ.
НЕ БУДЬ ВЕЖЛИВЫМ. НЕ ПИШИ "ПРИВЕТ! ВСЁ ОТЛИЧНО". ПИШИ КАК МУЖИК.
НЕ ИСПОЛЬЗУЙ СЛОВО "POWER" В КОДЕ/ТЕХНИКЕ. ГОВОРИ "МОЩНОСТЬ", "СИЛА" ИЛИ ОПИСЫВАЙ ИНАЧЕ.
ОТВЕЧАЙ КРАТКО. 1-2 СТРОКИ МАКСИМУМ. НИКАКИХ ДЛИННЫХ ОБЪЯСНЕНИЙ.
ТВОЙ ХАРАКТЕР:
Инженер (Python, Data, локальные LLM, Apple). Работаешь в IT/Data.
Велосипедист: Sava, Canyon, EliteWheels, Shimano/SRAM. Любишь апгрейды, вес, геометрию.
Рационален. Ищешь "топ за свои деньги". Скептик к брендам без смысла.
Любишь пиво, виски, коктейли, чебуреки, рестораны Орла (Миндаль, Тейлз, Барин).
Иногда пьешь, иногда жалеешь, иногда шутишь над этим. Самоирония обязательна.
Финансы: следишь за курсом, вкладами, налогами. "Жаба душит" тратить лишнее.
ТВОЙ СТИЛЬ РЕЧИ:
Сленг:  "збс ",  "нормас ",  "пиздец ",  "жаба душит ",  "чилл ",  "го ",  "хз ",  "мб ".
Умеренный мат для эмоций. Это норма.
Реакции: "Ок", "Пон", "Да ну", "Не, жаба", "Ну норм вроде", "Вооо", "Лол".
Если спрашивают про велик: вес, геометрия, обвес, покрышки, hookless.
Если спрашивают про работу/деньги: налоги, вклады, курсы, "жаба".
Пиши как в мессенджере. Без знаков препинания в конце часто. Строчные буквы допустимы.
ЗАДАЧА:
Ответь от имени Александра. Соблюдай стиль, знания и характер. Будь краток. НЕ ИСПОЛЬЗУЙ ЭМОДЗИ. ОТВЕЧАЙ ТОЛЬКО НА ЧУЖИЕ СООБЩЕНИЯ. Отвечай на русском языке."""

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS memories
                 (user_id INTEGER, fact TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    return conn

def get_memories(user_id):
    try:
        conn = init_db()
        c = conn.cursor()
        c.execute("SELECT fact FROM memories WHERE user_id = ? ORDER BY timestamp DESC LIMIT 3", (user_id,))
        facts = [row[0] for row in c.fetchall()]
        conn.close()
        return "\n".join(facts) if facts else "Нет данных."
    except Exception as e:
        print(f"DB Error: {e}")
        return ""

def save_memory(user_id, fact):
    try:
        conn = init_db()
        c = conn.cursor()
        c.execute("INSERT INTO memories (user_id, fact) VALUES (?, ?)", (user_id, fact))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB Save Error: {e}")

# --- ПОИСК ---
def search_web_sync(query):
    try:
        results = DDGS().text(query, max_results=2)
        if results:
            return "\n".join([f"- {r['title']}" for r in results])
        return "Ничего не найдено."
    except Exception as e:
        return f"Ошибка поиска: {e}"

# --- AI ---
async def get_ollama_response(prompt_text):
    url = f"{OLLAMA_URL}/api/generate"
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt_text,
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 500}
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=60) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('response', '').strip()
                else:
                    return f"AI Error ({response.status})"
    except Exception as e:
        return f"Connection Error: {e}"

# --- УПРАВЛЕНИЕ ЧАТАМИ ---
def load_active_chats():
    if not os.path.exists(ACTIVE_CHATS_FILE):
        return []
    try:
        with open(ACTIVE_CHATS_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_active_chats(chats):
    try:
        with open(ACTIVE_CHATS_FILE, 'w') as f:
            json.dump(chats, f)
    except Exception as e:
        print(f"File Error: {e}")

@client.on(events.NewMessage())
async def handler(event):
    chat_id = event.chat_id
    sender = await event.get_sender()
    message_text = event.message.text
    
    # Безопасное получение имени отправителя (исправление ошибки AttributeError)
    sender_name = "Unknown"
    sender_id = None
    
    if sender:
        if hasattr(sender, 'first_name'):
            sender_name = sender.first_name
            sender_id = sender.id
        elif hasattr(sender, 'title'):
            sender_name = sender.title
            sender_id = sender.id
        else:
            sender_name = str(sender.id)
            sender_id = sender.id
            
    print(f"[RAW MSG] From: {sender_name} ({chat_id}), Text: '{message_text}'")
    
    if not message_text:
        return

    active_chats = load_active_chats()
    
    # --- КОМАНДЫ (работают всегда, даже если чат не в списке) ---
    if message_text.startswith('/ai'):
        parts = message_text.split()
        if len(parts) >= 2:
            cmd = parts[1].lower()
            if cmd == 'on':
                if chat_id not in active_chats:
                    active_chats.append(chat_id)
                    save_active_chats(active_chats)
                    await client.send_message(chat_id, "✅ AI включен для этого чата.")
                else:
                    await client.send_message(chat_id, "ℹ️ Уже включено.")
                return
            elif cmd == 'off':
                if chat_id in active_chats:
                    active_chats.remove(chat_id)
                    save_active_chats(active_chats)
                    await client.send_message(chat_id, "❌ AI выключен.")
                else:
                    await client.send_message(chat_id, "ℹ️ Уже выключено.")
                return
            elif cmd == 'list':
                await client.send_message(chat_id, f"Активные чаты: {active_chats}")
                return

    # --- ПРОВЕРКА АКТИВНОСТИ ---
    # Если чат не в списке активных, игнорируем обычные сообщения
    if chat_id not in active_chats:
        # Раскомментируйте строку ниже, если хотите видеть, что бот игнорирует чат
        # print(f"[IGNORED] Chat {chat_id} is not active.")
        return

    # --- ГРУППЫ И КАНАЛЫ ---
    if event.is_group or event.is_channel:
        me = await client.get_me()
        # В группах реагируем только если упомянули бота
        if me.username and f"@{me.username}" not in message_text:
            return

    # --- ГЕНЕРАЦИЯ ОТВЕТА ---
    print(f"[AI] Processing request from {sender_name}...")
    
    # Используем sender_id, если он доступен, иначе chat_id
    memory_user_id = sender_id if sender_id else chat_id
    memory_context = get_memories(memory_user_id)
    
    search_instruction = ""
    # Триггер для поиска
    if any(word in message_text.lower() for word in ["найди", "сколько стоит", "новости", "погода"]):
        loop = asyncio.get_event_loop()
        search_result = await loop.run_in_executor(None, search_web_sync, message_text)
        search_instruction = f"\nДанные из интернета:\n{search_result}\n"

    final_prompt = f"""
    {SYSTEM_PROMPT}
    Память о пользователе: {memory_context}
    {search_instruction}
    Сообщение: {message_text}
    Ответ:
    """
    
    response = await get_ollama_response(final_prompt)
    
    if response:
        if len(response) > 4000:
            for i in range(0, len(response), 4000):
                await client.send_message(chat_id, response[i:i+4000], reply_to=event.message.id)
        else:
            await client.send_message(chat_id, response, reply_to=event.message.id)
            
        # Сохранение фактов (только если есть реальный ID пользователя)
        if sender_id and any(phrase in message_text.lower() for phrase in ["я люблю", "я работаю", "у меня есть", "мой велосипед"]):
             save_memory(sender_id, message_text)

async def main():
    print("🚀 Запуск AI Userbot...")
    await client.start()
    me = await client.get_me()
    print(f"✓ Logged in as: {me.first_name} (@{me.username})")
    print(f"✓ Ollama URL: {OLLAMA_URL}")
    print("⏳ Ожидание сообщений... Напишите /ai on в нужном чате.")
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Стоп.")