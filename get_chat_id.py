#!/usr/bin/env python3
"""
Скрипт для получения Chat ID
"""

import os
import requests

# Загрузка переменных из .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    if os.path.exists('.env'):
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')

if not TELEGRAM_BOT_TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN не установлен!")
    print("Установите: export TELEGRAM_BOT_TOKEN='ваш_токен'")
    exit(1)

print("=" * 60)
print("📱 ПОЛУЧЕНИЕ CHAT ID ДЛЯ TELEGRAM БОТА")
print("=" * 60)
print("\n⚠️ ВАЖНО: Chat ID - это НЕ ID бота!")
print("   Chat ID - это ID вашего личного чата или канала")
print("\n" + "-" * 60)
print("ИНСТРУКЦИЯ:")
print("-" * 60)
print("\n1. Откройте Telegram")
print("2. Найдите вашего бота (поиск по имени бота)")
print("3. Напишите боту ЛЮБОЕ сообщение (например: /start или 'Привет')")
print("4. Затем запустите этот скрипт снова")
print("\n" + "-" * 60)
print("ПОЛУЧЕНИЕ ОБНОВЛЕНИЙ:")
print("-" * 60)

response = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates")
if response.status_code == 200:
    data = response.json()
    if data.get('ok'):
        updates = data.get('result', [])
        if updates:
            print("\n✅ Найденные чаты:\n")
            seen_chats = set()
            for update in updates:
                if 'message' in update:
                    chat = update['message']['chat']
                    chat_id = chat['id']
                    if chat_id not in seen_chats:
                        seen_chats.add(chat_id)
                        chat_type = chat.get('type', 'unknown')
                        if chat_type == 'private':
                            name = chat.get('first_name', '') + ' ' + (chat.get('last_name', '') or '')
                            username = chat.get('username', '')
                            print(f"  👤 ЛИЧНЫЙ ЧАТ")
                            print(f"     Chat ID: {chat_id}")
                            print(f"     Имя: {name.strip() or 'Не указано'}")
                            if username:
                                print(f"     Username: @{username}")
                            print()
                        elif chat_type == 'group':
                            print(f"  👥 ГРУППА")
                            print(f"     Chat ID: {chat_id}")
                            print(f"     Название: {chat.get('title', 'Не указано')}")
                            print()
                        elif chat_type == 'channel':
                            print(f"  📢 КАНАЛ")
                            print(f"     Chat ID: {chat_id}")
                            print(f"     Название: {chat.get('title', 'Не указано')}")
                            print()
            
            if seen_chats:
                print("-" * 60)
                print("✅ ИСПОЛЬЗУЙТЕ ОДИН ИЗ ЭТИХ CHAT ID:")
                print("-" * 60)
                for chat_id in seen_chats:
                    print(f"export TELEGRAM_CHAT_ID=\"{chat_id}\"")
                print("\nИли обновите файл .env:")
                print(f"TELEGRAM_CHAT_ID={list(seen_chats)[0]}")
            else:
                print("\n⚠️ Сообщений не найдено.")
        else:
            print("\n⚠️ Сообщений не найдено.")
            print("\n📝 ДЕЙСТВИЯ:")
            print("   1. Откройте Telegram")
            print("   2. Найдите вашего бота")
            print("   3. Напишите ему любое сообщение")
            print("   4. Запустите этот скрипт снова")
    else:
        print(f"\n❌ Ошибка API: {data}")
else:
    print(f"\n❌ Ошибка подключения: HTTP {response.status_code}")
    print(f"Ответ: {response.text[:200]}")
