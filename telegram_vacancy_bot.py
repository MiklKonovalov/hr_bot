#!/usr/bin/env python3
"""
Скрипт для отправки вакансий в Telegram-канал
с возможностью генерации сопроводительного письма
"""

import json
import os
import re
import requests
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, JobQueue
import asyncio
import os
import tempfile
from datetime import datetime

# Загрузка переменных из .env файла (если есть)
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ Переменные загружены из .env файла")
except ImportError:
    # Если python-dotenv не установлен, пытаемся загрузить вручную
    try:
        if os.path.exists('.env'):
            with open('.env', 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ[key.strip()] = value.strip().strip('"').strip("'")
            print("✅ Переменные загружены из .env файла (вручную)")
    except Exception as e:
        print(f"⚠️ Не удалось загрузить .env файл: {e}")

# Конфигурация - переменные будут загружены после импорта dotenv
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')  # ID канала или чата
VACANCIES_FILE = 'product_manager_vacancies.json'
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')  # Опционально, для генерации письма
HH_ACCESS_TOKEN = os.getenv('HH_ACCESS_TOKEN', '')  # Токен доступа к HH API для откликов

# Перезагружаем переменные после загрузки .env
if not TELEGRAM_BOT_TOKEN:
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
if not TELEGRAM_CHAT_ID:
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')


class TelegramVacancyBot:
    def __init__(self):
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.vacancies_file = VACANCIES_FILE
        self.openai_api_key = OPENAI_API_KEY
        self.hh_access_token = HH_ACCESS_TOKEN  # Токен доступа к HH API
        self.resumes = {}  # Хранилище резюме: {user_id: resume_text}
        self.user_positions = {}  # Хранилище должностей: {user_id: position}
        self.user_subscriptions = {}  # Подписки пользователей: {user_id: {'position': str, 'active': bool}}
        self.fresh_vacancies = []  # Хранилище свежих вакансий за сегодня
        self.user_sent_fresh_vacancies = {}  # Отслеживание отправленных свежих вакансий: {user_id: set(vacancy_urls)}
        self.resumes_dir = 'resumes'  # Директория для сохранения резюме
        self.sent_vacancies_file = 'sent_vacancies.json'  # Файл для хранения отправленных вакансий
        self.users_data_file = 'users_data.json'  # Файл для хранения данных пользователей
        self.fresh_vacancies_file = 'fresh_vacancies.json'  # Файл для хранения свежих вакансий
        self.user_sent_fresh_file = 'user_sent_fresh.json'  # Файл для отслеживания отправленных свежих вакансий
        # Создаем директорию для резюме, если её нет
        if not os.path.exists(self.resumes_dir):
            os.makedirs(self.resumes_dir)
        
        # Загружаем список отправленных вакансий
        self.sent_vacancies = self._load_sent_vacancies()
        
        # Загружаем данные пользователей
        self._load_users_data()
        
        # Загружаем свежие вакансии
        self._load_fresh_vacancies()
        
        # Загружаем данные об отправленных свежих вакансиях пользователям
        self._load_user_sent_fresh()
        
        # Периодическое сканирование будет запущено через post_init после создания приложения
        
    def load_vacancies(self) -> List[Dict]:
        """Загрузка вакансий из JSON файла"""
        try:
            with open(self.vacancies_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"❌ Файл {self.vacancies_file} не найден")
            return []
        except json.JSONDecodeError:
            print(f"❌ Ошибка при чтении {self.vacancies_file}")
            return []
    
    def _load_sent_vacancies(self) -> set:
        """Загрузка списка отправленных вакансий (URL)"""
        try:
            if os.path.exists(self.sent_vacancies_file):
                with open(self.sent_vacancies_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return set(data.get('urls', []))
            return set()
        except Exception as e:
            print(f"⚠️ Ошибка при загрузке списка отправленных вакансий: {e}")
            return set()
    
    def _save_sent_vacancy(self, vacancy_url: str):
        """Сохранение URL отправленной вакансии"""
        try:
            self.sent_vacancies.add(vacancy_url)
            data = {
                'urls': list(self.sent_vacancies),
                'last_updated': datetime.now().isoformat()
            }
            with open(self.sent_vacancies_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Ошибка при сохранении отправленной вакансии: {e}")
    
    def _is_vacancy_sent(self, vacancy_url: str) -> bool:
        """Проверка, была ли вакансия уже отправлена"""
        if not vacancy_url:
            return False  # Вакансии без URL считаем новыми
        # Нормализуем URL (убираем параметры запроса для сравнения)
        normalized_url = vacancy_url.split('?')[0].rstrip('/')
        original_url = vacancy_url.rstrip('/')
        return normalized_url in self.sent_vacancies or original_url in self.sent_vacancies
    
    def _load_users_data(self):
        """Загрузка данных пользователей из файла"""
        try:
            if os.path.exists(self.users_data_file):
                with open(self.users_data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.user_positions = data.get('positions', {})
                    self.user_subscriptions = data.get('subscriptions', {})
                    # Конвертируем ключи в int
                    self.user_positions = {int(k): v for k, v in self.user_positions.items()}
                    self.user_subscriptions = {int(k): v for k, v in self.user_subscriptions.items()}
            else:
                self.user_positions = {}
                self.user_subscriptions = {}
        except Exception as e:
            print(f"⚠️ Ошибка при загрузке данных пользователей: {e}")
            self.user_positions = {}
            self.user_subscriptions = {}
    
    def _save_users_data(self):
        """Сохранение данных пользователей в файл"""
        try:
            data = {
                'positions': {str(k): v for k, v in self.user_positions.items()},
                'subscriptions': {str(k): v for k, v in self.user_subscriptions.items()},
                'last_updated': datetime.now().isoformat()
            }
            with open(self.users_data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Ошибка при сохранении данных пользователей: {e}")
    
    def _load_fresh_vacancies(self):
        """Загрузка свежих вакансий из файла"""
        try:
            if os.path.exists(self.fresh_vacancies_file):
                with open(self.fresh_vacancies_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.fresh_vacancies = data.get('vacancies', [])
                    # Фильтруем только сегодняшние вакансии
                    today = datetime.now().date()
                    self.fresh_vacancies = [
                        v for v in self.fresh_vacancies 
                        if self._is_vacancy_from_today(v.get('published', ''), today)
                    ]
                    print(f"✅ Загружено {len(self.fresh_vacancies)} свежих вакансий за сегодня")
            else:
                self.fresh_vacancies = []
        except Exception as e:
            print(f"⚠️ Ошибка при загрузке свежих вакансий: {e}")
            self.fresh_vacancies = []
    
    def _save_fresh_vacancies(self):
        """Сохранение свежих вакансий в файл"""
        try:
            data = {
                'vacancies': self.fresh_vacancies,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.fresh_vacancies_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Ошибка при сохранении свежих вакансий: {e}")
    
    def _load_user_sent_fresh(self):
        """Загрузка данных об отправленных свежих вакансиях пользователям"""
        try:
            if os.path.exists(self.user_sent_fresh_file):
                with open(self.user_sent_fresh_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.user_sent_fresh_vacancies = {
                        int(k): set(v) for k, v in data.get('user_sent', {}).items()
                    }
            else:
                self.user_sent_fresh_vacancies = {}
        except Exception as e:
            print(f"⚠️ Ошибка при загрузке отправленных свежих вакансий: {e}")
            self.user_sent_fresh_vacancies = {}
    
    def _save_user_sent_fresh(self):
        """Сохранение данных об отправленных свежих вакансиях пользователям"""
        try:
            data = {
                'user_sent': {
                    str(k): list(v) for k, v in self.user_sent_fresh_vacancies.items()
                },
                'last_updated': datetime.now().isoformat()
            }
            with open(self.user_sent_fresh_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Ошибка при сохранении отправленных свежих вакансий: {e}")
    
    def _is_vacancy_from_today(self, published_str: str, today_date=None) -> bool:
        """Проверка, опубликована ли вакансия сегодня"""
        try:
            if not published_str:
                return False
            
            if today_date is None:
                today_date = datetime.now().date()
            
            # Парсим дату из формата ISO (например, "2024-01-27T12:15:18+0300")
            if 'T' in published_str:
                date_str = published_str.split('T')[0]
                vacancy_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                return vacancy_date == today_date
            
            return False
        except Exception as e:
            print(f"⚠️ Ошибка при проверке даты вакансии: {e}")
            return False
    
    def _extract_position_from_resume(self, resume_text: str) -> Optional[str]:
        """Извлечение желаемой должности из резюме"""
        try:
            print("🔍 Начинаю извлечение должности из резюме...")
            print(f"📄 Длина текста резюме: {len(resume_text)} символов")
            
            # Нормализуем текст (заменяем множественные пробелы на одинарные)
            resume_text_normalized = re.sub(r'\s+', ' ', resume_text)
            
            # Паттерны для поиска должности (расширенный список)
            patterns = [
                # Основные паттерны с "желаемая"
                r'желаемая\s+должность[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'желаемая\s+позиция[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'желаемая\s+работа[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'желаемая\s+вакансия[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                
                # Паттерны без "желаемая"
                r'должность[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'позиция[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'профессия[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                
                # Английские варианты
                r'desired\s+position[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'desired\s+job[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'position[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'job\s+title[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'target\s+position[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                
                # Цель/Objective
                r'цель[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'objective[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'career\s+objective[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                
                # Специфичные для резюме форматы
                r'ищу\s+работу\s+на\s+позицию[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'ищу\s+позицию[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'looking\s+for[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
            ]
            
            # Ищем по паттернам
            for i, pattern in enumerate(patterns):
                matches = re.finditer(pattern, resume_text_normalized, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    position = match.group(1).strip()
                    # Очищаем от лишних символов, но сохраняем основные
                    position = re.sub(r'[^\w\s\-/()]', '', position).strip()
                    # Убираем лишние пробелы
                    position = re.sub(r'\s+', ' ', position).strip()
                    
                    # Проверяем, что это не слишком коротко и не слишком длинно
                    if position and 3 <= len(position) <= 100:
                        # Проверяем, что это не похоже на email, телефон или другую информацию
                        if not re.match(r'^[\d\s\-\+\(\)]+$', position):  # Не только цифры
                            if '@' not in position:  # Не email
                                print(f"✅ Должность найдена паттерном {i+1}: '{position}'")
                                return position
            
            # Если не нашли по паттернам, ищем в первых строках (обычно должность там)
            print("🔍 Паттерны не сработали, ищу в первых строках...")
            lines = resume_text.split('\n')[:15]  # Увеличиваем количество проверяемых строк
            
            for line_num, line in enumerate(lines):
                line = line.strip()
                if line and 5 <= len(line) <= 80:  # Должность обычно короткая
                    # Проверяем, не похоже ли на должность (содержит ключевые слова)
                    position_keywords = [
                        'менеджер', 'manager', 'разработчик', 'developer', 
                        'дизайнер', 'designer', 'аналитик', 'analyst',
                        'специалист', 'specialist', 'инженер', 'engineer',
                        'архитектор', 'architect', 'лид', 'lead',
                        'директор', 'director', 'руководитель', 'head',
                        'координатор', 'coordinator', 'консультант', 'consultant'
                    ]
                    line_lower = line.lower()
                    if any(keyword in line_lower for keyword in position_keywords):
                        # Проверяем, что это не контактная информация
                        if '@' not in line and not re.match(r'^[\d\s\-\+\(\)]+$', line):
                            print(f"✅ Должность найдена в строке {line_num+1}: '{line}'")
                            return line
            
            # Последняя попытка: ищем в заголовке (обычно это первая непустая строка)
            print("🔍 Последняя попытка: проверяю заголовок...")
            for line in resume_text.split('\n'):
                line = line.strip()
                if line and 5 <= len(line) <= 80:
                    # Если строка содержит только буквы, пробелы и дефисы - возможно это должность
                    if re.match(r'^[А-Яа-яA-Za-z\s\-]+$', line) and len(line.split()) <= 5:
                        print(f"✅ Возможная должность в заголовке: '{line}'")
                        return line
            
            print("❌ Должность не найдена")
            return None
        except Exception as e:
            print(f"⚠️ Ошибка при извлечении должности: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _extract_salary_from_resume(self, resume_text: str) -> Optional[str]:
        """Извлечение желаемой зарплаты из резюме"""
        try:
            print("🔍 Начинаю извлечение зарплаты из резюме...")
            
            # Паттерны для поиска зарплаты
            patterns = [
                r'желаемая\s+зарплата[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'зарплата[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'зарплата\s+от[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'оклад[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'salary[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'desired\s+salary[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
                r'compensation[:\s]*([^\n\r]+?)(?:\n|$|\.|;)',
            ]
            
            # Ищем по паттернам
            for pattern in patterns:
                matches = re.finditer(pattern, resume_text, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    salary = match.group(1).strip()
                    # Проверяем, что это похоже на зарплату (содержит цифры)
                    if re.search(r'\d', salary):
                        print(f"✅ Зарплата найдена: '{salary}'")
                        return salary
            
            print("❌ Зарплата не найдена")
            return None
        except Exception as e:
            print(f"⚠️ Ошибка при извлечении зарплаты: {e}")
            return None
    
    def get_vacancy_description(self, vacancy_url: str) -> Optional[str]:
        """Получение описания вакансии из HH API"""
        try:
            # Извлекаем ID вакансии из URL
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
                    # Очищаем HTML теги (простая очистка)
                    import re
                    description = re.sub(r'<[^>]+>', '', description)
                    return description[:2000]  # Ограничиваем длину
        except Exception as e:
            print(f"⚠️ Ошибка при получении описания вакансии: {e}")
        return None
    
    def generate_cover_letter(self, vacancy_title: str, company: str, description: str, user_id: int = None) -> tuple:
        """
        Генерация сопроводительного письма
        Всегда сначала пытается использовать OpenAI, при неудаче использует шаблон
        
        Returns:
            tuple: (текст_письма, метаданные)
            метаданные содержит:
            - method: 'openai' или 'template'
            - success: True/False
            - error_type: тип ошибки (если была)
            - error_message: сообщение об ошибке (если была)
        """
        resume_text = None
        if user_id and user_id in self.resumes:
            resume_text = self.resumes[user_id]
        
        # Всегда пытаемся использовать OpenAI сначала
        return self._generate_with_openai(vacancy_title, company, description, resume_text)
    
    def _generate_with_openai(self, vacancy_title: str, company: str, description: str, resume_text: str = None) -> tuple:
        """
        Генерация письма через OpenAI API
        Всегда пытается использовать OpenAI, при неудаче возвращает шаблон с указанием причины
        """
        metadata = {
            'method': 'template',
            'success': False,
            'error_type': None,
            'error_message': None,
            'openai_available': False,
            'attempted_openai': True  # Флаг, что пытались использовать OpenAI
        }
        
        # Проверяем наличие API ключа
        if not self.openai_api_key:
            print("⚠️ OpenAI API ключ не установлен. Использую шаблонную генерацию.")
            metadata['error_type'] = 'no_api_key'
            metadata['error_message'] = 'API ключ OpenAI не установлен в переменных окружения'
            metadata['success'] = True  # Шаблонная генерация успешна
            return self._generate_template(vacancy_title, company, description, resume_text), metadata
        
        try:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=self.openai_api_key)
                metadata['openai_available'] = True
                print("✅ OpenAI клиент инициализирован")
            except ImportError:
                # Старая версия openai
                try:
                    import openai
                    openai.api_key = self.openai_api_key
                    client = None
                    metadata['openai_available'] = True
                    print("✅ OpenAI (старая версия) инициализирован")
                except Exception as e:
                    print(f"⚠️ Не удалось импортировать библиотеку openai: {e}")
                    metadata['error_message'] = f"Библиотека openai не установлена или повреждена: {e}"
                    metadata['error_type'] = 'import_error'
                    metadata['success'] = True
                    return self._generate_template(vacancy_title, company, description, resume_text), metadata
            except Exception as e:
                print(f"⚠️ Не удалось инициализировать OpenAI клиент: {e}")
                metadata['error_message'] = f"Ошибка инициализации OpenAI: {e}"
                metadata['error_type'] = 'initialization_error'
                metadata['success'] = True
                return self._generate_template(vacancy_title, company, description, resume_text), metadata
            
            # Формируем промпт
            prompt_parts = [
                f"Составь профессиональное сопроводительное письмо на русском языке для вакансии \"{vacancy_title}\" в компании \"{company}\".",
                "",
                "Описание вакансии:",
                description[:2000] if description else "Описание не предоставлено"
            ]
            
            if resume_text:
                prompt_parts.extend([
                    "",
                    "Резюме кандидата:",
                    resume_text[:2000],
                    "",
                    "ВАЖНО:",
                    "1. Проанализируй все требования из описания вакансии",
                    "2. Найди в резюме ответы на КАЖДОЕ требование",
                    "3. Перечисли все найденные совпадения в письме",
                    "4. Для каждого требования из вакансии, которое есть в резюме, укажи конкретный опыт/навык",
                    "5. Структурируй письмо так, чтобы было видно соответствие каждому требованию"
                ])
            
            prompt_parts.extend([
                "",
                "Требования к письму:",
                "- Краткое (2-3 абзаца)",
                "- Профессиональное",
                "- Показывает интерес к позиции",
                "- Подчеркивает релевантный опыт и навыки из резюме",
                "- Заканчивается призывом к действию",
                "",
                "Начни письмо с обращения к HR-менеджеру."
            ])
            
            prompt = "\n".join(prompt_parts)
            
            # Используем OpenAI API
            if client:
                # Новая версия OpenAI API
                print("🔄 Отправляю запрос к OpenAI API...")
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "Ты профессиональный HR-консультант, который помогает составлять сопроводительные письма."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=500,
                    temperature=0.7
                )
                letter_text = response.choices[0].message.content.strip()
                metadata['method'] = 'openai'
                metadata['success'] = True
                print("✅ Письмо успешно сгенерировано через OpenAI")
                return letter_text, metadata
            else:
                # Старая версия (если используется)
                print("ℹ️ Использую старую версию OpenAI API")
                metadata['method'] = 'template'
                return self._generate_template(vacancy_title, company, description, resume_text), metadata
        except Exception as e:
            error_msg = str(e)
            print(f"⚠️ Ошибка при генерации через OpenAI: {e}")
            metadata['error_message'] = error_msg
            
            # Проверяем тип ошибки
            if "403" in error_msg or "unsupported_country" in error_msg.lower() or "forbidden" in error_msg.lower():
                print("ℹ️ OpenAI API недоступен в вашем регионе. Использую шаблонную генерацию с анализом резюме.")
                metadata['error_type'] = 'region_forbidden'
            elif "401" in error_msg or "unauthorized" in error_msg.lower():
                print("ℹ️ Неверный API ключ OpenAI. Использую шаблонную генерацию.")
                metadata['error_type'] = 'unauthorized'
            elif "429" in error_msg or "rate limit" in error_msg.lower():
                print("ℹ️ Превышен лимит запросов к OpenAI. Использую шаблонную генерацию.")
                metadata['error_type'] = 'rate_limit'
            elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                print("ℹ️ Таймаут при подключении к OpenAI. Использую шаблонную генерацию.")
                metadata['error_type'] = 'timeout'
            elif "connection" in error_msg.lower() or "network" in error_msg.lower():
                print("ℹ️ Проблема с подключением к OpenAI. Использую шаблонную генерацию.")
                metadata['error_type'] = 'connection_error'
            else:
                print("ℹ️ Переключаюсь на шаблонную генерацию с анализом резюме.")
                metadata['error_type'] = 'unknown_error'
            
            # Всегда возвращаем шаблонную генерацию при ошибке
            metadata['method'] = 'template'
            metadata['success'] = True  # Шаблонная генерация всегда успешна
            return self._generate_template(vacancy_title, company, description, resume_text), metadata
    
    def _extract_requirements(self, description: str) -> List[Dict[str, str]]:
        """Извлечение требований из описания вакансии"""
        requirements = []
        if not description:
            return requirements
        
        desc_lower = description.lower()
        
        # Расширенный список ключевых слов и фраз
        requirement_patterns = [
            # Технологии и инструменты
            {'keywords': ['agile', 'scrum', 'kanban', 'lean'], 'category': 'Методологии разработки'},
            {'keywords': ['jira', 'confluence', 'notion', 'figma', 'miro'], 'category': 'Инструменты'},
            {'keywords': ['sql', 'python', 'javascript', 'java', 'swift', 'kotlin'], 'category': 'Языки программирования'},
            {'keywords': ['api', 'rest', 'graphql', 'microservices'], 'category': 'Архитектура'},
            {'keywords': ['aws', 'azure', 'gcp', 'docker', 'kubernetes'], 'category': 'Инфраструктура'},
            {'keywords': ['analytics', 'метрики', 'аналитика', 'bi', 'tableau'], 'category': 'Аналитика'},
            {'keywords': ['ux', 'ui', 'дизайн', 'design'], 'category': 'Дизайн'},
            {'keywords': ['a/b тест', 'ab тест', 'a/b testing'], 'category': 'Тестирование'},
            {'keywords': ['b2b', 'b2c', 'saas', 'marketplace'], 'category': 'Бизнес-модели'},
            
            # Навыки и компетенции
            {'keywords': ['roadmap', 'roadmap', 'дорожная карта'], 'category': 'Планирование'},
            {'keywords': ['backlog', 'бэклог', 'приоритизация'], 'category': 'Управление задачами'},
            {'keywords': ['stakeholder', 'стейкхолдер', 'коммуникация'], 'category': 'Коммуникации'},
            {'keywords': ['метрики', 'kpi', 'okr', 'цели'], 'category': 'Метрики и цели'},
            {'keywords': ['гипотеза', 'hypothesis', 'эксперимент'], 'category': 'Экспериментирование'},
            {'keywords': ['юзер стори', 'user story', 'требования'], 'category': 'Работа с требованиями'},
            {'keywords': ['анализ данных', 'data analysis', 'исследования'], 'category': 'Исследования'},
            {'keywords': ['конкурентный анализ', 'competitive analysis'], 'category': 'Анализ рынка'},
        ]
        
        for pattern in requirement_patterns:
            for keyword in pattern['keywords']:
                if keyword in desc_lower:
                    # Находим контекст вокруг ключевого слова
                    idx = desc_lower.find(keyword)
                    context_start = max(0, idx - 100)
                    context_end = min(len(description), idx + len(keyword) + 100)
                    context = description[context_start:context_end].strip()
                    
                    requirement = {
                        'keyword': keyword,
                        'category': pattern['category'],
                        'context': context
                    }
                    if requirement not in requirements:
                        requirements.append(requirement)
                    break
        
        return requirements
    
    def _match_requirements_with_resume(self, requirements: List[Dict], resume_text: str) -> List[Dict]:
        """Сопоставление требований с резюме"""
        if not resume_text:
            return []
        
        resume_lower = resume_text.lower()
        matched = []
        
        for req in requirements:
            keyword = req['keyword']
            # Проверяем наличие ключевого слова в резюме
            if keyword in resume_lower:
                # Находим контекст в резюме
                idx = resume_lower.find(keyword)
                context_start = max(0, idx - 150)
                context_end = min(len(resume_text), idx + len(keyword) + 150)
                resume_context = resume_text[context_start:context_end].strip()
                
                matched.append({
                    'requirement': req,
                    'resume_context': resume_context,
                    'keyword': keyword
                })
        
        return matched
    
    def _generate_template(self, vacancy_title: str, company: str, description: str, resume_text: str = None) -> str:
        """Генерация письма по шаблону с детальным анализом требований"""
        letter = f"""Здравствуйте!

Меня заинтересовала вакансия "{vacancy_title}" в компании {company}. 

"""
        
        if resume_text and description:
            # Извлекаем требования из вакансии
            requirements = self._extract_requirements(description)
            print(f"📋 Найдено требований в вакансии: {len(requirements)}")
            
            # Сопоставляем с резюме
            matched_requirements = self._match_requirements_with_resume(requirements, resume_text)
            print(f"✅ Найдено совпадений с резюме: {len(matched_requirements)}")
            
            if matched_requirements:
                # Собираем все ключевые слова из совпадений
                keywords_list = []
                for match in matched_requirements:
                    keyword = match['keyword']
                    # Форматируем ключевое слово
                    if len(keyword) > 3:
                        keyword_display = keyword.title()
                    else:
                        keyword_display = keyword.upper()
                    keywords_list.append(keyword_display)
                
                # Убираем дубликаты, сохраняя порядок
                unique_keywords = []
                seen = set()
                for kw in keywords_list:
                    if kw.lower() not in seen:
                        unique_keywords.append(kw)
                        seen.add(kw.lower())
                
                # Формируем список через запятую
                if unique_keywords:
                    keywords_str = ', '.join(unique_keywords)
                    letter += f"Мой опыт соответствует требованиям: {keywords_str}. "
                
                letter += "Мой опыт, отраженный в резюме, показывает, что я обладаю необходимыми компетенциями для успешной работы на данной позиции. "
            else:
                # Если совпадений нет, используем общий подход
                letter += "Изучив описание вакансии, я вижу, что мой опыт работы в продуктовой разработке и управления продуктами соответствует требованиям данной позиции. "
        elif description:
            # Если нет резюме, но есть описание
            requirements = self._extract_requirements(description)
            if requirements:
                categories = list(set([r['category'] for r in requirements[:5]]))
                letter += f"Я вижу, что в вакансии упоминаются следующие области: {', '.join(categories)}. "
            letter += "Я имею опыт работы в продуктовой разработке и управления продуктами, что соответствует требованиям данной позиции. "
        else:
            letter += "Я имею опыт работы в продуктовой разработке и управления продуктами, что соответствует требованиям данной позиции. "
        
        letter += """Буду рад обсудить, как мой опыт может быть полезен для вашей команды. Готов предоставить дополнительную информацию и ответить на ваши вопросы.

С уважением,
[Ваше имя]"""
        
        return letter
    
    def format_vacancy_message(self, vacancy: Dict) -> str:
        """Форматирование сообщения о вакансии"""
        # Форматируем дату публикации
        published_date = self._format_published_date(vacancy.get('published', ''))
        
        message = f"""🎯 <b>{vacancy['title']}</b>

🏢 Компания: {vacancy['company']}
📍 Локация: {vacancy['location']}
💰 Зарплата: {vacancy['salary']}
📅 Источник: {vacancy['source']}"""
        
        if published_date:
            message += f"\n📆 Опубликовано: {published_date}"
        
        message += f"\n🔗 Ссылка: {vacancy['url']}"
        
        return message
    
    def _format_published_date(self, published_str: str) -> str:
        """Форматирование даты публикации в читаемый вид"""
        if not published_str:
            return ""
        
        try:
            # Парсим ISO формат даты (например: "2026-01-27T12:15:18+0300")
            # Убираем временную зону для упрощения
            date_str = published_str.split('+')[0].split('-')[0] if '+' in published_str else published_str.split('T')[0]
            
            # Пробуем разные форматы
            try:
                # Формат ISO: "2026-01-27T12:15:18+0300" или "2026-01-27T12:15:18"
                if 'T' in published_str:
                    dt = datetime.fromisoformat(published_str.replace('+', '+').split('+')[0])
                else:
                    dt = datetime.fromisoformat(published_str)
                
                # Вычисляем разницу с текущим временем
                now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
                if dt.tzinfo:
                    now = datetime.now(dt.tzinfo)
                else:
                    now = datetime.now()
                
                delta = now - dt.replace(tzinfo=None) if dt.tzinfo else now - dt
                
                # Форматируем в зависимости от давности
                if delta.days == 0:
                    hours = delta.seconds // 3600
                    if hours == 0:
                        minutes = delta.seconds // 60
                        if minutes == 0:
                            return "только что"
                        return f"{minutes} мин. назад"
                    return f"{hours} ч. назад"
                elif delta.days == 1:
                    return "вчера"
                elif delta.days < 7:
                    return f"{delta.days} дн. назад"
                elif delta.days < 30:
                    weeks = delta.days // 7
                    return f"{weeks} нед. назад"
                else:
                    # Форматируем как дату
                    months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                             'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
                    return f"{dt.day} {months[dt.month - 1]} {dt.year}"
            except:
                # Если не удалось распарсить, возвращаем как есть
                return published_str.split('T')[0] if 'T' in published_str else published_str
        except Exception as e:
            # В случае ошибки возвращаем пустую строку
            return ""
    
    def _get_vacancy_id(self, vacancy_url: str) -> str:
        """Извлечение ID вакансии из URL для callback_data"""
        try:
            if 'hh.ru/vacancy/' in vacancy_url:
                return vacancy_url.split('/vacancy/')[-1].split('?')[0]
            # Для других источников используем хеш
            import hashlib
            return hashlib.md5(vacancy_url.encode()).hexdigest()[:16]
        except:
            return str(hash(vacancy_url))[:16]
    
    async def send_vacancy(self, vacancy: Dict, context: ContextTypes.DEFAULT_TYPE, chat_id: int = None):
        """Отправка вакансии в канал с кнопками"""
        vacancy_url = vacancy.get('url', '')
        
        # Определяем chat_id (по умолчанию используем self.chat_id)
        target_chat_id = chat_id if chat_id else self.chat_id
        
        # Проверяем, не была ли вакансия уже отправлена (только для основного канала)
        if target_chat_id == self.chat_id and self._is_vacancy_sent(vacancy_url):
            print(f"⏭️  Вакансия уже была отправлена, пропускаю: {vacancy['title']} ({vacancy_url})")
            return False
        
        message = self.format_vacancy_message(vacancy)
        
        # Используем ID вместо полного URL для callback_data (ограничение Telegram - 64 байта)
        vacancy_id = self._get_vacancy_id(vacancy_url)
        
        # Сохраняем соответствие ID -> URL в контексте
        if not hasattr(context.bot_data, 'vacancy_urls'):
            context.bot_data['vacancy_urls'] = {}
        context.bot_data['vacancy_urls'][vacancy_id] = vacancy
        
        # Создаем кнопки
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, составить", callback_data=f"yes_{vacancy_id}"),
                InlineKeyboardButton("❌ Нет", callback_data=f"no_{vacancy_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Добавляем вопрос
        full_message = f"{message}\n\n❓ <b>Необходимо ли составить сопроводительное письмо?</b>"
        
        try:
            await context.bot.send_message(
                chat_id=target_chat_id,
                text=full_message,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
            # Сохраняем вакансию как отправленную только для основного канала
            if target_chat_id == self.chat_id:
                self._save_sent_vacancy(vacancy_url)
            print(f"✅ Вакансия отправлена: {vacancy['title']} в {vacancy['company']}")
            return True
        except Exception as e:
            print(f"❌ Ошибка при отправке вакансии: {e}")
            return False
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатий на кнопки"""
        try:
            print("🔔 handle_callback вызван")
            query = update.callback_query
            
            if not query:
                print("❌ Callback query отсутствует")
                return
            
            data = query.data
            print(f"🔔 Получен callback data: {data}")
            print(f"🔔 Query object: {query}")
            print(f"🔔 Message chat_id: {query.message.chat_id if query.message else 'None'}")
            
            # Отвечаем на callback сразу, чтобы Telegram знал, что запрос обработан
            try:
                await query.answer()
                print("✅ Callback answer отправлен")
            except Exception as e:
                print(f"⚠️ Ошибка при отправке callback answer: {e}")
            
            if data.startswith('yes_'):
                vacancy_id = data.replace('yes_', '')
                print(f"✅ Обрабатываю 'Да' для vacancy_id: {vacancy_id}")
                try:
                    await self.handle_yes(query, vacancy_id, context)
                except Exception as e:
                    print(f"❌ Ошибка в handle_yes: {e}")
                    import traceback
                    traceback.print_exc()
                    try:
                        await query.answer(f"Ошибка: {e}", show_alert=True)
                    except:
                        pass
            elif data.startswith('no_'):
                vacancy_id = data.replace('no_', '')
                print(f"✅ Обрабатываю 'Нет' для vacancy_id: {vacancy_id}")
                await self.handle_no(query, vacancy_id)
            elif data == 'send_more':
                print("✅ Обрабатываю 'Отправить ещё вакансии'")
                await self.handle_send_more(query, context)
            elif data == 'start':
                print("✅ Обрабатываю 'Начать'")
                await self.handle_start_button(query, context)
            elif data.startswith('apply_'):
                vacancy_id = data.replace('apply_', '')
                print(f"✅ Обрабатываю 'Откликнуться на вакансию' для vacancy_id: {vacancy_id}")
                await self.handle_apply_vacancy(query, vacancy_id, context)
            elif data.startswith('confirm_position_'):
                try:
                    user_id_str = data.replace('confirm_position_', '')
                    user_id = int(user_id_str)
                    print(f"✅ Обрабатываю подтверждение должности для user_id: {user_id}")
                    print(f"🔍 Callback data: {data}, извлеченный user_id: {user_id}")
                    await self.handle_confirm_position(query, user_id, context)
                except ValueError as e:
                    print(f"❌ Ошибка при парсинге user_id из '{data}': {e}")
                    await query.answer("Ошибка: неверный формат данных", show_alert=True)
                except Exception as e:
                    print(f"❌ Ошибка при обработке подтверждения должности: {e}")
                    import traceback
                    traceback.print_exc()
                    await query.answer(f"Ошибка: {e}", show_alert=True)
            elif data.startswith('change_position_'):
                try:
                    user_id_str = data.replace('change_position_', '')
                    user_id = int(user_id_str)
                    print(f"✅ Обрабатываю изменение должности для user_id: {user_id}")
                    await self.handle_change_position(query, user_id, context)
                except ValueError as e:
                    print(f"❌ Ошибка при парсинге user_id из '{data}': {e}")
                    await query.answer("Ошибка: неверный формат данных", show_alert=True)
                except Exception as e:
                    print(f"❌ Ошибка при обработке изменения должности: {e}")
                    import traceback
                    traceback.print_exc()
                    await query.answer(f"Ошибка: {e}", show_alert=True)
            else:
                print(f"⚠️ Неизвестный callback data: {data}")
                await query.answer("Неизвестная команда", show_alert=True)
        except Exception as e:
            print(f"❌ Ошибка в handle_callback: {e}")
            import traceback
            traceback.print_exc()
            try:
                if query:
                    await query.answer("Произошла ошибка", show_alert=True)
            except:
                pass
    
    async def handle_yes(self, query, vacancy_id: str, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатия "Да" - генерация письма"""
        try:
            print(f"📝 Начало генерации письма для vacancy_id: {vacancy_id}")
            await query.edit_message_text("⏳ Составляю сопроводительное письмо...")
            
            # Получаем вакансию из сохраненных данных или загружаем из файла
            vacancy = None
            
            # Проверяем кеш в bot_data
            if not hasattr(context.bot_data, 'vacancy_urls'):
                context.bot_data['vacancy_urls'] = {}
            
            print(f"🔍 Проверяю кеш, vacancy_id: {vacancy_id}")
            print(f"🔍 Доступные ID в кеше: {list(context.bot_data.get('vacancy_urls', {}).keys())}")
            if vacancy_id in context.bot_data.get('vacancy_urls', {}):
                vacancy = context.bot_data['vacancy_urls'][vacancy_id]
                print(f"✅ Вакансия найдена в кеше: {vacancy.get('title', 'Без названия')}")
            
            # Если не найдено в кеше, ищем в файле
            if not vacancy:
                print(f"🔍 Ищу вакансию в файле по vacancy_id: {vacancy_id}")
                vacancies = self.load_vacancies()
                print(f"📄 Загружено вакансий из файла: {len(vacancies)}")
                for v in vacancies:
                    v_id = self._get_vacancy_id(v['url'])
                    print(f"  Проверяю: {v_id} == {vacancy_id}")
                    if v_id == vacancy_id:
                        vacancy = v
                        print(f"✅ Вакансия найдена в файле: {vacancy['title']}")
                        break
            
            if not vacancy:
                print(f"❌ Вакансия не найдена для vacancy_id: {vacancy_id}")
                await query.edit_message_text("❌ Вакансия не найдена. Попробуйте отправить вакансии заново командой /send")
                return
            
            # Получаем описание вакансии
            print("📄 Получаю описание вакансии...")
            vacancy_url = vacancy.get('url', '')  # Сохраняем URL вакансии
            if not vacancy_url:
                print("❌ URL вакансии не найден")
                await query.edit_message_text("❌ Ошибка: URL вакансии не найден")
                return
            
            try:
                description = self.get_vacancy_description(vacancy_url)
                print(f"✅ Описание получено: {len(description or '')} символов")
            except Exception as e:
                print(f"⚠️ Ошибка при получении описания: {e}")
                description = ''  # Продолжаем без описания
            
            # Получаем user_id для поиска резюме
            user_id = query.from_user.id if query.from_user else None
            print(f"👤 User ID: {user_id}")
            if user_id and user_id in self.resumes:
                print(f"📄 Найдено резюме для user_id: {user_id}")
            else:
                print(f"ℹ️ Резюме не найдено для user_id: {user_id}")
            
            # Генерируем письмо (с учетом резюме, если есть)
            print("🤖 Генерирую сопроводительное письмо...")
            try:
                cover_letter, generation_metadata = self.generate_cover_letter(
                    vacancy.get('title', 'Вакансия'),
                    vacancy.get('company', 'Компания'),
                    description or '',
                    user_id
                )
                print(f"✅ Письмо сгенерировано: {len(cover_letter)} символов")
                print(f"📊 Метод генерации: {generation_metadata.get('method', 'unknown')}")
            except Exception as e:
                print(f"❌ Ошибка при генерации письма: {e}")
                import traceback
                traceback.print_exc()
                await query.edit_message_text(f"❌ Ошибка при генерации письма: {e}")
                return
            
            # Формируем сообщение о методе генерации
            method_info = ""
            if generation_metadata['method'] == 'openai':
                method_info = "✨ <i>Письмо сгенерировано с помощью OpenAI AI</i>"
            else:
                # Всегда указываем причину, почему не использовался OpenAI
                method_info = "📋 <i>Письмо сгенерировано по шаблону с анализом резюме</i>"
                
                # Определяем причину
                error_type = generation_metadata.get('error_type')
                if error_type:
                    error_descriptions = {
                        'no_api_key': 'API ключ OpenAI не установлен',
                        'import_error': 'Библиотека openai не установлена',
                        'initialization_error': 'Ошибка инициализации OpenAI клиента',
                        'region_forbidden': 'OpenAI недоступен в вашем регионе',
                        'unauthorized': 'Неверный API ключ OpenAI',
                        'rate_limit': 'Превышен лимит запросов к OpenAI',
                        'timeout': 'Таймаут при подключении к OpenAI',
                        'connection_error': 'Проблема с подключением к OpenAI',
                        'unknown_error': 'Ошибка при подключении к OpenAI'
                    }
                    error_desc = error_descriptions.get(error_type, 'Неизвестная ошибка')
                    method_info += f"\n⚠️ <i>Не удалось использовать OpenAI: {error_desc}</i>"
                else:
                    method_info += "\n⚠️ <i>Не удалось использовать OpenAI (причина не указана)</i>"
            
            # Отправляем письмо с кнопкой "Откликнуться на вакансию"
            letter_message = f"""📝 <b>Сопроводительное письмо</b>

<b>Вакансия:</b> {vacancy['title']}
<b>Компания:</b> {vacancy['company']}

─────────────────────

{cover_letter}

─────────────────────
{method_info}

<b>Ссылка на вакансию:</b> {vacancy_url}"""
            
            # Создаем кнопку "Откликнуться на вакансию" (только для вакансий с hh.ru)
            reply_markup = None
            if 'hh.ru' in vacancy_url:
                vacancy_id = self._get_vacancy_id(vacancy_url)
                keyboard = [
                    [InlineKeyboardButton("📤 Откликнуться на вакансию", callback_data=f"apply_{vacancy_id}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
            
            print("📤 Отправляю письмо...")
            print(f"📤 Chat ID: {query.message.chat_id}")
            print(f"📤 Длина письма: {len(letter_message)} символов")
            
            try:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=letter_message,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
                print("✅ Письмо отправлено через send_message")
            except Exception as e:
                print(f"❌ Ошибка при отправке письма: {e}")
                import traceback
                traceback.print_exc()
                raise
            
            try:
                await query.edit_message_text("✅ Сопроводительное письмо отправлено!")
                print("✅ Сообщение обновлено на 'Письмо отправлено'")
            except Exception as e:
                print(f"⚠️ Ошибка при обновлении сообщения после отправки: {e}")
                # Не критично, письмо уже отправлено
            
            print("✅ Письмо успешно отправлено!")
        except Exception as e:
            error_msg = f"❌ Ошибка: {e}"
            print(f"❌ Ошибка в handle_yes: {e}")
            import traceback
            traceback.print_exc()
            try:
                await query.edit_message_text(error_msg)
            except:
                try:
                    await query.answer(error_msg, show_alert=True)
                except:
                    pass
    
    async def handle_no(self, query, vacancy_id: str):
        """Обработка нажатия "Нет" """
        await query.edit_message_text("✅ Понятно, сопроводительное письмо не требуется.")
    
    async def _send_more_button(self, context: ContextTypes.DEFAULT_TYPE, remaining_count: int):
        """Отправка сообщения с кнопкой 'Отправить ещё вакансии'"""
        try:
            keyboard = [
                [InlineKeyboardButton("📤 Отправить ещё вакансии", callback_data="send_more")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = f"✅ Отправлено 10 вакансий!\n\n📊 Осталось вакансий: {remaining_count}\n\nНажмите кнопку, чтобы отправить ещё 10 вакансий."
            
            await context.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
            print(f"📤 Отправлена кнопка 'Отправить ещё' (осталось {remaining_count} вакансий)")
        except Exception as e:
            print(f"❌ Ошибка при отправке кнопки 'Отправить ещё': {e}")
    
    async def handle_send_more(self, query, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатия кнопки 'Отправить ещё вакансии'"""
        try:
            # Обновляем сообщение с кнопкой
            try:
                await query.edit_message_text("📤 Отправляю ещё вакансии...")
            except:
                # Если не удалось обновить, пытаемся удалить
                try:
                    await query.message.delete()
                except:
                    pass
            
            # Отправляем следующие 10 вакансий
            await self.send_all_vacancies(context, limit=10, show_more_button=True)
        except Exception as e:
            print(f"❌ Ошибка при обработке 'Отправить ещё': {e}")
            import traceback
            traceback.print_exc()
            try:
                await query.answer(f"Ошибка: {e}", show_alert=True)
            except:
                pass
    
    async def handle_start_button(self, query, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатия кнопки 'Начать'"""
        try:
            message_text = (
                "Привет! Я помогу тебе с поиском работы. Просто отправь своё резюме в формате word или pdf, я возьму из него твою должность и ожидания по заработной плате, если они там указаны. Дальше я буду отправлять тебе актуальные вакансии"
            )
            
            # Обновляем сообщение
            try:
                await query.edit_message_text(message_text)
            except:
                # Если не удалось обновить, отправляем новое сообщение
                await query.message.reply_text(message_text)
                
        except Exception as e:
            print(f"❌ Ошибка при обработке 'Начать': {e}")
            import traceback
            traceback.print_exc()
            try:
                await query.answer(f"Ошибка: {e}", show_alert=True)
            except:
                pass
    
    async def handle_apply_vacancy(self, query, vacancy_id: str, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатия кнопки 'Откликнуться на вакансию'"""
        try:
            await query.answer("⏳ Отправляю отклик...")
            
            # Получаем данные вакансии
            vacancy = None
            if hasattr(context.bot_data, 'vacancy_urls') and vacancy_id in context.bot_data.get('vacancy_urls', {}):
                vacancy = context.bot_data['vacancy_urls'][vacancy_id]
            else:
                # Пытаемся загрузить из файла
                vacancies = self.load_vacancies()
                for v in vacancies:
                    if self._get_vacancy_id(v.get('url', '')) == vacancy_id:
                        vacancy = v
                        break
            
            if not vacancy:
                await query.answer("❌ Вакансия не найдена", show_alert=True)
                return
            
            vacancy_url = vacancy.get('url', '')
            if 'hh.ru' not in vacancy_url:
                await query.answer("❌ Отклик возможен только для вакансий с hh.ru", show_alert=True)
                return
            
            # Проверяем наличие токена доступа
            if not self.hh_access_token:
                await query.answer(
                    "⚠️ Для отклика на вакансии необходим токен доступа к HH API.\n\n"
                    "Получите токен:\n"
                    "1. Зайдите на https://hh.ru/account/applications\n"
                    "2. Создайте приложение\n"
                    "3. Скопируйте Access Token\n"
                    "4. Добавьте в .env: HH_ACCESS_TOKEN=ваш_токен",
                    show_alert=True
                )
                return
            
            # Отправляем отклик через HH API
            success = await self._apply_to_hh_vacancy(vacancy_id, vacancy_url, query.message.chat_id, vacancy)
            
            if success:
                await query.answer("✅ Отклик успешно отправлен!", show_alert=True)
                # Обновляем сообщение с письмом
                try:
                    # Убираем кнопку и добавляем пометку
                    new_text = query.message.text + "\n\n✅ <b>Отклик отправлен работодателю!</b>"
                    await query.message.edit_text(new_text, parse_mode='HTML', reply_markup=None)
                except:
                    pass
            else:
                await query.answer("❌ Не удалось отправить отклик. Проверьте токен доступа.", show_alert=True)
                
        except Exception as e:
            print(f"❌ Ошибка при обработке отклика: {e}")
            import traceback
            traceback.print_exc()
            try:
                await query.answer(f"Ошибка: {e}", show_alert=True)
            except:
                pass
    
    async def _apply_to_hh_vacancy(self, vacancy_id: str, vacancy_url: str, user_chat_id: int, vacancy: Dict) -> bool:
        """Отправка отклика на вакансию через HH API"""
        try:
            # Получаем резюме пользователя для сопроводительного письма
            user_id = user_chat_id
            cover_letter_text = ""
            
            if user_id in self.resumes:
                # Генерируем сопроводительное письмо на основе резюме
                vacancy_title = vacancy.get('title', 'Вакансия')
                company = vacancy.get('company', 'Компания')
                
                # Получаем описание вакансии
                description = self.get_vacancy_description(vacancy_url)
                if description:
                    cover_letter, _ = self.generate_cover_letter(
                        vacancy_title, company, description, user_id
                    )
                    cover_letter_text = cover_letter
                else:
                    # Если не удалось получить описание, используем стандартное письмо
                    cover_letter_text = (
                        "Здравствуйте!\n\n"
                        "Меня заинтересовала данная вакансия. "
                        "Мой опыт и навыки соответствуют требованиям позиции. "
                        "Буду рад обсудить детали в личной беседе.\n\n"
                        "С уважением"
                    )
            else:
                # Если резюме нет, используем стандартное письмо
                cover_letter_text = (
                    "Здравствуйте!\n\n"
                    "Меня заинтересовала данная вакансия. "
                    "Буду рад обсудить детали в личной беседе.\n\n"
                    "С уважением"
                )
            
            # Получаем список резюме пользователя из HH
            resumes_response = requests.get(
                'https://api.hh.ru/resumes',
                headers={
                    'Authorization': f'Bearer {self.hh_access_token}',
                    'User-Agent': 'Mozilla/5.0'
                },
                timeout=10
            )
            
            if resumes_response.status_code != 200:
                print(f"❌ Ошибка при получении резюме: {resumes_response.status_code} - {resumes_response.text}")
                return False
            
            resumes_data = resumes_response.json()
            if not resumes_data.get('items'):
                print("❌ У пользователя нет резюме на HH")
                return False
            
            # Берем первое активное резюме
            resume_id = resumes_data['items'][0]['id']
            
            # Отправляем отклик
            apply_url = f'https://api.hh.ru/negotiations'
            apply_data = {
                'vacancy_id': vacancy_id,
                'resume_id': resume_id,
                'message': cover_letter_text
            }
            
            apply_response = requests.post(
                apply_url,
                headers={
                    'Authorization': f'Bearer {self.hh_access_token}',
                    'User-Agent': 'Mozilla/5.0',
                    'Content-Type': 'application/json'
                },
                json=apply_data,
                timeout=10
            )
            
            if apply_response.status_code in [201, 200]:
                print(f"✅ Отклик успешно отправлен на вакансию {vacancy_id}")
                return True
            else:
                error_text = apply_response.text
                print(f"❌ Ошибка при отправке отклика: {apply_response.status_code} - {error_text}")
                return False
                
        except Exception as e:
            print(f"❌ Ошибка при отправке отклика: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка загрузки документа (резюме)"""
        if not update.message or not update.message.document:
            await update.message.reply_text("❌ Ошибка: не удалось получить документ")
            return
        
        document = update.message.document
        user_id = update.message.from_user.id
        file_name = document.file_name.lower() if document.file_name else ''
        
        # Проверяем тип файла (для MVP только PDF и DOCX)
        allowed_extensions = ['.pdf', '.docx']
        if not any(file_name.endswith(ext) for ext in allowed_extensions):
            await update.message.reply_text(
                "❌ Неподдерживаемый формат файла.\n"
                "Поддерживаются: PDF, DOCX"
            )
            return
        
        try:
            # AC1.1: Отвечаем сразу
            await update.message.reply_text("Спасибо! Обрабатываю ваше резюме...")
            
            # Скачиваем файл
            file = await context.bot.get_file(document.file_id)
            file_path = os.path.join(self.resumes_dir, f"resume_{user_id}_{document.file_name}")
            await file.download_to_drive(file_path)
            
            # Извлекаем текст из файла
            resume_text = self._extract_text_from_file(file_path)
            
            if resume_text and not resume_text.startswith("⚠️"):
                # Сохраняем резюме
                self.resumes[user_id] = resume_text
                
                # Сохраняем в файл для постоянного хранения
                resume_text_file = os.path.join(self.resumes_dir, f"resume_{user_id}.txt")
                with open(resume_text_file, 'w', encoding='utf-8') as f:
                    f.write(resume_text)
                
                # Извлекаем должность из резюме
                position = self._extract_position_from_resume(resume_text)
                
                # Извлекаем зарплату из резюме (опционально)
                salary = self._extract_salary_from_resume(resume_text)
                
                if position:
                    # Сохраняем извлеченную должность
                    self.user_positions[user_id] = position
                    self._save_users_data()
                    
                    # Формируем сообщение с должностью и зарплатой (если найдена)
                    position_message = f"Я определил вашу желаемую должность как **{position}**"
                    if salary:
                        position_message += f"\n\n💰 Желаемая зарплата: **{salary}**"
                    position_message += "\n\nВерно?"
                    
                    # AC1.2: Предлагаем подтвердить должность
                    keyboard = [
                        [
                            InlineKeyboardButton("✅ Да", callback_data=f"confirm_position_{user_id}"),
                            InlineKeyboardButton("❌ Нет, указать другую", callback_data=f"change_position_{user_id}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        position_message,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                else:
                    # Если не удалось извлечь должность, просим указать вручную
                    message = "✅ Резюме загружено!\n\n"
                    if salary:
                        message += f"💰 Я определил вашу желаемую зарплату: **{salary}**\n\n"
                    message += "Не удалось автоматически определить желаемую должность.\n"
                    message += "Пожалуйста, отправьте название должности текстовым сообщением."
                    
                    await update.message.reply_text(
                        message,
                        parse_mode='Markdown'
                    )
            else:
                error_msg = resume_text if resume_text else "⚠️ Не удалось извлечь текст из файла."
                await update.message.reply_text(
                    f"{error_msg}\n\n"
                    "Попробуйте отправить резюме в формате PDF или DOCX."
                )
        except Exception as e:
            print(f"❌ Ошибка при обработке резюме: {e}")
            import traceback
            traceback.print_exc()
            await update.message.reply_text(f"❌ Ошибка при обработке файла: {e}")
    
    async def handle_confirm_position(self, query, user_id: int, context: ContextTypes.DEFAULT_TYPE):
        """Обработка подтверждения должности"""
        try:
            print(f"📝 handle_confirm_position вызван для user_id: {user_id}")
            print(f"📝 Query object: {query}")
            actual_user_id = query.from_user.id if query.from_user else None
            print(f"📝 Query.from_user.id: {actual_user_id}")
            
            # Проверяем безопасность: user_id в callback должен совпадать с реальным пользователем
            if actual_user_id and actual_user_id != user_id:
                print(f"⚠️ Несоответствие user_id: callback={user_id}, actual={actual_user_id}")
                await query.answer("Ошибка: неверный пользователь", show_alert=True)
                return
            
            # Отвечаем на callback
            try:
                await query.answer("⏳ Обрабатываю...")
                print("✅ Callback answer отправлен")
            except Exception as e:
                print(f"⚠️ Ошибка при отправке callback answer: {e}")
            
            # Получаем должность пользователя
            print(f"🔍 Ищу должность для user_id: {user_id}")
            print(f"🔍 Доступные user_positions: {list(self.user_positions.keys())}")
            position = self.user_positions.get(user_id)
            
            if not position:
                print(f"❌ Должность не найдена для user_id: {user_id}")
                await query.edit_message_text("❌ Должность не найдена. Пожалуйста, загрузите резюме заново.")
                return
            
            print(f"✅ Найдена должность: {position}")
            
            # Активируем подписку
            self.user_subscriptions[user_id] = {
                'position': position,
                'active': True,
                'created_at': datetime.now().isoformat()
            }
            self._save_users_data()
            print(f"✅ Подписка активирована для user_id: {user_id}")
            
            # AC1.3: Отвечаем подтверждением
            try:
                await query.edit_message_text("Отлично! Теперь буду присылать вам подборку вакансий.")
                print("✅ Сообщение обновлено")
            except Exception as e:
                print(f"⚠️ Ошибка при обновлении сообщения: {e}")
                # Пытаемся отправить новое сообщение
                try:
                    await query.message.reply_text("Отлично! Теперь буду присылать вам подборку вакансий.")
                except Exception as e2:
                    print(f"⚠️ Ошибка при отправке нового сообщения: {e2}")
            
            # AC1.4: Сразу отправляем вакансии
            print(f"🚀 Начинаю поиск и отправку вакансий для должности: {position}")
            await self._send_vacancies_for_user(user_id, position, context)
            print(f"✅ Поиск и отправка вакансий завершены")
            
        except Exception as e:
            print(f"❌ Ошибка при подтверждении должности: {e}")
            import traceback
            traceback.print_exc()
            try:
                await query.answer(f"Ошибка: {e}", show_alert=True)
            except:
                pass
    
    async def handle_change_position(self, query, user_id: int, context: ContextTypes.DEFAULT_TYPE):
        """Обработка изменения должности"""
        try:
            await query.answer()
            await query.edit_message_text(
                "Пожалуйста, отправьте название желаемой должности текстовым сообщением."
            )
            # Сохраняем состояние, что пользователь хочет указать должность
            if not hasattr(context.user_data, 'awaiting_position'):
                context.user_data['awaiting_position'] = {}
            context.user_data['awaiting_position'][user_id] = True
        except Exception as e:
            print(f"❌ Ошибка при изменении должности: {e}")
            import traceback
            traceback.print_exc()
    
    async def _send_vacancies_for_user(self, user_id: int, position: str, context: ContextTypes.DEFAULT_TYPE):
        """Поиск и отправка вакансий для пользователя"""
        try:
            print(f"🔍 _send_vacancies_for_user вызван для user_id: {user_id}, position: {position}")
            chat_id = user_id  # Отправляем пользователю лично
            
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🔍 Ищу вакансии по запросу: **{position}**...",
                    parse_mode='Markdown'
                )
                print(f"✅ Сообщение о поиске отправлено пользователю {user_id}")
            except Exception as e:
                print(f"❌ Ошибка при отправке сообщения о поиске: {e}")
                raise
            
            # Импортируем класс поисковика
            from ios_vacancies_finder import ProductManagerVacancyFinder
            
            # Создаем поисковик с должностью пользователя
            finder = ProductManagerVacancyFinder(max_vacancies=10)
            
            # Модифицируем поиск для использования должности пользователя
            vacancies = []
            
            # Поиск на hh.ru
            hh_vacancies = self._search_hh_ru_for_position(position, finder)
            vacancies.extend(hh_vacancies)
            
            # Поиск на Habr Career
            habr_vacancies = self._search_habr_for_position(position, finder)
            vacancies.extend(habr_vacancies)
            
            if not vacancies:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"😔 По запросу '{position}' вакансий не найдено. Попробуйте изменить название должности."
                )
                return
            
            # Отправляем вакансии
            sent_count = 0
            for vacancy in vacancies[:10]:  # Ограничиваем 10 вакансиями
                try:
                    # Используем существующий метод отправки с указанием chat_id пользователя
                    success = await self.send_vacancy(vacancy, context, chat_id=user_id)
                    if success:
                        sent_count += 1
                        # Небольшая задержка между отправками
                        import asyncio
                        await asyncio.sleep(1)
                except Exception as e:
                    print(f"⚠️ Ошибка при отправке вакансии: {e}")
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Отправлено вакансий: {sent_count}"
            )
            
        except Exception as e:
            print(f"❌ Ошибка при отправке вакансий пользователю: {e}")
            import traceback
            traceback.print_exc()
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"❌ Ошибка при поиске вакансий: {e}"
                )
            except:
                pass
    
    def _search_hh_ru_for_position(self, position: str, finder) -> List[Dict]:
        """Поиск вакансий на hh.ru по должности"""
        try:
            import requests
            vacancies = []
            
            # Используем API hh.ru для поиска
            url = 'https://api.hh.ru/vacancies'
            
            # Используем заголовки из finder или создаём свои
            headers = finder.headers if finder and hasattr(finder, 'headers') else {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # Функция для форматирования зарплаты
            def format_salary(salary_data):
                if not salary_data:
                    return 'Не указано'
                from_val = salary_data.get('from')
                to_val = salary_data.get('to')
                currency = salary_data.get('currency', 'RUR')
                if from_val and to_val:
                    return f"{from_val:,} - {to_val:,} {currency}"
                elif from_val:
                    return f"от {from_val:,} {currency}"
                elif to_val:
                    return f"до {to_val:,} {currency}"
                return 'Не указано'
            
            params = {
                'text': position,
                'area': 1,  # Москва
                'per_page': 50,  # Увеличиваем для получения большего количества
                'page': 0,
                'order_by': 'publication_time',  # Сортируем по времени публикации
                'period': 1  # За последние 24 часа
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                items = data.get('items', [])
                
                for item in items:
                    vacancy = {
                        'title': item.get('name', ''),
                        'company': item.get('employer', {}).get('name', ''),
                        'location': item.get('area', {}).get('name', ''),
                        'salary': format_salary(item.get('salary')),
                        'salary_data': item.get('salary'),
                        'experience': item.get('experience', {}).get('id'),
                        'experience_name': item.get('experience', {}).get('name', ''),
                        'url': item.get('alternate_url', ''),
                        'source': 'hh.ru',
                        'published': item.get('published_at', '')
                    }
                    vacancies.append(vacancy)
            
            return vacancies
        except Exception as e:
            print(f"❌ Ошибка при поиске на hh.ru: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _search_habr_for_position(self, position: str, finder) -> List[Dict]:
        """Поиск вакансий на Habr Career по должности"""
        try:
            import requests
            from bs4 import BeautifulSoup
            
            vacancies = []
            url = "https://career.habr.com/vacancies"
            params = {
                'q': position,
                'type': 'all'
            }
            
            response = requests.get(url, params=params, headers=finder.headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                items = soup.find_all('div', class_='vacancy-card')[:20]
                
                for item in items:
                    try:
                        title_elem = item.find('a', class_='vacancy-card__title-link')
                        title = title_elem.text.strip() if title_elem else ''
                        link = title_elem.get('href', '') if title_elem else ''
                        if link and not link.startswith('http'):
                            link = f"https://career.habr.com{link}"
                        
                        company_elem = item.find('div', class_='vacancy-card__company-title')
                        company = company_elem.text.strip() if company_elem else ''
                        
                        location_elem = item.find('div', class_='vacancy-card__meta')
                        location = location_elem.text.strip() if location_elem else ''
                        
                        salary_elem = item.find('div', class_='vacancy-card__salary')
                        salary = salary_elem.text.strip() if salary_elem else 'Не указано'
                        
                        vacancy = {
                            'title': title,
                            'company': company,
                            'location': location,
                            'salary': salary,
                            'url': link,
                            'source': 'career.habr.com',
                            'published': ''
                        }
                        if title and link:
                            vacancies.append(vacancy)
                    except Exception as e:
                        print(f"⚠️ Ошибка при парсинге вакансии с Habr: {e}")
                        continue
            
            return vacancies
        except Exception as e:
            print(f"❌ Ошибка при поиске на Habr: {e}")
            return []
    
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений (кнопки меню и резюме)"""
        text = update.message.text
        
        # Обработка кнопок меню
        if text == "🆕 Отправить свежие вакансии":
            await self.send_fresh_vacancies_command(update, context)
            return
        elif text == "📤 Отправить вакансии":
            await self.send_command(update, context)
            return
        elif text == "📄 Резюме":
            await self.resume_command(update, context)
            return
        elif text == "🗑️ Очистить резюме":
            await self.clear_resume_command(update, context)
            return
        elif text == "🔄 Очистить отправленные":
            await self.clear_sent_command(update, context)
            return
        elif text == "ℹ️ Помощь":
            await self.help_command(update, context)
            return
        elif text == "📋 Меню":
            await self.menu_command(update, context)
            return
        
        # Если это не кнопка меню, обрабатываем как резюме
        await self.handle_text_resume(update, context)
    
    async def handle_text_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстового резюме"""
        # Проверяем, не является ли это командой
        if update.message.text.startswith('/'):
            return
        
        user_id = update.message.from_user.id
        resume_text = update.message.text
        
        # Простая проверка - если сообщение длинное, считаем его резюме
        if len(resume_text) > 100:
            # Сохраняем резюме
            self.resumes[user_id] = resume_text
            
            # Сохраняем в файл
            resume_text_file = os.path.join(self.resumes_dir, f"resume_{user_id}.txt")
            with open(resume_text_file, 'w', encoding='utf-8') as f:
                f.write(resume_text)
            
            await update.message.reply_text(
                f"✅ Резюме сохранено!\n\n"
                f"📄 Размер: {len(resume_text)} символов\n\n"
                f"Теперь при составлении сопроводительных писем ИИ будет использовать информацию из вашего резюме.\n\n"
                f"Используйте /resume для просмотра или /clear_resume для удаления."
            )
        else:
            # Короткое сообщение - не резюме, игнорируем
            pass
    
    async def resume_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /resume - просмотр загруженного резюме"""
        user_id = update.message.from_user.id
        
        if user_id in self.resumes:
            resume_text = self.resumes[user_id]
            preview = resume_text[:500] + "..." if len(resume_text) > 500 else resume_text
            await update.message.reply_text(
                f"📄 Ваше резюме:\n\n{preview}\n\n"
                f"Полный размер: {len(resume_text)} символов\n\n"
                f"Используйте /clear_resume для удаления."
            )
        else:
            await update.message.reply_text(
                "❌ Резюме не найдено.\n\n"
                "Загрузите резюме:\n"
                "- Отправьте файл (PDF, DOC, DOCX, TXT)\n"
                "- Или отправьте текст резюме сообщением"
            )
    
    async def clear_resume_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /clear_resume - удаление резюме"""
        user_id = update.message.from_user.id
        
        if user_id in self.resumes:
            del self.resumes[user_id]
            # Удаляем файл
            resume_text_file = os.path.join(self.resumes_dir, f"resume_{user_id}.txt")
            if os.path.exists(resume_text_file):
                os.remove(resume_text_file)
            
            menu_keyboard = self.get_menu_keyboard()
            await update.message.reply_text("✅ Резюме удалено.", reply_markup=menu_keyboard)
        else:
            menu_keyboard = self.get_menu_keyboard()
            await update.message.reply_text("❌ Резюме не найдено.", reply_markup=menu_keyboard)
    
    def _extract_text_from_file(self, file_path: str) -> str:
        """Извлечение текста из файла резюме"""
        try:
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext == '.txt':
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            elif file_ext == '.pdf':
                try:
                    import PyPDF2
                    with open(file_path, 'rb') as f:
                        pdf_reader = PyPDF2.PdfReader(f)
                        text = ""
                        for page in pdf_reader.pages:
                            text += page.extract_text() + "\n"
                        return text
                except ImportError:
                    return "⚠️ Для обработки PDF требуется библиотека PyPDF2. Установите: pip install PyPDF2"
                except Exception as e:
                    print(f"Ошибка при чтении PDF: {e}")
                    return ""
            elif file_ext in ['.doc', '.docx']:
                try:
                    from docx import Document
                    doc = Document(file_path)
                    text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
                    return text
                except ImportError:
                    return "⚠️ Для обработки DOC/DOCX требуется библиотека python-docx. Установите: pip install python-docx"
                except Exception as e:
                    print(f"Ошибка при чтении DOC/DOCX: {e}")
                    return ""
            else:
                return ""
        except Exception as e:
            print(f"Ошибка при извлечении текста: {e}")
            return ""
    
    def _load_saved_resumes(self):
        """Загрузка сохраненных резюме при запуске"""
        try:
            if not os.path.exists(self.resumes_dir):
                return
            for filename in os.listdir(self.resumes_dir):
                if filename.startswith('resume_') and filename.endswith('.txt'):
                    try:
                        # Извлекаем user_id из имени файла (формат: resume_USERID.txt)
                        user_id_str = filename.replace('resume_', '').replace('.txt', '')
                        # Если есть дополнительные части (например, имя файла), берем только первую
                        if '_' in user_id_str:
                            user_id_str = user_id_str.split('_')[0]
                        user_id = int(user_id_str)
                        file_path = os.path.join(self.resumes_dir, filename)
                        with open(file_path, 'r', encoding='utf-8') as f:
                            self.resumes[user_id] = f.read()
                        print(f"✅ Загружено резюме для user_id: {user_id}")
                    except (ValueError, Exception) as e:
                        print(f"⚠️ Ошибка при загрузке резюме {filename}: {e}")
        except Exception as e:
            print(f"⚠️ Ошибка при загрузке резюме: {e}")
    
    async def send_all_vacancies(self, context: ContextTypes.DEFAULT_TYPE, limit: int = 10, show_more_button: bool = True):
        """
        Отправка вакансий из файла
        
        Args:
            context: Контекст бота
            limit: Максимальное количество вакансий для отправки за раз (по умолчанию 10)
            show_more_button: Показывать ли кнопку "Отправить ещё" после отправки
        """
        print(f"🔍 Загружаю вакансии из файла: {self.vacancies_file}")
        vacancies = self.load_vacancies()
        print(f"📊 Загружено вакансий из файла: {len(vacancies)}")
        
        if not vacancies:
            print("❌ Нет вакансий для отправки")
            try:
                await context.bot.send_message(
                    chat_id=self.chat_id,
                    text="❌ Нет вакансий для отправки. Убедитесь, что файл с вакансиями существует и содержит данные."
                )
            except:
                pass
            return
        
        # Фильтруем вакансии, которые еще не были отправлены
        print(f"🔍 Проверяю отправленные вакансии (всего в списке: {len(self.sent_vacancies)})")
        new_vacancies = []
        for v in vacancies:
            url = v.get('url', '')
            if not url:
                print(f"⚠️  Вакансия без URL: {v.get('title', 'Без названия')}")
                continue
            if not self._is_vacancy_sent(url):
                new_vacancies.append(v)
        
        skipped_count = len(vacancies) - len(new_vacancies)
        
        if skipped_count > 0:
            print(f"⏭️  Пропущено уже отправленных вакансий: {skipped_count}")
        
        if not new_vacancies:
            print("ℹ️  Все вакансии уже были отправлены ранее")
            try:
                await context.bot.send_message(
                    chat_id=self.chat_id,
                    text="ℹ️  Все вакансии уже были отправлены ранее. Используйте /clear_sent для очистки списка."
                )
            except:
                pass
            return
        
        # Ограничиваем количество вакансий для отправки
        vacancies_to_send = new_vacancies[:limit]
        remaining_count = len(new_vacancies) - len(vacancies_to_send)
        
        print(f"📤 Отправляю {len(vacancies_to_send)} вакансий (осталось {remaining_count})...")
        
        sent_count = 0
        failed_count = 0
        for vacancy in vacancies_to_send:
            try:
                success = await self.send_vacancy(vacancy, context)
                if success:
                    sent_count += 1
                else:
                    failed_count += 1
                await asyncio.sleep(1)  # Задержка между отправками
            except Exception as e:
                print(f"❌ Ошибка при отправке вакансии {vacancy.get('title', 'Без названия')}: {e}")
                failed_count += 1
        
        print(f"✅ Отправлено {sent_count} из {len(vacancies_to_send)} вакансий!")
        if failed_count > 0:
            print(f"⚠️  Не удалось отправить {failed_count} вакансий")
        
        # Если есть еще вакансии и нужно показать кнопку
        if remaining_count > 0 and show_more_button:
            await self._send_more_button(context, remaining_count)
    
    def get_menu_keyboard(self) -> ReplyKeyboardMarkup:
        """Создание клавиатуры меню"""
        keyboard = [
            [KeyboardButton("🆕 Отправить свежие вакансии"), KeyboardButton("📤 Отправить вакансии")],
            [KeyboardButton("📄 Резюме"), KeyboardButton("🗑️ Очистить резюме")],
            [KeyboardButton("🔄 Очистить отправленные"), KeyboardButton("ℹ️ Помощь")],
            [KeyboardButton("📋 Меню")]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        # Создаем меню с кнопками
        menu_keyboard = self.get_menu_keyboard()
        
        await update.message.reply_text(
            "Привет! Я помогу тебе с поиском работы. Просто отправь своё резюме в формате word или pdf, я возьму из него твою должность и ожидания по заработной плате, если они там указаны. Дальше я буду отправлять тебе актуальные вакансии",
            reply_markup=menu_keyboard
        )
    
    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /menu - показ меню с кнопками"""
        sent_count = len(self.sent_vacancies)
        menu_keyboard = self.get_menu_keyboard()
        
        await update.message.reply_text(
            "📋 <b>Меню бота</b>\n\n"
            "Доступные функции:\n\n"
            "📤 <b>Отправить вакансии</b> - отправить новые вакансии из файла\n"
            "📄 <b>Резюме</b> - загрузить или посмотреть резюме\n"
            "🗑️ <b>Очистить резюме</b> - удалить загруженное резюме\n"
            "🔄 <b>Очистить отправленные</b> - очистить список отправленных вакансий\n"
            "ℹ️ <b>Помощь</b> - показать справку\n"
            "📋 <b>Меню</b> - показать это меню\n\n"
            f"📊 Отправлено вакансий ранее: {sent_count}",
            reply_markup=menu_keyboard,
            parse_mode='HTML'
        )
    
    async def send_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /send - отправка всех вакансий"""
        menu_keyboard = self.get_menu_keyboard()
        try:
            await update.message.reply_text("📤 Начинаю отправку вакансий...", reply_markup=menu_keyboard)
            await self.send_all_vacancies(context)
            await update.message.reply_text("✅ Отправка завершена!", reply_markup=menu_keyboard)
        except Exception as e:
            error_msg = f"❌ Ошибка при отправке: {e}"
            print(error_msg)
            try:
                await update.message.reply_text(error_msg, reply_markup=menu_keyboard)
            except:
                pass  # Если не можем отправить сообщение об ошибке
    
    async def clear_sent_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /clear_sent - очистка списка отправленных вакансий"""
        try:
            self.sent_vacancies.clear()
            if os.path.exists(self.sent_vacancies_file):
                os.remove(self.sent_vacancies_file)
            menu_keyboard = self.get_menu_keyboard()
            await update.message.reply_text("✅ Список отправленных вакансий очищен!", reply_markup=menu_keyboard)
            print("✅ Список отправленных вакансий очищен")
        except Exception as e:
            error_msg = f"❌ Ошибка при очистке: {e}"
            print(error_msg)
            try:
                await update.message.reply_text(error_msg)
            except:
                pass
    
    async def send_fresh_vacancies_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда для отправки свежих вакансий за сегодня"""
        try:
            user_id = update.message.from_user.id
            menu_keyboard = self.get_menu_keyboard()
            
            # Обновляем свежие вакансии перед отправкой
            await self._scan_fresh_vacancies()
            
            # Получаем вакансии, которые ещё не были отправлены этому пользователю
            user_sent = self.user_sent_fresh_vacancies.get(user_id, set())
            today = datetime.now().date()
            
            # Фильтруем свежие вакансии за сегодня, которые ещё не отправлены
            available_vacancies = [
                v for v in self.fresh_vacancies
                if v.get('url', '') not in user_sent
                and self._is_vacancy_from_today(v.get('published', ''), today)
            ]
            
            if not available_vacancies:
                await update.message.reply_text(
                    "😔 Нет новых свежих вакансий за сегодня.\n\n"
                    "Бот автоматически сканирует hh.ru и обновляет список свежих вакансий.",
                    reply_markup=menu_keyboard
                )
                return
            
            # Отправляем первые 10 вакансий
            vacancies_to_send = available_vacancies[:10]
            sent_count = 0
            
            await update.message.reply_text(
                f"🆕 Отправляю {len(vacancies_to_send)} свежих вакансий за сегодня...",
                reply_markup=menu_keyboard
            )
            
            for vacancy in vacancies_to_send:
                try:
                    success = await self.send_vacancy(vacancy, context, chat_id=user_id)
                    if success:
                        sent_count += 1
                        # Отмечаем как отправленную этому пользователю
                        if user_id not in self.user_sent_fresh_vacancies:
                            self.user_sent_fresh_vacancies[user_id] = set()
                        self.user_sent_fresh_vacancies[user_id].add(vacancy.get('url', ''))
                        await asyncio.sleep(1)  # Задержка между отправками
                except Exception as e:
                    print(f"❌ Ошибка при отправке свежей вакансии: {e}")
            
            # Сохраняем данные об отправленных вакансиях
            self._save_user_sent_fresh()
            
            remaining = len(available_vacancies) - sent_count
            await update.message.reply_text(
                f"✅ Отправлено {sent_count} свежих вакансий за сегодня!\n\n"
                f"📊 Осталось новых вакансий: {remaining}\n\n"
                "Нажмите кнопку ещё раз, чтобы получить следующую порцию.",
                reply_markup=menu_keyboard
            )
            
        except Exception as e:
            print(f"❌ Ошибка при отправке свежих вакансий: {e}")
            import traceback
            traceback.print_exc()
            try:
                menu_keyboard = self.get_menu_keyboard()
                await update.message.reply_text(
                    f"❌ Ошибка при отправке свежих вакансий: {e}",
                    reply_markup=menu_keyboard
                )
            except:
                pass
    
    async def _scan_fresh_vacancies(self):
        """Сканирование hh.ru для получения свежих вакансий за сегодня"""
        try:
            print("🔍 Сканирую hh.ru для получения свежих вакансий...")
            today = datetime.now().date()
            
            # Получаем все активные подписки пользователей
            active_positions = set()
            for sub in self.user_subscriptions.values():
                if sub.get('active', False):
                    active_positions.add(sub.get('position', ''))
            
            # Если нет активных подписок, используем общий поиск
            if not active_positions:
                active_positions = {'Product Manager', 'Продакт менеджер'}
            
            new_vacancies = []
            
            # Сканируем для каждой должности
            for position in active_positions:
                if not position:
                    continue
                
                vacancies = self._search_hh_ru_for_position(position, None)
                
                # Фильтруем только сегодняшние вакансии
                today_vacancies = [
                    v for v in vacancies
                    if self._is_vacancy_from_today(v.get('published', ''), today)
                ]
                
                new_vacancies.extend(today_vacancies)
            
            # Удаляем дубликаты по URL
            seen_urls = set()
            unique_vacancies = []
            for v in new_vacancies:
                url = v.get('url', '')
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    unique_vacancies.append(v)
            
            # Обновляем список свежих вакансий
            # Сохраняем только сегодняшние
            self.fresh_vacancies = [
                v for v in unique_vacancies
                if self._is_vacancy_from_today(v.get('published', ''), today)
            ]
            
            # Сохраняем в файл
            self._save_fresh_vacancies()
            
            print(f"✅ Найдено {len(self.fresh_vacancies)} свежих вакансий за сегодня")
            
        except Exception as e:
            print(f"❌ Ошибка при сканировании свежих вакансий: {e}")
            import traceback
            traceback.print_exc()
    
    async def _start_vacancy_scanner(self, app):
        """Запуск периодического сканирования вакансий"""
        try:
            # Сканируем сразу при запуске
            print("🔍 Первичное сканирование свежих вакансий...")
            await self._scan_fresh_vacancies()
            
            # Проверяем наличие job_queue
            if not app.job_queue:
                print("⚠️ Job queue не инициализирован, используем альтернативный метод")
                # Используем альтернативный метод через asyncio
                async def periodic_scan():
                    while True:
                        await asyncio.sleep(1800)  # 30 минут
                        print("🔍 Периодическое сканирование свежих вакансий...")
                        await self._scan_fresh_vacancies()
                
                # Запускаем в фоне
                asyncio.create_task(periodic_scan())
                print("✅ Периодическое сканирование вакансий запущено через asyncio (каждые 30 минут)")
            else:
                # Настраиваем периодическое сканирование каждые 30 минут через job_queue
                def periodic_scan_callback(context: ContextTypes.DEFAULT_TYPE):
                    """Callback для периодического сканирования"""
                    asyncio.create_task(self._scan_fresh_vacancies())
                
                # Запускаем периодическое сканирование
                app.job_queue.run_repeating(
                    periodic_scan_callback,
                    interval=1800,  # 30 минут
                    first=1800  # Первый запуск через 30 минут
                )
                print("✅ Периодическое сканирование вакансий настроено через job_queue (каждые 30 минут)")
        except Exception as e:
            print(f"⚠️ Ошибка при запуске сканера вакансий: {e}")
            import traceback
            traceback.print_exc()
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /help - справка по использованию бота"""
        menu_keyboard = self.get_menu_keyboard()
        await update.message.reply_text(
            "ℹ️ <b>Справка по использованию бота</b>\n\n"
            "<b>Основные команды:</b>\n"
            "/start - запустить бота и показать приветствие\n"
            "/send - отправить новые вакансии из файла\n"
            "/menu - показать меню с кнопками\n"
            "/help - показать эту справку\n\n"
            "<b>Работа с резюме:</b>\n"
            "/resume - загрузить резюме (файл или текст)\n"
            "/clear_resume - удалить загруженное резюме\n\n"
            "<b>Управление вакансиями:</b>\n"
            "/clear_sent - очистить список отправленных вакансий\n\n"
            "<b>Свежие вакансии:</b>\n"
            "🆕 Кнопка 'Отправить свежие вакансии' отправляет 10 вакансий за сегодня.\n"
            "Бот автоматически сканирует hh.ru каждые 30 минут.\n\n"
            "<b>Как использовать:</b>\n"
            "1. Загрузите резюме командой /resume или через меню\n"
            "2. Отправьте вакансии командой /send или через меню\n"
            "3. Для каждой вакансии выберите, нужно ли сопроводительное письмо\n"
            "4. Если нужно - бот сгенерирует письмо на основе вашего резюме\n\n"
            "💡 Используйте кнопки меню для быстрого доступа к функциям!",
            reply_markup=menu_keyboard,
            parse_mode='HTML'
        )


def main():
    """Основная функция"""
    # Перезагружаем переменные на случай, если они изменились
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
    
    if not TELEGRAM_BOT_TOKEN:
        print("❌ Ошибка: TELEGRAM_BOT_TOKEN не установлен!")
        print("\nПопробуйте:")
        print("1. Установить переменную: export TELEGRAM_BOT_TOKEN='ваш_токен'")
        print("2. Или убедитесь, что файл .env существует и содержит TELEGRAM_BOT_TOKEN")
        print(f"3. Проверьте текущее значение: {os.getenv('TELEGRAM_BOT_TOKEN', 'НЕ УСТАНОВЛЕН')}")
        return
    
    if not TELEGRAM_CHAT_ID:
        print("❌ Ошибка: TELEGRAM_CHAT_ID не установлен!")
        print("\nПопробуйте:")
        print("1. Установить переменную: export TELEGRAM_CHAT_ID='ваш_chat_id'")
        print("2. Или убедитесь, что файл .env существует и содержит TELEGRAM_CHAT_ID")
        print("3. Используйте get_chat_id.py для получения правильного Chat ID")
        print(f"4. Проверьте текущее значение: {os.getenv('TELEGRAM_CHAT_ID', 'НЕ УСТАНОВЛЕН')}")
        return
    
    print(f"✅ Токен бота загружен: {TELEGRAM_BOT_TOKEN[:20]}...")
    print(f"✅ Chat ID загружен: {TELEGRAM_CHAT_ID}")
    
    bot = TelegramVacancyBot()
    
    # Проверяем подключение к Telegram API перед запуском
    print("🔍 Проверяю подключение к Telegram API...")
    try:
        import asyncio
        from telegram import Bot
        
        async def test_connection():
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            try:
                me = await bot.get_me()
                print(f"✅ Бот подключен: @{me.username}")
                return True
            except Exception as e:
                print(f"❌ Ошибка подключения: {e}")
                return False
        
        if not asyncio.run(test_connection()):
            print("\n⚠️ Не удалось подключиться к Telegram API.")
            print("Проверьте:")
            print("1. Интернет-соединение")
            print("2. Правильность токена бота")
            print("3. Доступность api.telegram.org")
            return
    except Exception as e:
        print(f"⚠️ Ошибка при проверке подключения: {e}")
    
    # Создаем приложение с увеличенным таймаутом
    # Исправляем проблему с event loop для Python 3.9+
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Запускаем периодическое сканирование вакансий после запуска polling
    async def post_init(app: Application) -> None:
        """Инициализация после запуска приложения"""
        # Небольшая задержка для полной инициализации job_queue
        await asyncio.sleep(2)
        await bot._start_vacancy_scanner(app)
    
    application.post_init = post_init
    
    # Добавляем обработчик ошибок
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка ошибок"""
        error = context.error
        if isinstance(error, Exception):
            error_msg = str(error)
            print(f"❌ Ошибка: {error_msg}")
            if "Timed out" in error_msg or "ConnectTimeout" in error_msg:
                print("⚠️ Таймаут подключения к Telegram. Проверьте интернет-соединение.")
            elif "Unauthorized" in error_msg:
                print("⚠️ Неверный токен бота. Проверьте TELEGRAM_BOT_TOKEN.")
            elif "Chat not found" in error_msg:
                print("⚠️ Чат не найден. Проверьте TELEGRAM_CHAT_ID.")
    
    application.add_error_handler(error_handler)
    
    # Загружаем сохраненные резюме
    bot._load_saved_resumes()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", bot.start_command))
    application.add_handler(CommandHandler("send", bot.send_command))
    application.add_handler(CommandHandler("resume", bot.resume_command))
    application.add_handler(CommandHandler("clear_resume", bot.clear_resume_command))
    application.add_handler(CommandHandler("clear_sent", bot.clear_sent_command))
    application.add_handler(CommandHandler("menu", bot.menu_command))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CallbackQueryHandler(bot.handle_callback))
    
    # Обработчики для загрузки резюме
    application.add_handler(MessageHandler(filters.Document.ALL, bot.handle_document))
    # Обработчик текстовых сообщений (кнопки меню и резюме)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text_message))
    
    print("🤖 Бот запущен! Ожидаю команды...")
    print("Используйте /start для начала работы")
    print("Используйте /send для отправки всех вакансий")
    
    # Запускаем бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
