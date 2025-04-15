import os
import logging
import re
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, Dispatcher
import requests
from bs4 import BeautifulSoup
import openai
import web_search
import threading
from flask import Flask, request
from telegram.error import TimedOut

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PORT = int(os.environ.get('PORT', 5000))
APP_URL = os.environ.get('APP_URL', 'https://your-app-name.onrender.com')

openai.api_key = OPENAI_API_KEY

# Создаем Flask приложение
app = Flask(__name__)

# Глобальные переменные для телеграм-бота
bot = Bot(token=TELEGRAM_TOKEN)
dispatcher = None

def start(update: Update, context: CallbackContext) -> None:
    """Отправляет приветственное сообщение при команде /start."""
    update.message.reply_text(
        'Привет! Я бот для создания прогнозов на спортивные матчи. '
        'Отправьте мне сообщение в формате:\n\n'
        'на [дата] (не позднее [дедлайн])\n\n'
        '1. [Команда1] - [Команда2]                [Турнир] ([мин_символов])\n'
        '...'
    )

def help_command(update: Update, context: CallbackContext) -> None:
    """Отправляет помощь при команде /help."""
    update.message.reply_text(
        'Отправьте мне сообщение в формате:\n\n'
        'на [дата] (не позднее [дедлайн])\n\n'
        '1. [Команда1] - [Команда2]                [Турнир] ([мин_символов])\n'
        '2. Все [X] матчей                [Турнир] ([мин_символов])\n'
        '...'
    )

def parse_match_text(text):
    """Парсит текст сообщения с матчами и возвращает структурированные данные."""
    try:
        # Разделяем по датам
        date_blocks = []
        current_block = {'date': '', 'deadline': '', 'matches': []}
        
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
                    current_block['matches'].append({
                        'number': number,
                        'is_all_matches': True,
                        'count': count,
                        'tournament': tournament,
                        'min_symbols': min_symbols,
                        'date': current_block['date']  # Добавляем дату из текущего блока
                    })
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
            return matches
        else:
            teams = match['teams'].split(' - ')
            team1 = teams[0].strip()
            team2 = teams[1].strip()
            
            # Получаем информацию о командах
            team1_info = web_search.get_team_info(team1)
            team2_info = web_search.get_team_info(team2)
            
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
        return None

def generate_match_prediction(match_info, min_symbols):
    """Генерирует прогноз на матч с использованием OpenAI API (ChatCompletion)."""
    try:
        if isinstance(match_info, list):
            # Для "Все X матчей"
            predictions = []
            for match in match_info:
                system_prompt = "Ты - опытный спортивный аналитик, создающий прогнозы на футбольные матчи."
                user_prompt = f"""
                Напиши оригинальный прогноз на футбольный матч между командами {match['team1']} и {match['team2']} 
                в рамках турнира {match['tournament']}. 
                Прогноз должен содержать не менее {min_symbols} символов.
                Учти, что команды определены как {match['team1']} и {match['team2']} для данного матча.
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
            system_prompt = "Ты - опытный спортивный аналитик, создающий прогнозы на футбольные матчи на основе предоставленных данных."
            user_prompt = f"""
            Напиши оригинальный прогноз на футбольный матч между командами {match_info['team1']} и {match_info['team2']} 
            в рамках турнира {match_info['tournament']}. 
            
            Используй следующую информацию:
            - Последние матчи {match_info['team1']}: {match_info['last_matches_team1']}
            - Последние матчи {match_info['team2']}: {match_info['last_matches_team2']}
            - Состав {match_info['team1']}: {match_info['lineup_team1']}
            - Состав {match_info['team2']}: {match_info['lineup_team2']}
            
            Прогноз должен содержать не менее {min_symbols} символов и быть оригинальным.
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
        return f"Ошибка при генерации прогноза. {error_message}"

def process_matches(update: Update, context: CallbackContext) -> None:
    """Обрабатывает полученное сообщение и генерирует прогнозы."""
    message_text = update.message.text
    
    # Если сообщение начинается с '@Get articles', обрабатываем его содержимое
    if message_text.startswith('@Get articles'):
        # Удаляем метку '@Get articles' из текста
        content = message_text.replace('@Get articles', '').strip()
        update.message.reply_text("Начинаю обработку данных из сообщения...")
    else:
        # Если обычное сообщение, проверяем его формат
        if "на " in message_text and " (не позднее " in message_text:
            content = message_text
            update.message.reply_text("Начинаю обработку данных из сообщения...")
        else:
            # Неверный формат сообщения
            return
    
    # Парсинг текста сообщения
    date_blocks = parse_match_text(content)
    if not date_blocks:
        update.message.reply_text("Не удалось обработать данные о матчах.")
        return
    
    for date_block in date_blocks:
        update.message.reply_text(f"Обрабатываю матчи на {date_block['date']} (дедлайн: {date_block['deadline']})...")
        
        for match in date_block['matches']:
            try:
                # Поиск информации
                match_info = search_match_info(match)
                if not match_info:
                    update.message.reply_text(f"Не удалось найти информацию для матча #{match['number']}.")
                    continue
                
                # Генерация прогноза
                predictions = generate_match_prediction(match_info, match['min_symbols'])
                
                # Отправка результатов
                if isinstance(predictions, list):
                    for idx, pred in enumerate(predictions, 1):
                        message = f"Прогноз #{idx} для {pred['teams']}:\n\n{pred['prediction']}"
                        update.message.reply_text(message[:4096])  # Ограничение Telegram
                else:
                    message = f"Прогноз для {predictions['teams']}:\n\n{predictions['prediction']}"
                    update.message.reply_text(message[:4096])  # Ограничение Telegram
            
            except Exception as e:
                logger.error(f"Ошибка при обработке матча #{match['number']}: {e}")
                update.message.reply_text(f"Ошибка при обработке матча #{match['number']}.")
    
    update.message.reply_text("Обработка завершена.")

# Обработчик для webhook
@app.route('/' + TELEGRAM_TOKEN, methods=['POST'])
def webhook():
    """Обработчик для входящих сообщений через webhook."""
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return 'ok'

# Маршрут для проверки работоспособности
@app.route('/')
def index():
    return 'Бот работает!'

# Маршрут для установки webhook
@app.route('/set_webhook')
def set_webhook():
    s = bot.set_webhook(APP_URL + '/' + TELEGRAM_TOKEN)
    if s:
        return "Webhook установлен!"
    else:
        return "Ошибка установки webhook"

def setup_bot():
    """Настройка и запуск бота."""
    global dispatcher
    
    # Создаем диспетчер
    dispatcher = Dispatcher(bot, None, workers=0)
    
    # Регистрируем обработчики команд
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    
    # Обработчик обычных сообщений
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, process_matches))
    
    # Устанавливаем webhook
    logger.info("Запуск бота в режиме webhook...")
    try:
        bot.set_webhook(APP_URL + '/' + TELEGRAM_TOKEN)
        logger.info(f"Вебхук установлен на {APP_URL}")
    except TimedOut:
        logger.warning("Не удалось установить вебхук автоматически из-за таймаута. "
                       f"Пожалуйста, установите его вручную, перейдя по ссылке: {APP_URL}/set_webhook")
    except Exception as e:
        logger.error(f"Произошла ошибка при установке вебхука: {e}")

    # Настройка обработчиков Flask
    setup_flask_routes(app, dispatcher)

def run_polling():
    """Запуск бота в режиме polling (для локальной разработки)."""
    updater = Updater(TELEGRAM_TOKEN)
    dispatcher = updater.dispatcher
    
    # Регистрируем обработчики команд
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    
    # Обработчик обычных сообщений
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, process_matches))
    
    # Запускаем бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    # Режим работы в зависимости от среды
    if os.environ.get('USE_POLLING', 'False').lower() == 'true':
        # Локальный запуск с polling
        print("Запуск бота в режиме polling...")
        run_polling()
    else:
        # Запуск на сервере с webhook
        print("Запуск бота в режиме webhook...")
        setup_bot()
        # Запуск Flask приложения
        app.run(host='0.0.0.0', port=PORT) 