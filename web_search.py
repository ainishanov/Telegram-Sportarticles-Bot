import requests
from bs4 import BeautifulSoup
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

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
        # Преобразование даты в формат, необходимый для поиска
        month_map = {
            'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04',
            'мая': '05', 'июня': '06', 'июля': '07', 'августа': '08',
            'сентября': '09', 'октября': '10', 'ноября': '11', 'декабря': '12'
        }
        
        day, month_name = date_str.split()
        month = month_map.get(month_name, '01')
        current_year = datetime.now().year
        formatted_date = f"{current_year}-{month}-{day.zfill(2)}"
        
        # Запрос к поисковой системе
        search_query = f"{tournament} матчи {date_str}"
        url = f"https://www.google.com/search?q={search_query}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Ошибка при запросе: {response.status_code}")
            return []
        
        # В реальности нужно использовать более сложный парсинг,
        # так как Google и другие сайты могут блокировать автоматические запросы
        # и структура их страниц сложная
        
        # Это упрощенная реализация для демонстрации
        # В реальном проекте рекомендуется использовать специализированные API спортивных данных
        matches = []
        for i in range(1, 7):  # Предполагаем, что есть 6 матчей
            matches.append({
                'team1': f"Команда{i}A ({tournament})",
                'team2': f"Команда{i}B ({tournament})",
                'tournament': tournament,
                'date': formatted_date
            })
        
        return matches
    
    except Exception as e:
        logger.error(f"Ошибка при поиске матчей: {e}")
        return []

def get_team_info(team_name):
    """
    Получает информацию о команде: последние матчи и состав.
    
    Args:
        team_name: Название команды
    
    Returns:
        dict: Словарь с информацией о команде
    """
    try:
        # Запрос к поисковой системе
        search_query = f"{team_name} футбол последние матчи состав"
        url = f"https://www.google.com/search?q={search_query}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Ошибка при запросе: {response.status_code}")
            return {
                'last_matches': [f"Нет данных о последних матчах {team_name}"],
                'lineup': [f"Нет данных о составе {team_name}"]
            }
        
        # В реальности нужно использовать более сложный парсинг
        # Это упрощенная реализация для демонстрации
        
        # Имитация найденных данных
        last_matches = [
            f"{team_name} - Соперник1: 2-1 (03.03.2023)",
            f"Соперник2 - {team_name}: 0-3 (28.02.2023)",
            f"{team_name} - Соперник3: 1-1 (23.02.2023)"
        ]
        
        lineup = [f"Игрок {i} ({team_name})" for i in range(1, 12)]
        
        return {
            'last_matches': last_matches,
            'lineup': lineup
        }
    
    except Exception as e:
        logger.error(f"Ошибка при получении информации о команде: {e}")
        return {
            'last_matches': [f"Нет данных о последних матчах {team_name}"],
            'lineup': [f"Нет данных о составе {team_name}"]
        } 