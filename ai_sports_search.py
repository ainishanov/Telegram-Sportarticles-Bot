import os
import re
import json
import logging
from anthropic import Anthropic
from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

class AISportsSearch:
    """Класс для поиска спортивной информации с использованием Claude API"""
    
    def __init__(self, api_key=None):
        """Инициализация клиента Claude API"""
        self.api_key = api_key or ANTHROPIC_API_KEY
        if not self.api_key:
            logger.error("ANTHROPIC_API_KEY не задан в переменных окружения")
        
        self.client = Anthropic(api_key=self.api_key)
    
    def get_team_info(self, team_name, english_name=None):
        """
        Получает актуальную информацию о команде через Claude API
        
        Args:
            team_name (str): Название команды
            english_name (str, optional): Название команды на английском
        
        Returns:
            dict: Информация о команде (последние матчи, состав, тренер и т.д.)
        """
        try:
            search_name = english_name or team_name
            
            prompt = f"""Найди актуальную информацию о футбольной команде {team_name} ({search_name}).
            
            Требуется следующая информация:
            1. Общие сведения (лига, страна, стадион)
            2. Последние матчи (не менее 5, включая дату, соперника и счет)
            3. Ближайшие матчи (не менее 3, если есть информация)
            4. Текущий состав команды (основные игроки)
            5. Главный тренер
            6. Текущая позиция в турнирной таблице
            
            Информация должна быть максимально актуальной.
            """
            
            system_prompt = """
            Ты - помощник, специализирующийся на спортивной аналитике и данных.
            Твоя задача - использовать возможность поиска в интернете для получения максимально
            актуальной информации о спортивных командах, игроках и событиях.
            Всегда указывай дату найденной информации.
            Представь информацию в структурированном виде для дальнейшей обработки.
            """
            
            logger.info(f"Отправка запроса к Claude API для поиска информации о {team_name}")
            
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20240620",
                max_tokens=2000,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            response_text = response.content[0].text
            logger.info(f"Получен ответ от Claude API: {len(response_text)} символов")
            
            # Извлекаем структурированные данные
            team_data = self._parse_team_info(response_text, team_name)
            
            return team_data
            
        except Exception as e:
            logger.error(f"Ошибка при запросе к Claude API: {e}")
            return {
                "error": str(e),
                "team_name": team_name,
                "last_matches": f"Не удалось получить информацию о последних матчах {team_name}",
                "lineup": f"Не удалось получить информацию о составе {team_name}"
            }
    
    def _parse_team_info(self, response_text, team_name):
        """
        Парсит ответ от Claude API и извлекает структурированные данные
        
        Args:
            response_text (str): Текстовый ответ от Claude API
            team_name (str): Название команды
        
        Returns:
            dict: Структурированные данные о команде
        """
        # Базовая структура ответа
        result = {
            "team_name": team_name,
            "info": {},
            "last_matches": "",
            "upcoming_matches": "",
            "lineup": "",
            "manager": "",
            "league_position": "",
            "raw_response": response_text
        }
        
        # Извлечение последних матчей
        last_matches_section = self._extract_section(response_text, 
                                                   ["Последние матчи", "Recent matches", "Last matches"])
        if last_matches_section:
            matches = self._extract_matches(last_matches_section)
            last_matches_text = f"Последние матчи {team_name}:\n"
            for match in matches:
                last_matches_text += f"- {match['date']}: {match['team1']} {match['score1']}:{match['score2']} {match['team2']}\n"
            result["last_matches"] = last_matches_text
        else:
            result["last_matches"] = f"Не удалось выделить информацию о последних матчах {team_name}"
        
        # Извлечение состава
        lineup_section = self._extract_section(response_text, 
                                             ["Состав", "Текущий состав", "Основные игроки", 
                                              "Roster", "Squad", "Players"])
        if lineup_section:
            players = self._extract_players(lineup_section)
            lineup_text = f"Состав {team_name}:\n"
            for player in players:
                position = player.get('position', 'Н/Д')
                lineup_text += f"- {player['name']} ({position})\n"
            result["lineup"] = lineup_text
        else:
            result["lineup"] = f"Не удалось выделить информацию о составе {team_name}"
        
        # Извлечение главного тренера
        result["manager"] = self._extract_manager(response_text)
        
        # Извлечение позиции в лиге
        result["league_position"] = self._extract_league_position(response_text)
        
        return result
    
    def _extract_section(self, text, section_names):
        """Извлекает раздел из текста по возможным названиям раздела"""
        # Ищем начало секции
        section_start = None
        next_section_start = None
        
        for name in section_names:
            pattern = re.compile(f"(?:^|\n)(?:#{1,3} |[0-9]+\\.)?\\s*{name}[:\n]", re.IGNORECASE)
            match = pattern.search(text)
            if match and (section_start is None or match.start() < section_start):
                section_start = match.end()
        
        if section_start is None:
            return None
        
        # Ищем начало следующей секции
        section_patterns = [
            r"(?:^|\n)(?:#{1,3} |[0-9]+\.)?\\s*(?:Общие сведения|Общая информация|General info)[:\n]",
            r"(?:^|\n)(?:#{1,3} |[0-9]+\.)?\\s*(?:Последние матчи|Recent matches|Last matches)[:\n]",
            r"(?:^|\n)(?:#{1,3} |[0-9]+\.)?\\s*(?:Ближайшие матчи|Upcoming matches|Next matches)[:\n]",
            r"(?:^|\n)(?:#{1,3} |[0-9]+\.)?\\s*(?:Состав|Текущий состав|Основные игроки|Roster|Squad|Players)[:\n]",
            r"(?:^|\n)(?:#{1,3} |[0-9]+\.)?\\s*(?:Главный тренер|Тренер|Manager|Coach)[:\n]",
            r"(?:^|\n)(?:#{1,3} |[0-9]+\.)?\\s*(?:Позиция в турнирной таблице|Текущая позиция|League position|Standing)[:\n]"
        ]
        
        for pattern_str in section_patterns:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            match = pattern.search(text, section_start)
            if match and (next_section_start is None or match.start() < next_section_start):
                next_section_start = match.start()
        
        # Извлекаем текст секции
        if next_section_start:
            return text[section_start:next_section_start].strip()
        else:
            return text[section_start:].strip()
    
    def _extract_matches(self, matches_text):
        """Извлекает данные о матчах из текста"""
        matches = []
        
        # Попытка найти матчи с различными форматами дат
        patterns = [
            # Формат: 01.02.2023: Команда1 1:0 Команда2
            r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})[:\s]+([^0-9]+)\s+(\d+)[:-](\d+)\s+([^0-9]+)",
            # Формат: 1 января 2023: Команда1 1:0 Команда2
            r"(\d{1,2}\s+[а-яА-Яa-zA-Z]+\s+\d{2,4})[:\s]+([^0-9]+)\s+(\d+)[:-](\d+)\s+([^0-9]+)",
            # Формат: 01.02.23: Команда1 - Команда2 1:0
            r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})[:\s]+([^0-9-]+)\s+-\s+([^0-9:]+)\s+(\d+)[:-](\d+)",
            # Формат: Команда1 1:0 Команда2 (01.02.2023)
            r"([^0-9(]+)\s+(\d+)[:-](\d+)\s+([^0-9(]+)\s+\((\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\)"
        ]
        
        for pattern_str in patterns:
            pattern = re.compile(pattern_str)
            for line in matches_text.split('\n'):
                match = pattern.search(line)
                if match:
                    groups = match.groups()
                    if len(groups) == 5:
                        if pattern_str == patterns[0] or pattern_str == patterns[1]:
                            date, team1, score1, score2, team2 = groups
                        elif pattern_str == patterns[2]:
                            date, team1, team2, score1, score2 = groups
                        else:  # patterns[3]
                            team1, score1, score2, team2, date = groups
                        
                        matches.append({
                            'date': date.strip(),
                            'team1': team1.strip(),
                            'team2': team2.strip(),
                            'score1': score1,
                            'score2': score2
                        })
        
        # Если не нашли ни одного матча с помощью регулярок, поищем более простым методом
        if not matches:
            lines = matches_text.split('\n')
            for i, line in enumerate(lines):
                if any(x in line.lower() for x in [':', ' - ', 'vs']):
                    # Ищем цифры, которые могут быть счетом
                    score_match = re.search(r'(\d+)\s*[-:]\s*(\d+)', line)
                    if score_match:
                        score1, score2 = score_match.groups()
                        
                        # Пытаемся найти дату
                        date_match = re.search(r'(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}\s+[а-яА-Яa-zA-Z]+\s+\d{2,4})', line)
                        date = date_match.group(1) if date_match else "Н/Д"
                        
                        # Разделяем строку по счету
                        parts = re.split(r'\d+\s*[-:]\s*\d+', line, 1)
                        if len(parts) == 2:
                            team_part = parts[0].strip()
                            # Ищем команды в части до счета
                            team_split = re.split(r'\s+-\s+|vs\.?|против', team_part)
                            
                            if len(team_split) >= 2:
                                team1, team2 = team_split[0].strip(), team_split[1].strip()
                            else:
                                # Если не получилось разделить, попробуем использовать общую логику
                                team1 = team_part
                                team2 = parts[1].strip()
                            
                            matches.append({
                                'date': date,
                                'team1': team1,
                                'team2': team2,
                                'score1': score1,
                                'score2': score2
                            })
        
        return matches
    
    def _extract_players(self, lineup_text):
        """Извлекает данные об игроках из текста"""
        players = []
        
        # Ищем строки, начинающиеся с дефиса или звездочки (маркеры списка)
        lines = lineup_text.split('\n')
        for line in lines:
            line = line.strip()
            player_match = re.match(r'[-*•]\s+([^(]+)(?:\(([^)]+)\))?', line)
            
            if player_match:
                name = player_match.group(1).strip()
                position = player_match.group(2).strip() if player_match.group(2) else "Н/Д"
                
                players.append({
                    'name': name,
                    'position': position
                })
        
        # Если не нашли игроков по маркерам списка, попробуем другой подход
        if not players:
            # Ищем строки с позициями игроков
            position_patterns = [
                r'([^:]+):\s+(.+)',  # Формат: "Вратари: Игрок1, Игрок2"
                r'([^-]+)\s*-\s*([^(]+)(?:\(([^)]+)\))?'  # Формат: "Игрок - позиция"
            ]
            
            for pattern_str in position_patterns:
                pattern = re.compile(pattern_str)
                for line in lines:
                    match = pattern.search(line)
                    if match:
                        groups = match.groups()
                        if len(groups) >= 2:
                            if ":" in line:  # Первый формат
                                position, names = groups[0].strip(), groups[1].strip()
                                for name in re.split(r',\s*', names):
                                    players.append({
                                        'name': name.strip(),
                                        'position': position
                                    })
                            else:  # Второй формат
                                name, position = groups[0].strip(), groups[1].strip()
                                players.append({
                                    'name': name,
                                    'position': position
                                })
        
        return players
    
    def _extract_manager(self, text):
        """Извлекает информацию о главном тренере"""
        manager_section = self._extract_section(text, 
                                             ["Главный тренер", "Тренер", "Manager", "Coach"])
        
        if manager_section:
            # Ищем имя тренера
            manager_pattern = re.compile(r'(?:главный тренер|тренер|coach|manager)[:\s-]+([^\n]+)', re.IGNORECASE)
            match = manager_pattern.search(manager_section)
            
            if match:
                return match.group(1).strip()
            else:
                # Если не нашли с помощью паттерна, возьмем первую строку
                return manager_section.split('\n')[0].strip()
        
        # Если не нашли отдельной секции, поищем в тексте
        manager_pattern = re.compile(r'(?:главный тренер|тренер|coach|manager)[:\s-]+([^\n\.]+)', re.IGNORECASE)
        match = manager_pattern.search(text)
        
        if match:
            return match.group(1).strip()
        
        return "Н/Д"
    
    def _extract_league_position(self, text):
        """Извлекает информацию о позиции в турнирной таблице"""
        position_section = self._extract_section(text, 
                                               ["Позиция в турнирной таблице", "Текущая позиция",
                                                "League position", "Standing", "Турнирная таблица"])
        
        if position_section:
            # Ищем позицию
            position_pattern = re.compile(r'(?:позиция|место|position|place)[:\s-]+(\d+)', re.IGNORECASE)
            match = position_pattern.search(position_section)
            
            if match:
                return match.group(1).strip()
            else:
                # Если не нашли с помощью паттерна, вернем весь текст секции
                return position_section.strip()
        
        # Если не нашли отдельной секции, поищем в тексте
        position_pattern = re.compile(r'(?:занимает|находится на|is currently|current position)[:\s]+(\d+)(?:[а-яА-Я\s-]+|\w+)?(?:место|позиция|position|place)', re.IGNORECASE)
        match = position_pattern.search(text)
        
        if match:
            return match.group(1).strip()
        
        return "Н/Д"

# Пример использования
if __name__ == "__main__":
    # Проверка на наличие API ключа
    if not ANTHROPIC_API_KEY:
        print("ОШИБКА: Необходимо указать ANTHROPIC_API_KEY в .env файле")
    else:
        # Создание экземпляра класса
        ai_search = AISportsSearch()
        
        # Поиск информации о команде
        team_name = "Люцерн"
        english_name = "FC Luzern"
        
        print(f"Поиск информации о команде: {team_name}")
        team_info = ai_search.get_team_info(team_name, english_name)
        
        # Вывод результатов
        print("\nОБЩАЯ ИНФОРМАЦИЯ:")
        print(team_info.get("info", "Информация отсутствует"))
        
        print("\nПОСЛЕДНИЕ МАТЧИ:")
        print(team_info.get("last_matches", "Информация о матчах отсутствует"))
        
        print("\nСОСТАВ КОМАНДЫ:")
        print(team_info.get("lineup", "Информация о составе отсутствует"))
        
        print("\nГЛАВНЫЙ ТРЕНЕР:")
        print(team_info.get("manager", "Информация о тренере отсутствует"))
        
        print("\nПОЗИЦИЯ В ТУРНИРНОЙ ТАБЛИЦЕ:")
        print(team_info.get("league_position", "Информация о позиции отсутствует")) 