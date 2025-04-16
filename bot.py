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
from sports_api import TheSportsDB

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

# Инициализация API для спортивных данных
sports_api = TheSportsDB()

def start(update: Update, context: CallbackContext) -> None:
    """Отправляет приветственное сообщение при команде /start."""
    update.message.reply_text(
        'Привет! Я бот для создания прогнозов на спортивные матчи. '
        'Отправьте мне сообщение в формате:\n\n'
        'на [дата] (не позднее [дедлайн])\n\n'
        '1. [Команда1] - [Команда2]                [Турнир] ([мин_символов])\n'
        '...\n\n'
        'Или используйте команду /team [название команды] для получения информации о команде.'
    )

def help_command(update: Update, context: CallbackContext) -> None:
    """Отправляет помощь при команде /help."""
    update.message.reply_text(
        'Доступные команды:\n\n'
        '/team [название команды] - Получить информацию о команде\n'
        '/start - Показать приветственное сообщение\n\n'
        'Для получения прогнозов отправьте сообщение в формате:\n'
        'на [дата] (не позднее [дедлайн])\n\n'
        '1. [Команда1] - [Команда2]                [Турнир] ([мин_символов])\n'
        '2. Все [X] матчей                [Турнир] ([мин_символов])\n'
        '...'
    )

def team_command(update: Update, context: CallbackContext) -> None:
    """Обрабатывает команду /team для получения информации о команде."""
    # Проверка наличия аргументов
    if not context.args:
        update.message.reply_text("Пожалуйста, укажите название команды. Например: /team Спартак")
        return
    
    # Получение названия команды из аргументов
    team_name = ' '.join(context.args)
    update.message.reply_text(f"Ищу информацию о команде: {team_name}...")
    
    try:
        # Словарь переводов для известных команд
        team_translations = {
            # Российские команды
            "Спартак": "Spartak Moscow",
            "ЦСКА": "CSKA Moscow",
            "Зенит": "Zenit Saint Petersburg",
            "Локомотив": "Lokomotiv Moscow",
            "Динамо": "Dynamo Moscow",
            "Краснодар": "FC Krasnodar",
            "Ростов": "FC Rostov",
            "Сочи": "PFC Sochi",
            
            # Популярные европейские команды
            "Реал": "Real Madrid",
            "Реал Мадрид": "Real Madrid",
            "Барселона": "FC Barcelona",
            "Атлетико": "Atletico Madrid",
            "Бавария": "Bayern Munich",
            "Боруссия": "Borussia Dortmund",
            "ПСЖ": "Paris Saint-Germain",
            "МЮ": "Manchester United",
            "Манчестер Юнайтед": "Manchester United",
            "Манчестер Сити": "Manchester City",
            "Ливерпуль": "Liverpool FC",
            "Челси": "Chelsea FC",
            "Арсенал": "Arsenal FC",
            "Тоттенхэм": "Tottenham Hotspur",
            "Ювентус": "Juventus FC",
            "Милан": "AC Milan",
            "Интер": "Inter Milan",
            "Наполи": "SSC Napoli",
            "Рома": "AS Roma",
            "Аякс": "Ajax Amsterdam",
            "Порту": "FC Porto",
            "Бенфика": "SL Benfica",
            "Люцерн": "FC Luzern",
            "Ксамакс": "Neuchatel Xamax"
        }
        
        # Ищем английский перевод названия
        english_name = team_translations.get(team_name, team_name)
        
        # Получаем информацию о команде
        team_data = sports_api.search_team(english_name)
        
        if not team_data or 'teams' not in team_data or not team_data['teams']:
            # Если не найдено, пробуем искать по первому слову
            first_word = english_name.split()[0]
            team_data = sports_api.search_team(first_word)
            
            if not team_data or 'teams' not in team_data or not team_data['teams']:
                update.message.reply_text(f"К сожалению, не удалось найти информацию о команде {team_name}.")
                return
        
        # Получаем детальную информацию
        team = team_data['teams'][0]
        team_id = team['idTeam']
        
        # Формируем сообщение с базовой информацией
        message = f"*{team['strTeam']}*\n\n"
        message += f"🌍 Страна: {team.get('strCountry', 'Н/Д')}\n"
        message += f"🏆 Лига: {team.get('strLeague', 'Н/Д')}\n"
        message += f"🏟️ Стадион: {team.get('strStadium', 'Н/Д')}\n"
        message += f"📅 Год основания: {team.get('intFormedYear', 'Н/Д')}\n"
        message += f"🌐 Сайт: {team.get('strWebsite', 'Н/Д')}\n\n"
        
        # Отправляем первую часть информации
        update.message.reply_text(message, parse_mode='Markdown')
        
        # Получаем информацию о последних матчах
        matches = sports_api.get_last_events_by_team(team_id)
        matches_message = "*Последние матчи:*\n"
        
        if matches and 'results' in matches and matches['results']:
            for match in matches['results'][:5]:
                date = match.get('dateEvent', 'Н/Д')
                home = match.get('strHomeTeam', 'Н/Д')
                away = match.get('strAwayTeam', 'Н/Д')
                home_score = match.get('intHomeScore', '?')
                away_score = match.get('intAwayScore', '?')
                matches_message += f"- {date}: {home} {home_score}:{away_score} {away}\n"
        else:
            matches_message += "Информация о последних матчах недоступна\n"
        
        update.message.reply_text(matches_message, parse_mode='Markdown')
        
        # Получаем информацию об игроках команды
        players = sports_api.list_all_players_in_team(team_id)
        players_message = "*Состав команды:*\n"
        
        if players and 'player' in players and players['player']:
            for player in players['player'][:10]:
                name = player.get('strPlayer', 'Н/Д')
                position = player.get('strPosition', 'Н/Д')
                nationality = player.get('strNationality', 'Н/Д')
                players_message += f"- {name} ({position}, {nationality})\n"
        else:
            players_message += "Информация о составе недоступна (требуется платная версия API)\n"
        
        update.message.reply_text(players_message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка при получении информации о команде {team_name}: {e}")
        update.message.reply_text(f"Произошла ошибка при получении информации о команде {team_name}.")

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

# Маршрут для тестирования API для команд
@app.route('/test_api')
def test_api():
    try:
        import web_search
        import json
        
        # Функция для тестирования API и форматирования результатов
        def get_team_info_formatted(team_name, english_name):
            result = "<h3>Тестирование API для команды: " + team_name + " (англ: " + english_name + ")</h3>"
            
            # URL для поиска команды
            url = f"https://www.thesportsdb.com/api/v1/json/3/searchteams.php?t={english_name}"
            result += f"<p>URL запроса: <a href='{url}' target='_blank'>{url}</a></p>"
            
            try:
                search_response = requests.get(url)
                search_data = search_response.json()
                
                if search_data.get('teams'):
                    team = search_data['teams'][0]
                    team_id = team['idTeam']
                    result += f"<p>Найдена команда: {team['strTeam']} (ID: {team_id})</p>"
                    result += f"<p>Лига: {team.get('strLeague', 'Н/Д')}, Страна: {team.get('strCountry', 'Н/Д')}</p>"
                    
                    # Последние матчи
                    matches_url = f"https://www.thesportsdb.com/api/v1/json/3/eventslast.php?id={team_id}"
                    result += f"<p>URL последних матчей: <a href='{matches_url}' target='_blank'>{matches_url}</a></p>"
                    
                    matches_response = requests.get(matches_url)
                    matches_data = matches_response.json()
                    
                    result += "<h4>Последние матчи:</h4>"
                    if matches_data.get('results'):
                        result += "<ul>"
                        for match in matches_data['results'][:5]:
                            date = match.get('dateEvent', 'Н/Д')
                            home = match.get('strHomeTeam', 'Н/Д')
                            away = match.get('strAwayTeam', 'Н/Д')
                            score = f"{match.get('intHomeScore', '?')}:{match.get('intAwayScore', '?')}"
                            result += f"<li>{date}: {home} {score} {away}</li>"
                        result += "</ul>"
                    else:
                        result += "<p>Нет данных о последних матчах</p>"
                    
                    # Игроки
                    players_url = f"https://www.thesportsdb.com/api/v1/json/3/lookup_all_players.php?id={team_id}"
                    result += f"<p>URL состава: <a href='{players_url}' target='_blank'>{players_url}</a></p>"
                    
                    players_response = requests.get(players_url)
                    players_data = players_response.json()
                    
                    result += "<h4>Игроки команды:</h4>"
                    if players_data.get('player'):
                        result += "<ul>"
                        for player in players_data['player'][:10]:
                            name = player.get('strPlayer', 'Н/Д')
                            position = player.get('strPosition', 'Н/Д')
                            result += f"<li>{name} ({position})</li>"
                        result += "</ul>"
                    else:
                        result += "<p>Нет данных о составе</p>"
                else:
                    result += "<p>Команда не найдена!</p>"
                    
            except Exception as e:
                result += f"<p>Ошибка при получении данных: {str(e)}</p>"
                
            return result
        
        # Формируем HTML страницу
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Тестирование API для команд</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                h1 { color: #333; }
                hr { margin: 30px 0; }
                a { color: #0066cc; }
            </style>
        </head>
        <body>
            <h1>Тестирование API для команд</h1>
        """
        
        # Добавляем результаты тестирования для команд
        html += get_team_info_formatted("Люцерн", "FC Luzern")
        html += "<hr>"
        html += get_team_info_formatted("Ксамакс", "Neuchatel Xamax")
        
        html += "</body></html>"
        
        return html
    
    except Exception as e:
        return f"Произошла ошибка: {str(e)}"

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
    dispatcher.add_handler(CommandHandler("team", team_command))
    
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

def run_polling():
    """Запуск бота в режиме polling (для локальной разработки)."""
    updater = Updater(TELEGRAM_TOKEN)
    dispatcher = updater.dispatcher
    
    # Регистрируем обработчики команд
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("team", team_command))
    
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