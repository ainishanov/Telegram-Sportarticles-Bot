# Телеграм Бот для Прогнозов на Спортивные Матчи

Этот бот анализирует сообщения от пользователей с информацией о предстоящих матчах, собирает информацию о командах и генерирует прогнозы на матчи с использованием OpenAI API.

## Функциональность

- Обрабатывает сообщения в специальном формате (или с префиксом "@Get articles")
- Ищет информацию о командах и последних матчах в интернете
- Генерирует подробные прогнозы на матчи с учетом минимального количества символов
- Автоматически обрабатывает записи "Все X матчей" путем поиска информации о предстоящих матчах в указанном турнире

## Установка

1. Клонируйте репозиторий
2. Установите зависимости:
   ```
   pip install -r requirements.txt
   ```
3. Создайте файл `.env` на основе `.env.example` и добавьте свои ключи API:
   ```
   TELEGRAM_BOT_TOKEN=ваш_токен_бота
   OPENAI_API_KEY=ваш_ключ_openai
   ```

## Использование

1. Запустите бота:
   ```
   python bot.py
   ```
2. В Telegram, отправьте боту сообщение в формате:
   ```
   на [дата] (не позднее [дедлайн])
   
   1. [Команда1] - [Команда2]                [Турнир] ([мин_символов])
   2. [Все X матчей]                [Турнир] ([мин_символов])
   ...
   ```
   
   Или можно использовать префикс "@Get articles" перед сообщением.

3. Бот обработает сообщение и начнет генерировать прогнозы

## Деплой на Render

1. Создайте аккаунт на [Render](https://render.com/)
2. Подключите ваш GitHub репозиторий
3. Создайте новый веб-сервис, выбрав репозиторий
4. В разделе настроек укажите:
   - **Environment**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`
5. Добавьте переменные окружения:
   - `TELEGRAM_BOT_TOKEN`: ваш токен от BotFather
   - `OPENAI_API_KEY`: ваш ключ API OpenAI
   - `APP_URL`: URL вашего приложения на Render (например, https://telegram-sportarticles-bot.onrender.com)
6. Нажмите "Create Web Service"
7. После успешного деплоя, откройте URL `/set_webhook` для активации вебхука бота

## Локальная разработка

Для локального запуска в режиме polling добавьте переменную окружения:
```
USE_POLLING=true
```

## Примечания по реализации

- Поиск информации о матчах реализован через модуль `web_search.py`
- Для генерации прогнозов используется OpenAI API (**gpt-3.5-turbo**)
- Бот настроен для обработки как конкретных матчей, так и целых турниров

## Требования
- Python 3.9+
- Токен Telegram бота
- Ключ API OpenAI 

## TheSportsDB API

Бот использует TheSportsDB API для получения информации о спортивных событиях, командах и игроках.

### Модуль `sports_api.py`

Класс `TheSportsDB` предоставляет методы для взаимодействия с API:

#### Основные методы:

1. **Поиск команд**
   - `search_team(team_name)` - поиск команды по названию
   - `search_team_by_short_code(short_code)` - поиск команды по короткому коду

2. **Поиск игроков**
   - `search_player(player_name)` - поиск игрока по имени

3. **События и матчи**
   - `search_events(query)` - поиск событий по запросу
   - `get_last_events_by_team(team_id)` - получение последних матчей команды
   - `search_matches_for_tournament(russian_name, date, english_name)` - поиск матчей для турнира на определенную дату

4. **Информация о лигах и странах**
   - `list_all_leagues()` - список всех лиг
   - `list_all_countries()` - список всех стран
   - `list_leagues_in_country(country, sport="Soccer")` - список лиг в стране
   - `list_teams_in_league(league_name)` - список команд в лиге
   - `list_teams_in_country(country)` - список команд в стране

5. **Детальная информация**
   - `lookup_team(team_id)` - получение детальной информации о команде
   - `lookup_player(player_id)` - получение детальной информации об игроке
   - `lookup_event(event_id)` - получение детальной информации о событии

6. **Составы команд**
   - `list_all_players_in_team(team_id)` - список всех игроков команды

7. **Вспомогательные методы**
   - `get_team_info(russian_name, english_name=None)` - комплексная информация о команде
   - `search_venues(query)` - поиск спортивных сооружений по запросу

#### Пример использования:

```python
from sports_api import TheSportsDB

# Создание экземпляра класса API
api = TheSportsDB()

# Поиск команды
team_result = api.search_team("Arsenal")
if team_result and team_result.get('teams'):
    team_id = team_result['teams'][0]['idTeam']
    team_name = team_result['teams'][0]['strTeam']
    print(f"Найдена команда: {team_name} (ID: {team_id})")

    # Получение последних матчей команды
    last_matches = api.get_last_events_by_team(team_id)
    if last_matches and last_matches.get('results'):
        print("\nПоследние матчи:")
        for match in last_matches['results'][:3]:
            home = match['strHomeTeam']
            away = match['strAwayTeam']
            score = f"{match['intHomeScore']} - {match['intAwayScore']}"
            print(f"{match['dateEvent']}: {home} {score} {away}")
```

### Тестирование API

Для тестирования API можно использовать скрипт `test_sports_api.py`:

```bash
python test_sports_api.py
```

## Хостинг

Бот развернут на платформе Render. Для настройки вебхуков используется переменная окружения `APP_URL`.

## Лицензия

MIT 