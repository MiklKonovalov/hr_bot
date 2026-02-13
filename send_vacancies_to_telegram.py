#!/usr/bin/env python3
"""
Упрощенный скрипт для автоматической отправки вакансий в Telegram
без необходимости запуска бота в режиме polling
"""

import argparse
import json
import os
import requests
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Загрузка переменных из .env файла (если есть)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv не установлен, используем переменные окружения

# Конфигурация
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
VACANCIES_FILE = 'product_manager_vacancies.json'
# Максимальный возраст вакансий в днях при отправке без --refresh (только свежие)
MAX_DAYS_OLD_DEFAULT = 3


def get_vacancy_description(vacancy_url: str) -> Optional[str]:
    """Получение описания вакансии из HH API"""
    try:
        if 'hh.ru/vacancy/' in vacancy_url:
            vacancy_id = vacancy_url.split('/vacancy/')[-1].split('?')[0]
            api_url = f"https://api.hh.ru/vacancies/{vacancy_id}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = requests.get(api_url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                description = data.get('description', '')
                import re
                description = re.sub(r'<[^>]+>', '', description)
                return description[:2000]
    except Exception as e:
        print(f"⚠️ Ошибка при получении описания: {e}")
    return None


def generate_cover_letter(vacancy_title: str, company: str, description: str) -> str:
    """Генерация сопроводительного письма"""
    keywords = []
    if description:
        desc_lower = description.lower()
        tech_keywords = ['agile', 'scrum', 'kanban', 'b2b', 'b2c', 'saas', 'api', 'ux', 'ui', 'analytics', 'метрики', 'аналитика']
        for keyword in tech_keywords:
            if keyword in desc_lower:
                keywords.append(keyword)
    
    letter = f"""Здравствуйте!

Меня заинтересовала вакансия "{vacancy_title}" в компании {company}. 

"""
    
    if keywords:
        letter += f"Я вижу, что в вакансии упоминаются следующие технологии и подходы: {', '.join(keywords[:5])}. "
    
    letter += """Я имею опыт работы в продуктовой разработке и управления продуктами, что соответствует требованиям данной позиции.

Буду рад обсудить, как мой опыт может быть полезен для вашей команды. Готов предоставить дополнительную информацию и ответить на ваши вопросы.

С уважением,
[Ваше имя]"""
    
    return letter


def format_vacancy_message(vacancy: Dict) -> str:
    """Форматирование сообщения о вакансии"""
    message = f"""🎯 <b>{vacancy['title']}</b>

🏢 Компания: {vacancy['company']}
📍 Локация: {vacancy['location']}
💰 Зарплата: {vacancy['salary']}
🔗 Ссылка: {vacancy['url']}
📅 Источник: {vacancy['source']}

❓ <b>Необходимо ли составить сопроводительное письмо?</b>"""
    
    return message


def send_message_with_buttons(text: str, buttons: List[List[Dict]]) -> bool:
    """Отправка сообщения с inline кнопками"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    keyboard = {
        "inline_keyboard": buttons
    }
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": keyboard
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return True
        else:
            print(f"❌ Ошибка API: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Ошибка при отправке: {e}")
        return False


def send_cover_letter(vacancy: Dict, cover_letter: str) -> bool:
    """Отправка сопроводительного письма"""
    message = f"""📝 <b>Сопроводительное письмо</b>

<b>Вакансия:</b> {vacancy['title']}
<b>Компания:</b> {vacancy['company']}

─────────────────────

{cover_letter}

─────────────────────
<b>Ссылка на вакансию:</b> {vacancy['url']}"""
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Ошибка при отправке письма: {e}")
        return False


def _parse_published_date(published_str: str) -> Optional[datetime]:
    """Извлечь дату публикации из строки (ISO или HH format)."""
    if not published_str:
        return None
    try:
        # HH: "2026-02-11T18:39:21+0300"
        s = published_str.strip().split('+')[0].split('Z')[0]
        if 'T' in s:
            s = s.split('T')[0]
        return datetime.strptime(s, '%Y-%m-%d')
    except (ValueError, TypeError):
        return None


def _is_vacancy_within_days(vacancy: Dict, max_days: int) -> bool:
    """Проверить, что вакансия опубликована не более max_days дней назад."""
    if max_days is None or max_days <= 0:
        return True
    pub = _parse_published_date(vacancy.get('published', ''))
    if pub is None:
        return True  # без даты не отфильтровываем
    limit = datetime.now().date() - timedelta(days=max_days)
    return pub.date() >= limit


def refresh_vacancies_file() -> bool:
    """Обновить файл вакансий через ios_vacancies_finder (актуальные с HH и Habr)."""
    try:
        from ios_vacancies_finder import ProductManagerVacancyFinder
        finder = ProductManagerVacancyFinder()
        finder.find_all_vacancies()
        finder.save_to_json(VACANCIES_FILE)
        return True
    except Exception as e:
        print(f"⚠️ Не удалось обновить список вакансий: {e}")
        return False


def load_vacancies(max_days_old: Optional[int] = None) -> List[Dict]:
    """Загрузка вакансий из JSON. Если задан max_days_old — только за последние N дней."""
    try:
        with open(VACANCIES_FILE, 'r', encoding='utf-8') as f:
            vacancies = json.load(f)
    except FileNotFoundError:
        print(f"❌ Файл {VACANCIES_FILE} не найден")
        return []
    except json.JSONDecodeError:
        print(f"❌ Ошибка при чтении {VACANCIES_FILE}")
        return []

    if max_days_old is not None and max_days_old > 0:
        filtered = [v for v in vacancies if _is_vacancy_within_days(v, max_days_old)]
        if len(filtered) < len(vacancies):
            print(f"📅 Отобрано вакансий за последние {max_days_old} дн.: {len(filtered)} из {len(vacancies)}")
        return filtered
    return vacancies


def get_vacancy_id(vacancy_url: str) -> str:
    """Извлечение ID вакансии из URL для callback_data"""
    try:
        if 'hh.ru/vacancy/' in vacancy_url:
            return vacancy_url.split('/vacancy/')[-1].split('?')[0]
        # Для других источников используем хеш
        import hashlib
        return hashlib.md5(vacancy_url.encode()).hexdigest()[:16]
    except:
        return str(hash(vacancy_url))[:16]


def send_all_vacancies(refresh: bool = False, max_days_old: Optional[int] = MAX_DAYS_OLD_DEFAULT):
    """Отправка вакансий. refresh: обновить список с HH/Habr перед отправкой; max_days_old: только вакансии за последние N дней (None = не фильтровать)."""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ Ошибка: TELEGRAM_BOT_TOKEN не установлен!")
        return
    
    if not TELEGRAM_CHAT_ID:
        print("❌ Ошибка: TELEGRAM_CHAT_ID не установлен!")
        return
    
    if refresh:
        print("🔄 Обновляю список вакансий с hh.ru и career.habr.com...")
        if not refresh_vacancies_file():
            print("⚠️ Продолжаю отправку из существующего файла.")
        else:
            print("✅ Список вакансий обновлён.")
        # После обновления отправляем все найденные (не фильтруем по дате)
        max_days_old = None
    
    vacancies = load_vacancies(max_days_old=max_days_old)
    
    if not vacancies:
        if not refresh and max_days_old:
            print(f"❌ Нет вакансий за последние {max_days_old} дн. в файле {VACANCIES_FILE}")
            print("   Запустите с обновлением: python3 send_vacancies_to_telegram.py --refresh")
            print("   или сначала: python3 ios_vacancies_finder.py")
        else:
            print("❌ Нет вакансий для отправки")
        return
    
    print(f"📤 Отправляю {len(vacancies)} вакансий...")
    
    for i, vacancy in enumerate(vacancies, 1):
        message = format_vacancy_message(vacancy)
        
        # Используем ID вместо полного URL (ограничение Telegram - 64 байта)
        vacancy_id = get_vacancy_id(vacancy['url'])
        
        # Создаем кнопки
        buttons = [[
            {
                "text": "✅ Да, составить",
                "callback_data": f"yes_{vacancy_id}"
            },
            {
                "text": "❌ Нет",
                "callback_data": f"no_{vacancy_id}"
            }
        ]]
        
        if send_message_with_buttons(message, buttons):
            print(f"✅ [{i}/{len(vacancies)}] Вакансия отправлена: {vacancy['title']} в {vacancy['company']}")
        else:
            print(f"❌ [{i}/{len(vacancies)}] Ошибка при отправке: {vacancy['title']}")
        
        time.sleep(1)  # Задержка между отправками
    
    print(f"\n✅ Все вакансии отправлены!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Отправка вакансий в Telegram. По умолчанию отправляются только вакансии за последние 3 дня из файла."
    )
    parser.add_argument(
        "--refresh", "-r",
        action="store_true",
        help="Сначала обновить список вакансий с hh.ru и career.habr.com, затем отправить (актуальные вакансии на сегодня)"
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=MAX_DAYS_OLD_DEFAULT,
        metavar="N",
        help=f"Отправлять только вакансии за последние N дней (по умолчанию {MAX_DAYS_OLD_DEFAULT}). Игнорируется при --refresh"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Отправить все вакансии из файла без фильтра по дате (без обновления файла)"
    )
    args = parser.parse_args()
    max_days = None if args.all else args.days
    if args.refresh:
        max_days = None  # после refresh отправляем все найденные
    send_all_vacancies(refresh=args.refresh, max_days_old=max_days)
