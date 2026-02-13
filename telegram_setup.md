# Настройка Telegram бота для отправки вакансий

## Шаг 1: Создание Telegram бота

1. Откройте Telegram и найдите [@BotFather](https://t.me/botfather)
2. Отправьте команду `/newbot`
3. Следуйте инструкциям и создайте бота
4. Сохраните полученный токен (например: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

## Шаг 2: Получение Chat ID

### Для личного чата:
1. Напишите боту любое сообщение
2. Откройте в браузере: `https://api.telegram.org/bot<ВАШ_ТОКЕН>/getUpdates`
3. Найдите `"chat":{"id":123456789}` - это ваш Chat ID

### Для канала:
1. Добавьте бота в канал как администратора
2. Отправьте сообщение в канал
3. Откройте: `https://api.telegram.org/bot<ВАШ_ТОКЕН>/getUpdates`
4. Найдите `"chat":{"id":-1001234567890}` - это Chat ID канала (отрицательное число)

## Шаг 3: Установка переменных окружения

### Linux/Mac:
```bash
export TELEGRAM_BOT_TOKEN="ваш_токен_бота"
export TELEGRAM_CHAT_ID="ваш_chat_id"
```

### Windows (PowerShell):
```powershell
$env:TELEGRAM_BOT_TOKEN="ваш_токен_бота"
$env:TELEGRAM_CHAT_ID="ваш_chat_id"
```

### Или создайте файл .env:
```bash
cp .env.example .env
# Отредактируйте .env и добавьте свои токены
```

## Шаг 4: Установка зависимостей

```bash
pip install -r requirements.txt
```

## Шаг 5: Запуск бота

```bash
python3 telegram_vacancy_bot.py
```

## Использование

1. Напишите боту `/start` для начала работы
2. Используйте `/send` для отправки всех вакансий из файла `product_manager_vacancies.json`
3. Для каждой вакансии появятся кнопки "Да" или "Нет"
4. При нажатии "Да" будет сгенерировано сопроводительное письмо

## Опционально: Улучшенная генерация писем через OpenAI

1. Получите API ключ на [OpenAI](https://platform.openai.com/api-keys)
2. Добавьте в переменные окружения:
   ```bash
   export OPENAI_API_KEY="ваш_openai_api_key"
   ```
3. Установите библиотеку OpenAI:
   ```bash
   pip install openai
   ```

## Примечания

- Бот должен быть запущен постоянно для обработки callback от кнопок
- Для работы в канале бот должен быть администратором
- Файл с вакансиями должен быть создан заранее через `ios_vacancies_finder.py`
