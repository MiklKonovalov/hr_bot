#!/usr/bin/env python3
"""
Скрипт для поиска актуальных вакансий Product Manager
на различных площадках
"""

import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
from typing import List, Dict, Optional
import time
import os
import re

# Загрузка переменных из .env файла (если есть)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class ProductManagerVacancyFinder:
    def __init__(self, min_salary: Optional[int] = None, min_experience_years: Optional[int] = None, max_vacancies: Optional[int] = None):
        """
        Инициализация поисковика вакансий
        
        Args:
            min_salary: Минимальная зарплата (фильтр по зарплате)
            min_experience_years: Минимальный опыт в годах (фильтр по опыту)
            max_vacancies: Максимальное количество вакансий для вывода (по умолчанию 10)
        """
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.vacancies = []
        
        # Загружаем фильтры из переменных окружения или параметров
        self.min_salary = min_salary or self._get_int_env('MIN_SALARY')
        self.min_experience_years = min_experience_years or self._get_int_env('MIN_EXPERIENCE_YEARS')
        self.max_vacancies = max_vacancies or self._get_int_env('MAX_VACANCIES') or 10
        
        if self.min_salary:
            print(f"💰 Фильтр по зарплате: от {self.min_salary:,} руб.")
        if self.min_experience_years:
            print(f"📅 Фильтр по опыту: от {self.min_experience_years} лет")
        if self.min_salary and self.min_experience_years:
            print("ℹ️  Вакансии должны удовлетворять ОБОИМ фильтрам (И)")
            print("   💡 Вакансии без указания зарплаты проходят, если подходят по опыту")
        elif self.min_salary or self.min_experience_years:
            print("ℹ️  Применяется заданный фильтр")
        print(f"📊 Максимальное количество вакансий: {self.max_vacancies}\n")
    
    def _get_int_env(self, key: str) -> Optional[int]:
        """Получение целочисленной переменной окружения"""
        value = os.getenv(key)
        if value:
            try:
                return int(value)
            except ValueError:
                return None
        return None
    
    def _is_product_manager_vacancy(self, title: str) -> bool:
        """Проверка, является ли вакансия Product Manager"""
        title_lower = title.lower()
        pm_keywords = [
            'product manager', 'продакт менеджер', 'продакт-менеджер', 
            'product owner', 'продакт оунер', 'продакт-оунер',
            'product lead', 'продакт лид', 'продакт-лид',
            'product', 'продакт', 'pm', 'po'
        ]
        exclude_keywords = [
            'project manager', 'проект менеджер', 'проект-менеджер',
            'project', 'проект', 'программный менеджер', 'program manager'
        ]
        
        # Проверяем наличие ключевых слов Product Manager
        has_pm = any(keyword in title_lower for keyword in pm_keywords)
        
        # Исключаем Project Manager (если нет упоминания Product)
        has_exclude = any(keyword in title_lower for keyword in exclude_keywords)
        
        if has_pm:
            # Если есть исключающие слова, проверяем, что есть явное упоминание Product
            if has_exclude:
                return 'product' in title_lower or 'продакт' in title_lower
            return True
        return False
    
    def search_hh_ru(self) -> List[Dict]:
        """Поиск вакансий на HeadHunter с пагинацией"""
        print("🔍 Поиск на hh.ru...")
        vacancies = []
        try:
            # HH API endpoint
            url = "https://api.hh.ru/vacancies"
            
            # Определяем, сколько вакансий нужно собрать (берем больше для фильтрации)
            # Если max_vacancies не задан, собираем до 200 вакансий для фильтрации
            target_count = max(200, self.max_vacancies * 5) if self.max_vacancies else 200
            
            # Максимум страниц для запроса (HH API обычно дает до 2000 результатов = 20 страниц по 100)
            max_pages = min(20, (target_count // 100) + 1)
            per_page = 100  # Максимум для HH API
            
            print(f"   📄 Будет запрошено до {max_pages} страниц (по {per_page} вакансий на страницу)")
            
            for page in range(max_pages):
                params = {
                    'text': 'Product Manager OR Продакт менеджер OR Product Owner OR Продакт оунер',
                    'area': ['1', '2'],  # Москва и Санкт-Петербург
                    'per_page': per_page,
                    'page': page
                }
                
                response = requests.get(url, params=params, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    items = data.get('items', [])
                    
                    if not items:
                        print(f"   ℹ️  Страница {page + 1}: нет вакансий, завершаю поиск")
                        break
                    
                    found_on_page = 0
                    for item in items:
                        title = item.get('name', '')
                        # Фильтруем только Product Manager вакансии
                        if self._is_product_manager_vacancy(title):
                            # Получаем данные о зарплате и опыте
                            salary_data = item.get('salary')
                            experience_data = item.get('experience', {})
                            
                            vacancy = {
                                'title': title,
                                'company': item.get('employer', {}).get('name', ''),
                                'location': item.get('area', {}).get('name', ''),
                                'salary': self._format_salary(salary_data),
                                'salary_data': salary_data,  # Сохраняем сырые данные для фильтрации
                                'experience': experience_data.get('id'),  # Сохраняем ID опыта
                                'experience_name': experience_data.get('name', ''),  # Название опыта
                                'url': item.get('alternate_url', ''),
                                'source': 'hh.ru',
                                'published': item.get('published_at', '')
                            }
                            vacancies.append(vacancy)
                            found_on_page += 1
                    
                    print(f"   📄 Страница {page + 1}: найдено {found_on_page} подходящих вакансий (всего собрано: {len(vacancies)})")
                    
                    # Проверяем, достигли ли нужного количества
                    if len(vacancies) >= target_count:
                        print(f"   ✅ Собрано достаточно вакансий ({len(vacancies)}), завершаю поиск")
                        break
                    
                    # Проверяем, есть ли еще страницы
                    pages = data.get('pages', 0)
                    found = data.get('found', 0)
                    if page + 1 >= pages:
                        print(f"   ℹ️  Достигнут конец результатов (всего найдено на HH: {found})")
                        break
                    
                    # Задержка между запросами, чтобы не перегружать API
                    if page < max_pages - 1:
                        time.sleep(0.5)
                else:
                    print(f"   ⚠️  Ошибка при запросе страницы {page + 1}: статус {response.status_code}")
                    break
                    
        except Exception as e:
            print(f"❌ Ошибка при поиске на hh.ru: {e}")
        
        print(f"   ✅ Всего собрано с hh.ru: {len(vacancies)} вакансий")
        return vacancies
    
    def search_avito(self) -> List[Dict]:
        """Поиск вакансий на Авито"""
        print("🔍 Поиск на Авито...")
        vacancies = []
        try:
            # Авито API или парсинг
            url = "https://www.avito.ru/all/vakansii"
            params = {
                'q': 'Product Manager Продакт менеджер',
                'p': 1
            }
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                # Парсинг структуры Авито (требует адаптации под актуальную структуру)
                items = soup.find_all('div', class_='iva-item-content')[:10]
                for item in items:
                    title_elem = item.find('h3', class_='title-root')
                    if title_elem:
                        vacancy = {
                            'title': title_elem.get_text(strip=True),
                            'company': 'Не указано',
                            'location': 'Не указано',
                            'salary': 'Не указано',
                            'salary_data': None,
                            'experience': None,
                            'experience_name': '',
                            'url': 'https://www.avito.ru' + (item.find('a', href=True)['href'] if item.find('a', href=True) else ''),
                            'source': 'avito.ru',
                            'published': datetime.now().isoformat()
                        }
                        vacancies.append(vacancy)
        except Exception as e:
            print(f"❌ Ошибка при поиске на Авито: {e}")
        return vacancies
    
    def search_habr_career(self) -> List[Dict]:
        """Поиск вакансий на Habr Career"""
        print("🔍 Поиск на Habr Career...")
        vacancies = []
        try:
            url = "https://career.habr.com/vacancies"
            params = {
                'q': 'Product Manager Продакт менеджер',
                'type': 'all'
            }
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                # Парсинг структуры Habr (требует адаптации)
                # Берем больше для фильтрации (в 2-3 раза больше, чем нужно)
                items_limit = max(50, self.max_vacancies * 5) if self.max_vacancies else 50
                items = soup.find_all('div', class_='vacancy-card')[:items_limit]
                for item in items:
                    title_elem = item.find('a', class_='vacancy-card__title-link')
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                        # Фильтруем только Product Manager вакансии
                        if self._is_product_manager_vacancy(title):
                            vacancy = {
                                'title': title,
                                'company': 'Не указано',
                                'location': 'Не указано',
                                'salary': 'Не указано',
                                'salary_data': None,
                                'experience': None,
                                'experience_name': '',
                                'url': 'https://career.habr.com' + title_elem.get('href', ''),
                                'source': 'habr.com',
                                'published': datetime.now().isoformat()
                            }
                            vacancies.append(vacancy)
                            # Ограничиваем количество вакансий (берем больше для фильтрации)
                            # Берем в 2-3 раза больше, чем нужно, чтобы после фильтрации осталось достаточно
                            limit = max(30, self.max_vacancies * 3) if self.max_vacancies else 30
                            if len(vacancies) >= limit:
                                break
        except Exception as e:
            print(f"❌ Ошибка при поиске на Habr Career: {e}")
        return vacancies
    
    def search_sber(self) -> List[Dict]:
        """Поиск вакансий на карьерном сайте Сбера"""
        print("🔍 Поиск на Сбер (career.sber.ru)...")
        vacancies = []
        
        # Сначала пробуем через HH API - это более надежный способ
        try:
            hh_url = "https://api.hh.ru/vacancies"
            search_queries = [
                {'text': 'Product Manager Сбер', 'per_page': 10},
                {'text': 'Продакт менеджер Сбербанк', 'per_page': 10},
                {'text': 'Product Manager', 'employer_id': '3529'},  # ID Сбера на HH
            ]
            
            for params in search_queries:
                if 'per_page' not in params:
                    params['per_page'] = 10
                response = requests.get(hh_url, params=params, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    for item in data.get('items', []):
                        title = item.get('name', '')
                        employer_name = item.get('employer', {}).get('name', '').lower()
                        # Проверяем, что это действительно Сбер
                        if self._is_product_manager_vacancy(title) and ('сбер' in employer_name or 'sber' in employer_name or 'сбербанк' in employer_name):
                            salary_data = item.get('salary')
                            experience_data = item.get('experience', {})
                            vacancy = {
                                'title': title,
                                'company': item.get('employer', {}).get('name', 'Сбер'),
                                'location': item.get('area', {}).get('name', 'Москва'),
                                'salary': self._format_salary(salary_data),
                                'salary_data': salary_data,
                                'experience': experience_data.get('id'),
                                'experience_name': experience_data.get('name', ''),
                                'url': item.get('alternate_url', ''),
                                'source': 'hh.ru (Сбер)',
                                'published': item.get('published_at', '')
                            }
                            vacancies.append(vacancy)
                            if len(vacancies) >= 5:
                                break
                    if vacancies:
                        break
        except Exception as e:
            print(f"   ⚠️  Ошибка поиска через HH API: {e}")
        
        # Если не нашли через HH, пробуем парсинг сайта
        if not vacancies:
            try:
                # Пробуем несколько вариантов URL
                urls = [
                    "https://career.sber.ru/vacancies",
                    "https://sberbank.ru/careers/vacancies",
                    "https://www.sberbank.ru/careers/vacancies"
                ]
                
                for base_url in urls:
                    try:
                        # Пробуем поиск через API или парсинг
                        search_url = f"{base_url}?query=Product Manager"
                        response = requests.get(search_url, headers=self.headers, timeout=10)
                        
                        if response.status_code == 200:
                            soup = BeautifulSoup(response.text, 'html.parser')
                            
                            # Различные возможные селекторы для вакансий
                            selectors = [
                                ('div', {'class': 'vacancy-item'}),
                                ('div', {'class': 'vacancy-card'}),
                                ('a', {'class': 'vacancy-link'}),
                                ('div', {'data-vacancy': True}),
                            ]
                            
                            for tag, attrs in selectors:
                                items = soup.find_all(tag, attrs)
                                if items:
                                    for item in items:
                                        title_elem = item.find(['h2', 'h3', 'a', 'span'], class_=lambda x: x and ('title' in x.lower() or 'name' in x.lower()))
                                        if not title_elem:
                                            title_elem = item.find(['h2', 'h3', 'a'])
                                        
                                        if title_elem:
                                            title = title_elem.get_text(strip=True)
                                            if self._is_product_manager_vacancy(title):
                                                link = item.find('a', href=True)
                                                url = link['href'] if link else base_url
                                                if not url.startswith('http'):
                                                    url = f"https://career.sber.ru{url}" if url.startswith('/') else f"{base_url}/{url}"
                                                
                                                vacancy = {
                                                    'title': title,
                                                    'company': 'Сбер',
                                                    'location': 'Москва',
                                                    'salary': 'Не указано',
                                                    'salary_data': None,
                                                    'experience': None,
                                                    'experience_name': '',
                                                    'url': url,
                                                    'source': 'career.sber.ru',
                                                    'published': datetime.now().isoformat()
                                                }
                                                vacancies.append(vacancy)
                                                if len(vacancies) >= 5:
                                                    break
                                    if vacancies:
                                        break
                            if vacancies:
                                break
                    except Exception as e:
                        continue
            except Exception as e:
                print(f"   ⚠️  Ошибка при парсинге сайта Сбера: {e}")
                    
        return vacancies
    
    def search_tinkoff(self) -> List[Dict]:
        """Поиск вакансий на карьерном сайте Т-Банка (Tinkoff)"""
        print("🔍 Поиск на Т-Банк (Tinkoff)...")
        vacancies = []
        
        # Сначала пробуем через HH API
        try:
            hh_url = "https://api.hh.ru/vacancies"
            search_queries = [
                {'text': 'Product Manager Tinkoff', 'per_page': 10},
                {'text': 'Продакт менеджер Тинькофф', 'per_page': 10},
                {'text': 'Product Manager', 'employer_id': '78638'},  # ID Tinkoff на HH
            ]
            
            for params in search_queries:
                if 'per_page' not in params:
                    params['per_page'] = 10
                response = requests.get(hh_url, params=params, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    for item in data.get('items', []):
                        title = item.get('name', '')
                        employer_name = item.get('employer', {}).get('name', '').lower()
                        # Проверяем, что это действительно Tinkoff
                        if self._is_product_manager_vacancy(title) and ('tinkoff' in employer_name or 'тинькофф' in employer_name or 't-банк' in employer_name):
                            salary_data = item.get('salary')
                            experience_data = item.get('experience', {})
                            vacancy = {
                                'title': title,
                                'company': item.get('employer', {}).get('name', 'Т-Банк (Tinkoff)'),
                                'location': item.get('area', {}).get('name', 'Москва'),
                                'salary': self._format_salary(salary_data),
                                'salary_data': salary_data,
                                'experience': experience_data.get('id'),
                                'experience_name': experience_data.get('name', ''),
                                'url': item.get('alternate_url', ''),
                                'source': 'hh.ru (Tinkoff)',
                                'published': item.get('published_at', '')
                            }
                            vacancies.append(vacancy)
                            if len(vacancies) >= 5:
                                break
                    if vacancies:
                        break
        except Exception as e:
            print(f"   ⚠️  Ошибка поиска через HH API: {e}")
        
        # Если не нашли через HH, пробуем парсинг сайта
        if not vacancies:
            try:
                # Пробуем несколько вариантов URL
                urls = [
                    "https://www.tinkoff.ru/career/vacancies/",
                    "https://jobs.tinkoff.ru/",
                    "https://www.tinkoff.ru/career/"
                ]
                
                for base_url in urls:
                    try:
                        response = requests.get(base_url, headers=self.headers, timeout=10)
                        
                        if response.status_code == 200:
                            soup = BeautifulSoup(response.text, 'html.parser')
                            
                            # Различные возможные селекторы
                            selectors = [
                                ('div', {'class': 'vacancy'}),
                                ('div', {'class': 'vacancy-card'}),
                                ('a', {'class': 'vacancy-link'}),
                                ('div', {'class': 'job-item'}),
                            ]
                            
                            for tag, attrs in selectors:
                                items = soup.find_all(tag, attrs)
                                if items:
                                    for item in items:
                                        title_elem = item.find(['h2', 'h3', 'a', 'span'], class_=lambda x: x and ('title' in x.lower() or 'name' in x.lower()))
                                        if not title_elem:
                                            title_elem = item.find(['h2', 'h3', 'a'])
                                        
                                        if title_elem:
                                            title = title_elem.get_text(strip=True)
                                            if self._is_product_manager_vacancy(title):
                                                link = item.find('a', href=True)
                                                url = link['href'] if link else base_url
                                                if not url.startswith('http'):
                                                    url = f"https://www.tinkoff.ru{url}" if url.startswith('/') else f"{base_url}/{url}"
                                                
                                                vacancy = {
                                                    'title': title,
                                                    'company': 'Т-Банк (Tinkoff)',
                                                    'location': 'Москва',
                                                    'salary': 'Не указано',
                                                    'salary_data': None,
                                                    'experience': None,
                                                    'experience_name': '',
                                                    'url': url,
                                                    'source': 'tinkoff.ru',
                                                    'published': datetime.now().isoformat()
                                                }
                                                vacancies.append(vacancy)
                                                if len(vacancies) >= 5:
                                                    break
                                    if vacancies:
                                        break
                            if vacancies:
                                break
                    except Exception as e:
                        continue
            except Exception as e:
                print(f"   ⚠️  Ошибка при парсинге сайта Т-Банка: {e}")
                    
        return vacancies
    
    def search_aviasales(self) -> List[Dict]:
        """Поиск вакансий на карьерном сайте Aviasales"""
        print("🔍 Поиск на Aviasales...")
        vacancies = []
        
        # Сначала пробуем через HH API
        try:
            hh_url = "https://api.hh.ru/vacancies"
            search_queries = [
                {'text': 'Product Manager Aviasales', 'per_page': 10},
                {'text': 'Продакт менеджер Авиасейлс', 'per_page': 10},
                {'text': 'Product Manager', 'employer_id': '1455'},  # Aviasales (примерный ID)
            ]
            
            for params in search_queries:
                if 'per_page' not in params:
                    params['per_page'] = 10
                response = requests.get(hh_url, params=params, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    for item in data.get('items', []):
                        title = item.get('name', '')
                        employer_name = item.get('employer', {}).get('name', '').lower()
                        # Проверяем, что это действительно Aviasales
                        if self._is_product_manager_vacancy(title) and ('aviasales' in employer_name or 'авиасейлс' in employer_name):
                            salary_data = item.get('salary')
                            experience_data = item.get('experience', {})
                            vacancy = {
                                'title': title,
                                'company': item.get('employer', {}).get('name', 'Aviasales'),
                                'location': item.get('area', {}).get('name', 'Москва'),
                                'salary': self._format_salary(salary_data),
                                'salary_data': salary_data,
                                'experience': experience_data.get('id'),
                                'experience_name': experience_data.get('name', ''),
                                'url': item.get('alternate_url', ''),
                                'source': 'hh.ru (Aviasales)',
                                'published': item.get('published_at', '')
                            }
                            vacancies.append(vacancy)
                            if len(vacancies) >= 5:
                                break
                    if vacancies:
                        break
        except Exception as e:
            print(f"   ⚠️  Ошибка поиска через HH API: {e}")
        
        # Если не нашли через HH, пробуем парсинг сайта
        if not vacancies:
            try:
                # Пробуем несколько вариантов URL
                urls = [
                    "https://careers.aviasales.ru/",
                    "https://www.aviasales.ru/jobs",
                    "https://aviasales.ru/careers"
                ]
                
                for base_url in urls:
                    try:
                        response = requests.get(base_url, headers=self.headers, timeout=10)
                        
                        if response.status_code == 200:
                            soup = BeautifulSoup(response.text, 'html.parser')
                            
                            # Различные возможные селекторы
                            selectors = [
                                ('div', {'class': 'vacancy'}),
                                ('div', {'class': 'vacancy-card'}),
                                ('a', {'class': 'vacancy-link'}),
                                ('div', {'class': 'job-item'}),
                                ('div', {'class': 'position'}),
                            ]
                            
                            for tag, attrs in selectors:
                                items = soup.find_all(tag, attrs)
                                if items:
                                    for item in items:
                                        title_elem = item.find(['h2', 'h3', 'a', 'span'], class_=lambda x: x and ('title' in x.lower() or 'name' in x.lower()))
                                        if not title_elem:
                                            title_elem = item.find(['h2', 'h3', 'a'])
                                        
                                        if title_elem:
                                            title = title_elem.get_text(strip=True)
                                            if self._is_product_manager_vacancy(title):
                                                link = item.find('a', href=True)
                                                url = link['href'] if link else base_url
                                                if not url.startswith('http'):
                                                    url = f"https://careers.aviasales.ru{url}" if url.startswith('/') else f"{base_url}/{url}"
                                                
                                                vacancy = {
                                                    'title': title,
                                                    'company': 'Aviasales',
                                                    'location': 'Москва',
                                                    'salary': 'Не указано',
                                                    'salary_data': None,
                                                    'experience': None,
                                                    'experience_name': '',
                                                    'url': url,
                                                    'source': 'aviasales.ru',
                                                    'published': datetime.now().isoformat()
                                                }
                                                vacancies.append(vacancy)
                                                if len(vacancies) >= 5:
                                                    break
                                    if vacancies:
                                        break
                            if vacancies:
                                break
                    except Exception as e:
                        continue
            except Exception as e:
                print(f"   ⚠️  Ошибка при парсинге сайта Aviasales: {e}")
                    
        return vacancies
    
    def _format_salary(self, salary_data: Dict) -> str:
        """Форматирование зарплаты"""
        if not salary_data:
            return 'Не указано'
        from_sal = salary_data.get('from')
        to_sal = salary_data.get('to')
        currency = salary_data.get('currency', 'RUR')
        
        if from_sal and to_sal:
            return f"{from_sal:,} - {to_sal:,} {currency}"
        elif from_sal:
            return f"от {from_sal:,} {currency}"
        elif to_sal:
            return f"до {to_sal:,} {currency}"
        return 'Не указано'
    
    def _parse_salary_from_string(self, salary_str: str) -> Optional[int]:
        """Парсинг минимальной зарплаты из строки"""
        if not salary_str or salary_str == 'Не указано':
            return None
        
        # Убираем пробелы и запятые для парсинга
        clean_str = salary_str.replace(',', '').replace(' ', '')
        
        # Ищем паттерны типа "250000-350000", "от 250000", "250000 - 350000"
        # Сначала ищем диапазон
        range_match = re.search(r'(\d+)\s*-\s*(\d+)', clean_str)
        if range_match:
            try:
                # Берем первое число (минимальная зарплата)
                return int(range_match.group(1))
            except ValueError:
                pass
        
        # Ищем "от X"
        from_match = re.search(r'от\s*(\d+)', clean_str, re.IGNORECASE)
        if from_match:
            try:
                return int(from_match.group(1))
            except ValueError:
                pass
        
        # Ищем просто числа
        numbers = re.findall(r'\d+', clean_str)
        if numbers:
            # Берем первое число (минимальная зарплата)
            try:
                return int(numbers[0])
            except ValueError:
                return None
        return None
    
    def _get_experience_years_from_hh_id(self, experience_id: str) -> Optional[int]:
        """
        Преобразование ID опыта из HH API в количество лет
        HH API использует следующие ID:
        - 'noExperience' = 0 лет
        - 'between1And3' = 1-3 года (берем минимум 1)
        - 'between3And6' = 3-6 лет (берем минимум 3)
        - 'moreThan6' = более 6 лет (берем минимум 6)
        """
        if not experience_id:
            return None
        
        experience_map = {
            'noExperience': 0,
            'between1And3': 1,
            'between3And6': 3,
            'moreThan6': 6
        }
        return experience_map.get(experience_id)
    
    def _parse_experience_from_string(self, experience_str: str) -> Optional[int]:
        """Парсинг опыта из строки (например, 'от 3 лет', '3+ лет')"""
        if not experience_str:
            return None
        
        experience_str_lower = experience_str.lower()
        
        # Ищем паттерны типа "от 3 лет", "3+ лет", "3 года"
        patterns = [
            r'от\s+(\d+)\s+лет',
            r'(\d+)\+\s+лет',
            r'(\d+)\s+лет',
            r'(\d+)\s+года',
            r'(\d+)\s+год'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, experience_str_lower)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue
        
        return None
    
    def _check_salary_filter(self, vacancy: Dict, allow_no_salary: bool = False) -> bool:
        """
        Проверка соответствия фильтру по зарплате
        
        Args:
            vacancy: Данные вакансии
            allow_no_salary: Если True, вакансии без зарплаты проходят фильтр (только если зарплата действительно не указана)
        """
        if not self.min_salary:
            return True  # Если фильтр не задан, считаем что проходит
        
        # Проверяем сырые данные о зарплате
        salary_data = vacancy.get('salary_data')
        has_salary_data = False
        
        if salary_data:
            has_salary_data = True
            from_sal = salary_data.get('from')
            to_sal = salary_data.get('to')
            
            # Если есть минимальная зарплата - проверяем её
            if from_sal is not None:
                if from_sal >= self.min_salary:
                    return True
                else:
                    return False  # Минимальная зарплата меньше фильтра - НЕ проходит (даже если allow_no_salary=True)
            
            # Если есть только максимальная зарплата (без минимальной)
            if to_sal is not None and from_sal is None:
                # Если максимальная меньше фильтра - точно не проходит
                if to_sal < self.min_salary:
                    return False
                # Если максимальная >= фильтра, но нет минимальной - не можем точно сказать
                # Для безопасности не пропускаем такие вакансии
                return False
        
        # Парсим из строки (для вакансий из других источников)
        salary_str = vacancy.get('salary', '')
        if salary_str and salary_str != 'Не указано':
            parsed_salary = self._parse_salary_from_string(salary_str)
            if parsed_salary is not None:
                # Если зарплата указана и меньше фильтра - НЕ проходит
                if parsed_salary < self.min_salary:
                    return False
                # Если зарплата >= фильтра - проходит
                if parsed_salary >= self.min_salary:
                    return True
        
        # Если зарплата действительно не указана (нет salary_data и нет в строке)
        if not has_salary_data and (not salary_str or salary_str == 'Не указано'):
            if allow_no_salary:
                return True  # Разрешаем вакансии без зарплаты только если allow_no_salary=True
            return False  # Не проходит фильтр
        
        # Если не смогли определить зарплату - не пропускаем
        return False
    
    def _check_experience_filter(self, vacancy: Dict) -> bool:
        """Проверка соответствия фильтру по опыту"""
        if not self.min_experience_years:
            return False
        
        # Проверяем ID опыта из HH API
        experience_id = vacancy.get('experience')
        if experience_id:
            experience_years = self._get_experience_years_from_hh_id(experience_id)
            if experience_years is not None and experience_years >= self.min_experience_years:
                return True
        
        # Парсим из строки названия опыта
        experience_name = vacancy.get('experience_name', '')
        if experience_name:
            parsed_experience = self._parse_experience_from_string(experience_name)
            if parsed_experience is not None and parsed_experience >= self.min_experience_years:
                return True
        
        # Парсим из описания вакансии (если есть)
        description = vacancy.get('description', '')
        if description:
            parsed_experience = self._parse_experience_from_string(description)
            if parsed_experience is not None and parsed_experience >= self.min_experience_years:
                return True
        
        return False
    
    def _apply_filters(self, vacancies: List[Dict]) -> List[Dict]:
        """
        Применение фильтров к вакансиям
        Вакансия проходит фильтр, если удовлетворяет ВСЕМ заданным условиям (И)
        """
        if not self.min_salary and not self.min_experience_years:
            return vacancies
        
        filtered = []
        rejected_by_salary = 0
        rejected_by_experience = 0
        rejected_by_both = 0
        
        # Если заданы оба фильтра, разрешаем вакансии без зарплаты, если они подходят по опыту
        allow_no_salary = (self.min_salary is not None and self.min_experience_years is not None)
        
        for vacancy in vacancies:
            # Проверяем все заданные фильтры
            salary_match = True  # Если фильтр не задан, считаем что проходит
            experience_match = True  # Если фильтр не задан, считаем что проходит
            
            if self.min_salary:
                salary_match = self._check_salary_filter(vacancy, allow_no_salary=allow_no_salary)
                if not salary_match:
                    rejected_by_salary += 1
            
            if self.min_experience_years:
                experience_match = self._check_experience_filter(vacancy)
                if not experience_match:
                    rejected_by_experience += 1
            
            # Вакансия проходит, если удовлетворяет ВСЕМ заданным фильтрам (И)
            # Но если заданы оба фильтра, вакансия без зарплаты проходит, если подходит по опыту
            if salary_match and experience_match:
                filtered.append(vacancy)
            elif not salary_match and not experience_match:
                rejected_by_both += 1
        
        # Выводим статистику отсева
        if self.min_salary or self.min_experience_years:
            total_rejected = len(vacancies) - len(filtered)
            if total_rejected > 0:
                print(f"   ⚠️  Отсеяно вакансий: {total_rejected}")
                if self.min_salary and rejected_by_salary > 0:
                    print(f"      - по зарплате: {rejected_by_salary}")
                if self.min_experience_years and rejected_by_experience > 0:
                    print(f"      - по опыту: {rejected_by_experience}")
                if rejected_by_both > 0:
                    print(f"      - по обоим фильтрам: {rejected_by_both}")
        
        return filtered
    
    def find_all_vacancies(self) -> List[Dict]:
        """Поиск вакансий: 10 с hh.ru и 10 с career.habr.com"""
        print("🚀 Начинаю поиск вакансий Product Manager...\n")
        print(f"📋 Ищу вакансии на hh.ru и career.habr.com (максимум: {self.max_vacancies})\n")
        
        all_vacancies = []
        
        # Поиск на hh.ru - берем 10 вакансий
        print("=" * 60)
        hh_vacancies = self.search_hh_ru()
        print(f"✅ Найдено {len(hh_vacancies)} вакансий на hh.ru")
        all_vacancies.extend(hh_vacancies)
        time.sleep(1)  # Задержка между запросами
        
        # Поиск на career.habr.com - берем 10 вакансий
        print("=" * 60)
        habr_vacancies = self.search_habr_career()
        print(f"✅ Найдено {len(habr_vacancies)} вакансий на career.habr.com")
        all_vacancies.extend(habr_vacancies)
        
        print("=" * 60)
        print(f"\n📊 Всего собрано: {len(all_vacancies)} вакансий")
        
        # Убираем дубликаты по URL
        seen_urls = set()
        unique_vacancies = []
        for vacancy in all_vacancies:
            if vacancy['url'] not in seen_urls:
                seen_urls.add(vacancy['url'])
                unique_vacancies.append(vacancy)
        
        if len(unique_vacancies) < len(all_vacancies):
            print(f"🔄 После удаления дубликатов: {len(unique_vacancies)} вакансий")
        
        # Применяем фильтры (если заданы)
        if self.min_salary or self.min_experience_years:
            print(f"\n🔍 Применяю фильтры к {len(unique_vacancies)} вакансиям...")
            filtered_vacancies = self._apply_filters(unique_vacancies)
            print(f"📊 После фильтрации: {len(filtered_vacancies)} из {len(unique_vacancies)} вакансий")
            
            # Показываем статистику по источникам
            hh_count = sum(1 for v in filtered_vacancies if v.get('source') == 'hh.ru')
            habr_count = sum(1 for v in filtered_vacancies if v.get('source') == 'habr.com')
            print(f"   - hh.ru: {hh_count} вакансий")
            print(f"   - career.habr.com: {habr_count} вакансий")
        else:
            filtered_vacancies = unique_vacancies
        
        # Ограничиваем до max_vacancies (по умолчанию 10, но можно настроить)
        self.vacancies = filtered_vacancies[:self.max_vacancies]
        print(f"✅ Итого выводится: {len(self.vacancies)} вакансий\n")
        return self.vacancies
    
    def display_vacancies(self):
        """Вывод найденных вакансий"""
        if not self.vacancies:
            print("\n❌ Вакансии не найдены")
            return
        
        print(f"\n✅ Найдено {len(self.vacancies)} вакансий:\n")
        print("=" * 80)
        
        for i, vacancy in enumerate(self.vacancies, 1):
            print(f"\n{i}. {vacancy['title']}")
            print(f"   Компания: {vacancy['company']}")
            print(f"   Локация: {vacancy['location']}")
            print(f"   Зарплата: {vacancy['salary']}")
            print(f"   Источник: {vacancy['source']}")
            print(f"   Ссылка: {vacancy['url']}")
            print("-" * 80)
    
    def save_to_json(self, filename: str = 'product_manager_vacancies.json'):
        """Сохранение результатов в JSON"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.vacancies, f, ensure_ascii=False, indent=2)
        print(f"\n💾 Результаты сохранены в {filename}")


def main():
    finder = ProductManagerVacancyFinder()
    vacancies = finder.find_all_vacancies()
    finder.display_vacancies()
    finder.save_to_json()


if __name__ == "__main__":
    main()
