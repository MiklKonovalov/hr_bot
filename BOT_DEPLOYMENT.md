# Инструкция по постоянному запуску бота

Есть несколько способов запустить бота так, чтобы он работал постоянно:

## Способ 1: Использование screen (Рекомендуется для начала)

**Screen** - простой способ запустить бота в фоновом режиме в терминале.

### Установка screen (если не установлен):
```bash
# macOS
brew install screen
```

### Запуск бота:
```bash
# 1. Создайте сессию screen
screen -S telegram_bot

# 2. В сессии screen запустите бота
cd /Users/konovalovmihail/hr_app
chmod +x start_bot.sh
./start_bot.sh

# 3. Отключитесь от сессии (бот продолжит работать)
# Нажмите: Ctrl+A, затем D
```

### Управление:
```bash
# Посмотреть список сессий
screen -ls

# Подключиться к сессии
screen -r telegram_bot

# Остановить бота
# Подключитесь к сессии (screen -r telegram_bot)
# Нажмите Ctrl+C для остановки
# Выйдите из сессии: exit
```

---

## Способ 2: Использование tmux

**Tmux** - более современная альтернатива screen.

### Установка tmux:
```bash
brew install tmux
```

### Запуск бота:
```bash
# 1. Создайте сессию tmux
tmux new -s telegram_bot

# 2. В сессии запустите бота
cd /Users/konovalovmihail/hr_app
./start_bot.sh

# 3. Отключитесь от сессии
# Нажмите: Ctrl+B, затем D
```

### Управление:
```bash
# Посмотреть список сессий
tmux ls

# Подключиться к сессии
tmux attach -t telegram_bot

# Остановить бота
# Подключитесь к сессии
# Нажмите Ctrl+C
# Выйдите: exit
```

---

## Способ 3: Использование launchd (macOS сервис)

**Launchd** - нативный способ macOS для запуска приложений как системных сервисов.
Бот будет автоматически запускаться при загрузке системы и перезапускаться при сбоях.

### Настройка:

1. **Отредактируйте plist файл:**
   ```bash
   # Откройте файл com.telegram.vacancy.bot.plist
   # Убедитесь, что пути правильные:
   # - /Users/konovalovmihail/hr_app/telegram_vacancy_bot.py
   # - /Users/konovalovmihail/hr_app (рабочая директория)
   ```

2. **Загрузите сервис:**
   ```bash
   # Скопируйте plist файл в директорию LaunchAgents
   cp com.telegram.vacancy.bot.plist ~/Library/LaunchAgents/
   
   # Загрузите сервис
   launchctl load ~/Library/LaunchAgents/com.telegram.vacancy.bot.plist
   ```

3. **Управление сервисом:**
   ```bash
   # Запустить сервис
   launchctl start com.telegram.vacancy.bot
   
   # Остановить сервис
   launchctl stop com.telegram.vacancy.bot
   
   # Перезагрузить сервис (после изменения plist)
   launchctl unload ~/Library/LaunchAgents/com.telegram.vacancy.bot.plist
   launchctl load ~/Library/LaunchAgents/com.telegram.vacancy.bot.plist
   
   # Проверить статус
   launchctl list | grep telegram
   ```

4. **Просмотр логов:**
   ```bash
   # Логи бота
   tail -f /Users/konovalovmihail/hr_app/bot.log
   
   # Логи ошибок
   tail -f /Users/konovalovmihail/hr_app/bot_error.log
   ```

### Важно для launchd:
- Убедитесь, что в `.env` файле указаны все необходимые переменные
- Или добавьте их в секцию `EnvironmentVariables` в plist файле
- Проверьте права доступа к файлам

---

## Способ 4: Использование nohup (Простой способ)

**Nohup** - самый простой способ запустить процесс в фоне.

### Запуск:
```bash
cd /Users/konovalovmihail/hr_app
nohup python3 telegram_vacancy_bot.py > bot.log 2>&1 &
```

### Управление:
```bash
# Найти процесс
ps aux | grep telegram_vacancy_bot

# Остановить процесс
kill <PID>

# Или найти и остановить одной командой
pkill -f telegram_vacancy_bot.py
```

---

## Рекомендации

### Для разработки и тестирования:
- Используйте **screen** или **tmux** - легко подключиться и посмотреть логи

### Для продакшена:
- Используйте **launchd** - автоматический запуск при загрузке системы и перезапуск при сбоях

### Мониторинг:
- Регулярно проверяйте логи на наличие ошибок
- Настройте уведомления о сбоях (опционально)

---

## Проверка работы бота

После запуска любым способом проверьте:

1. **Отправьте команду боту в Telegram:**
   ```
   /start
   ```

2. **Проверьте логи:**
   ```bash
   # Для screen/tmux - подключитесь к сессии
   # Для launchd
   tail -f bot.log
   # Для nohup
   tail -f bot.log
   ```

3. **Проверьте процесс:**
   ```bash
   ps aux | grep telegram_vacancy_bot
   ```

---

## Устранение проблем

### Бот не запускается:
1. Проверьте наличие `.env` файла
2. Проверьте переменные `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`
3. Проверьте логи ошибок

### Бот останавливается:
1. Проверьте логи на наличие ошибок
2. Убедитесь, что интернет-соединение стабильное
3. Для launchd проверьте настройки `KeepAlive`

### Бот не отвечает:
1. Проверьте, что процесс запущен: `ps aux | grep telegram_vacancy_bot`
2. Проверьте логи на наличие ошибок
3. Попробуйте перезапустить бота
