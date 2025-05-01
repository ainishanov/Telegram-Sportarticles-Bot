import requests
from bs4 import BeautifulSoup
import logging
import re
from datetime import datetime
import urllib.parse
import time
import json

logger = logging.getLogger(__name__)

# Константы для API TheSportsDB
API_BASE_URL = "https://www.thesportsdb.com/api/v1/json"
API_KEY = "3"  # Бесплатный тестовый ключ
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# Ограничения для API запросов
MAX_RETRIES = 3
RETRY_DELAY = 2  # секунды
REQUEST_TIMEOUT = 10  # секунды
MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB

# Словарь для преобразования названий турниров в правильные запросы к API
TOURNAMENT_MAPPINGS = {
    "ЧМ-2026. Европа. Квалификация": "FIFA World Cup qualification (UEFA)",
    "Лига Наций. Переходные матчи": "UEFA Nations League",
    "Клубы. Товарищеский матч": "Club Friendlies"
}

def validate_api_params(params):
    """
    Проверяет и очищает параметры запроса к API от потенциально опасных значений.
    
    Args:
        params: Словарь параметров запроса
    
    Returns:
        dict: Очищенный словарь параметров
    """
    if not params:
        return {}
    
    validated_params = {}
    for key, value in params.items():
        # Убеждаемся, что ключи и значения - строки
        key_str = str(key)
        value_str = str(value)
        
        # Очищаем значения от потенциально опасных символов
        clean_value = re.sub(r'[^\w\s\-\.,]', '', value_str)
        validated_params[key_str] = clean_value
        
    return validated_params

def api_request(endpoint, params=None):
    """
    Выполняет запрос к API TheSportsDB с проверками безопасности.
    
    Args:
        endpoint: Эндпоинт API
        params: Параметры запроса
    
    Returns:
        dict: Ответ от API в формате JSON
    """
    # Проверяем и очищаем параметры
    validated_params = validate_api_params(params)
    
    for attempt in range(MAX_RETRIES):
        try:
            # Ограничиваем длину URL
            endpoint = endpoint[:100]  # Ограничение длины эндпоинта
            url = f"{API_BASE_URL}/{API_KEY}/{endpoint}"
            
            # Устанавливаем таймаут для защиты от зависаний
            response = requests.get(
                url, 
                params=validated_params, 
                headers=HEADERS, 
                timeout=REQUEST_TIMEOUT
            )
            
            # Проверка статус-кода
            if response.status_code != 200:
                logger.error(f"Ошибка API: {response.status_code}, URL: {url}, Ответ: {response.text[:500]}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                return None
            
            # Проверка размера ответа
            if len(response.content) > MAX_RESPONSE_SIZE:
                logger.error(f"Ответ API слишком большой: {len(response.content)} байт")
                return None
            
            # Безопасный JSON парсинг
            try:
                data = response.json()
                return data
            except json.JSONDecodeError as e:
                logger.error(f"Ошибка при разборе JSON: {e}")
                return None
                
        except requests.RequestException as e:
            logger.error(f"Ошибка при запросе к API: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                return None
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при запросе к API: {e}")
            return None
    
    return None  # В случае всех неудачных попыток

def search_team(team_name):
    """
    Ищет команду по названию и возвращает её данные.
    
    Args:
        team_name: Название команды
    
    Returns:
        dict: Данные о команде
    """
    # Проверка и очистка входных данных
    if not team_name or not isinstance(team_name, str):
        logger.warning("Получено некорректное название команды")
        return None
    
    # Ограничиваем длину названия команды
    team_name = team_name[:50]
    
    endpoint = "searchteams.php"
    params = {"t": team_name}
    
    data = api_request(endpoint, params)
    
    if not data or "teams" not in data or not data["teams"]:
        logger.warning(f"Команда не найдена: {team_name}")
        return None
    
    return data["teams"][0]  # Возвращаем первую найденную команду

def get_team_last_matches(team_id):
    """
    Получает последние матчи команды.
    
    Args:
        team_id: ID команды
    
    Returns:
        list: Список последних матчей
    """
    endpoint = "eventslast.php"
    params = {"id": team_id}
    
    data = api_request(endpoint, params)
    
    if not data or "results" not in data or not data["results"]:
        logger.warning(f"Не найдены последние матчи для команды с ID: {team_id}")
        return []
    
    matches = []
    for match in data["results"]:
        match_info = {
            "date": match.get("dateEvent", ""),
            "home_team": match.get("strHomeTeam", ""),
            "away_team": match.get("strAwayTeam", ""),
            "home_score": match.get("intHomeScore", ""),
            "away_score": match.get("intAwayScore", ""),
            "league": match.get("strLeague", "")
        }
        
        result = f"{match_info['home_team']} {match_info['home_score']} - {match_info['away_score']} {match_info['away_team']} ({match_info['date']})"
        matches.append(result)
    
    return matches

def get_team_players(team_name):
    """
    Получает игроков команды.
    
    Args:
        team_name: Название команды
    
    Returns:
        list: Список игроков
    """
    endpoint = "searchplayers.php"
    params = {"t": team_name}
    
    data = api_request(endpoint, params)
    
    if not data or "player" not in data or not data["player"]:
        logger.warning(f"Не найдены игроки для команды: {team_name}")
        return []
    
    players = []
    for player in data["player"]:
        player_info = f"{player.get('strPlayer', 'Неизвестный игрок')} ({player.get('strPosition', 'Неизвестная позиция')})"
        players.append(player_info)
    
    return players

def convert_date_format(date_str):
    """
    Преобразует дату из формата "день месяц" в формат "YYYY-MM-DD" с проверками безопасности.
    
    Args:
        date_str: Дата в формате "21 марта"
    
    Returns:
        str: Дата в формате "YYYY-MM-DD"
    """
    if not date_str or not isinstance(date_str, str):
        logger.warning("Получена некорректная дата")
        return datetime.now().strftime("%Y-%m-%d")
    
    # Ограничиваем длину строки даты
    date_str = date_str[:20]
    
    try:
        months = {
            'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04',
            'мая': '05', 'июня': '06', 'июля': '07', 'августа': '08',
            'сентября': '09', 'октября': '10', 'ноября': '11', 'декабря': '12'
        }
        
        # Безопасное разделение строки
        parts = date_str.split()
        if len(parts) < 2:
            logger.warning(f"Неверный формат даты: {date_str}")
            return datetime.now().strftime("%Y-%m-%d")
            
        day = parts[0]
        month_name = parts[1].lower()
        
        # Проверка на числовой день
        if not day.isdigit():
            logger.warning(f"День не является числом: {day}")
            day = "1"
        
        month = months.get(month_name, '01')
        current_year = datetime.now().year
        
        # Проверка валидности дня
        day_int = int(day)
        if day_int < 1 or day_int > 31:
            logger.warning(f"Некорректный день: {day}")
            day = "1"
        
        # Форматируем день с ведущим нулем
        day = day.zfill(2)
        
        return f"{current_year}-{month}-{day}"
    
    except Exception as e:
        logger.error(f"Ошибка при преобразовании даты: {e}")
        # Возвращаем сегодняшнюю дату в случае ошибки
        return datetime.now().strftime("%Y-%m-%d")

def get_league_by_tournament(tournament_name):
    """
    Преобразует название турнира в формат для API.
    
    Args:
        tournament_name: Название турнира из исходного файла
    
    Returns:
        str: Название лиги для API
    """
    # Проверяем есть ли прямое соответствие
    if tournament_name in TOURNAMENT_MAPPINGS:
        return TOURNAMENT_MAPPINGS[tournament_name]
    
    # Поиск по ключевым словам
    for key, value in TOURNAMENT_MAPPINGS.items():
        if key in tournament_name or tournament_name in key:
            return value
    
    # Возвращаем оригинальное название, если не нашли соответствия
    return tournament_name

def get_team_info(team_name):
    """
    Получает информацию о команде: последние матчи и состав.
    
    Args:
        team_name: Название команды
    
    Returns:
        dict: Словарь с информацией о команде
    """
    try:
        # Ищем команду
        team = search_team(team_name)
        
        if not team:
            # Если не нашли, возвращаем заглушку
            logger.warning(f"Не удалось найти команду: {team_name}, используем заглушку")
            return {
                'last_matches': [f"Нет данных о последних матчах для {team_name}"],
                'lineup': [f"Нет данных о составе для {team_name}"]
            }
        
        # Получаем ID команды
        team_id = team.get("idTeam", "")
        
        # Получаем последние матчи
        last_matches = get_team_last_matches(team_id)
        
        # Получаем игроков
        players = get_team_players(team_name)
        
        # Если не удалось получить данные, используем заглушки
        if not last_matches:
            last_matches = [f"Нет данных о последних матчах для {team_name}"]
        
        if not players:
            players = [f"Нет данных о составе для {team_name}"]
        
        return {
            'last_matches': last_matches,
            'lineup': players
        }
    
    except Exception as e:
        logger.error(f"Ошибка при получении информации о команде {team_name}: {e}")
        return {
            'last_matches': [f"Ошибка при получении данных о последних матчах для {team_name}"],
            'lineup': [f"Ошибка при получении данных о составе для {team_name}"]
        }

def search_matches_for_tournament(tournament, date_str):
    """
    Ищет все матчи для указанного турнира на указанную дату.
    
    Args:
        tournament: Название турнира (например, "ЧМ-2026. Европа. Квалификация")
        date_str: Дата в формате "день месяц" (например, "21 марта")
    
    Returns:
        list: Список словарей с информацией о матчах
    """
    try:
        # Преобразуем дату в формат API (YYYY-MM-DD)
        formatted_date = convert_date_format(date_str)
        
        # Преобразуем название турнира в формат для API
        league_name = get_league_by_tournament(tournament)
        
        # Делаем запрос на поиск матчей в этот день
        endpoint = "eventsday.php"
        params = {"d": formatted_date}
        
        data = api_request(endpoint, params)
        
        matches = []
        
        # Проверяем есть ли данные о матчах
        if not data or "events" not in data or not data["events"]:
            logger.warning(f"Не найдены матчи для турнира {tournament} на дату {date_str}")
            
            # Если данных нет, генерируем примерные матчи (для примера или тестирования)
            for i in range(1, 7):  # Предполагаем, что нужно 6 матчей
                matches.append({
                    'team1': f"Команда{i}A ({tournament})",
                    'team2': f"Команда{i}B ({tournament})",
                    'tournament': tournament,
                    'date': formatted_date
                })
            
            return matches
        
        # Фильтруем матчи по нужному турниру/лиге
        for event in data["events"]:
            event_league = event.get("strLeague", "")
            
            # Проверяем соответствие лиги/турнира
            if league_name.lower() in event_league.lower() or event_league.lower() in league_name.lower():
                match = {
                    'team1': event.get("strHomeTeam", ""),
                    'team2': event.get("strAwayTeam", ""),
                    'tournament': tournament,
                    'date': formatted_date
                }
                matches.append(match)
        
        # Если после фильтрации не осталось матчей, возвращаем примерные
        if not matches:
            logger.warning(f"После фильтрации не найдены матчи для {tournament} на {date_str}")
            for i in range(1, 7):
                matches.append({
                    'team1': f"Команда{i}A ({tournament})",
                    'team2': f"Команда{i}B ({tournament})",
                    'tournament': tournament,
                    'date': formatted_date
                })
        
        return matches
    
    except Exception as e:
        logger.error(f"Ошибка при поиске матчей для турнира {tournament} на дату {date_str}: {e}")
        # В случае ошибки возвращаем примерные данные
        matches = []
        for i in range(1, 7):
            matches.append({
                'team1': f"Команда{i}A ({tournament})",
                'team2': f"Команда{i}B ({tournament})",
                'tournament': tournament,
                'date': date_str
            })
        
        return matches 