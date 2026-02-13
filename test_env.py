#!/usr/bin/env python3
"""Тестовый скрипт для проверки загрузки переменных окружения"""

import os
import sys

print("=" * 50)
print("Проверка переменных окружения")
print("=" * 50)

# Загрузка из .env
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ Загружено через python-dotenv")
except ImportError:
    print("⚠️ python-dotenv не установлен, пробую загрузить вручную...")
    if os.path.exists('.env'):
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")
        print("✅ Загружено вручную из .env")
    else:
        print("❌ Файл .env не найден")

# Проверка переменных
print("\nПроверка переменных:")
print("-" * 50)

token = os.getenv('TELEGRAM_BOT_TOKEN', '')
chat_id = os.getenv('TELEGRAM_CHAT_ID', '')

if token:
    print(f"✅ TELEGRAM_BOT_TOKEN: {token[:20]}...{token[-10:]}")
else:
    print("❌ TELEGRAM_BOT_TOKEN: НЕ УСТАНОВЛЕН")

if chat_id:
    print(f"✅ TELEGRAM_CHAT_ID: {chat_id}")
else:
    print("❌ TELEGRAM_CHAT_ID: НЕ УСТАНОВЛЕН")

print("\n" + "=" * 50)

if token and chat_id:
    print("✅ Все переменные установлены! Можно запускать бота.")
    sys.exit(0)
else:
    print("❌ Не все переменные установлены!")
    print("\nРешение:")
    print("1. Убедитесь, что файл .env существует")
    print("2. Или установите переменные: export TELEGRAM_BOT_TOKEN='...'")
    sys.exit(1)
