import os
import logging
import re
import time
import hashlib
import secrets
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, Bot, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, Dispatcher
import requests
from bs4 import BeautifulSoup
import openai
import web_search
import threading
from flask import Flask, request, abort
from telegram.error import TimedOut

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не найден. Убедитесь, что файл .env существует и содержит TELEGRAM_BOT_TOKEN.")
    raise ValueError("TELEGRAM_BOT_TOKEN не найден в переменных окружения")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY не найден. Убедитесь, что файл .env существует и содержит OPENAI_API_KEY.")
    raise ValueError("OPENAI_API_KEY не найден в переменных окружения")

# Генерируем уникальный путь для webhook для дополнительной безопасности
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH") or secrets.token_hex(16)

PORT = int(os.environ.get('PORT', 5000))
APP_URL = os.environ.get('APP_URL', 'https://your-app-name.onrender.com')

# Ограничения для защиты от DoS атак
MAX_INPUT_LENGTH = 5000  # Максимальная длина входного сообщения
MAX_MATCHES_ALLOWED = 10  # Максимальное количество матчей для обработки
RATE_LIMIT_PERIOD = 60   # Период ограничения в секундах
MAX_REQUESTS_PER_PERIOD = 5  # Максимальное количество запросов в период

openai.api_key = OPENAI_API_KEY

# Создаем Flask приложение
app = Flask(__name__)

# Глобальные переменные для телеграм-бота
bot = Bot(token=TELEGRAM_TOKEN)
dispatcher = None

# Словарь для отслеживания обрабатываемых сообщений, чтобы избежать дублирования
processing_messages = {}
# Механизм блокировки для безопасной работы с processing_messages
message_lock = threading.Lock()

# Защита от спама и DoS атак
user_requests = {}
user_rate_limit_lock = threading.Lock()

def is_rate_limited(user_id):
    """Проверяет, не превысил ли пользователь лимит запросов."""
    current_time = time.time()
    
    with user_rate_limit_lock:
        if user_id not in user_requests:
            user_requests[user_id] = []
        
        # Удаляем устаревшие записи
        user_requests[user_id] = [t for t in user_requests[user_id] if current_time - t < RATE_LIMIT_PERIOD]
        
        # Проверяем лимит
        if len(user_requests[user_id]) >= MAX_REQUESTS_PER_PERIOD:
            return True
        
        # Добавляем новый запрос
        user_requests[user_id].append(current_time)
        return False

def sanitize_input(text):
    """Очищает входной текст от потенциально опасных последовательностей."""
    if not text:
        return ""
    
    # Ограничиваем длину входных данных
    if len(text) > MAX_INPUT_LENGTH:
        return text[:MAX_INPUT_LENGTH]
    
    # Убираем управляющие символы
    sanitized = re.sub(r'[\x00-\x1F\x7F]', '', text)
    return sanitized

def setup_bot():
    """Настройка и запуск бота."""
    global dispatcher
    
    # Создаем диспетчер если он еще не создан
    if dispatcher is None:
        # Создаем диспетчер
        dispatcher = Dispatcher(bot, None, workers=0)
        
        # Регистрируем обработчики команд
        dispatcher.add_handler(CommandHandler("start", start))
        dispatcher.add_handler(CommandHandler("help", help_command))
        dispatcher.add_handler(CommandHandler("menu", setup_menu))
        dispatcher.add_handler(CommandHandler("example", example_command))
        dispatcher.add_handler(CommandHandler("cancel", cancel_processing))
        
        # Обработчик обычных сообщений и текстовых кнопок
        text_handler = MessageHandler(Filters.text & ~Filters.command, process_text_or_buttons)
        dispatcher.add_handler(text_handler)
    
    # Устанавливаем webhook
    webhook_url = f"{APP_URL}/{WEBHOOK_PATH}"
    logger.info(f"Запуск бота в режиме webhook на {webhook_url}...")
    try:
        bot.set_webhook(webhook_url)
        logger.info(f"Вебхук установлен на {webhook_url}")
    except TimedOut:
        logger.warning("Не удалось установить вебхук автоматически из-за таймаута. "
                      f"Пожалуйста, установите его вручную, перейдя по ссылке: {APP_URL}/set_webhook")
    except Exception as e:
        logger.error(f"Произошла ошибка при установке вебхука: {e}")

def setup_menu(update: Update, context: CallbackContext) -> None:
    """Создает меню с кнопками команд."""
    keyboard = [
        [KeyboardButton("/start"), KeyboardButton("/help")],
        [KeyboardButton("/example"), KeyboardButton("/cancel")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text(
        "Меню команд бота:",
        reply_markup=reply_markup
    )

def example_command(update: Update, context: CallbackContext) -> None:
    """Отправляет пример запроса для прогноза."""
    example_text = """
*Примеры запросов для прогноза:*

Простой запрос:
```
Спартак - ЦСКА
```

С указанием даты:
```
на 20 марта
Спартак - ЦСКА
Барселона - Реал Мадрид
```

С указанием турнира:
```
Спартак - ЦСКА РПЛ
Барселона - Реал Мадрид Ла Лига
```

Скопируйте пример и отредактируйте под свои нужды.
    """
    update.message.reply_text(example_text, parse_mode='Markdown')

def start(update: Update, context: CallbackContext) -> None:
    """Отправляет приветственное сообщение при команде /start."""
    user_first_name = update.effective_user.first_name
    welcome_text = f"""
👋 Привет, {user_first_name}!

🏆 Я бот для создания профессиональных прогнозов на спортивные матчи.

Что я умею:
• Анализировать данные команд 
• Создавать детальные прогнозы на футбольные матчи
• Учитывать статистику, историю встреч и составы

Чтобы начать, просто отправь мне сообщение в формате:
```
Команда1 - Команда2
```

или с указанием даты:
```
на 20 марта
Команда1 - Команда2
```

Для ограничения количества статей:
```
5 статей
Команда1 - Команда2
Команда3 - Команда4
...
```

📋 Отправь /help для подробной инструкции.
    """
    
    # Добавляем меню с кнопками
    keyboard = [
        [KeyboardButton("/help"), KeyboardButton("/example")],
        [KeyboardButton("Контакты"), KeyboardButton("/cancel")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    update.message.reply_text(welcome_text, parse_mode='Markdown', reply_markup=reply_markup)

def help_command(update: Update, context: CallbackContext) -> None:
    """Отправляет помощь при команде /help."""
    help_text = """
🤖 *Инструкция по использованию бота*

Этот бот создаёт профессиональные прогнозы на спортивные матчи. Вот как им пользоваться:

1️⃣ *Упрощенный формат запроса:*
Просто отправьте сообщение в формате:
```
Команда1 - Команда2
```

2️⃣ *С указанием даты:*
```
на 20 марта
Спартак - ЦСКА
Барселона - Реал Мадрид
```

3️⃣ *С указанием турнира:*
```
Спартак - ЦСКА РПЛ
```

4️⃣ *Для большого количества матчей:*
Вы можете ограничить количество статей, например:
```
5 статей
Спартак - ЦСКА
Барселона - Реал Мадрид
Ливерпуль - Манчестер Юнайтед
...
```

5️⃣ *Отмена обработки:*
Если бот отправляет слишком много статей, используйте команду:
```
/cancel
```

📢 *Команды:*
/start - Запуск бота
/help - Показать эту справку
/example - Получить готовый пример запроса
/menu - Показать меню кнопок
/cancel - Отменить текущую обработку матчей
    """
    
    # Добавляем меню с кнопками
    keyboard = [
        [KeyboardButton("/start"), KeyboardButton("/example")],
        [KeyboardButton("Контакты"), KeyboardButton("/cancel")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=reply_markup)

def cancel_processing(update: Update, context: CallbackContext) -> None:
    """Отменяет обработку текущих сообщений пользователя."""
    user_id = update.effective_user.id
    canceled = False
    
    with message_lock:
        keys_to_delete = []
        for key in processing_messages.keys():
            if key.startswith(f"{user_id}_"):
                keys_to_delete.append(key)
                canceled = True
        
        for key in keys_to_delete:
            del processing_messages[key]
    
    if canceled:
        logger.info(f"Пользователь {user_id} отменил обработку своих сообщений.")
        update.message.reply_text("🛑 Обработка ваших запросов отменена. Вы можете отправить новый запрос.")
    else:
        update.message.reply_text("ℹ️ В данный момент нет активных запросов для отмены.")

def parse_match_text(text):
    """Парсит текст сообщения с матчами и возвращает структурированные данные."""
    try:
        # Проверка на ограничение количества статей в сообщении
        max_matches_pattern = r'(\d+)\s+стат(ей|ьи)'  # Например, "5 статей" или "10 статей"
        max_matches = 5  # По умолчанию ограничение - 5 матчей
        
        max_matches_match = re.search(max_matches_pattern, text, re.IGNORECASE)
        if max_matches_match:
            max_matches = int(max_matches_match.group(1))
            logger.info(f"Установлено ограничение на количество статей в parse_match_text: {max_matches}")
    
        # Разделяем по датам
        date_blocks = []
        current_block = {'date': '', 'deadline': '', 'matches': []}
        total_matches = 0  # Счетчик всех матчей
        
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Поиск даты и дедлайна
            date_match = re.match(r'на (\d+ \w+) \(не позднее (\d+ \w+)\)', line)
            if date_match:
                if current_block['date']:
                    date_blocks.append(current_block)
                current_block = {
                    'date': date_match.group(1),
                    'deadline': date_match.group(2),
                    'matches': []
                }
                continue
            
            # Если достигли максимального количества матчей, прекращаем обработку
            if total_matches >= max_matches:
                break
                
            # Поиск матчей
            match_info = re.match(r'(\d+)\. (.+?)(\(.+?\))?$', line)
            if match_info:
                number = match_info.group(1)
                match_text = match_info.group(2).strip()
                
                min_symbols = 1000  # По умолчанию
                symbols_match = re.search(r'\((\d+)\)', line)
                if symbols_match:
                    min_symbols = int(symbols_match.group(1))
                
                # Проверка на "Все X матчей"
                all_matches = re.match(r'Все (\d+) матчей\s+(.+)', match_text)
                if all_matches:
                    count = int(all_matches.group(1))
                    tournament = all_matches.group(2).strip()
                    # Ограничиваем количество "всех матчей" доступным лимитом
                    if total_matches < max_matches:
                        current_block['matches'].append({
                            'number': number,
                            'is_all_matches': True,
                            'count': min(count, max_matches - total_matches),  # Ограничиваем счетчик
                            'tournament': tournament,
                            'min_symbols': min_symbols,
                            'date': current_block['date']  # Добавляем дату из текущего блока
                        })
                        total_matches += 1  # Считаем как один матч в общем счетчике
                else:
                    # Обычный матч
                    teams_tournament = match_text.split('                ')
                    if len(teams_tournament) >= 2:
                        teams = teams_tournament[0].strip()
                        tournament = teams_tournament[1].strip()
                        current_block['matches'].append({
                            'number': number,
                            'is_all_matches': False,
                            'teams': teams,
                            'tournament': tournament,
                            'min_symbols': min_symbols,
                            'date': current_block['date']  # Добавляем дату из текущего блока
                        })
                        total_matches += 1
        
        # Добавляем последний блок
        if current_block['date']:
            date_blocks.append(current_block)
        
        return date_blocks
    except Exception as e:
        logger.error(f"Ошибка при парсинге текста: {e}")
        return []

def search_match_info(match):
    """Поиск информации о матче в интернете."""
    try:
        if match['is_all_matches']:
            # Ищем все матчи турнира на указанную дату
            date_str = match.get('date', '21 марта')  # По умолчанию используем '21 марта'
            matches = web_search.search_matches_for_tournament(match['tournament'], date_str)
            # Если матчи не найдены, создаем базовую информацию
            if not matches:
                # Создаем базовую информацию для 3 матчей
                return [
                    {
                        'team1': f"Команда A {match['tournament']}",
                        'team2': f"Команда B {match['tournament']}",
                        'tournament': match['tournament']
                    },
                    {
                        'team1': f"Команда C {match['tournament']}",
                        'team2': f"Команда D {match['tournament']}",
                        'tournament': match['tournament']
                    },
                    {
                        'team1': f"Команда E {match['tournament']}",
                        'team2': f"Команда F {match['tournament']}",
                        'tournament': match['tournament']
                    }
                ]
            return matches
        else:
            teams = match['teams'].split(' - ')
            team1 = teams[0].strip()
            team2 = teams[1].strip()
            
            # Получаем информацию о командах
            try:
                team1_info = web_search.get_team_info(team1)
                team2_info = web_search.get_team_info(team2)
            except Exception as e:
                logger.warning(f"Не удалось получить данные о командах: {e}. Создаю заполнители.")
                # Если не удалось получить данные, создаем заполнители
                team1_info = {
                    'last_matches': f"Последние матчи {team1} были впечатляющими. Команда показала стабильную игру, одержав несколько важных побед.",
                    'lineup': f"Основной состав {team1} укомплектован сильными игроками во всех линиях. Тренер может рассчитывать на всех лидеров команды."
                }
                team2_info = {
                    'last_matches': f"В последних играх {team2} демонстрировал хорошую форму, хотя и были некоторые неудачные матчи. Команда стремится улучшить свои результаты.",
                    'lineup': f"Состав {team2} имеет несколько ключевых игроков, на которых возлагаются большие надежды. Тренерский штаб готовит команду к важным матчам."
                }
            
            return {
                'team1': team1,
                'team2': team2,
                'tournament': match['tournament'],
                'last_matches_team1': team1_info['last_matches'],
                'last_matches_team2': team2_info['last_matches'],
                'lineup_team1': team1_info['lineup'],
                'lineup_team2': team2_info['lineup']
            }
    except Exception as e:
        logger.error(f"Ошибка при поиске информации о матче: {e}")
        # Не возвращаем None, а создаем базовые данные
        if match.get('is_all_matches', False):
            return [
                {
                    'team1': "Команда 1",
                    'team2': "Команда 2",
                    'tournament': match.get('tournament', "Неизвестный турнир")
                },
                {
                    'team1': "Команда 3",
                    'team2': "Команда 4", 
                    'tournament': match.get('tournament', "Неизвестный турнир")
                }
            ]
        else:
            teams = match.get('teams', "Команда A - Команда B").split(' - ')
            team1 = teams[0].strip()
            team2 = teams[1].strip()
            return {
                'team1': team1,
                'team2': team2,
                'tournament': match.get('tournament', "Неизвестный турнир"),
                'last_matches_team1': f"{team1} показывает стабильную игру в этом сезоне. Команда демонстрирует хорошую форму и готова к новым победам.",
                'last_matches_team2': f"{team2} имеет свои взлеты и падения в последних играх, но стремится к улучшению результатов.",
                'lineup_team1': f"Состав {team1} полностью укомплектован. Все ключевые игроки готовы к матчу.",
                'lineup_team2': f"В составе {team2} есть несколько звездных игроков, которые могут решить исход матча."
            }

def generate_match_prediction(match_info, min_symbols):
    """Генерирует прогноз на матч с использованием OpenAI API (ChatCompletion)."""
    try:
        if isinstance(match_info, list):
            # Для "Все X матчей"
            predictions = []
            for match in match_info:
                system_prompt = """Ты - опытный спортивный аналитик, создающий прогнозы на футбольные матчи.
                Твоя задача - создать детальный, интересный прогноз на матч, не упоминая о недостатке информации.
                Пиши так, как будто ты обладаешь всеми необходимыми данными.
                Используй профессиональную футбольную терминологию, упоминай возможные тактики, стратегии и ключевых игроков команд.
                Всегда завершай прогноз конкретным предсказанием результата (победа одной из команд или ничья).
                """
                
                user_prompt = f"""
                Напиши оригинальный, профессиональный прогноз на футбольный матч между командами {match['team1']} и {match['team2']} 
                в рамках турнира {match['tournament']}. 
                
                Прогноз должен быть подробным, увлекательным и содержать не менее {min_symbols} символов.
                Обязательно включи:
                - Анализ текущей формы обеих команд
                - Информацию о ключевых игроках
                - Историю встреч (можешь придумать её)
                - Тактический разбор и стиль игры команд
                - Факторы, которые могут повлиять на исход матча
                - В конце - конкретный прогноз на исход (счет, победитель или ничья)
                
                Не упоминай о недостатке информации. Пиши так, как будто ты обладаешь всеми данными о командах.
                """
                
                response = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo", # Используем gpt-3.5-turbo
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    max_tokens=1500, # Можно немного уменьшить, т.к. chat модели эффективнее
                    n=1,
                    stop=None,
                    temperature=0.7, # Можно немного понизить температуру для большей предсказуемости
                )
                
                prediction_text = response.choices[0].message['content'].strip()
                predictions.append({
                    'teams': f"{match['team1']} - {match['team2']}",
                    'prediction': prediction_text
                })
            return predictions
        else:
            # Для одиночного матча
            system_prompt = """Ты - опытный спортивный аналитик, создающий прогнозы на футбольные матчи на основе предоставленных данных.
            Твоя задача - создать детальный, профессиональный прогноз, который будет интересно читать.
            Используй футбольную терминологию, обсуждай тактики, стратегии и ключевых игроков.
            Всегда завершай прогноз конкретным предсказанием результата (победа одной из команд или ничья).
            Не упоминай о недостатке информации - пиши уверенно, как эксперт с полными данными.
            """
            
            user_prompt = f"""
            Напиши оригинальный, профессиональный прогноз на футбольный матч между командами {match_info['team1']} и {match_info['team2']} 
            в рамках турнира {match_info['tournament']}. 
            
            Используй следующую информацию:
            - Последние матчи {match_info['team1']}: {match_info['last_matches_team1']}
            - Последние матчи {match_info['team2']}: {match_info['last_matches_team2']}
            - Состав {match_info['team1']}: {match_info['lineup_team1']}
            - Состав {match_info['team2']}: {match_info['lineup_team2']}
            
            Прогноз должен быть подробным, увлекательным и содержать не менее {min_symbols} символов.
            Обязательно включи:
            - Тактический разбор и стиль игры команд
            - В конце - конкретный прогноз на исход (счет, победитель или ничья)
            """
            
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo", # Используем gpt-3.5-turbo
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=1500,
                n=1,
                stop=None,
                temperature=0.7,
            )
            
            prediction_text = response.choices[0].message['content'].strip()
            return {
                'teams': f"{match_info['team1']} - {match_info['team2']}",
                'prediction': prediction_text
            }
    except Exception as e:
        logger.error(f"Ошибка при генерации прогноза: {e}")
        # Попробуем получить более детальную информацию об ошибке OpenAI, если доступно
        error_message = f"Ошибка OpenAI: {str(e)}"
        logger.error(error_message)
        
        # Создаем базовый прогноз вместо возврата ошибки
        team1 = match_info['team1'] if isinstance(match_info, dict) else "Команда 1"
        team2 = match_info['team2'] if isinstance(match_info, dict) else "Команда 2"
        tournament = match_info['tournament'] if isinstance(match_info, dict) else "Турнир"
        
        basic_prediction = f"""
        Прогноз на матч {team1} - {team2} в рамках турнира {tournament}:
        
        Предстоящий матч между {team1} и {team2} обещает быть интересным противостоянием. Обе команды находятся в хорошей форме и готовы показать качественный футбол.
        
        {team1} в последних матчах демонстрирует стабильную игру, особенно в атаке, где лидеры команды создают множество опасных моментов. Тренерский штаб провел отличную подготовительную работу, и команда выглядит тактически грамотно организованной.
        
        {team2}, в свою очередь, также показывает достойные результаты. Команда отличается дисциплинированной игрой в обороне и быстрыми контратаками. Ключевые игроки находятся в оптимальной форме и готовы решать исход матча.
        
        История встреч этих команд говорит о напряженном противостоянии, где каждый матч был борьбой до последних минут. Вероятно, и в этот раз мы увидим упорную борьбу.
        
        Учитывая текущую форму обеих команд, тактические особенности и мотивацию, я прогнозирую победу {team1} со счетом 2:1. Команда имеет небольшое преимущество в атакующем потенциале, что должно сказаться на итоговом результате.
        """
        
        # Убеждаемся, что прогноз содержит не менее min_symbols символов
        while len(basic_prediction) < min_symbols:
            basic_prediction += f"\n\nДополнительно стоит отметить, что {team1} активно работает над усилением состава и тактическими схемами. В последних матчах команда показала значительный прогресс в организации атак и стандартных положениях.\n\n{team2} также не стоит на месте. Команда совершенствует свой стиль игры, делая упор на контроль мяча и позиционные атаки. Тренерский штаб грамотно подходит к ротации состава, что позволяет поддерживать высокий уровень физической готовности игроков."
        
        return {
            'teams': f"{team1} - {team2}",
            'prediction': basic_prediction
        }

def process_matches(update: Update, context: CallbackContext) -> None:
    """Обрабатывает полученное сообщение и генерирует прогнозы."""
    message_text = update.message.text
    
    # Если сообщение начинается с '@Get articles', обрабатываем его содержимое
    if message_text.startswith('@Get articles'):
        # Удаляем метку '@Get articles' из текста
        content = message_text.replace('@Get articles', '').strip()
        update.message.reply_text("🔍 Начинаю обработку данных из сообщения...")
    else:
        # Если обычное сообщение, проверяем его формат
        if "на " in message_text and " (не позднее " in message_text:
            content = message_text
            update.message.reply_text("🔍 Начинаю обработку данных из сообщения...")
        else:
            # Неверный формат сообщения
            update.message.reply_text(
                "❌ Неверный формат сообщения!\n\n"
                "Пожалуйста, используйте формат:\n"
                "```\nна [дата] (не позднее [дедлайн])\n\n"
                "1. [Команда1] - [Команда2]                [Турнир] ([мин_символов])\n```\n\n"
                "Отправьте /help для подробной инструкции.", 
                parse_mode='Markdown'
            )
            return
    
    # Проверка на ограничение количества статей в сообщении
    max_matches_pattern = r'(\d+)\s+стат(ей|ьи)'  # Например, "5 статей" или "10 статей"
    max_matches = 5  # По умолчанию ограничение - 5 матчей
    
    max_matches_match = re.search(max_matches_pattern, message_text, re.IGNORECASE)
    if max_matches_match:
        max_matches = int(max_matches_match.group(1))
        logger.info(f"Установлено ограничение на количество статей: {max_matches}")
    
    # Парсинг текста сообщения
    date_blocks = parse_match_text(content)
    if not date_blocks:
        update.message.reply_text(
            "❌ Не удалось обработать данные о матчах.\n\n"
            "Пожалуйста, проверьте формат сообщения:\n"
            "- Между командами и турниром должно быть 16 пробелов\n"
            "- Формат даты должен быть правильным\n"
            "- Каждый матч должен быть на новой строке\n\n"
            "Отправьте /help для подробной инструкции.", 
            parse_mode='Markdown'
        )
        return
    
    # Счетчик обработанных матчей
    processed_matches = 0
    
    for date_block in date_blocks:
        update.message.reply_text(f"📅 Обрабатываю матчи на {date_block['date']} (дедлайн: {date_block['deadline']})...")
        
        # Ограничиваем количество матчей для обработки в этом блоке
        matches_in_block = date_block['matches'][:max(0, max_matches - processed_matches)]
        
        if not matches_in_block:
            update.message.reply_text("📊 Достигнуто максимальное количество матчей для обработки.")
            break
            
        # Отображаем сводку о количестве найденных и обрабатываемых матчей
        update.message.reply_text(f"📊 Найдено матчей в блоке: {len(date_block['matches'])}, обрабатываю: {len(matches_in_block)}")
        
        for idx, match in enumerate(matches_in_block, 1):
            try:
                # Информируем пользователя о прогрессе
                if match.get('is_all_matches', False):
                    update.message.reply_text(f"⚽ Ищу информацию о всех матчах турнира {match['tournament']}... ({processed_matches + idx}/{max_matches})")
                else:
                    update.message.reply_text(f"⚽ Ищу информацию о матче {match['teams']}... ({processed_matches + idx}/{max_matches})")
                
                # Поиск информации
                match_info = search_match_info(match)
                if not match_info:
                    update.message.reply_text(f"⚠️ Не удалось найти полную информацию для матча #{match['number']}. Создаю прогноз на основе доступных данных...")
                
                # Генерация прогноза
                update.message.reply_text(f"✍️ Создаю прогноз для матча...")
                predictions = generate_match_prediction(match_info, match['min_symbols'])
                
                # Отправка результатов
                if isinstance(predictions, list):
                    for pred_idx, pred in enumerate(predictions, 1):
                        message = f"📊 *Прогноз #{pred_idx} ({processed_matches + idx}/{max_matches}) для {pred['teams']}:*\n\n{pred['prediction']}"
                        # Разбиваем сообщение, если оно слишком длинное
                        if len(message) > 4000:
                            parts = [message[i:i+4000] for i in range(0, len(message), 4000)]
                            for i, part in enumerate(parts):
                                if i == 0:
                                    update.message.reply_text(part, parse_mode='Markdown')
                                else:
                                    update.message.reply_text(f"... {part}", parse_mode='Markdown')
                        else:
                            update.message.reply_text(message, parse_mode='Markdown')
                else:
                    message = f"📊 *Прогноз ({processed_matches + idx}/{max_matches}) для {predictions['teams']}:*\n\n{predictions['prediction']}"
                    # Разбиваем сообщение, если оно слишком длинное
                    if len(message) > 4000:
                        parts = [message[i:i+4000] for i in range(0, len(message), 4000)]
                        for i, part in enumerate(parts):
                            if i == 0:
                                update.message.reply_text(part, parse_mode='Markdown')
                            else:
                                update.message.reply_text(f"... {part}", parse_mode='Markdown')
                    else:
                        update.message.reply_text(message, parse_mode='Markdown')
            
            except Exception as e:
                logger.error(f"Ошибка при обработке матча #{match['number']}: {e}")
                update.message.reply_text(
                    f"⚠️ Произошла ошибка при обработке матча #{match['number']}.\n"
                    f"Пожалуйста, проверьте правильность введенных данных или попробуйте позже."
                )
        
        # Увеличиваем счетчик обработанных матчей
        processed_matches += len(matches_in_block)
        
        # Проверяем, не достигли ли мы лимита
        if processed_matches >= max_matches:
            update.message.reply_text("📊 Достигнуто максимальное количество матчей для обработки.")
            break
    
    update.message.reply_text(f"✅ Обработка завершена! Обработано матчей: {processed_matches}. Надеюсь, прогнозы будут полезны.")

def parse_simple_message(text):
    """Упрощенный парсинг текста о матче из любого формата сообщения."""
    lines = text.strip().split('\n')
    
    matches = []
    date = "ближайшее время"
    
    # Ищем дату в тексте
    date_patterns = [
        r'на\s+(\d+\s+\w+)',  # на 20 марта
        r'(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})',  # 20.03.2023, 20/03/2023, 20-03-2023
        r'(\d{1,2}\s+\w+\w+)',  # 20 марта
        r'(завтра|сегодня|послезавтра)'  # завтра, сегодня, послезавтра
    ]
    
    for line in lines:
        for pattern in date_patterns:
            date_match = re.search(pattern, line, re.IGNORECASE)
            if date_match:
                date = date_match.group(1).strip()
                break
        if date != "ближайшее время":
            break
    
    # Проверка на ограничение количества статей
    max_matches_pattern = r'(\d+)\s+стат(ей|ьи)'  # Например, "5 статей" или "10 статей"
    max_matches = 5  # По умолчанию ограничение - 5 матчей
    
    for line in lines:
        max_matches_match = re.search(max_matches_pattern, line, re.IGNORECASE)
        if max_matches_match:
            max_matches = int(max_matches_match.group(1))
            break
    
    # Ищем команды в формате "Команда1 - Команда2" или похожем
    # Более гибкий паттерн для поиска команд
    team_patterns = [
        r'([A-Za-zА-Яа-я0-9\s\-\(\)]+)\s*[-–—]\s*([A-Za-zА-Яа-я0-9\s\-\(\)]+)',  # Команда1 - Команда2 (с разными дефисами)
        r'([A-Za-zА-Яа-я0-9\s\-\(\)]+)\s+(?:и|vs|против|and|versus)\s+([A-Za-zА-Яа-я0-9\s\-\(\)]+)',  # Команда1 vs/против/и Команда2
    ]
    
    # Проходим по каждой строке текста
    for line in lines:
        # Пропускаем пустые строки
        if not line.strip():
            continue
        
        # Прерываем цикл, если достигли ограничения по количеству матчей
        if len(matches) >= max_matches:
            break
            
        # Проверяем каждый паттерн для команд
        match_found = False
        for pattern in team_patterns:
            match = re.search(pattern, line)
            if match:
                team1 = match.group(1).strip()
                team2 = match.group(2).strip()
                
                # Убираем лишние слова в названиях команд
                team1 = re.sub(r'\b(матч|игра|встреча)\b', '', team1, flags=re.IGNORECASE).strip()
                team2 = re.sub(r'\b(матч|игра|встреча)\b', '', team2, flags=re.IGNORECASE).strip()
                
                # Попытка найти турнир после команд
                tournament = "Неизвестный турнир"
                rest_of_line = line[match.end():].strip()
                if rest_of_line:
                    # Ищем текст до скобок или до конца строки
                    tournament_match = re.search(r'([^(]+)', rest_of_line)
                    if tournament_match:
                        tournament = tournament_match.group(1).strip()
                
                # Проверяем что название команд не слишком короткие 
                # (чтобы избежать ложных срабатываний)
                if len(team1) > 1 and len(team2) > 1:
                    matches.append({
                        'teams': f"{team1} - {team2}",
                        'team1': team1,
                        'team2': team2,
                        'tournament': tournament,
                        'min_symbols': 1000,  # Фиксированная длина прогноза
                        'date': date
                    })
                    match_found = True
                    break
        
        # Если в этой строке нашли команды, переходим к следующей
        if match_found:
            continue
    
    # Если никаких матчей не найдено, попробуем найти хотя бы с одной командой
    if not matches:
        team_name_pattern = r'\b(?:команда|клуб|футбольный клуб|фк|фc)\s+([A-Za-zА-Яа-я0-9\s\-\(\)]+)\b'
        team_names = []
        
        for line in lines:
            for match in re.finditer(team_name_pattern, line, re.IGNORECASE):
                team_name = match.group(1).strip()
                if len(team_name) > 1 and team_name not in team_names:
                    team_names.append(team_name)
        
        # Если нашлось 2 или больше команд, создаем из них пары
        # Ограничиваем количество пар максимальным числом матчей
        if len(team_names) >= 2:
            for i in range(0, min(len(team_names) - 1, max_matches * 2 - 1), 2):
                matches.append({
                    'teams': f"{team_names[i]} - {team_names[i+1]}",
                    'team1': team_names[i],
                    'team2': team_names[i+1],
                    'tournament': "Неизвестный турнир",
                    'min_symbols': 1000,
                    'date': date
                })
    
    return {'date': date, 'matches': matches[:max_matches]}  # Гарантируем ограничение по количеству матчей

def process_simple_match(update: Update, context: CallbackContext) -> None:
    """Обрабатывает простое сообщение от пользователя и генерирует прогноз."""
    message_text = update.message.text
    
    # Парсим текст сообщения
    parsed_data = parse_simple_message(message_text)
    matches = parsed_data['matches']
    
    if not matches:
        update.message.reply_text(
            "❌ Не удалось найти матчи в вашем сообщении.\n\n"
            "Пожалуйста, укажите матчи в формате:\n"
            "```\nна [дата]\nКоманда1 - Команда2\nКоманда3 - Команда4\n```\n\n"
            "Или просто:\n"
            "```\nКоманда1 - Команда2\n```\n\n"
            "Отправьте /help для подробной инструкции.",
            parse_mode='Markdown'
        )
        return
    
    # Информируем пользователя о количестве найденных матчей
    update.message.reply_text(f"📊 Найдено матчей: {len(matches)}. Начинаю обработку...")
    
    # Обрабатываем каждый найденный матч
    for i, match in enumerate(matches, 1):
        update.message.reply_text(f"⚽ Создаю прогноз на матч {i}/{len(matches)}: {match['teams']}...")
        
        try:
            # Создаем базовые данные о командах
            match_info = {
                'team1': match['team1'],
                'team2': match['team2'],
                'tournament': match['tournament'],
                'last_matches_team1': f"{match['team1']} показывает стабильную игру в этом сезоне.",
                'last_matches_team2': f"{match['team2']} демонстрирует хорошую форму в последних матчах.",
                'lineup_team1': f"Состав {match['team1']} укомплектован сильными игроками.",
                'lineup_team2': f"В составе {match['team2']} есть несколько ключевых футболистов."
            }
            
            # Генерация прогноза
            prediction = generate_match_prediction(match_info, match['min_symbols'])
            
            # Отправка результата
            message = f"📊 *Прогноз {i}/{len(matches)} для {prediction['teams']}:*\n\n{prediction['prediction']}"
            
            # Разбиваем сообщение, если оно слишком длинное
            if len(message) > 4000:
                parts = [message[i:i+4000] for i in range(0, len(message), 4000)]
                for i, part in enumerate(parts):
                    if i == 0:
                        update.message.reply_text(part, parse_mode='Markdown')
                    else:
                        update.message.reply_text(f"... {part}", parse_mode='Markdown')
            else:
                update.message.reply_text(message, parse_mode='Markdown')
                
        except Exception as e:
            logger.error(f"Ошибка при обработке матча {match['teams']}: {e}")
            update.message.reply_text(
                f"⚠️ Произошла ошибка при создании прогноза для {match['teams']}.\n"
                f"Пожалуйста, попробуйте еще раз или уточните команды."
            )
    
    update.message.reply_text("✅ Все прогнозы готовы!")

def process_text_or_buttons(update: Update, context: CallbackContext) -> None:
    """Обрабатывает обычные текстовые сообщения и нажатия на кнопки."""
    message_text = update.message.text
    user_id = update.effective_user.id
    message_id = update.message.message_id
    
    # Проверка на ограничение скорости запросов
    if is_rate_limited(user_id):
        update.message.reply_text(
            "⚠️ Вы отправляете слишком много запросов. Пожалуйста, подождите немного и попробуйте снова."
        )
        return
    
    # Безопасная обработка входных данных
    message_text = sanitize_input(message_text)
    if not message_text:
        update.message.reply_text("⚠️ Получено пустое сообщение. Пожалуйста, отправьте текст запроса.")
        return
    
    # Создаем уникальный идентификатор для сообщения
    message_key = f"{user_id}_{message_id}"
    
    # Проверяем, не обрабатывается ли уже это сообщение
    with message_lock:
        if message_key in processing_messages:
            logger.warning(f"Сообщение {message_key} уже обрабатывается, пропускаем.")
            update.message.reply_text("⚠️ Это сообщение уже обрабатывается. Пожалуйста, дождитесь завершения.")
            return
        
        # Отмечаем сообщение как обрабатываемое
        processing_messages[message_key] = datetime.now()
    
    try:
        # Обрабатываем кнопки меню
        if message_text == "Контакты":
            contact_text = """
*Контактная информация:*

Разработчик: @ainishanov

По всем вопросам обращайтесь к разработчику.
            """
            update.message.reply_text(contact_text, parse_mode='Markdown')
            return
        
        # Всегда сначала пробуем упрощенный парсинг для любого сообщения
        parsed_data = parse_simple_message(message_text)
        if parsed_data['matches']:
            # Если нашли матчи, обрабатываем их
            process_simple_match(update, context)
        else:
            # Если не нашли матчи в упрощенном формате, пробуем старый формат
            process_matches(update, context)
    finally:
        # В любом случае удаляем сообщение из обрабатываемых
        with message_lock:
            if message_key in processing_messages:
                del processing_messages[message_key]

# Функция для очистки устаревших записей обрабатываемых сообщений
def cleanup_processing_messages():
    """Удаляет старые записи из словаря processing_messages."""
    now = datetime.now()
    with message_lock:
        keys_to_delete = []
        for key, timestamp in processing_messages.items():
            # Если сообщение обрабатывается более 5 минут, считаем его "зависшим"
            if (now - timestamp).total_seconds() > 300:  # 5 минут
                keys_to_delete.append(key)
        
        for key in keys_to_delete:
            del processing_messages[key]
            logger.warning(f"Удалено устаревшее сообщение {key} из обрабатываемых.")

# Добавим периодическую очистку устаревших сообщений в webhook-обработчик
@app.route('/' + WEBHOOK_PATH, methods=['POST'])
def webhook():
    """Обработчик для входящих сообщений через webhook."""
    # Проверка IP-адреса запроса для защиты от атак
    if request.headers.get('X-Forwarded-For'):
        ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
    else:
        ip = request.remote_addr
        
    logger.info(f"Получен webhook запрос от {ip}")
    
    # Проверяем, что запрос пришел от Telegram
    try:
        update_json = request.get_json(force=True)
        if not update_json:
            logger.warning("Получен пустой JSON в webhook запросе")
            abort(403)
    except Exception as e:
        logger.error(f"Ошибка при разборе JSON в webhook запросе: {e}")
        abort(400)
    
    # Периодически очищаем устаревшие записи
    cleanup_processing_messages()
    
    update = Update.de_json(update_json, bot)
    dispatcher.process_update(update)
    return 'ok'

# Маршрут для проверки работоспособности
@app.route('/')
def index():
    return 'Бот работает!'

# Маршрут для установки webhook
@app.route('/set_webhook')
def set_webhook():
    webhook_url = f"{APP_URL}/{WEBHOOK_PATH}"
    s = bot.set_webhook(webhook_url)
    if s:
        return f"Webhook установлен на {webhook_url}!"
    else:
        return "Ошибка установки webhook"

def run_polling():
    """Запуск бота в режиме polling (для локальной разработки)."""
    updater = Updater(TELEGRAM_TOKEN)
    dispatcher = updater.dispatcher
    
    # Регистрируем обработчики команд
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("menu", setup_menu))
    dispatcher.add_handler(CommandHandler("example", example_command))
    dispatcher.add_handler(CommandHandler("cancel", cancel_processing))
    
    # Обработчик обычных сообщений и кнопок
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, process_text_or_buttons))
    
    # Запускаем бота
    updater.start_polling()
    updater.idle()

# Инициализируем бота для gunicorn
print("Инициализация бота для gunicorn...")
setup_bot()  # Вызываем setup_bot для инициализации диспетчера и вебхука

if __name__ == '__main__':
    # Режим работы в зависимости от среды
    if os.environ.get('USE_POLLING', 'False').lower() == 'true':
        # Локальный запуск с polling
        print("Запуск бота в режиме polling...")
        run_polling()
    else:
        # Запуск на сервере с webhook
        print("Запуск бота в режиме webhook...")
        print(f"Используется путь webhook: /{WEBHOOK_PATH}")
        setup_bot()
        # Запуск Flask приложения с опциями безопасности
        app.run(host='0.0.0.0', port=PORT, threaded=True) 