import asyncio
import random
import string
import datetime
import aiofiles
from pyexpat.errors import messages

import dictionaries

from telebot.async_telebot import AsyncTeleBot
import os
import sqlite3
from telebot import types
import json
import time

os.getenv('')

token = os.getenv('BOT_TOKEN')
bot = AsyncTeleBot(token)

conn = sqlite3.connect('bunker.db', check_same_thread=False)
c = conn.cursor()


def create_referral_chat_link(chat_id):
    link = f'https://t.me/Bunkerbe_bot?start={chat_id}'
    return link


def create_user_link(user_id, user_name):
    link = f'<a href="tg://openmessage?user_id={user_id}">{user_name}</a>'
    return link


c.execute('''CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    games_played INTEGER DEFAULT 0,
    win_games INTEGER DEFAULT 0,
    points INTEGER DEFAULT 0,
    is_in_game INTEGER DEFAULT 0,
    is_banned BOOLEAN DEFAULT False,
    registration_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    theme TEXT DEFAULT 'classic')''')

card_name_translation = {
    'baggage': 'Багаж',
    'health': 'Состояние здоровья',
    'profession': 'Профессия',
    "skills": "Навык",
    'facts': 'Факт',
    'hobby': 'Хобби',
    'biology': 'Биология'
}


class IsInGameNow:
    def __init__(self):
        pass

    ACTIVE = "active"  # Идёт набор игроков в команду
    INACTIVE = 'inactive'  # Игра не идёт, набор не идёт
    IN_GAME = 'in_game'  # Идёт игра без набора игроков


class Discussion:
    def __init__(self):
        pass

    stop = "stop"  # Игрок нажал на кнопку для завершения обсуждения
    in_discussion = "in_discussion"  # Игрок сейчас отвечает за свои карты
    not_in_discussion = "not_in_discussion"  # Игрок уже ответил за свои карты


c.execute(f'''CREATE TABLE IF NOT EXISTS chats(
chat_id INTEGER PRIMARY KEY,
is_in_game  TEXT DEFAULT "{IsInGameNow.INACTIVE}",
catastrophe INTEGER DEFAULT 0,
last_message_id INTEGER DEFAULT 0,
chat_name TEXT,
discussion_time INTEGER DEFAULT 60,
open_time INTEGER DEFAULT 60,
voting_time INTEGER DEFAULT 60,
delete_message BOOLEAN DEFAULT 1)''')

c.execute(f'''CREATE TABLE IF NOT EXISTS admins(
user_id INTEGER PRIMARY KEY DEFAULT 0,
can_change_status_of_game BOOLEAN DEFAULT False,
can_ban_people BOOLEAN DEFAULT False,
is_main BOOLEAN DEFAULT False )''')

c.execute(f'''CREATE TABLE IF NOT EXISTS admin_info (
reserv_code TEXT PRIMARY KEY,
game_stop BOOLEAN DEFAULT False)''')  # False - можно создавать игры, True - нельзя

user_cards = ['profession', 'health', 'baggage', "skills", 'facts', 'hobby', 'biology']


async def load_config():
    with open("classic.json", 'r', encoding='utf-8') as f:
        for_return = json.load(f)
    return for_return


async def check_cards(user_id, table_chat_id):
    opened_cards = []
    closed_cards = []
    for card in user_cards:
        c.execute(f'''SELECT {card}, {card}_on FROM chat_{table_chat_id} WHERE user_id = ?''', (user_id,))
        result = c.fetchall()[0]
        if int(result[1]) == 1:
            opened_cards.append((card, result))
        elif int(result[1]) == 0:
            closed_cards.append((card, result))
    return opened_cards, closed_cards


async def get_all_cards(user_id, table_chat_id):
    all_cards = []
    for card in user_cards:
        c.execute(f'''SELECT {card} FROM chat_{table_chat_id} WHERE user_id = ?''', (user_id,))
        result = c.fetchone()[0]
        all_cards.append(result)
    return all_cards



async def set_can_open(table_chat_id: int, value: bool, user_id):
    if user_id is None:
        c.execute(f'''UPDATE chat_{table_chat_id} SET can_open = {value}''')
        conn.commit()
        return
    c.execute(f'''UPDATE chat_{table_chat_id} SET can_open = {value} WHERE user_id = ?''', (user_id,))
    conn.commit()
    return


async def is_alive(table_chat_id):
    c.execute(f'''SELECT user_id, user_title FROM chat_{table_chat_id} WHERE is_alive = ?''', (True,))
    result = c.fetchall()
    return result


async def is_dead(table_chat_id):
    c.execute(f'''SELECT user_id, user_title FROM chat_{table_chat_id} WHERE is_alive = ?''', (False,))
    result = c.fetchall()
    return result


async def open_random_card(user_id, table_chat_id):
    closed_cards = []
    result = tuple()
    for card in user_cards:
        c.execute(f'''SELECT {card}, {card}_on FROM chat_{table_chat_id} WHERE user_id = ?''', (user_id,))
        result = c.fetchall()[0]

        if int(result[1]) == 0:
            closed_cards.append(card)

    if not closed_cards:
        return

    card_to_open = random.choice(closed_cards)

    c.execute(f'''UPDATE chat_{table_chat_id} SET {card_to_open}_on = 1, can_open = 0
                  WHERE user_id = ?''', (user_id,))
    conn.commit()

    card_value = result[0]  # Получаем значение вскрываемой карты
    card_name = card_name_translation.get(card_to_open, card_to_open)
    text = await load_config()
    answer_text = f"{str(text['you_didnt_choose_card']['text']).format(card_name=card_name, card_value=card_value)}"
    try:
        await bot.send_message(user_id, answer_text)
    except Exception:
        pass


async def is_game_active(table_chat_id):
    c.execute(f'''SELECT is_in_game FROM chats WHERE chat_id = {table_chat_id}''')
    result = c.fetchone()[0]
    return result == IsInGameNow.IN_GAME


async def is_banned(user_id):
    c.execute(f'''SELECT is_banned FROM users WHERE user_id = ?''', (user_id,))
    result = c.fetchone()

    if result is None:
        return False

    is_banned_value = result[0]

    return bool(is_banned_value)


async def which_chat_with_logs():
    c.execute(f'''SELECT log_chat_id FROM admin_info''')
    result = int(c.fetchone()[0])
    return result


@bot.message_handler(commands=['start'])
async def start(me):
    user_id = int(me.from_user.id)

    if await is_banned(user_id) is True:
        return

    command = me.text.split(' ')
    markup = types.InlineKeyboardMarkup()
    c.execute(
        '''INSERT OR IGNORE INTO users (user_id, games_played, win_games, points, is_in_game) VALUES (?, ?, ?, ?, ?)''',
        (user_id, 0, 0, 0, 0))
    conn.commit()

    if len(command) == 1:
        config = await load_config()
        if me.chat.type == 'private':
            message = (
                "👋 <b>Добро пожаловать в БУНКЕР.</b>\n\n"
                "Мир снаружи уничтожен, и ты оказался в одном из последних убежищ человечества. Здесь нет места слабакам. Каждая игра — это новая битва за выживание, и никто не знает, сколько из нас доживёт до следующего раунда.\n\n"
                "Ты должен бороться за своё место в бункере, а конкурентов много. Тебе придётся делать трудные выборы, и каждый твой шаг может привести к гибели.\n\n"
                "<b>Как начать:</b>\n"
                "Добавь меня в свой групповой чат и используй команду /new_game, чтобы начать борьбу за выживание. Помощь всегда рядом — просто введи /help.\n"
                "Желаем удачи")
            markup.add(types.InlineKeyboardButton(text=config['add_bot_to_chat']['text'],
                                                  url=config['add_bot_to_chat']['url']),
                       types.InlineKeyboardButton(text=config['tg_channel']['text'],
                                                  url=config['tg_channel']['url'])
                       )
            markup.add(types.InlineKeyboardButton(text=config['rules']['text'],
                                                  url=config['rules']['url']))
            await bot.send_message(user_id, message, reply_markup=markup, parse_mode='HTML')
        elif me.chat.type in ['group', 'supergroup']:
            # Получаем имя чата и обновляем его в бд
            chat_name = me.chat.title
            chat_id = me.chat.id

            c.execute('''UPDATE chats SET chat_name = ? WHERE chat_id = ?''', (chat_name, -1 * chat_id))
            conn.commit()

    elif len(command) == 2 and me.chat.type == 'private':
        chat_id = -1 * int(command[1])
        c.execute('''SELECT game_stop FROM admin_info''')
        game_stop_status = bool(c.fetchone()[0])

        if game_stop_status:
            await bot.send_message(user_id, "Создание и участие в играх пока что недоступно.")
            return
        c.execute(f'''SELECT is_in_game FROM chats WHERE chat_id = {chat_id}''')
        chat_status = c.fetchone()[0]

        if chat_status != IsInGameNow.ACTIVE:
            await bot.send_message(user_id, "Этот чат сейчас не набирает игроков.")
            return
        c.execute(F'''SELECT is_in_game FROM users WHERE user_id = {user_id}''')
        result = c.fetchone()[0]
        config = await load_config()
        if result != 0:
            await bot.send_message(user_id, config['already_in_game']['text'])
            return
        elif result == 0:
            c.execute(f'''UPDATE users SET is_in_game = {chat_id} WHERE user_id = {user_id}''')

        c.execute('''SELECT chat_name FROM chats WHERE chat_id = ?''', (chat_id,))
        chat_name = c.fetchone()[0]
        chat_name_for_insert = f'chat_{chat_id}'
        c.execute(F'''INSERT OR IGNORE INTO {chat_name_for_insert} (user_id, user_title) VALUES (?, ?)''',
                  (user_id, me.from_user.first_name))
        conn.commit()
        text = str(config['added_to_game']['text'])
        await bot.send_message(user_id, f'{text.format(chat_name=chat_name)}')


@bot.callback_query_handler(func=lambda call: call.data.startswith('open_'))
async def handle_card_open(call):
    data_parts = call.data.split('_')
    if len(data_parts) != 4:
        await bot.answer_callback_query(call.id, 'Ошибка: неправильные данные.', show_alert=True)
        return

    _, card_type, table_chat_id, _ = data_parts
    user_id = call.from_user.id
    config = await load_config()

    # Проверка существования таблицы
    table_name = f'chat_{str(table_chat_id)}'
    c.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';")
    if not c.fetchone():
        await bot.answer_callback_query(call.id, "Этот выбор карт уже недоступен", show_alert=True)
        return

    try:
        c.execute(f'''SELECT can_open FROM {table_name} WHERE user_id = ?''', (user_id,))
    except Exception:
        await bot.answer_callback_query(call.id, "Этот выбор карт уже недоступен", show_alert=True)
        return

    can_open_result = c.fetchone()
    if can_open_result is None or can_open_result[0] == 0:
        await bot.answer_callback_query(call.id, config['already_opened_card']['text'], show_alert=True)
        return

    await set_can_open(table_chat_id, False, user_id)
    c.execute(f'''SELECT {card_type}, {card_type}_on FROM {table_name} WHERE user_id = ?''', (user_id,))
    result = c.fetchone()

    if result is None or result[1] == 1:
        await bot.answer_callback_query(call.id, config['open_card_error']['text'], show_alert=True)
        return

    # Обновляем статус карты на открытый
    c.execute(f'''UPDATE {table_name} SET {card_type}_on = 1 WHERE user_id = ?''', (user_id,))
    conn.commit()

    card_name = card_name_translation.get(card_type, card_type)
    await bot.answer_callback_query(call.id, config['card_opened']['text'].format(card_name=card_name), show_alert=True)

    opened_cards, closed_cards = await check_cards(user_id, table_chat_id)

    # Текст для редактирования
    opened_text = "Открытые карты:\n" + "\n".join(
        [f"- {card_name_translation.get(card[0], card[0])}: {card[1][0]}" for card in opened_cards]
    )
    closed_text = "Закрытые карты:\n" + "\n".join(
        [f"- {card_name_translation.get(card[0], card[0])}: Скрыто" for card in closed_cards]
    )
    message_text = f"{config['card_opened']['text'].format(card_name=card_name)}\n\n{opened_text}\n\n{closed_text}"

    await bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                text=message_text, parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: call.data.startswith('voting_'))
async def call_voting(call):
    _, table_chat_id, voted_for_user_id, unique_number = call.data.split('_')
    user_id = call.from_user.id
    voted_for_user_id = int(voted_for_user_id)
    table_chat_id = int(table_chat_id)
    unique_number = int(unique_number)
    sqlite_table_name = f'voting_in_chat_{table_chat_id}_{unique_number}'

    config = await load_config()

    # Проверяем, существует ли таблица
    c.execute(f'''SELECT name FROM sqlite_master WHERE type="table" AND name="{sqlite_table_name}"''')
    result = c.fetchone()

    if result is None:
        await bot.answer_callback_query(call.id, config['voting_unavailable']['text'], show_alert=True)
        return

    # Проверяем, голосовал ли пользователь уже
    c.execute(f'''SELECT voter_id FROM {sqlite_table_name} WHERE voter_id = ?''', (user_id,))
    if c.fetchone() is not None:
        await bot.answer_callback_query(call.id, config['already_voted']['text'], show_alert=True)
        return

    # Записываем голос
    c.execute(f'''INSERT INTO {sqlite_table_name} (voter_id, "{voted_for_user_id}") VALUES (?, ?)''', (user_id, 1))
    conn.commit()

    vote_text = config["vote_registered"]["text"]

    await bot.answer_callback_query(call.id, vote_text, show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data in ["events"])
async def handle_shop_category(call):
    if call.data == "events":
        await show_events(call)
    await bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == 'start_game_now')
async def start_game_now_callback(call):
    chat_id = call.message.chat.id
    chat_id = str(chat_id).replace('-', '')
    table_chat_id = int(chat_id)
    safe_table_chat_id = f'chat_{table_chat_id}'
    c.execute('''SELECT game_stop FROM admin_info''')
    game_stop_status = c.fetchone()[0]

    if game_stop_status:
        await bot.answer_callback_query(call.id, "По решению администратора(ов) проведение игр временно недоступно.",
                                        show_alert=True)
        return
    c.execute(f'''SELECT COUNT(*) FROM {safe_table_chat_id}''')
    player_count = int(c.fetchone()[0])

    c.execute(f'''SELECT is_in_game FROM chats WHERE chat_id = {table_chat_id}''')
    chat_info = c.fetchone()[0]
    if chat_info != IsInGameNow.ACTIVE:
        await bot.answer_callback_query(call.id, "Эту игру нельзя начать.", show_alert=True)
        return

    if 4 <= player_count <= 16:
        # Меняем статус игры на "в игре"
        c.execute('''UPDATE chats SET is_in_game = ? WHERE chat_id = ?''', (IsInGameNow.IN_GAME, table_chat_id))
        conn.commit()

        who_started = create_user_link(call.from_user.id, call.from_user.first_name)
        chat_id = call.message.chat.id

        await bot.send_message(chat_id, f"Игра запущена досрочно пользователем {who_started}! 🎉", parse_mode='HTML')
        c.execute(f'''SELECT catastrophe FROM chats WHERE chat_id = ?''', (table_chat_id,))
        catastrophe = c.fetchone()[0]
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(current_dir, 'catastrophe_photos',
                                 f"{dictionaries.catastrophe[catastrophe]['image']}.jpg")
        with open(file_path, 'rb') as file:
            image_data = file.read()
        try:
            await bot.send_photo(chat_id, photo=image_data,
                                 caption=f"☠️ Набор игроков завершен. Большинство из {player_count} человек останутся умирать за пределами бункера\n"
                                         f"🌪️ Ужасный катаклизм настиг планету – {dictionaries.catastrophe[catastrophe]['name'].lower()}\n"
                                         f"{dictionaries.catastrophe[catastrophe]['description']}\n"
                                         f"Удачной игры")
        except Exception as e:
            await break_game(chat_id)
            return

        await bot.answer_callback_query(call.id)
        if player_count in [3, 4]:
            await rounds(0, 0, 1, 1, chat_id)
        elif player_count in [5, 6]:
            await rounds(0, 1, 1, 1, chat_id)
        elif player_count in [7, 8]:
            await rounds(1, 1, 1, 1, chat_id)
        elif player_count in [9, 10]:
            await rounds(1, 1, 1, 2, chat_id)
        elif player_count in [11, 12]:
            await rounds(1, 1, 2, 2, chat_id)
        elif player_count in [13, 14]:
            await rounds(1, 2, 2, 2, chat_id)
        elif player_count in [15, 16]:
            await rounds(2, 2, 2, 2, chat_id)
    else:
        await bot.answer_callback_query(call.id, "Недостаточно игроков для досрочного запуска (минимум 4).",
                                        show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith("end_discussion_"))
async def end_discussion_callback(call):
    data_parts = call.data.split("_")
    if len(data_parts) != 4:
        await bot.answer_callback_query(call.id, "Ошибка: неправильные данные.", show_alert=True)
        return
    user_name = call.from_user.first_name
    _, _, user_id, table_chat_id = data_parts
    user_id = int(user_id)
    table_chat_id = int(table_chat_id)

    # Проверяем, какой игрок нажал кнопку
    if call.from_user.id != user_id:
        await bot.answer_callback_query(call.id, "Эта кнопка не для вас!", show_alert=True)
        return

    # Проверяем, существует ли таблица
    c.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='chat_{table_chat_id}'")
    if c.fetchone() is None:
        await bot.answer_callback_query(call.id, "Ошибка: обсуждение уже завершено или игра не найдена.",
                                        show_alert=True)
        return

    # Обновляем статус игрока
    c.execute(f'''UPDATE chat_{table_chat_id} SET is_in_discussion = ? WHERE user_id = ?''',
              (Discussion.stop, user_id))
    conn.commit()

    # Уведомляем игрока и группу
    message = f'Игрок {user_name}, его открытые карты:\n'
    opened_cards, _ = await check_cards(user_id, table_chat_id)
    for card, result in opened_cards:
        card_name = card_name_translation.get(card, card).capitalize()  # Получаем название карты
        message += f'• {card_name}: {result[0]}\n'  # 0 - значение карты
    message += "Вы завершили обсуждение. Ждем следующего игрока."
    await bot.answer_callback_query(call.id, "Вы завершили обсуждение.")

    try:
        await bot.edit_message_text(chat_id=call.message.chat.id,
                                    message_id=call.message.message_id,
                                    text=message)
    except Exception as e:
        print(f"Ошибка при редактировании сообщения: {e}")


async def show_events(call):
    user_id = call.id
    await bot.answer_callback_query(user_id, "Команда пока что в разработке. Следите за новостями в нашем тгк",
                                    show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith("time_for_cards"))
async def change_cards(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    admins = await bot.get_chat_administrators(chat_id)
    is_admin = any(admin.user.id == user_id for admin in admins)

    if not is_admin:
        await bot.answer_callback_query(call.id, "Обратитесь к администратору чата для настроек", show_alert=True)
        return

    table_chat_id = -1 * chat_id
    _, _, _, time_for_discuss = call.data.split("_")
    time_for_discuss = int(time_for_discuss)
    message = "Настройка времени для обсуждения карт\n"
    if time_for_discuss == 0:
        c.execute(f"""SELECT discussion_time FROM chats WHERE chat_id = ?""", (table_chat_id,))
        time_for_discuss = c.fetchone()[0]
        time_for_discuss = int(time_for_discuss)
    else:
        c.execute(f"""UPDATE chats SET discussion_time = ? WHERE chat_id = ?""", (time_for_discuss, table_chat_id))
        conn.commit()
    message += f"Текущее время: {time_for_discuss} секунд\n"
    message += f"Поменять время можно используя кнопки снизу\n\n"
    markup = types.InlineKeyboardMarkup()
    if time_for_discuss < 75:
        markup.add(types.InlineKeyboardButton(text=f"{time_for_discuss + 15}", callback_data=f"time_for_cards_{time_for_discuss + 15}"))
    elif time_for_discuss > 285:
        markup.add(types.InlineKeyboardButton(text=f"{time_for_discuss - 15}", callback_data=f"time_for_cards_{time_for_discuss - 15}"))
    else:
        markup.add(types.InlineKeyboardButton(text=f"{time_for_discuss - 15}", callback_data=f"time_for_cards_{time_for_discuss - 15}"),
                   types.InlineKeyboardButton(text=f"{time_for_discuss + 15}", callback_data=f"time_for_cards_{time_for_discuss + 15}"))
    markup.add(types.InlineKeyboardButton(text="Назад к настройкам", callback_data="settings"))
    await bot.edit_message_text(message, chat_id, call.message.id, parse_mode='HTML', reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("time_for_open_cards"))
async def change_cards(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    admins = await bot.get_chat_administrators(chat_id)
    is_admin = any(admin.user.id == user_id for admin in admins)

    if not is_admin:
        await bot.answer_callback_query(call.id, "Обратитесь к администратору чата для настроек", show_alert=True)
        return

    table_chat_id = -1 * chat_id
    _, _, _, _, time_for_open = call.data.split("_")
    time_for_open = int(time_for_open)
    message = "Настройка времени для открытия карт\n"
    if time_for_open == 0:
        c.execute(f"""SELECT open_time FROM chats WHERE chat_id = ?""", (table_chat_id,))
        time_for_open = c.fetchone()[0]
        time_for_open = int(time_for_open)
    else:
        c.execute(f"""UPDATE chats SET open_time = ? WHERE chat_id = ?""", (time_for_open, table_chat_id))
        conn.commit()
    message += f"Текущее время: {time_for_open} секунд\n\n"
    message += f"Поменять время можно используя кнопки снизу\n"
    markup = types.InlineKeyboardMarkup()
    if time_for_open < 45:
        markup.add(types.InlineKeyboardButton(text=f"{time_for_open + 15}", callback_data=f"time_for_open_cards_{time_for_open + 15}"))
    elif time_for_open > 105:
        markup.add(types.InlineKeyboardButton(text=f"{time_for_open - 15}", callback_data=f"time_for_open_cards_{time_for_open - 15}"))
    else:
        markup.add(types.InlineKeyboardButton(text=f"{time_for_open - 15}", callback_data=f"time_for_open_cards_{time_for_open - 15}"),
                   types.InlineKeyboardButton(text=f"{time_for_open + 15}", callback_data=f"time_for_open_cards_{time_for_open + 15}"))
    markup.add(types.InlineKeyboardButton(text="Назад к настройкам", callback_data="settings"))
    await bot.edit_message_text(message, chat_id, call.message.id, parse_mode='HTML', reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("time_for_voting"))
async def change_voting_time(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    admins = await bot.get_chat_administrators(chat_id)
    is_admin = any(admin.user.id == user_id for admin in admins)

    if not is_admin:
        await bot.answer_callback_query(call.id, "Обратитесь к администратору чата для настройки", show_alert=True)
        return

    table_chat_id = -1 * chat_id
    _, _, _, time_for_voting = call.data.split("_")
    time_for_voting = int(time_for_voting)

    message = "Настройка времени для голосования\n"
    if time_for_voting == 0:
        c.execute(f"""SELECT voting_time FROM chats WHERE chat_id = ?""", (table_chat_id,))
        time_for_voting = int(c.fetchone()[0])
    else:
        c.execute(f"""UPDATE chats SET voting_time = ? WHERE chat_id = ?""", (time_for_voting, table_chat_id))
        conn.commit()

    message += f"Текущее время: {time_for_voting} секунд\n\n"
    message += f"Поменять время можно используя кнопки снизу\n"

    markup = types.InlineKeyboardMarkup()
    if time_for_voting < 45:
        markup.add(types.InlineKeyboardButton(text=f"{time_for_voting + 15}",
                                              callback_data=f"time_for_voting_{time_for_voting + 15}"))
    elif time_for_voting > 165:
        markup.add(types.InlineKeyboardButton(text=f"{time_for_voting - 15}",
                                              callback_data=f"time_for_voting_{time_for_voting - 15}"))
    else:
        markup.add(types.InlineKeyboardButton(text=f"{time_for_voting - 15}",
                                              callback_data=f"time_for_voting_{time_for_voting - 15}"),
                   types.InlineKeyboardButton(text=f"{time_for_voting + 15}",
                                              callback_data=f"time_for_voting_{time_for_voting + 15}"))
    markup.add(types.InlineKeyboardButton(text="Назад к настройкам", callback_data="settings"))


    await bot.edit_message_text(message, chat_id, call.message.id, parse_mode='HTML', reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "reset_settings")
async def reset_settings(call):
    user_id = call.from_user.id
    user_name = call.from_user.first_name
    chat_id = call.message.chat.id
    table_chat_id = -1 * chat_id
    admins = await bot.get_chat_administrators(chat_id)
    is_admin = any(admin.user.id == user_id for admin in admins)

    if not is_admin:
        await bot.answer_callback_query(call.id, "Обратитесь к администратору чата для настройки", show_alert=True)
        return

    discussion_time = 60
    open_time = 60
    voting_time = 60
    message = (f"Настройки успешно обновлены пользователем {create_user_link(user_id, user_name)}. Текущие настройки:\n"
               f"Время на обсуждение игроками своих карт: {discussion_time}\n"
               f"Время на вскрытие карт: {open_time}\n"
               f"Время на голосование: {voting_time}\n"
               f"Сейчас бот удаляет сообщения от других игроков")
    try:
        c.execute(f"""UPDATE chats SET discussion_time = ?, open_time = ?, voting_time = ?, delete_message = ? WHERE chat_id = ?""",
                  (discussion_time, open_time, voting_time, True, table_chat_id))
        conn.commit()
    except Exception:
        await bot.send_message(chat_id, "Что-то пошло не по плану...")
        return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="Назад к настройкам", callback_data="settings"))
    await bot.edit_message_text(message, chat_id, call.message.id, parse_mode='HTML', reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_message_"))
async def needed_to_delete_message(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    admins = await bot.get_chat_administrators(chat_id)
    is_admin = any(admin.user.id == user_id for admin in admins)

    if not is_admin:
        await bot.answer_callback_query(call.id, "Обратитесь к администратору чата для настройки", show_alert=True)
        return

    table_chat_id = -1 * chat_id
    _, _, delete_message = call.data.split("_")
    delete_message = bool(int(delete_message))

    c.execute(f"""SELECT delete_message FROM chats WHERE chat_id = ?""", (table_chat_id,))
    result = bool(int(c.fetchone()[0]))

    if delete_message:

        for_update = not result
        c.execute(f"""UPDATE chats SET delete_message = ?""", (for_update,))
        conn.commit()
        if not for_update:
            message = "Теперь бот не удаляет сообщения от выбывших игроков"
        else:
            message = "Теперь бот удаляет сообщения от выбывших игроков"
    else:
        if result:
            message = "Сейчас бот удаляет сообщения от других игроков."
        else:
            message = "Сейчас бот не удаляет сообщения от других игроков"
    message += "\n\nСменить можно по кнопке ниже"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="Сменить режим удаления", callback_data="delete_message_1"))
    markup.add(types.InlineKeyboardButton(text="Назад к настройкам", callback_data="settings"))
    await bot.edit_message_text(message, chat_id, call.message.id, parse_mode='HTML', reply_markup=markup)




@bot.message_handler(commands=['new_game'])
async def start_new_game(me):
    if me.chat.type == 'private':
        return
    user_id = me.from_user.id
    if await is_banned(user_id) is True:
        return
    try:
        _, count_players = str(me.text).split(' ')
        count_players = int(count_players)
    except Exception:
        count_players = 8
    if count_players < 4 or count_players > 16:
        await bot.send_message(me.chat.id, f'🚫 Игра с количеством игроков {count_players} недоступна.')
        return
    chat_id = me.chat.id
    safe_chat_id = str(chat_id * -1)
    c.execute('''SELECT is_in_game FROM chats WHERE chat_id = ?''', (safe_chat_id,))
    try:
        result = c.fetchone()[0]
    except Exception:
        result = IsInGameNow.INACTIVE
    if result == IsInGameNow.IN_GAME:
        await bot.send_message(chat_id,
                               '⚠️ Игра уже запущена. Ожидайте конца текущей игры или удалите её и начните заново, '
                               'используя команду /stop_game.')
        return
    elif result == IsInGameNow.ACTIVE:
        await bot.send_message(chat_id, '⏳ Вы уже запустили набор игроков. Ожидайте, пока другие присоединятся, '
                                        'либо остановите игру командой /stop_game')
        return
    else:
        # Проверяем, остановлены ли игры
        c.execute('''SELECT game_stop FROM admin_info''')
        game_stop_status = c.fetchone()[0]

        if game_stop_status:
            await bot.send_message(me.chat.id, "По решению администратора(ов) проведение игр временно недоступно.")
            return
        bot_id = (await bot.get_me()).id
        chat_member = await bot.get_chat_member(chat_id, bot_id)
        if not chat_member.can_delete_messages or not chat_member.can_restrict_members:
            await bot.send_message(chat_id,
                                   '❗️ У меня недостаточно прав для проведения игры. Убедитесь, что у меня есть права '
                                   'администратора, включая удаление сообщений и ограничение участников.')
            return
        # Обновляем статус игры
        c.execute('''UPDATE chats SET is_in_game = ? WHERE chat_id = ?''',
                  (IsInGameNow.ACTIVE, safe_chat_id))
        conn.commit()

    catastrophe = random.randint(1, len(dictionaries.catastrophe))
    safe_chat_id = f'chat_{safe_chat_id}'
    c.execute(f'''DROP TABLE IF EXISTS {safe_chat_id}''')
    c.execute(f'''CREATE TABLE IF NOT EXISTS {safe_chat_id} (
        user_id INTEGER PRIMARY KEY,
        user_title TEXT NOT NULL,
        baggage INTEGER DEFAULT 0,
        baggage_on BOOLEAN DEFAULT False,
        health INTEGER DEFAULT 0,
        health_on BOOLEAN DEFAULT False,
        profession INTEGER DEFAULT 0,
        profession_on BOOLEAN DEFAULT True,
        facts INTEGER DEFAULT 0,
        facts_on BOOLEAN DEFAULT False,
        hobby INTEGER DEFAULT 0,
        hobby_on BOOLEAN DEFAULT False,
        biology INTEGER DEFAULT 0,
        biology_on BOOLEAN DEFAULT False,
        skills INTEGER DEFAULT 0,
        skills_on BOOLEAN DEFAULT False,
        is_alive BOOLEAN DEFAULT True,
        can_open BOOLEAN DEFAULT False,
        is_in_discussion TEXT DEFAULT "{Discussion.not_in_discussion}"
    )''')
    conn.commit()
    safe_chat_id = chat_id * -1
    c.execute(F'''UPDATE chats SET catastrophe = ? WHERE chat_id = ?''', (catastrophe, safe_chat_id))
    conn.commit()
    markup_start_game = types.InlineKeyboardMarkup()
    markup_start_game.add(types.InlineKeyboardButton(text='Начать игру досрочно', callback_data='start_game_now'))
    link = create_referral_chat_link(chat_id)
    markup_start_game.add(types.InlineKeyboardButton(text='Присоединиться к игре', url=link))

    # Уведомление
    catastrophe_name = dictionaries.catastrophe[catastrophe]['name']
    start_message = (
            "🚀 Идёт набор игроков\n\n"
            "🌪 Над миром нависла ужасающая катастрофа  – " + catastrophe_name.lower() + "\n"
                                                                                        "🎭 Ожидаемое количество игроков: " + str(count_players) + "\n\n"
    )

    last_send_message = await bot.send_message(chat_id=chat_id, text=start_message, reply_markup=markup_start_game)

    await game(me, last_send_message.id, last_send_message, count_players, markup_start_game)


async def game(me, last_message_sended, last_message, count_players, markup):
    chat_id = me.chat.id
    table_chat_id = int(chat_id) * -1

    last_message_text = last_message.text

    c.execute(f'''SELECT COUNT(*) FROM chat_{table_chat_id}''')
    result = int(c.fetchone()[0])

    remaining_time = 300

    last_message_text = f"{last_message_text}\nПрисоединившиеся: \n"
    new_text = last_message_text
    all_players = []
    try:
        c.execute(f'''SELECT user_id, user_title FROM chat_{table_chat_id}''')
        all_players = c.fetchall()
    except Exception:
        pass
    for player in all_players:
        user_id, user_name = player
        new_text = new_text + create_user_link(user_id, user_name) + '\n'

    c.execute(f'''SELECT is_in_game FROM chats WHERE chat_id = {table_chat_id}''')
    chat_info = c.fetchone()[0]

    while result < count_players and remaining_time > 0 and chat_info == IsInGameNow.ACTIVE:
        try:
            await bot.edit_message_text(new_text, chat_id, last_message_sended, parse_mode='HTML', reply_markup=markup)
        except Exception:
            pass

        c.execute(f'''SELECT is_in_game FROM chats WHERE chat_id = {table_chat_id}''')
        zzz = c.fetchone()
        if zzz is not None:
            chat_info = zzz[0]

        await asyncio.sleep(3)
        remaining_time -= 3

        c.execute(f'''SELECT COUNT(*) FROM chat_{table_chat_id}''')
        result = int(c.fetchone()[0])
        try:
            c.execute(f'''SELECT user_id, user_title FROM chat_{table_chat_id}''')
            all_players = c.fetchall()
            new_text = last_message_text
            for player in all_players:
                user_id, user_name = player
                new_text = new_text + create_user_link(user_id, user_name) + '\n'
        except Exception:
            pass

    if remaining_time <= 0:
        await break_game(chat_id)
        await bot.edit_message_text('Игра была отменена из-за истечения времени ожидания.', chat_id,
                                    last_message_sended)
        return

    c.execute(f'''SELECT is_in_game FROM chats WHERE chat_id = ?''', (table_chat_id,))
    chat_info = str(c.fetchone()[0])

    if chat_info == IsInGameNow.INACTIVE:
        await bot.edit_message_text('Игра была отменена', chat_id, last_message_sended)
        return
    elif chat_info == IsInGameNow.IN_GAME:
        return
    elif chat_info == IsInGameNow.ACTIVE:
        chat_info = IsInGameNow.IN_GAME
        c.execute('''UPDATE chats SET is_in_game = ? WHERE chat_id = ?''', (chat_info, table_chat_id))

        c.execute(f'''SELECT catastrophe FROM chats WHERE chat_id = ?''', (table_chat_id,))
        catastrophe = c.fetchone()[0]
        current_dir = os.getcwd()
        file_path = os.path.join(
            current_dir,
            'catastrophe_photos',
            f"{dictionaries.catastrophe[catastrophe]['image']}.jpg"
        )
        with open(file_path, 'rb') as file:  # Открытие в бинарном режиме для изображений
            image_data = file.read()
        try:
            await bot.send_photo(chat_id, photo=image_data,
                                 caption=f"☠️ Набор игроков завершен. Большинство из {count_players} человек останутся умирать за пределами бункера\n"
                                         f"🌪️ Ужасный катаклизм настиг планету – {dictionaries.catastrophe[catastrophe]['name'].lower()}\n"
                                         f"{dictionaries.catastrophe[catastrophe]['description']}\n"
                                         f"Готовьтесь к борьбе за выживание! 💪")
        except Exception:
            await break_game(chat_id)
            return

    c.execute(f'''SELECT user_id, user_title FROM chat_{table_chat_id}''')
    all_players = c.fetchall()
    new_text = last_message_text
    for player in all_players:
        user_id, user_name = player
        new_text = new_text + create_user_link(user_id, user_name) + '\n'
        try:
            await bot.edit_message_text(new_text, chat_id, last_message_sended, parse_mode='HTML', reply_markup=markup)
        except Exception:
            pass
    if result < 4:
        c.execute(f'''DROP TABLE IF EXISTS chat_{table_chat_id}''')
        return
    if result in [4]:
        await rounds(0, 0, 1, 1, chat_id)
    elif result in [5, 6]:
        await rounds(0, 1, 1, 1, chat_id)
    elif result in [7, 8]:
        await rounds(1, 1, 1, 1, chat_id)
    elif result in [9, 10]:
        await rounds(1, 1, 1, 2, chat_id)
    elif result in [11, 12]:
        await rounds(1, 1, 2, 2, chat_id)
    elif result in [13, 14]:
        await rounds(1, 2, 2, 2, chat_id)
    elif result in [15, 16]:
        await rounds(2, 2, 2, 2, chat_id)


async def rounds(round_1, round_2, round_3, round_4, chat_id: int):
    x = await which_chat_with_logs()
    await bot.send_message(x, f'🏁 В чате {chat_id} началась новая игра!')
    table_chat_id = -1 * chat_id
    c.execute(f'''SELECT user_id FROM chat_{table_chat_id}''')
    list_of_ids = c.fetchall()

    for user_id_tuple in list_of_ids:
        user_id = int(user_id_tuple[0])
        await cards(user_id, chat_id)
        c.execute('''UPDATE users SET games_played = games_played + 1 WHERE user_id = ?''', (user_id,))
        conn.commit()


    rounds_data = [round_1, round_2, round_3, round_4]
    for round_count in rounds_data:
        if round_count > 0:  # Проверяем, нужно ли проводить раунд
            if await is_game_active(table_chat_id) is False:
                return
            lives = await is_alive(table_chat_id)

            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton('Перейти к боту', url='https://t.me/bunkerbe_bot'))
            players_alive = ""
            i = 1
            for user in lives:
                user_id = user[0]
                user_name = user[1]
                players_alive += f"{str(i)}. {create_user_link(user_id, user_name)}\n"
                i += 1
            try:
                await bot.send_message(chat_id, f"Пришло время вскрыть свои карты. В бункере остались:\n"
                                                f"{players_alive}"
                                                f"Выберите карту которая поможет вам попасть внутрь.\n"
                                                f"Потом вам предстоит доказать остальным что именно вы достойны места в бункере.",
                                       reply_markup=markup, parse_mode='HTML')
            except Exception:
                await break_game(chat_id)
                return
            await set_can_open(table_chat_id, True, None)
            for user in lives:
                user_id = user[0]
                user_name = user[1]
                await open_some_card(table_chat_id, True, user_id, user_name)

            c.execute(f'''SELECT open_time FROM chats WHERE chat_id = ?''', (table_chat_id, ))
            open_time = int(c.fetchone()[0])

            await asyncio.sleep(open_time)

            if await is_game_active(table_chat_id) is False:
                return

            for user in lives:
                user_id = user[0]
                c.execute(f'''SELECT can_open FROM chat_{table_chat_id} WHERE user_id = {user_id}''')
                result = bool(c.fetchone()[0])
                if result is True:
                    await open_random_card(user_id, table_chat_id)

            await about_players(chat_id)

            for _ in range(round_count):
                if await is_game_active(table_chat_id) is False:
                    return
                await voting(chat_id, table_chat_id)
    lives = await is_alive(table_chat_id)
    user_ids_to_reset = [user[0] for user in lives] + [user[0] for user in await is_dead(table_chat_id)]
    await reset_player_status(user_ids_to_reset)
    message_text = (
        f"⚰️ <b>Те, кто прошёл в бункер:</b>\n\n"
    )

    for user_id, user_name in lives:
        user_id = int(user_id)
        c.execute('''UPDATE users SET win_games = win_games + 1, points = points + 10 WHERE user_id = ?''', (user_id,))
        conn.commit()
        new_user = create_user_link(user_id, user_name)
        message_text += f"• {new_user}\n"
    c.execute(f'''DROP TABLE chat_{table_chat_id}''')
    conn.commit()
    c.execute(f'''UPDATE chats SET is_in_game = "{IsInGameNow.INACTIVE}" WHERE chat_id = {table_chat_id}''')
    conn.commit()
    message_text += (
        f"⚡️ <b>Поздравляем выживших.</b> Но помните: выжить — это только начало. Теперь вам предстоит столкнуться с кошмарами нового мира. Вы пожалеете, что остались в живых.\n\n"
        f"💀 <b>Бункер не спасёт вас от ада, который ждёт снаружи.</b>"
    )

    try:
        await bot.send_message(chat_id, message_text, parse_mode='HTML')
    except Exception as e:
        print(f"Ошибка при отправке сообщения: {e}")  # Логируем ошибку для отладки


async def voting(chat_id, table_chat_id):
    lives = await is_alive(table_chat_id)
    number_for_unique_dictionary = random.randint(0, 1000000000)
    sqlite_table_name = f'voting_in_chat_{table_chat_id}_{number_for_unique_dictionary}'

    markup = types.InlineKeyboardMarkup()

    c.execute(f'''CREATE TABLE IF NOT EXISTS {sqlite_table_name} (voter_id INTEGER)''')  # Колонка для ID голосующего
    for user in lives:
        user_id = user[0]
        c.execute(f'ALTER TABLE {sqlite_table_name} ADD COLUMN "{user_id}" INTEGER DEFAULT 0')

    markup.add(types.InlineKeyboardButton('Перейти к голосованию', url='https://t.me/bunkerbe_bot'))
    try:
        photo_filename = 'voting.jpg'
        photo_path = os.path.join("gifs", photo_filename)
        photo = open(photo_path, 'rb')

        await bot.send_photo(chat_id, photo=photo,
                                 caption='Время вышло. Выбирайте жертву которая останется за пределами бункера',
                                 reply_markup=markup)
    except Exception:
        await break_game(chat_id)
        return
    # Создаем кнопки и отправляем соо
    for user in lives:
        user_id = user[0]
        user_title = user[1]
        markup = types.InlineKeyboardMarkup()
        for voted_user in lives:
            voted_user_id = voted_user[0]
            voted_user_title = voted_user[1]
            markup.add(types.InlineKeyboardButton(f'Голос за {voted_user_title}',
                                                  callback_data=f'voting_{table_chat_id}_'
                                                                f'{voted_user_id}_{number_for_unique_dictionary}'))

        try:
            await bot.send_message(user_id, f'{user_title}, выберите кого вы хотите выгнать в этом раунде:',
                                   reply_markup=markup)
        except Exception:
            pass

    c.execute(f"""SELECT voting_time FROM chats WHERE chat_id = ?""", (table_chat_id,))
    voting_time = int(c.fetchone()[0])

    await asyncio.sleep(voting_time)

    # Подсчитываем голоса
    voting_results = {}
    for user in lives:
        user_id = user[0]
        c.execute(f'''SELECT COUNT(*) FROM {sqlite_table_name} WHERE "{user_id}" = 1''')  # Используем COUNT
        votes_count = c.fetchone()[0]
        voting_results[user_id] = {"name": user[1], "votes": votes_count}

    # Определяем, кого исключить
    max_votes = 0
    players_with_max_votes = []
    all_users = []

    for user_id, data in voting_results.items():
        all_users.append(user_id)
        if data["votes"] > max_votes:
            max_votes = data["votes"]
            players_with_max_votes = [user_id]
        elif data["votes"] == max_votes:
            players_with_max_votes.append(user_id)

    if len(voting_results) == 0:
        kicked_player_id = random.choice(all_users)
    elif len(players_with_max_votes) > 1:
        kicked_player_id = random.choice(players_with_max_votes)
    else:
        kicked_player_id = players_with_max_votes[0]

    # Кикаем игрока из бд
    c.execute(f'''UPDATE chat_{table_chat_id} SET is_alive = False WHERE user_id = ?''', (kicked_player_id,))
    conn.commit()

    photo_filename = 'kick.jpg'
    photo_path = os.path.join("gifs", photo_filename)
    photo = open(photo_path, 'rb')

    # Отправляем сообщение исключенному игроку
    try:
        await bot.send_photo(kicked_player_id, photo=photo, caption="Извини, но для тебя места не нашлось, может как-нибудь в другой раз...")
    except Exception as e:
        print(f"Ошибка отправки личного сообщения: {e}")
    # Сообщаем о результатах
    c.execute(f'''SELECT user_title FROM chat_{table_chat_id} WHERE user_id = ?''', (kicked_player_id,))
    result = c.fetchone()

    kicked_player_name = result[0]

    all_cards = await get_all_cards(kicked_player_id, table_chat_id)

    opened_text = ""

    # Текст для редактирования
    for card_type, card_value in zip(user_cards, all_cards):
        card_name = card_name_translation.get(card_type, card_type).capitalize()  # Получаем название карты
        opened_text += f"- {card_name}: {card_value}\n"


    photo = open(photo_path, 'rb')
    if len(voting_results) == 0:
        try:
            await bot.send_photo(chat_id, photo=photo, caption=f'⚠️ Вы так и не пришли к решению, '
                                                               f'так что мы убьём: {create_user_link(kicked_player_id, kicked_player_name)}.\n'
                                                               f'Его карты: \n{opened_text}', parse_mode='HTML')
        except Exception:
            await break_game(chat_id)
            return
    else:
        try:
            await bot.send_photo(chat_id, photo=photo,
                                 caption=f'По итогам обсуждения из бункера был выгнан {create_user_link(kicked_player_id, kicked_player_name)}.\n'
                                 f'Его карты: \n{opened_text}', parse_mode='HTML')
        except Exception:
            await break_game(chat_id)
            return

    # Удаляем таблицу голосования
    c.execute(f'''DROP TABLE {sqlite_table_name}''')
    conn.commit()


async def about_players(chat_id):
    table_chat_id = chat_id * (-1)
    players = await is_alive(table_chat_id)
    for user_id, user_name in players:

        if await is_game_active(table_chat_id) is False:
            return

        opened_cards, closed_cards = await check_cards(user_id, table_chat_id)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="Завершить рассказ",
                                              callback_data=f"end_discussion_{user_id}_{table_chat_id}"))
        message = f'Игрок {user_name}, его открытые карты:\n'
        for card, result in opened_cards:
            card_name = card_name_translation.get(card, card).capitalize()  # Получаем название карты
            message += f'• {card_name}: {result[0]}\n'  # 0 - это значение карты

        c.execute(
            f"""UPDATE chat_{table_chat_id} SET is_in_discussion = "{Discussion.in_discussion}" WHERE user_id = {user_id}""")
        conn.commit()
        c.execute(f"""SELECT discussion_time FROM chats WHERE chat_id = {table_chat_id}""")
        timer = int(c.fetchone()[0])
        message += f"У вас есть {timer} секунд, чтобы отстоять своё право на место в бункере."
        # Теперь каждый игрок будет рассказывать о себе
        try:
            await bot.send_message(chat_id, message, reply_markup=markup)
        except Exception:
            await break_game(chat_id)
            return
        c.execute(f"""SELECT is_in_discussion FROM chat_{table_chat_id} WHERE user_id = {user_id}""")
        status = c.fetchone()[0]
        while timer > 0 and status != Discussion.stop:
            await asyncio.sleep(1)
            timer -= 1
            c.execute(f"""SELECT is_in_discussion FROM chat_{table_chat_id} WHERE user_id = {user_id}""")
            status = str(c.fetchone()[0])
        c.execute(
            f"""UPDATE chat_{table_chat_id} SET is_in_discussion = "{Discussion.not_in_discussion}" WHERE user_id = {user_id}""")
        conn.commit()


async def open_some_card(table_chat_id, is_opened: bool, user_id, user_name):
    # Смотрим карты пользователя
    opened_cards, closed_cards = await check_cards(user_id, table_chat_id)

    text_opened_cards = ''
    text_closed_cards = ''

    if opened_cards:
        for card, result in opened_cards:
            card_name = card_name_translation.get(card, card).capitalize()  # Получаем русское название
            text_opened_cards += f"- {card_name}: {result[0]}\n"  # Добавляем значение карты

    markup = types.InlineKeyboardMarkup()
    config = await load_config()
    if closed_cards:  # Если есть закрытые карты
        for card, result in closed_cards:
            card_name = card_name_translation.get(card, card).capitalize()
            if is_opened:
                reply_markup = config['choose_card_to_open']['reply_markup']
                button = types.InlineKeyboardButton(text=str(reply_markup['text']).format(card_name=card_name),
                                                    callback_data=str(reply_markup['callback_data']).format(
                                                        card_type=card, table_chat_id=table_chat_id, user_id=user_id))
                markup.add(button)
            text_closed_cards += f"- {card_name}: {result[0]}\n"
        # Отправляем сообщение с кнопками
        try:
            message_text = str(config['choose_card_to_open']['text']).format(user_name=user_name,
                                                                             opened_cards=text_opened_cards,
                                                                             closed_cards=text_closed_cards)
            await bot.send_message(user_id, message_text, reply_markup=markup, parse_mode='HTML')
        except Exception:
            pass
    else:
        try:
            await bot.send_message(user_id, str(config['all_cards_opened']['text']).format(user_name=user_name))
        except Exception:
            pass


@bot.message_handler(commands="leave")
async def leave(me):
    user_id = me.from_user.id
    if await is_banned(user_id) is True:
        return
    c.execute(f'''SELECT is_in_game FROM users WHERE user_id = {user_id}''')
    chat_id = c.fetchone()
    if chat_id is None or int(chat_id[0]) == 0:
        await bot.send_message(me.chat.id, "Вы не состоите ни в какой игре")
        return
    chat_id = int(chat_id[0])
    c.execute(f'''SELECT is_in_game FROM chats WHERE chat_id = {chat_id}''')
    is_wait_for_new_players = c.fetchone()
    if is_wait_for_new_players is None:
        await bot.send_message(me.chat.id,
                               "Произошла какая-то ошибка... Если вы видите это сообщение, то напишите в наш чат поддержки")
        return
    if is_wait_for_new_players[0] != IsInGameNow.ACTIVE:
        if is_wait_for_new_players[0] == IsInGameNow.IN_GAME:
            await bot.send_message(me.chat.id, "Вы не можете выйти из игры которая уже началась")
            return
        elif is_wait_for_new_players[0] == IsInGameNow.INACTIVE:
            await bot.send_message(me.chat.id,
                                   "Произошла какая-то ошибка... Если вы видите это сообщение, то напишите в наш чат поддержки")
            return
    elif is_wait_for_new_players[0] == IsInGameNow.ACTIVE:
        c.execute(f'''DELETE FROM chat_{chat_id} WHERE user_id = {user_id}''')
        conn.commit()
        c.execute(f'''UPDATE users SET is_in_game = 0 WHERE user_id = {user_id}''')
        conn.commit()
        await bot.send_message(me.chat.id, "Вы успешно покинули игру")


@bot.message_handler(content_types=['new_chat_members'])
async def mi(message):
    for new_member in message.new_chat_members:
        if new_member.id == 7790371742:
            chat_id = message.chat.id
            print(chat_id)
            chat_name = message.chat.title
            c.execute(f'''INSERT OR IGNORE INTO chats (chat_id, is_in_game, chat_name) VALUES (?, ?, ?)''',
                      (-1 * chat_id, IsInGameNow.INACTIVE, chat_name))
            conn.commit()
            welcome_message = (
                "<b>👋 Добро пожаловать в БУНКЕР!</b>\n\n"
                "🌍 Здесь начинается ваше путешествие через руины мира, где выживание — единственный закон. Вас ждёт суровая борьба за место под защитой нашего укрытия. Но будьте осторожны — каждый шаг может оказаться последним...\n\n"
                "<b>🎮 Правила игры:</b>\n"
                "1. Ваша цель — выжить и занять одно из немногих мест в нашем бункере.\n"
                "2. В игре участвуют от 4 до 16 человек.\n"
                "3. Каждому игроку выдаётся уникальная карточка с особыми навыками и характеристиками.\n"
                "4. Используйте свои навыки и убеждения, чтобы убедить остальных, что именно вы заслуживаете остаться.\n"
                "5. Голосование решит судьбу каждого участника... Кто же останется в живых?\n\n"
                "🔥 Готовьтесь к борьбе за жизнь! Команда /new_game запустит новую партию, а команда /help предоставит дополнительную информацию."
            )

            await bot.send_message(chat_id, welcome_message, parse_mode="HTML")
            x = await which_chat_with_logs()
            await bot.send_message(x, f'Бот был добавлен в чат {message.chat.title}')


async def about_user(user_id, table_chat_id):
    c.execute(f'''SELECT user_title, baggage, baggage_on, health, health_on,
                  facts, facts_on, hobby, hobby_on, profession, biology, biology_on
                  FROM chat_{table_chat_id} WHERE user_id = ?''', (user_id,))
    user_data = c.fetchone()
    user_name, *card_data = user_data

    message_text = f"*Информация о игроке {user_name}:*\n\n"

    for i in range(0, len(card_data), 2):
        card_type = ['baggage', 'health', 'facts', 'hobby', 'profession', 'biology'][i // 2]  # Добавили biology
        card_value = card_data[i]
        card_open = card_data[i + 1]

        card_name = card_name_translation.get(card_type, card_type).capitalize()
        if card_open:
            message_text += f"• *{card_name}:* {card_value}\n"
        else:
            message_text += f"• *{card_name}:* Закрыто\n"

    try:
        await bot.send_message(chat_id, message_text)
    except Exception:
        await break_game(table_chat_id * (-1))
        return


async def cards(user_id, chat_id):
    table_chat_id = int(chat_id) * (-1)

    baggage = dictionaries.baggage[random.randint(1, len(dictionaries.baggage))]
    health = dictionaries.health[random.randint(1, len(dictionaries.health))]
    facts = dictionaries.facts[random.randint(1, len(dictionaries.facts))]
    profession = dictionaries.profession[random.randint(1, len(dictionaries.profession))]
    hobby = dictionaries.hobby[random.randint(1, len(dictionaries.hobby))]
    biology = dictionaries.biology[random.randint(1, len(dictionaries.biology))]  # Добавили biology
    skills = dictionaries.skills[random.randint(1, len(dictionaries.skills))]

    c.execute(
        f'''UPDATE chat_{table_chat_id} SET baggage = ?, health = ?, facts = ?, profession = ?, hobby = ?, biology = ?, skills = ?
        WHERE user_id = ?''', (baggage, health, facts, profession, hobby, biology, skills, user_id))
    conn.commit()
    gif_filename = 'in_bunker.gif'
    gif_path = os.path.join("gifs", gif_filename)
    gif = open(gif_path, 'rb')
    message = f'Ваши карты: \n'\
              f'Багаж - {baggage}\nСостояние здоровья - {health}\nНавык - {skills}\n'\
              f'Факт - {facts}\nПрофессия - {profession}\nХобби - {hobby}\nБиология - {biology}'
    await bot.send_animation(user_id, animation=gif, caption=message)


@bot.message_handler(commands=['rules'])
async def send_rules(message):
    rules_text = (
        "ПРАВИЛА ИГРЫ 'БУНКЕР' В TELEGRAM\n\n"
        "Цель игры:\n"
        "Выжить в условиях пост-апокалипсиса, убедив остальных участников, что вы достойны места в бункере.\n\n"

        "Количество участников:\n"
        "От 4 до 16 игроков.\n\n"

        "Подготовка:\n"
        "1. Каждый игрок присоединяется к игре через команду /new_game в групповом чате.\n"
        "2. Бот назначает роли игрокам и предоставляет карточки персонажей, содержащие информацию о профессии, "
        "здоровье и других характеристиках.\n"
        "3. Ведущий - бот, предоставляет описание катастрофы, с которой предстоит столкнуться игрокам.\n\n"

        "Игровой процесс:\n"
        "1. Игроки по очереди открывают свои карточки или части информации о своих персонажах, выбирая карты с помощью "
        "кнопок.\n"
        "2. Каждый игрок аргументирует, почему именно он должен попасть в бункер, используя данные о своем персонаже.\n"
        "3. Игроки могут задавать друг другу вопросы, чтобы выяснить подробности и понять кто заслуживает жить.\n"
        "4. По итогам обсуждений проводится голосование, в котором участники решают, кто должен покинуть игру. Тот, кто"
        " набирает больше всего голосов, выбывает.\n"
        "5. Повторение шагов 1-4, пока не останется нужное количество игроков для бункера.\n\n"

        "Конец игры:\n"
        "Игра заканчивается, когда остаётся заданное количество игроков, которые считаются выжившими и попавшими в "
        "бункер.\n\n"

        "Команды для игры:\n"
        "- /start — Начать взаимодействие с ботом.\n"
        "- /new_game [количество игроков] — Запустить новую игру.\n"
        "- /stop_game — Остановить текущую игру.\n"
        "- /help — Показать доступные команды и их описание.\n\n"

        "Примечание:\n"
        "Эти правила могут быть адаптированы под предпочтения игроков. Наслаждайтесь игрой и удачи в выживании!"
    )
    await bot.send_message(message.chat.id, rules_text)


@bot.message_handler(commands=['help'])
async def help_command(message):
    help_text = (
        "Привет! Вот список команд, которые вы можете использовать:\n\n"
        "/start - Начать взаимодействие с ботом.\n"
        "/new_game [количество игроков] - Запустить новую игру. Можно указать количество участников (от 4 до 16).\n"
        "/stop_game - Остановить текущую игру.\n"
        "/rules - Показать правила игры.\n"
        "/profile - Посмотреть свой профиль с информацией об играх и очках.\n"
        "/settings - Открыть настройки чата.\n"
        "/shop - Открыть магазин, где можно приобрести события для игры. (Пока что в разработке)\n"
        "/about_update - Посмотреть информацию про последнее обновление\n"
        "/help - Показать это сообщение с полным списком команд.\n\n"
        "\nКанал с новостями про этого бота: t.me/bunker_bot_from_bebra\n"
    )
    await bot.send_message(message.chat.id, help_text, disable_web_page_preview=True)


@bot.message_handler(commands=['profile'])
async def profile(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    if await is_banned(user_id) is True:
        return
    # Получаем данные пользователя из бд
    c.execute('''SELECT games_played, win_games, points, registration_date FROM users WHERE user_id = ?''', (user_id,))
    user_data = c.fetchone()

    if user_data is None:
        await bot.send_message(chat_id, "Вы ещё не играли ни в одной игре.")
        return

    games_played, win_games, points, registration_date = user_data
    registration_date = datetime.datetime.strptime(registration_date, '%Y-%m-%d %H:%M:%S')
    first_name = message.from_user.first_name
    # Вычисляем процент побед
    win_rate = (win_games / games_played) * 100 if games_played > 0 else 0
    win_rate = round(win_rate, 2)
    config = await load_config()
    osnova_text = str(config['profile_message']['text'])
    registration_date = registration_date.strftime('%d.%m.%Y %H:%M')
    text = f"{osnova_text.format(first_name=first_name, registration_date=registration_date, games_played=games_played, win_games=win_games, win_rate=win_rate, points=points)} "

    gif_filename = 'profile.jpg'
    gif_path = os.path.join("gifs", gif_filename)
    photo = open(gif_path, 'rb')

    await bot.send_photo(chat_id, photo=photo, caption=text, parse_mode="Markdown")


@bot.message_handler(commands=['shop'])
async def shop(me):
    if me.chat.type != 'private':
        return
    user_id = me.from_user.id
    if await is_banned(user_id) is True:
        return
    shop_message = "Приветствую вас в пост-апокалиптическом магазине!\n Здесь вы можете купить события которые влияют на игру."
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text='События', callback_data="events"))
    await bot.send_message(user_id, shop_message, reply_markup=markup)


@bot.message_handler(commands=['settings'])
async def settings(message):
    if message.chat.type == "private":
        return
    user_id = message.from_user.id
    chat_id = message.chat.id
    table_chat_id = chat_id * -1
    admins = await bot.get_chat_administrators(chat_id)
    is_admin = any(admin.user.id == user_id for admin in admins)

    if not is_admin:
        await bot.send_message(chat_id, "Обратитесь к администратору для настройки чата")
        return

    c.execute(f"""SELECT open_time, discussion_time, voting_time, delete_message FROM chats WHERE chat_id = ?""", (table_chat_id,))
    open_time, discussion_time, voting_time, delete_message = c.fetchone()

    delete_message = bool(delete_message)

    if delete_message:
        is_delete = ""
    else:
        is_delete = "не "
    message = (f"Здесь вы можете настроить чат по своему желанию, в настройки чата входят: \n"
               f"Время для обсуждения игроками своих карт: {discussion_time}\n"
               f"Время на вскрытие карт: {open_time}\n"
               f"Время на голосование: {voting_time}\n"
               f"Сейчас бот {is_delete}удаляет сообщения выбывших игроков\n"
               f"Для настроек чата вы можете использовать кнопки снизу")

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="Время обсуждения", callback_data="time_for_cards_0"))
    markup.add(types.InlineKeyboardButton(text="Время на вскрытие карт", callback_data="time_for_open_cards_0"))
    markup.add(types.InlineKeyboardButton(text="Время на голосование", callback_data="time_for_voting_0"))
    markup.add(types.InlineKeyboardButton(text="Настройки удаления сообщений", callback_data=f"delete_message_0"))
    markup.add(types.InlineKeyboardButton(text="Сбросить настройки", callback_data="reset_settings"))
    await bot.send_message(chat_id, message, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "settings")
async def call_settings(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    table_chat_id = chat_id * -1
    admins = await bot.get_chat_administrators(chat_id)
    is_admin = any(admin.user.id == user_id for admin in admins)

    if not is_admin:
        await bot.answer_callback_query(call.id, "Обратитесь к администратору чата для настройки", show_alert=True)
        return

    c.execute(f"""SELECT open_time, discussion_time, voting_time, delete_message FROM chats WHERE chat_id = ?""", (table_chat_id,))
    open_time, discussion_time, voting_time, delete_message = c.fetchone()

    delete_message = bool(delete_message)

    if delete_message:
        is_delete = ""
    else:
        is_delete = "не "
    message = (f"Здесь вы можете настроить чат по своему желанию, в настройки чата входят: \n"
               f"Время для обсуждения игроками своих карт: {discussion_time}\n"
               f"Время на вскрытие карт: {open_time}\n"
               f"Время на голосование: {voting_time}\n"
               f"Сейчас бот {is_delete}удаляет сообщения выбывших игроков\n"
               f"Для настроек чата вы можете использовать кнопки снизу")

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="Время обсуждения", callback_data="time_for_cards_0"))
    markup.add(types.InlineKeyboardButton(text="Время на вскрытие карт", callback_data="time_for_open_cards_0"))
    markup.add(types.InlineKeyboardButton(text="Время на голосование", callback_data="time_for_voting_0"))
    markup.add(types.InlineKeyboardButton(text="Настройки удаления сообщений", callback_data=f"delete_message_0"))
    markup.add(types.InlineKeyboardButton(text="Сбросить настройки", callback_data="reset_settings"))
    await bot.edit_message_text(message, chat_id, call.message.id, parse_mode='HTML', reply_markup=markup)


@bot.message_handler(commands=["about_update"])
async def about_update(message):
    chat_id = message.chat.id
    config = await load_config()

    message_text = config["about_update"]["text"]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(config["tg_channel"]["text"], callback_data=config["tg_channel"]["url"]))
    await bot.send_message(chat_id, message_text, reply_markup=markup)


@bot.message_handler(commands=['stop_game'])
async def stop_game(message):
    if message.chat.type == 'private':
        return

    user_id = message.from_user.id
    if await is_banned(user_id) is True:
        return

    chat_id = message.chat.id
    safe_chat_id = int(chat_id) * (-1)

    admins = await bot.get_chat_administrators(chat_id)

    is_admin = any(admin.user.id == user_id for admin in admins)

    if not is_admin:
        await bot.send_message(chat_id, "У вас нет прав для остановки игры.")
        return
    c.execute("""SELECT is_in_game FROM chats WHERE chat_id = ?""", (safe_chat_id, ))
    is_in_game = c.fetchone()[0]
    if is_in_game != IsInGameNow.INACTIVE:
        c.execute('''UPDATE chats SET is_in_game = ? WHERE chat_id = ?''', (IsInGameNow.INACTIVE, safe_chat_id))
        conn.commit()
        await bot.send_message(chat_id, 'Игра остановлена в этом чате')
        for user_id, user_name in await is_alive(safe_chat_id):
            c.execute(F'''UPDATE users SET is_in_game = 0 WHERE user_id = {user_id}''')
            conn.commit()
        try:
            c.execute(f'''DROP TABLE IF EXISTS chat_{safe_chat_id}''')
            conn.commit()
        except Exception:
            pass
    else:
        await bot.send_message(chat_id, "В этом чате игра не начиналась")


async def break_game(chat_id):
    """Завершает игру в чате."""
    table_chat_id = -1 * chat_id
    c.execute(f'''SELECT user_id FROM chat_{table_chat_id}''')
    user_ids = [row[0] for row in c.fetchall()]
    for user_id, user_name in await is_alive(table_chat_id):
        try:
            c.execute(F'''UPDATE users SET is_in_game = 0 WHERE user_id = {user_id}''')
            config = await load_config()
            message = str(config['game_interrupted']['text'])
            await bot.send_message(user_id, message)
        except Exception:
            pass

    c.execute(f'''UPDATE chats SET is_in_game = ? WHERE chat_id = ?''', (IsInGameNow.INACTIVE, table_chat_id))
    c.execute(f'''DROP TABLE IF EXISTS chat_{table_chat_id}''')
    await reset_player_status(user_ids)
    conn.commit()


async def reset_player_status(user_ids):
    if user_ids:
        for user_id in user_ids:
            c.execute('''UPDATE users SET is_in_game = 0 WHERE user_id = ?''', (user_id,))
            conn.commit()


@bot.message_handler(commands=['ban', 'unban'])
async def ban_unban_user(message):
    """
    Банит или разбанивает пользователя в игре.
    Доступно только администраторам с правом can_ban_people.
    Работает как с реплаем на сообщение пользователя, так и с указанием ID.
    Администраторы не могут банить других администраторов (кроме главного администратора).
    """
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Проверяем, является ли пользователь админом с правом банить
    c.execute('''SELECT can_ban_people, is_main FROM admins WHERE user_id = ?''', (user_id,))
    admin_data = c.fetchone()

    if admin_data is None or not admin_data[0]:
        await bot.send_message(chat_id, "У вас нет прав для бана/разбана пользователей.")
        return

    is_main_admin = admin_data[1]  # True, если пользователь - гл админ

    if message.reply_to_message is not None:
        # Получаем ID из реплая
        target_user_id = message.reply_to_message.from_user.id
    else:
        # Получаем ID из команды
        try:
            target_user_id = int(message.text.split()[1])
        except (IndexError, ValueError):
            await bot.send_message(chat_id,
                                   "Введите ID пользователя для бана/разбана: /ban {user_id} или /unban {user_id}")
            return

    # Проверяем, является ли жертва администратором
    c.execute('''SELECT is_main FROM admins WHERE user_id = ?''', (target_user_id,))
    target_admin_data = c.fetchone()

    if target_admin_data is not None and target_admin_data[0] and not is_main_admin:
        await bot.send_message(chat_id, "Вы не можете банить/разбанивать других администраторов.")
        return

    if message.text.startswith('/ban'):
        # Баним
        c.execute('''UPDATE users SET is_banned = True WHERE user_id = ?''', (target_user_id,))
        action = "забанен"
    elif message.text.startswith('/unban'):
        # Разбаниваем
        c.execute('''UPDATE users SET is_banned = False WHERE user_id = ?''', (target_user_id,))
        action = "разбанен"
    else:
        return

    conn.commit()
    x = await which_chat_with_logs()
    await bot.send_message(x, f"Пользователь {create_user_link(target_user_id, 'Игрок')} был {action} "
                              f"администратором {create_user_link(user_id, 'Админ')}", parse_mode='HTML')

    await bot.send_message(chat_id, f"Пользователь с ID {target_user_id} был {action}.")


@bot.message_handler(commands=['add_admin'])
async def add_admin(message):
    user_id = message.from_user.id
    admin_table = 'admins'

    # Проверяем, является ли пользователь админом
    c.execute(f'''SELECT is_main FROM {admin_table} WHERE user_id = ?''', (user_id,))
    is_main = c.fetchone()

    if is_main is None or not is_main[0]:
        await bot.send_message(message.chat.id, 'У вас недостаточно прав')
        return

    try:
        # Извлекаем аргументы из запроса
        args = message.text.split(' ')
        target_user_id = int(args[1])
        change_status = bool(int(args[2]))
        ban_people = bool(int(args[3]))
        is_main_flag = bool(int(args[4]))
    except (IndexError, ValueError):
        await bot.send_message(message.chat.id,
                               'Введите данные в формате: /add_admin {user_id} {change_status} {ban_people} {is_main}\n'
                               'Где {change_status}, {ban_people}, {is_main} 0 или 1.')
        return

    # Проверяем, есть ли уже администратор
    c.execute(f'''SELECT user_id FROM {admin_table} WHERE user_id = ?''', (target_user_id,))
    existing_admin = c.fetchone()

    if existing_admin:
        # Обновляем его права
        c.execute(f'''
            UPDATE {admin_table}
            SET can_change_status_of_game = ?, can_ban_people = ?, is_main = ?
            WHERE user_id = ?''', (change_status, ban_people, is_main_flag, target_user_id))
    else:
        # Добавляем его
        c.execute(f'''
            INSERT INTO {admin_table} (user_id, can_change_status_of_game, can_ban_people, is_main)
            VALUES (?, ?, ?, ?)''', (target_user_id, change_status, ban_people, is_main_flag))

    conn.commit()
    x = await which_chat_with_logs()
    await bot.send_message(x, f"Пользователь {create_user_link(target_user_id, 'Админ')} был назначен "
                              f"администратором {create_user_link(user_id, 'Админ')}", parse_mode='HTML')
    await bot.send_message(message.chat.id, f"Пользователь {create_user_link(target_user_id, 'Админ')} "
                                            f"был назначен администратором {create_user_link(user_id, 'Админ')}.",
                           parse_mode='HTML')


@bot.message_handler(commands=['del_admin'])
async def remove_admin(message):
    admin_table = 'admins'
    user_id = message.from_user.id
    # Проверяем, является ли пользователь админом
    c.execute(f'''SELECT is_main FROM {admin_table} WHERE user_id = ?''', (user_id,))
    existing_admin = c.fetchone()
    if existing_admin is None:
        return
    elif existing_admin[0] is False:
        await bot.send_message(message.chat.id, 'У вас недостаточно прав.')
        return

    try:
        args = message.text.split(' ')
        target_user_id = int(args[1])
    except (IndexError, ValueError):
        await bot.send_message(message.chat.id,
                               'Введите данные в формате: /del_admin {user_id}')
        return

    # Удаляем админа
    c.execute(f'''DELETE FROM {admin_table} WHERE user_id = ?''', (target_user_id,))
    conn.commit()

    x = await which_chat_with_logs()
    await bot.send_message(x, f"Пользователь {create_user_link(target_user_id, 'Админ')} был снят "
                              f"администратором {create_user_link(user_id, 'Админ')}", parse_mode='HTML')
    await bot.send_message(message.chat.id, f"Пользователь {create_user_link(target_user_id, 'Админ')} был снят "
                                            f"администратором {create_user_link(user_id, 'Админ')}", parse_mode='HTML')


@bot.message_handler(commands=['list_admins'])
async def list_admins(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Проверяем, является ли пользователь админом
    c.execute(f'''SELECT can_change_status_of_game FROM admins WHERE user_id = ?''', (user_id,))
    is_admin = c.fetchone()

    if not is_admin:
        await bot.send_message(chat_id, 'У вас нет прав для просмотра списка администраторов.')
        return

    c.execute('''SELECT user_id, can_change_status_of_game, can_ban_people, is_main FROM admins''')
    admins = c.fetchall()

    if not admins:
        await bot.send_message(chat_id, 'Список администраторов пуст.')
        return

    message_text = "Список администраторов:\n"
    for admin in admins:
        admin_id, can_change, can_ban, is_main = admin
        admin_status = "(Главный администратор)" if is_main else ""
        message_text += f"• Пользователь ID: {admin_id} {admin_status}\n" \
                        f"  Может изменять статус игры: {'Да' if can_change else 'Нет'}\n" \
                        f"  Может банить игроков: {'Да' if can_ban else 'Нет'}\n" \
                        f"  Ссылка: {create_user_link(admin_id, 'Админ')}\n"

    await bot.send_message(chat_id, message_text, parse_mode='HTML')


@bot.message_handler(commands=['set_log_chat'])
async def set_log_chat(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Проверяем, является ли пользователь админом
    c.execute(f'''SELECT is_main FROM admins WHERE user_id = ?''', (user_id,))
    result = c.fetchone()
    if result is None or not result[0]:
        await bot.send_message(chat_id, "У вас недостаточно прав для установки ID лог-чата.")
        return

    x = await which_chat_with_logs()
    await bot.send_message(x, f"Пользователь {create_user_link(user_id, 'Админ')} создал новый чат логов: "
                              f"{chat_id}", parse_mode='HTML')

    c.execute('''UPDATE admin_info SET log_chat_id = ?''', (chat_id,))
    conn.commit()

    await bot.send_message(chat_id, f"ID лог-чата успешно установлен: {chat_id}.")


@bot.message_handler(commands=['restore_admin'])
async def restore_admin(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Получаем резервный код
    try:
        reserv_code = message.text.split()[1]
    except IndexError:
        await bot.send_message(chat_id, "Введите резервный код: /restore_admin {код}")
        return

    # Проверяем резервный код в бд
    c.execute('''SELECT reserv_code FROM admin_info''')
    stored_code = c.fetchone()

    if stored_code is None or stored_code[0] != reserv_code:
        await bot.send_message(chat_id, "Неверный резервный код.")
        return

    # Назначаем пользователя гл админом
    c.execute('''DELETE FROM admins''')
    c.execute(f'''INSERT INTO admins (user_id, can_change_status_of_game, can_ban_people, is_main)
                  VALUES (?, ?, ?, ?)''', (user_id, True, True, True))
    new_reserv_code = ''.join(random.choices(string.ascii_letters + string.digits, k=50))
    c.execute('''UPDATE admin_info SET reserv_code = ?''', (new_reserv_code,))
    conn.commit()
    x = await which_chat_with_logs()
    await bot.send_message(x, f"Пользователь {message.from_user.first_name} восстановил себя в правах")
    await bot.send_message(chat_id, f"Вы успешно восстановлены как главный администратор. Новый резервный код: "
                                    f"{new_reserv_code}")


@bot.message_handler(commands=['change_games'])
async def stop_all_games(me):
    user_id = me.from_user.id
    chat_id = me.chat.id
    c.execute(f'''SELECT can_change_status_of_game FROM admins WHERE user_id = {user_id}''')
    result = c.fetchone()

    # Результат
    if result is None:
        await bot.send_message(chat_id, 'У вас недостаточно прав. Обратитесь к главному администратору.')
        return

    # Проверяем права админа
    if result[0] == 0:
        await bot.send_message(chat_id, 'У вас недостаточно прав. Обратитесь к главному администратору.')
        return
    elif result[0] == 1:
        c.execute(f'''SELECT game_stop FROM admin_info''')
        result = c.fetchone()

        if result is None:
            await bot.send_message(chat_id, 'Ошибка, не удалось получить информацию о состоянии игры.')
            return

        if not result[0]:  # Если game_stop равен False
            c.execute(f'''UPDATE admin_info SET game_stop = True ''')
            conn.commit()
            c.execute(f'''UPDATE chats SET is_in_game = "{IsInGameNow.INACTIVE}"''')
            conn.commit()
            c.execute(f'''SELECT chat_id FROM chats WHERE is_in_game = "{IsInGameNow.IN_GAME}"''')
            c.execute(f'''UPDATE users SET is_in_game = 0''')
            conn.commit()
            chat_results = c.fetchall()
            for chat_tuple in chat_results:
                chat_id = -1 * chat_tuple[0]
                try:
                    await bot.send_message(chat_id, 'Приносим извинения за прерванную игру. '
                                                    'Бо т был остановлен по решению модератора '
                                                    'для решения некоторых проблем. Не рекомендуется использовать '
                                                    'бота до объявления о решении проблем. Для получения подробностей '
                                                    'вам сюда: ')
                except Exception:
                    pass
            await bot.send_message(chat_id, f'''Все игры были остановлены. Создание игр недоступно''')
        elif result[0]:  # Если game_stop равен True
            c.execute(f'''UPDATE admin_info SET game_stop = False ''')
            await bot.send_message(chat_id, 'Бот снова работает в штатном режиме.')
        x = await which_chat_with_logs()
        await bot.send_message(x, f"Пользователь {create_user_link(user_id, 'Админ')} сменил режим игр",
                               parse_mode='HTML')


@bot.message_handler(commands=['send_add'])
async def change_add(me):
    """
    Отправляет рекламное сообщение во все чаты, где добавлен бот.
    Доступно только главному администратору.
    """
    user_id = me.from_user.id
    first_chat = me.chat.id

    c.execute('''SELECT is_main FROM admins WHERE user_id = ?''', (user_id,))
    is_main_admin = c.fetchone()

    if is_main_admin is None or not is_main_admin[0]:
        await bot.send_message(me.chat.id, "У вас нет прав для отправки рекламы.")
        return

    message = me.reply_to_message
    if message is None:
        await bot.send_message(me.chat.id, "Ответьте на сообщение, которое хотите отправить как рекламу.")
        return

    c.execute("SELECT chat_id FROM chats")
    chat_ids = [row[0] for row in c.fetchall()]

    successful_sends = 0
    failed_sends = 0

    for chat_id in chat_ids:
        try:
            await bot.copy_message(-1 * chat_id, first_chat, message.message_id)
            successful_sends += 1
            print(f"Сообщение успешно отправлено в чат {chat_id}")
        except Exception as e:
            failed_sends += 1
            if '403' in str(e):
                c.execute('''DELETE FROM chats WHERE chat_id = ?''', (chat_id,))

    await bot.send_message(me.chat.id, f"Рекламное сообщение отправлено в {successful_sends} чатов. "
                                       f"Не удалось отправить в {failed_sends} чатов.")


@bot.message_handler(commands=['statistics'])
async def get_statistics(message):
    user_id = message.from_user.id
    c.execute('SELECT user_id FROM admins WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    if result is None or not result[0]:
        await bot.send_message(message.chat.id, "У вас нет прав для получения статистики.")
        return

    c.execute('SELECT COUNT(*) FROM users')
    total_users = c.fetchone()[0]

    c.execute('SELECT COUNT(*) FROM users WHERE games_played > 0')
    active_users = c.fetchone()[0]

    c.execute('SELECT COUNT(*) FROM chats')
    total_chats = c.fetchone()[0]

    # Топ 3 игроков по победам
    c.execute('''SELECT user_id, win_games FROM users 
                 ORDER BY win_games DESC LIMIT 3''')
    top_winners = c.fetchall()

    # Топ 3 игроков по очкам
    c.execute('''SELECT user_id, points FROM users 
                 ORDER BY points DESC LIMIT 3''')
    top_points = c.fetchall()

    stats_message = (
        f"📊 *Общая статистика:*\n"
        f"👥 *Всего пользователей:* {total_users}\n"
        f"🎮 *Активных пользователей:* {active_users}\n"
        f"💬 *Всего чатов:* {total_chats}\n\n"
    )

    stats_message += "🥇 *Топ-3 игроков по победам:*\n"
    for idx, (user_id, wins) in enumerate(top_winners, 1):
        stats_message += f"{idx}. {create_user_link(user_id, f'Игрок {user_id}')} — {wins} побед\n"

    stats_message += "\n💰 *Топ-3 игроков по очкам:*\n"
    for idx, (user_id, points) in enumerate(top_points, 1):
        stats_message += f"{idx}. {create_user_link(user_id, f'Игрок {user_id}')} — {points} очков\n"

    await bot.send_message(message.chat.id, stats_message, parse_mode="HTML")


@bot.message_handler(func=lambda message: True)  # Обработчик всех сообщений
async def handle_all_messages(message):
    if message.chat.type == 'private':
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    try:
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (f"chat_{str(-1 * chat_id)}",))
        if c.fetchone() is None:
            return

        # Проверяем, идёт ли игра в этом чате и нужно ли удалять сообщения
        c.execute(f'''SELECT is_in_game, delete_message FROM chats WHERE chat_id = ?''', (-1 * chat_id, ))
        is_in_game, delete_message = c.fetchone()
        if is_in_game != IsInGameNow.IN_GAME:
            return
        if not delete_message:
            return
        admins = await bot.get_chat_administrators(chat_id)
        admin_ids = [admin.user.id for admin in admins]
        # Игра идёт, проверяем, жив ли пользователь
        c.execute(f'''SELECT is_alive FROM chat_{-1 * chat_id} WHERE user_id = ?''', (user_id,))
        is_user_alive = c.fetchone()
        if is_user_alive is None:
            is_user_alive = False
        else:
            is_user_alive = bool(is_user_alive[0])
        if is_user_alive is True:
            return
        if user_id not in admin_ids:
            try:
                await bot.delete_message(chat_id, message.message_id)
                await bot.restrict_chat_member(chat_id, user_id, until_date=int(time.time()) + 60,
                                               can_send_messages=False,
                                               can_send_media_messages=False,
                                               can_send_other_messages=False,
                                               can_add_web_page_previews=False)
            except Exception:
                pass
        else:
            if not message.text.startswith('!'):
                try:
                    await bot.delete_message(chat_id, message.message_id)
                except Exception:
                    pass

    except Exception as e:
        x = await which_chat_with_logs()
        try:
            await bot.send_message(x, e)
        except Exception:
            pass


async def main():
    # Удаление таблиц чатов при запуске бота
    c.execute('''SELECT chat_id FROM chats''')
    chat_ids = c.fetchall()
    for chat_id_tuple in chat_ids:
        chat_id = chat_id_tuple[0]
        c.execute(f'''DROP TABLE IF EXISTS chat_{chat_id}''')
    c.execute(f'''UPDATE chats SET is_in_game = "{IsInGameNow.INACTIVE}"''')
    conn.commit()
    # Удаление таблиц голосования
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = c.fetchall()
    for table in tables:
        table_name = table[0]
        if table_name.startswith("voting_in_chat_"):
            c.execute(f"DROP TABLE IF EXISTS {table_name}")
    conn.commit()
    c.execute('''SELECT user_id FROM users''')
    result = c.fetchall()
    if result:
        user_ids = [row[0] for row in result]
        await reset_player_status(user_ids)
    await bot.polling(non_stop=True)


if __name__ == '__main__':
    asyncio.run(main())
