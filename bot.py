import json
import logging
import random
import asyncio
import time
import os
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# === БЕЗОПАСНАЯ ЗАГРУЗКА ТОКЕНА ===
# 1. Сначала пробуем загрузить из переменных окружения
TOKEN = os.environ.get("BOT_TOKEN")

# 2. Если не нашли в переменных окружения, пробуем загрузить из файла .env
if not TOKEN:
    try:
        from dotenv import load_dotenv
        load_dotenv()
        TOKEN = os.environ.get("BOT_TOKEN")
    except ImportError:
        pass

# 3. Если токен так и не найден, завершаем работу с ошибкой
if not TOKEN:
    print("❌ ОШИБКА: Токен бота не найден!")
    print("Добавьте токен одним из способов:")
    print("1. В переменную окружения TELEGRAM_BOT_TOKEN")
    print("2. В файл .env (TELEGRAM_BOT_TOKEN=ваш_токен)")
    print("3. Для Bothost: Settings → Environment Variables")
    exit(1)

print("✅ Токен успешно загружен")

# --- LOGGING & DATA LOADING (SIMPLE LOGIC) ---
# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === ЗАГРУЗКА ВСЕХ ДАННЫХ (ИСПРАВЛЕННАЯ ВЕРСИЯ) ===
# Получаем текущую директорию
current_dir = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(current_dir, 'data')

# Проверяем существование директории data
if not os.path.exists(data_dir):
    print(f"❌ ОШИБКА: Директория 'data' не найдена! Путь: {data_dir}")
    print("Создайте директорию 'data' и поместите туда все JSON файлы")
    exit(1)

# Загрузка всех данных с проверкой файлов
def load_json_file(filename):
    """Загружает JSON файл с обработкой ошибок"""
    filepath = os.path.join(data_dir, filename)
    if not os.path.exists(filepath):
        print(f"❌ ОШИБКА: Файл '{filename}' не найден! Путь: {filepath}")
        return {}
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ ОШИБКА: Неверный JSON формат в файле '{filename}': {e}")
        return {}
    except Exception as e:
        print(f"❌ ОШИБКА при загрузке '{filename}': {e}")
        return {}

# Загружаем все данные
print("📂 Загрузка игровых данных...")
CLASSES = load_json_file('classes.json')
LOCATIONS = load_json_file('locations.json')
ENEMIES = load_json_file('enemies.json')
BOSSES = load_json_file('bosses.json')
QUESTS = load_json_file('quests.json')
ITEMS = load_json_file('items.json')
SPECIAL_ACTIONS = load_json_file('special_actions.json')
STORY = load_json_file('story.json')
RANDOM_EVENTS = load_json_file('random_events.json')
ABILITIES = load_json_file('abilities.json')

# Проверяем, что все файлы загрузились
data_files = {
    'classes.json': CLASSES,
    'locations.json': LOCATIONS,
    'enemies.json': ENEMIES,
    'bosses.json': BOSSES,
    'quests.json': QUESTS,
    'items.json': ITEMS,
    'special_actions.json': SPECIAL_ACTIONS,
    'story.json': STORY,
    'random_events.json': RANDOM_EVENTS,
    'abilities.json': ABILITIES
}

for filename, data in data_files.items():
    if data:
        print(f"✅ {filename} загружен ({len(data)} записей)")
    else:
        print(f"⚠️ {filename} пуст или не загружен")

print("✅ Все данные загружены!")

player_states = {}

# --- GAME CONSTANTS ---

# Mapping damage types to emojis
DAMAGE_ICONS = {
    "physical": "⚔️",
    "fire": "🔥",
    "ice": "❄️",
    "poison": "☠️",
    "magic": "✨",
    "lightning": "⚡",
    "light": "☀️",
    "earth": "🪨",
    "dark": "🌑"
}

# --- PLAYER CLASS ---
class Player:
    def __init__(self, user_id):
        self.user_id = user_id
        self.class_name = None
        self.base_stats = {}
        self.base_abilities = []
        self.inventory = []
        self.equipped_artifacts = []
        self.artifact_slots = 1
        self.gold = 50
        self.active_effects = []
        self.active_quests = []
        self.completed_quests = []
        self.location = "class_selection"
        self.level = 1
        self.experience = 0
        self.kill_count = {}
        self.visited_locations = set()
        self.defeated_bosses = set()
        self.current_city = "village_square"
        self.camp_entry_time = 0
        self.fatigue = 100
        self.last_fatigue_update = time.time()
        self.story_progress = {}
        self.unlocked_cities = set(["village_square"])
        self.last_location = "village_square"

    def update_fatigue(self):
        current_time = time.time()
        passed = current_time - self.last_fatigue_update
        gain = passed * (100 / 3600)
        if gain > 0:
            self.fatigue = min(100, self.fatigue + gain)
            self.last_fatigue_update = current_time

    def can_do_event(self, cost):
        self.update_fatigue()
        return self.fatigue >= cost

    def spend_fatigue(self, amount):
        self.update_fatigue()
        self.fatigue = max(0, self.fatigue - amount)
        self.last_fatigue_update = time.time()

    def get_total_stats(self):
        stats = self.base_stats.copy()
        stats['gold'] = self.gold
        for item_id in self.equipped_artifacts:
            item = ITEMS.get(item_id)
            if item and 'stats' in item:
                for stat, value in item['stats'].items():
                    stats[stat] = stats.get(stat, 0) + value
        for effect in self.active_effects:
            for stat, value in effect.get('stats', {}).items():
                stats[stat] = stats.get(stat, 0) + value
        return stats

    def add_effect(self, name, stats, duration):
        self.active_effects.append({'name': name, 'stats': stats, 'duration': duration})

    def tick_effects(self):
        expired = []
        for effect in self.active_effects:
            effect['duration'] -= 1
            if effect['duration'] <= 0:
                expired.append(effect)
        for e in expired:
            if e in self.active_effects:
                self.active_effects.remove(e)
        return len(expired) > 0

    def get_max_health(self):
        c_data = CLASSES.get(self.class_name)
        if not c_data: return 100
        return c_data['base_stats']['health'] + (self.level - 1) * 10

    def get_all_abilities(self):
        # Base (Level 1) abilities
        abilities = set(self.base_abilities)

        # Check for Level Unlocks defined in Classes
        c_data = CLASSES.get(self.class_name)
        if c_data and 'unlocks' in c_data:
            for lvl_req, unlocked_abs in c_data['unlocks'].items():
                if self.level >= int(lvl_req):
                    for ab in unlocked_abs:
                        abilities.add(ab)

        return list(abilities)

    def equip_artifact(self, item_id):
        if item_id not in self.inventory: return False, "Нет в инвентаре."
        if item_id in self.equipped_artifacts: return False, "Уже надето."
        item = ITEMS.get(item_id)
        if not item or item.get('type') != 'artifact': return False, "Это не артефакт."
        if len(self.equipped_artifacts) >= self.artifact_slots:
            return False, f"Нет свободных слотов ({len(self.equipped_artifacts)}/{self.artifact_slots}). Снимите что-нибудь."
        self.equipped_artifacts.append(item_id)
        return True, "Артефакт надет."

    def unequip_artifact(self, item_id):
        if item_id in self.equipped_artifacts:
            self.equipped_artifacts.remove(item_id)
            return True, "Артефакт снят."
        return False, "Не надето."

    def unlock_city(self, city_id):
        self.unlocked_cities.add(city_id)

    def has_completed_story(self, city):
        storyline = STORY.get(f"{city}_storyline", [])
        if not storyline: return False
        last_scene_id = storyline[-1]["id"]
        return self.story_progress.get(city) == last_scene_id

def get_player(user_id):
    if user_id not in player_states: player_states[user_id] = Player(user_id)
    return player_states[user_id]

def get_keyboard_layout(buttons, cols=2):
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]

# --- DAMAGE CALCULATION SYSTEM (UPDATED WITH RESISTANCE) ---
def calculate_single_layer_damage(base_attack, multiplier, dmg_type, resistances):
    # Base calculation
    raw = base_attack * multiplier

    # Resistance Check
    # Resistance is 0.0 to 1.0 (percent blocked). Negative means weakness (bonus damage).
    # Cap at 1.0 (immune).
    res_val = resistances.get(dmg_type, 0.0)
    res_factor = max(0.0, 1.0 - res_val)

    final_val = raw * res_factor

    # Random Variance
    min_dmg = int(final_val * 0.8)
    max_dmg = int(final_val * 1.2)
    return max(1, random.randint(min_dmg, max_dmg))

async def generic_back_button(update, context, player):
    if context.user_data.get('in_inventory'):
        await show_inventory_menu(update, context, player)
    elif context.user_data.get('in_shop') or context.user_data.get('in_shop_sell') or context.user_data.get('shop_confirm_buy') or context.user_data.get('shop_confirm_sell'):
        # Reset specific shop states
        context.user_data['shop_confirm_buy'] = None
        context.user_data['shop_confirm_sell'] = None
        context.user_data['in_shop_sell'] = False
        await show_shop_menu(update, context, player, context.user_data.get('current_shop_items', []))
    elif context.user_data.get('in_city_teleport'):
        context.user_data['in_city_teleport'] = False
        await show_location(update, context, player, player.location)
    elif player.location == "class_selection":
        await show_class_selection(update, context, player)
    else:
        await show_location(update, context, player, player.location)

# --- CORE GAMEPLAY ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    player = get_player(update.effective_user.id)
    if player.class_name:
        if context.user_data.get('in_battle'):
             await update.message.reply_text("⚔️ Вы находитесь в бою! Закончите его или сбегите.")
             return
        await update.message.reply_text("👋 С возвращением! Продолжаем путешествие.")
        if player.location == "class_selection":
            await show_location(update, context, player, player.current_city)
        else:
            await show_location(update, context, player, player.location)
    else:
        await show_class_selection(update, context, player)

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in player_states: del player_states[uid]
    context.user_data.clear()
    player = get_player(uid)
    await update.message.reply_text("🔄 Игра перезапущена! Начинаем заново...", reply_markup=ReplyKeyboardRemove())
    await show_class_selection(update, context, player)

async def show_class_selection(update, context, player):
    player.location = "class_selection"
    if 'selected_class' in context.user_data: del context.user_data['selected_class']
    buttons = [KeyboardButton(f"👁️ {c['name']}") for c in CLASSES.values()]
    layout = get_keyboard_layout(buttons, 2)
    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo="https://i.imgur.com/3Vk5Q7a.jpeg",
        caption="**🎯 Выберите ваш класс**\n\nНажмите на класс чтобы посмотреть его характеристики.",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup(layout, resize_keyboard=True)
    )

async def handle_class_selection(update, context, player, text):
    if text == "⬅️ Назад к выбору класса" or text == "⬅️ Назад":
        await show_class_selection(update, context, player)
        return
    if text.startswith("👁️ "):
        c_name = text[3:]
        c_id = next((k for k, v in CLASSES.items() if v['name'] == c_name), None)
        if c_id:
            c_data = CLASSES[c_id]
            stats = c_data['base_stats']
            abilities = "\n".join([f"• {a}" for a in c_data["starting_abilities"]])
            msg = (f"**{c_data['name']}**\n\n*{c_data['description']}*\n\n💪 **Характеристики:**\n❤️ HP: {stats['health']}\n⚔️ ATK: {stats['attack']}\n🛡️ DEF: {stats['defense']}\n\n🔮 **Способности:**\n{abilities}")
            kb = [[KeyboardButton("✅ Выбрать этот класс")], [KeyboardButton("⬅️ Назад к выбору класса")]]
            context.user_data['selected_class'] = c_id
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=c_data['image'],
                caption=msg,
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
            )
    elif text == "✅ Выбрать этот класс":
        c_id = context.user_data.get('selected_class')
        if not c_id:
            await show_class_selection(update, context, player)
            return
        player.class_name = c_id
        player.base_stats = CLASSES[c_id]['base_stats'].copy()
        player.base_abilities = CLASSES[c_id]['starting_abilities'].copy()
        if 'selected_class' in context.user_data: del context.user_data['selected_class']
        await update.message.reply_text(f"🎉 **Вы стали {CLASSES[c_id]['name']}!**", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
        await start_intro_story(update, context, player)

async def start_quest(update, context, player, quest_id):
    quest = QUESTS.get(quest_id)
    if not quest: return
    if quest_id not in player.active_quests and quest_id not in player.completed_quests:
        player.active_quests.append(quest_id)
        await update.message.reply_text(f"📜 **Новый квест: {quest['name']}**\n\n{quest['description']}", parse_mode='Markdown')

async def start_intro_story(update, context, player, quest_id=None):
    await update.message.reply_text("Вы просыпаетесь в маленькой деревне. Старейшина просит вас подойти к нему.", reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(0.5)
    await start_quest(update, context, player, "first_steps")
    await asyncio.sleep(0.5)
    player.location = "village_square"
    player.current_city = "village_square"
    await show_location(update, context, player, "village_square")

async def show_location(update, context, player, loc_id):
    # Очистка всех временных состояний
    keys = ['in_battle', 'in_story', 'in_shop', 'in_shop_sell', 'in_inventory', 'in_city_teleport', 'viewing_item', 'in_random_event', 'current_event_chain', 'battle_potion_menu', 'shop_confirm_buy', 'shop_confirm_sell']
    for key in keys:
        if key in context.user_data: del context.user_data[key]

    location = LOCATIONS.get(loc_id)
    if not location:
        loc_id = player.current_city if player.current_city in LOCATIONS else "village_square"
        location = LOCATIONS[loc_id]

    player.location = loc_id
    player.last_location = loc_id
    player.visited_locations.add(loc_id)
    if location.get('is_city'): player.current_city = loc_id

    buttons = []
    for action in location.get("actions", []):
        if action["type"] == "story":
            city = action["target"]
            if player.has_completed_story(city): continue
        if action.get("target") == "capital_city" and "capital_city" not in player.unlocked_cities: continue
        buttons.append(KeyboardButton(action["text"]))

    menu = get_keyboard_layout(buttons, 2)
    footer = []
    if len(player.unlocked_cities) > 1 and location.get('is_city'):
        footer.append([KeyboardButton("🚀 Телепортация")])
    footer.append([KeyboardButton("📊 Характеристики"), KeyboardButton("🎒 Инвентарь")])
    if not location.get('is_city'): footer.append([KeyboardButton("🏠 В город")])

    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=location.get("image", "https://i.imgur.com/3Vk5Q7a.jpeg"),
        caption=f"**{location['name']}**\n\n{location['description']}",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup(menu + footer, resize_keyboard=True)
    )

async def handle_location_action(update, context, player, text):
    loc = LOCATIONS.get(player.location)
    if not loc:
        await show_location(update, context, player, player.current_city)
        return False
    action = next((a for a in loc.get("actions", []) if a["text"] == text), None)
    if action:
        t, target = action["type"], action.get("target")
        if t == "location": await show_location(update, context, player, target)
        elif t == "battle": await start_battle(update, context, player, target)
        elif t == "quest": await start_quest(update, context, player, target)
        elif t == "story": await start_story_line(update, context, player, target)
        elif t == "shop": await start_shop(update, context, player, action.get("shop_items", []))
        elif t == "random_events": await start_random_event(update, context, player, target)
        return True
    return False

async def start_story_line(update, context, player, city):
    storyline_key = f"{city}_storyline"
    storyline = STORY.get(storyline_key)
    if not storyline:
        await update.message.reply_text("❌ Сюжетная линия временно недоступна.")
        return
    current_scene_id = player.story_progress.get(city)
    if not current_scene_id:
        current_scene_id = storyline[0]["id"]
        player.story_progress[city] = current_scene_id
    context.user_data['current_story'] = {'type': 'main_story', 'city': city, 'current_scene': current_scene_id, 'storyline': storyline}
    await show_story_scene(update, context, player, city, current_scene_id)

async def show_story_scene(update, context, player, city, scene_id):
    story_data = context.user_data.get('current_story')
    if not story_data: return
    scene = next((s for s in story_data['storyline'] if s["id"] == scene_id), None)
    if not scene: return

    context.user_data['in_story'] = True
    context.user_data['current_story']['current_scene'] = scene_id

    scene_type = scene["type"]
    keyboard = []
    if scene_type == "dialogue": keyboard.append([KeyboardButton("➡️ Продолжить")])
    keyboard.append([KeyboardButton("🏠 Вернуться в город")])

    if scene_type == "dialogue":
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=scene.get("image", "https://i.imgur.com/3Vk5Q7a.jpeg"),
            caption=f"**📖 {scene.get('title', 'Сюжет')}**\n\n{scene['text']}",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
    elif scene_type == "battle":
        await update.message.reply_text(f"⚔️ **Сюжетный бой!**\n\n{scene['text']}", parse_mode='Markdown')
        await start_battle(update, context, player, scene["enemy"])
    elif scene_type == "location":
        if "rewards" in scene: await apply_rewards(update, player, scene["rewards"])
        if scene.get("unlock_city"):
            player.unlock_city(scene["unlock_city"])
            await update.message.reply_text(f"🔓 **Открыт доступ: {LOCATIONS[scene['unlock_city']]['name']}!**")
        player.story_progress[city] = scene_id
        context.user_data['in_story'] = False
        await update.message.reply_text(scene["text"], parse_mode='Markdown')
        await show_location(update, context, player, scene["target"])

async def handle_story_action(update, context, player, text):
    if text == "🏠 Вернуться в город":
        context.user_data['in_story'] = False
        await show_location(update, context, player, player.current_city)
        return
    if text == "➡️ Продолжить":
        story_data = context.user_data.get('current_story', {})
        current_scene_id = story_data.get('current_scene')
        scene = next((s for s in story_data['storyline'] if s["id"] == current_scene_id), None)
        if scene and scene.get("next_scene"):
            player.story_progress[story_data['city']] = scene["next_scene"]
            await show_story_scene(update, context, player, story_data['city'], scene["next_scene"])

async def start_random_event(update, context, player, city):
    context.user_data['current_event_chain'] = None
    context.user_data['in_random_event'] = False
    context.user_data['in_battle_from_event'] = False
    player.update_fatigue()
    city_key = city.replace("_square", "").replace("_city", "")
    small = RANDOM_EVENTS.get(f"{city_key}_small_events", [])
    medium = RANDOM_EVENTS.get(f"{city_key}_medium_events", [])
    all_events = small + medium

    if not all_events:
        await update.message.reply_text("Здесь ничего не происходит.")
        return

    available = [e for e in all_events if player.fatigue >= e.get("fatigue_cost", 0)]
    if not available:
        await update.message.reply_text(f"❌ Вы слишком устали! ({int(player.fatigue)}/100). Отдохните.")
        return

    event = random.choice(available)
    player.spend_fatigue(event.get("fatigue_cost", 0))
    await show_random_event(update, context, player, event)

async def show_random_event(update, context, player, event):
    context.user_data['in_random_event'] = True
    context.user_data['current_random_event'] = event
    fatigue_txt = f"😴 Усталость: {int(player.fatigue)}/100"

    if event["type"] == "chain":
        context.user_data['current_event_chain'] = {'scenes': event["scenes"], 'index': 0}
        await continue_event_chain(update, context, player, "start")
    elif event["type"] == "reward":
        if "rewards" in event: await apply_rewards(update, player, event["rewards"])
        kb = [[KeyboardButton("🎲 Еще событие")], [KeyboardButton("🏠 Вернуться в город")]]
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=event.get("image", "https://i.imgur.com/9vOMVqL.png"),
            caption=f"**{event['name']}**\n\n{event['description']}\n\n{fatigue_txt}",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
        )

async def continue_event_chain(update, context, player, text):
    chain = context.user_data.get('current_event_chain')
    if not chain: return
    scenes = chain['scenes']
    idx = chain['index']

    if idx >= len(scenes):
        context.user_data['current_event_chain'] = None
        kb = [[KeyboardButton("🎲 Еще событие")], [KeyboardButton("🏠 Вернуться в город")]]
        await update.message.reply_text("Событие завершено.", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        return

    scene = scenes[idx]
    chain['index'] += 1
    kb = []
    if scene["type"] == "dialogue": kb.append([KeyboardButton("➡️ Продолжить")])

    if scene["type"] == "dialogue":
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=scene.get("image", "https://i.imgur.com/9vOMVqL.png"),
            caption=scene["text"],
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
        )
    elif scene["type"] == "battle":
         await update.message.reply_text(f"⚔️ **Внезапная атака!**\n\n{scene['text']}", parse_mode='Markdown')
         context.user_data['in_battle_from_event'] = True
         await start_battle(update, context, player, scene["enemy"])
    elif scene["type"] == "reward":
        await update.message.reply_text(scene["text"], parse_mode='Markdown')
        if "rewards" in scene: await apply_rewards(update, player, scene["rewards"])
        await continue_event_chain(update, context, player, "continue")

async def handle_random_event_action(update, context, player, text):
    if context.user_data.get('current_event_chain'):
        await continue_event_chain(update, context, player, text)
        return
    if text == "🏠 Вернуться в город":
        await show_location(update, context, player, player.current_city)
        return
    if text == "🎲 Еще событие":
        await start_random_event(update, context, player, player.current_city)
        return

async def apply_rewards(update, player, rewards):
    txt = "🎁 **Получено:**"
    if "experience" in rewards:
        player.experience += rewards["experience"]
        txt += f"\n📈 +{rewards['experience']} XP"
    if "gold" in rewards:
        player.gold += rewards["gold"]
        txt += f"\n💰 +{rewards['gold']} золота"
    if "items" in rewards:
        player.inventory.extend(rewards["items"])
        item_names = [ITEMS[i]['name'] for i in rewards['items'] if i in ITEMS]
        if item_names: txt += f"\n🎒 Предметы: {', '.join(item_names)}"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def start_battle(update, context, player, enemy_id):
    enemy = ENEMIES.get(enemy_id) or BOSSES.get(enemy_id)
    if not enemy: return
    context.user_data['in_battle'] = True
    stats = player.get_total_stats()

    # Init counters for skills and DoTs
    context.user_data['battle'] = {
        'enemy': enemy.copy(),
        'e_hp': enemy['health'],
        'p_hp': stats['health'],
        'e_id': enemy_id,
        'phase': 1,
        'skill_uses': {},
        'active_dots': [] # List of active DoTs on enemy
    }

    abilities = player.get_all_abilities()
    buttons = [KeyboardButton("⚔️ Атака")] + [KeyboardButton(f"🔮 {a}") for a in abilities] + [KeyboardButton("🧪 Зелья"), KeyboardButton("🏃 Бежать")]
    layout = get_keyboard_layout(buttons, 2)

    buff_txt = ""
    if player.active_effects:
        buff_txt = "\n\n🧪 **Активные эффекты:**"
        for e in player.active_effects:
            buff_txt += f"\n• {e['name']} ({e['duration']} боев)"

    resist_txt = ""
    if "resistances" in enemy:
        r_list = []
        for r_type, r_val in enemy["resistances"].items():
             icon = DAMAGE_ICONS.get(r_type, r_type)
             pct = int(r_val * 100)
             sign = "-" if pct > 0 else "+" # Resistance decreases dmg, negative resistance increases
             r_list.append(f"{icon} {pct}%")
        if r_list: resist_txt = "\n🛡️ Резисты: " + ", ".join(r_list)

    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=enemy['image'],
        caption=f"⚔️ **Бой с {enemy['name']}!**\nHP: {enemy['health']} | ATK: {enemy['attack']}{buff_txt}{resist_txt}",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup(layout, resize_keyboard=True)
    )

async def handle_battle(update, context, player, text):
    b = context.user_data['battle']
    enemy = b['enemy']
    stats = player.get_total_stats()
    turn_ended = False

    # --- Potion Logic (Unchanged) ---
    if context.user_data.get('battle_potion_menu'):
        if text == "⬅️ Назад":
            del context.user_data['battle_potion_menu']
            abilities = player.get_all_abilities()
            buttons = [KeyboardButton("⚔️ Атака")] + [KeyboardButton(f"🔮 {a}") for a in abilities] + [KeyboardButton("🧪 Зелья"), KeyboardButton("🏃 Бежать")]
            layout = get_keyboard_layout(buttons, 2)
            await update.message.reply_text("⚔️ Бой продолжается!", reply_markup=ReplyKeyboardMarkup(layout, resize_keyboard=True))
            return
        if "🍺 " in text:
            try:
                p_name = text.split("🍺 ")[1].rsplit(" (", 1)[0]
                item_id = next((k for k,v in ITEMS.items() if v['name'] == p_name), None)
                if item_id and item_id in player.inventory:
                    item = ITEMS[item_id]
                    heal = item.get('stats', {}).get('health', 0)
                    buffs = item.get('buffs', {})
                    max_hp = player.get_max_health()
                    if heal > 0 and not buffs and b['p_hp'] >= max_hp:
                        await update.message.reply_text("❤️ Здоровье и так полное!")
                        return
                    player.inventory.remove(item_id)
                    msg = f"🧪 Вы выпили {p_name}."
                    if heal > 0:
                        b['p_hp'] = min(max_hp, b['p_hp'] + heal)
                        player.base_stats['health'] = b['p_hp']
                        msg += f" HP +{heal}. Здоровье: {b['p_hp']}"
                    if buffs:
                        buff_stats = {k: v for k, v in buffs.items() if k != 'duration'}
                        duration = buffs.get('duration', 1)
                        player.add_effect(item['name'], buff_stats, duration)
                        msg += f"\n💪 Эффект наложен на {duration} боев!"
                        for stat, val in buff_stats.items():
                            msg += f"\n+ {stat.upper()} +{val}"
                    await update.message.reply_text(msg)
                    del context.user_data['battle_potion_menu']
                    turn_ended = True
                else:
                    await update.message.reply_text("Ошибка: зелье не найдено.")
                    return
            except Exception as e:
                logger.error(f"Potion error: {e}")
                return
        else: return
    elif text == "🧪 Зелья":
         potions = [i for i in player.inventory if ITEMS.get(i, {}).get('type') == 'consumable']
         if not potions:
             await update.message.reply_text("У вас нет зелий!")
             return
         buttons = []
         for pid in set(potions):
             item = ITEMS[pid]
             count = potions.count(pid)
             buttons.append(KeyboardButton(f"🍺 {item['name']} ({count})"))
         buttons.append(KeyboardButton("⬅️ Назад"))
         layout = get_keyboard_layout(buttons, 1)
         context.user_data['battle_potion_menu'] = True
         await update.message.reply_text("Выберите зелье:", reply_markup=ReplyKeyboardMarkup(layout, resize_keyboard=True))
         return
    elif text == "🏃 Бежать":
        context.user_data['in_battle'] = False
        context.user_data['in_battle_from_event'] = False
        if player.tick_effects():
            await update.message.reply_text("⏳ Действие некоторых зелий закончилось.")
        await update.message.reply_text("🏃 Вы сбежали с поля боя!")
        await show_location(update, context, player, player.current_city)
        return

    # --- Player Turn ---
    if not context.user_data.get('battle_potion_menu') and not turn_ended:
        desc = ""
        total_dmg = 0
        enemy_res = enemy.get('resistances', {})

        # Standard Attack
        if text == "⚔️ Атака":
            dmg = calculate_single_layer_damage(stats['attack'], 1.0, "physical", enemy_res)
            b['e_hp'] -= dmg
            desc = f"{DAMAGE_ICONS['physical']} Вы ударили {enemy['name']} и нанесли {dmg} физ. урона."

        # Special Abilities
        elif text.startswith("🔮"):
            ability_name = text[2:].strip()
            effect = ABILITIES.get(ability_name)

            if effect:
                # Check limits
                uses = b['skill_uses'].get(ability_name, 0)
                limit = effect.get('max_uses', 99)
                if uses >= limit:
                    await update.message.reply_text(f"❌ Способность {ability_name} исчерпана ({limit}/{limit})!")
                    return

                b['skill_uses'][ability_name] = uses + 1

                # Calculate Layers
                layers_txt = []
                total_ability_dmg = 0

                if "layers" in effect:
                    for layer in effect["layers"]:
                        l_dmg = calculate_single_layer_damage(stats['attack'], layer["mult"], layer["type"], enemy_res)
                        total_ability_dmg += l_dmg
                        layers_txt.append(f"{l_dmg} {DAMAGE_ICONS.get(layer['type'], '')}")
                elif "dmg_mult" in effect: # Backwards compatibility
                    total_ability_dmg = calculate_single_layer_damage(stats['attack'], effect["dmg_mult"], "physical", enemy_res)
                    layers_txt.append(f"{total_ability_dmg} {DAMAGE_ICONS['physical']}")

                b['e_hp'] -= total_ability_dmg
                desc = f"✨ **{ability_name}** ({uses+1}/{limit}):\nУрон: {' + '.join(layers_txt)}"

                # Apply DoT
                if "dot" in effect:
                    dot_conf = effect["dot"]
                    # Calculate snapshot damage for DoT (DoTs usually ignore resistance or check it? Let's assume DoTs check resist on application or tick. Let's do raw for now then resist on tick if needed, but here we do simple snapshot logic)
                    # Let's apply resistance to the DoT value now so it ticks for the correct amount.
                    dot_raw = stats['attack'] * dot_conf["mult"]
                    # Usually DoTs match the damage type of the spell, or specific poison type.
                    dot_res_val = enemy_res.get(dot_conf["type"], 0.0)
                    dot_dmg = int(dot_raw * max(0.0, 1.0 - dot_res_val))

                    # Check if DoT exists to refresh instead of stack
                    existing = next((d for d in b['active_dots'] if d['name'] == dot_conf['name']), None)

                    if existing:
                        existing['duration'] = dot_conf['duration']
                        existing['damage'] = max(1, dot_dmg) # Update dmg based on current stats
                        desc += f"\n🔄 {dot_conf['name']} обновлено ({dot_conf['duration']} ход.)"
                    else:
                        b['active_dots'].append({
                            "type": dot_conf["type"],
                            "name": dot_conf["name"],
                            "damage": max(1, dot_dmg),
                            "duration": dot_conf["duration"]
                        })
                        desc += f"\n💀 Наложен эффект: {dot_conf['name']} ({dot_conf['duration']} ход.)"

                # Apply Heals
                if "heal" in effect:
                    healed = int(total_ability_dmg * effect["heal"])
                    b['p_hp'] += healed
                    desc += f"\n💚 Лечение: +{healed}"
                if "heal_flat" in effect:
                    b['p_hp'] += effect["heal_flat"]
                    desc += f"\n💚 Лечение: +{effect['heal_flat']}"

                # Defense Buff
                if "defense_buff" in effect:
                     player.add_effect(ability_name, {"defense": effect["defense_buff"]}, 1)
                     desc += f"\n🛡️ Защита +{effect['defense_buff']} на 1 ход."

        await update.message.reply_text(desc, parse_mode='Markdown')

        if b['e_hp'] <= 0:
            await handle_enemy_death(update, context, player, b)
            return

    # --- DoT Phase (Enemy takes damage) ---
    dot_log = []
    active_dots_new = []
    for dot in b['active_dots']:
        b['e_hp'] -= dot['damage']
        dot_log.append(f"{DAMAGE_ICONS.get(dot['type'], '')} {dot['name']}: {dot['damage']}")
        dot['duration'] -= 1
        if dot['duration'] > 0:
            active_dots_new.append(dot)

    b['active_dots'] = active_dots_new

    if dot_log:
        await update.message.reply_text("💀 Периодический урон:\n" + "\n".join(dot_log))
        if b['e_hp'] <= 0:
             await handle_enemy_death(update, context, player, b)
             return

    # --- Enemy Turn ---
    e_base_dmg = max(1, enemy['attack'] - stats['defense'])
    e_dmg = int(e_base_dmg * random.uniform(0.9, 1.1))
    b['p_hp'] -= e_dmg

    status = f"{enemy['name']} бьет в ответ! Урон: {e_dmg}.\n\n❤️ Ваш HP: {b['p_hp']}\n💀 Враг HP: {b['e_hp']}"
    abilities = player.get_all_abilities()
    buttons = [KeyboardButton("⚔️ Атака")] + [KeyboardButton(f"🔮 {a}") for a in abilities] + [KeyboardButton("🧪 Зелья"), KeyboardButton("🏃 Бежать")]
    layout = get_keyboard_layout(buttons, 2)
    await update.message.reply_text(status, reply_markup=ReplyKeyboardMarkup(layout, resize_keyboard=True))

    if b['p_hp'] <= 0: await lose_battle(update, context, player)
    else: player.base_stats['health'] = b['p_hp']

async def handle_enemy_death(update, context, player, battle_data):
    enemy = battle_data['enemy']
    if "phases" in enemy and battle_data['phase'] <= len(enemy["phases"]):
        phase_data = enemy["phases"][battle_data['phase'] - 1]
        battle_data['phase'] += 1
        battle_data['e_hp'] = phase_data['health']
        enemy['attack'] = phase_data['attack']
        enemy['name'] = phase_data['name']
        enemy['image'] = phase_data['image']

        # Load Phase resistances if exist
        if "resistances" in phase_data:
            enemy['resistances'] = phase_data['resistances']

        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=enemy['image'],
            caption=f"⚠️ **{enemy['name']} ВОЗРОЖДАЕТСЯ!** (Фаза {battle_data['phase']})\n\n{phase_data.get('message', 'Враг стал сильнее!')}\nHP: {battle_data['e_hp']} | ATK: {enemy['attack']}",
            parse_mode='Markdown'
        )
        return
    await win_battle(update, context, player, battle_data['enemy'], battle_data['e_id'])

async def win_battle(update, context, player, enemy, enemy_id):
    context.user_data['in_battle'] = False

    # Regeneration Logic
    max_hp = player.get_max_health()
    current_hp = player.base_stats['health']
    heal_amt = int(max_hp * 0.3) # 30% regen
    player.base_stats['health'] = min(max_hp, current_hp + heal_amt)
    healed = player.base_stats['health'] - current_hp

    status_msg = f"\n💚 Восстановлено сил: +{healed} HP."

    if player.tick_effects(): status_msg += "\n⏳ Действие некоторых зелий закончилось."

    is_event_battle = context.user_data.get('in_battle_from_event')
    rewards = {'experience': enemy['experience'], 'gold': int(enemy['experience'] * 0.8)}

    if enemy.get('is_boss'):
        player.defeated_bosses.add(enemy_id)
        player.artifact_slots += 1
        rewards['gold'] += 100
        await update.message.reply_text(f"🏆 **БОСС ПОВЕРЖЕН!** Слот под артефакт открыт!{status_msg}")
    else:
        await update.message.reply_text(f"⚔️ **Победа!**{status_msg}")

    player.kill_count[enemy_id] = player.kill_count.get(enemy_id, 0) + 1
    for q_id in player.active_quests[:]:
        quest = QUESTS.get(q_id)
        if quest and all(player.kill_count.get(mob, 0) >= count for mob, count in quest.get('objectives', {}).items()):
            player.active_quests.remove(q_id)
            player.completed_quests.append(q_id)
            await update.message.reply_text(f"✅ **Квест '{quest['name']}' выполнен!**")
            await apply_rewards(update, player, quest['rewards'])

    if player.experience >= player.level * 100:
        player.experience -= player.level * 100
        player.level += 1
        player.base_stats['attack'] += 2
        player.base_stats['health'] += 10
        await update.message.reply_text(f"🆙 **Уровень {player.level}!**\n❤️+10, ⚔️+2")

        # Check for new ability unlock immediately
        c_data = CLASSES.get(player.class_name)
        if c_data and 'unlocks' in c_data:
            new_skills = c_data['unlocks'].get(str(player.level))
            if new_skills:
                await update.message.reply_text(f"✨ **Новая способность разблокирована:** {', '.join(new_skills)}!")

    if is_event_battle:
        context.user_data['in_battle_from_event'] = False
        await apply_rewards(update, player, rewards)
        await continue_event_chain(update, context, player, "win")
    elif context.user_data.get('in_story'):
        await apply_rewards(update, player, rewards)
        story_data = context.user_data.get('current_story', {})
        current_scene = next((s for s in story_data['storyline'] if s["id"] == story_data['current_scene']), None)
        if current_scene and current_scene.get("next_scene"):
             player.story_progress[story_data['city']] = current_scene["next_scene"]
             await show_story_scene(update, context, player, story_data['city'], current_scene["next_scene"])
        else:
             context.user_data['in_story'] = False
             await show_location(update, context, player, player.location)
    else:
        await apply_rewards(update, player, rewards)
        await show_location(update, context, player, player.location)

async def lose_battle(update: Update, context: ContextTypes.DEFAULT_TYPE, player):
    last_location_before_battle = player.last_location if player.last_location in LOCATIONS else "village_square"

    await update.message.reply_text(
        "💀 **Поражение!** Вы пали в бою...\n"
        "Вы возрождаетесь в лагере для восстановления сил.",
        parse_mode='Markdown'
    )

    context.user_data['in_battle'] = False
    context.user_data['in_battle_from_event'] = False
    context.user_data['in_story'] = False

    if player.active_effects:
        player.active_effects = []
        await update.message.reply_text("☠️ Эффекты всех зелий рассеялись.")

    player.base_stats['health'] = CLASSES[player.class_name]['base_stats']['health'] + (player.level - 1) * 10

    location = LOCATIONS.get("player_camp", {
        "name": "Лагерь",
        "description": "Безопасное место.",
        "image": "https://i.imgur.com/6ZJZT8q.jpeg"
    })
    player.location = "player_camp"

    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=location["image"],
        caption=f"**{location['name']}**\n\n{location['description']}\n⏳ _Отдых 15 секунд..._",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )

    await asyncio.sleep(15)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⏰ 15 секунд прошло! Возвращаемся к приключениям..."
    )
    await show_location(update, context, player, last_location_before_battle)

# --- INVENTORY & ITEMS ---

async def show_inventory_menu(update, context, player):
    context.user_data['in_inventory'] = True
    context.user_data['viewing_item'] = None
    msg = f"🎒 **Инвентарь**\n💰 {player.gold}\n📦 Артефакты: {len(player.equipped_artifacts)}/{player.artifact_slots}\n\n"
    if not player.inventory: msg += "Пусто."
    item_counts = {i: player.inventory.count(i) for i in set(player.inventory)}
    buttons = []
    for item_id, count in item_counts.items():
        item = ITEMS.get(item_id)
        if item:
            status = " (E)" if item_id in player.equipped_artifacts else ""
            buttons.append(KeyboardButton(f"{item['name']} x{count}{status}"))
    buttons.append(KeyboardButton("⬅️ Назад"))
    layout = get_keyboard_layout(buttons, 2)
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=ReplyKeyboardMarkup(layout, resize_keyboard=True))

async def handle_inventory_action(update, context, player, text):
    if text == "⬅️ Назад":
        if context.user_data.get('viewing_item'): await show_inventory_menu(update, context, player)
        else: await show_location(update, context, player, player.location)
        return
    if not context.user_data.get('viewing_item'):
        for item_id in set(player.inventory):
            item = ITEMS.get(item_id)
            if item:
                status = " (E)" if item_id in player.equipped_artifacts else ""
                if text == f"{item['name']} x{player.inventory.count(item_id)}{status}":
                    await show_item_details(update, context, player, item_id)
                    return
    item_id = context.user_data.get('viewing_item')
    if item_id:
        item = ITEMS.get(item_id)
        if text == "🖐 Использовать" and item:
            if item['type'] == 'consumable':
                player.inventory.remove(item_id)
                if 'stats' in item and 'health' in item['stats']:
                    heal = item['stats']['health']
                    player.base_stats['health'] = min(player.get_max_health(), player.base_stats['health'] + heal)
                    await update.message.reply_text(f"❤️ Восстановлено {heal} HP.")
                if 'buffs' in item:
                    buff_stats = {k: v for k, v in item['buffs'].items() if k != 'duration'}
                    duration = item['buffs'].get('duration', 1)
                    player.add_effect(item['name'], buff_stats, duration)
                    await update.message.reply_text(f"🧪 Выпит {item['name']}. Эффект на {duration} боев.")
                await show_inventory_menu(update, context, player)
        elif text == "🛡️ Надеть":
            success, msg = player.equip_artifact(item_id)
            await update.message.reply_text(msg)
            await show_inventory_menu(update, context, player)
        elif text == "🔻 Снять":
            success, msg = player.unequip_artifact(item_id)
            await update.message.reply_text(msg)
            await show_inventory_menu(update, context, player)

async def show_item_details(update, context, player, item_id):
    context.user_data['viewing_item'] = item_id
    item = ITEMS[item_id]
    desc = f"**{item['name']}**\n{item['description']}"
    if 'stats' in item: desc += "\n" + ", ".join([f"{k.upper()}: {v}" for k,v in item['stats'].items()])
    if 'buffs' in item:
        dur = item['buffs'].get('duration', 1)
        desc += f"\n⏳ Длительность: {dur} боев"

    buttons = []
    if item['type'] == 'consumable': buttons.append(KeyboardButton("🖐 Использовать"))
    elif item['type'] == 'artifact':
        if item_id in player.equipped_artifacts: buttons.append(KeyboardButton("🔻 Снять"))
        else: buttons.append(KeyboardButton("🛡️ Надеть"))
    buttons.append(KeyboardButton("⬅️ Назад"))
    layout = get_keyboard_layout(buttons, 2)
    await update.message.reply_text(desc, parse_mode='Markdown', reply_markup=ReplyKeyboardMarkup(layout, resize_keyboard=True))

# --- SHOP SYSTEM (CONFIRMATION ADDED) ---

async def start_shop(update, context, player, shop_items):
    context.user_data['in_shop'] = True
    context.user_data['current_shop_items'] = shop_items
    await show_shop_menu(update, context, player, shop_items)

async def show_shop_menu(update, context, player, items):
    msg = f"🏪 **Магазин**\n💰 {player.gold}\n_Нажмите на предмет, чтобы увидеть описание и купить._"
    buttons = []
    for item_id in items:
        item = ITEMS.get(item_id)
        if item: buttons.append(KeyboardButton(f"{item['name']} ({item['price']}💰)"))
    buttons.append(KeyboardButton("💰 Продать предметы"))
    buttons.append(KeyboardButton("⬅️ Назад"))
    layout = get_keyboard_layout(buttons, 1)
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=ReplyKeyboardMarkup(layout, resize_keyboard=True))

async def show_shop_item_details(update, context, player, item_id, is_selling=False):
    item = ITEMS[item_id]
    desc = f"**{item['name']}**\n{item['description']}"
    if 'stats' in item: desc += "\n" + ", ".join([f"{k.upper()}: {v}" for k,v in item['stats'].items()])

    if is_selling:
        sell_price = max(1, int(item['price'] * 0.5))
        desc += f"\n\n💰 Цена продажи: {sell_price}"
        buttons = [[KeyboardButton("✅ Подтвердить продажу")], [KeyboardButton("⬅️ Назад")]]
        context.user_data['shop_confirm_sell'] = item_id
    else:
        desc += f"\n\n💰 Цена: {item['price']}"
        buttons = [[KeyboardButton("✅ Подтвердить покупку")], [KeyboardButton("⬅️ Назад")]]
        context.user_data['shop_confirm_buy'] = item_id

    await update.message.reply_text(desc, parse_mode='Markdown', reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))

async def show_sell_menu(update, context, player):
    context.user_data['in_shop_sell'] = True
    msg = f"💰 **Скупка краденого**\nЯ куплю твои вещи за полцены.\nУ тебя: {player.gold}💰\n_Нажмите, чтобы увидеть детали._"
    buttons = []
    seen = set()
    for item_id in player.inventory:
        if item_id in seen: continue
        if item_id in player.equipped_artifacts: continue
        item = ITEMS.get(item_id)
        if item:
            seen.add(item_id)
            count = player.inventory.count(item_id)
            sell_price = max(1, int(item['price'] * 0.5))
            buttons.append(KeyboardButton(f"{item['name']} ({sell_price}💰) x{count}"))
    buttons.append(KeyboardButton("⬅️ Назад"))
    layout = get_keyboard_layout(buttons, 1)
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=ReplyKeyboardMarkup(layout, resize_keyboard=True))

async def handle_shop_action(update, context, player, text):
    if text == "⬅️ Назад":
        if context.user_data.get('shop_confirm_buy') or context.user_data.get('shop_confirm_sell'):
            # Back from details to list
            context.user_data['shop_confirm_buy'] = None
            context.user_data['shop_confirm_sell'] = None
            if context.user_data.get('in_shop_sell'):
                await show_sell_menu(update, context, player)
            else:
                await show_shop_menu(update, context, player, context.user_data.get('current_shop_items', []))
        elif context.user_data.get('in_shop_sell'):
            context.user_data['in_shop_sell'] = False
            await show_shop_menu(update, context, player, context.user_data.get('current_shop_items', []))
        else:
            context.user_data['in_shop'] = False
            await show_location(update, context, player, player.location)
        return

    # --- Buying Logic ---
    if context.user_data.get('shop_confirm_buy'):
        if text == "✅ Подтвердить покупку":
            item_id = context.user_data['shop_confirm_buy']
            item = ITEMS[item_id]
            if player.gold >= item['price']:
                player.gold -= item['price']
                player.inventory.append(item_id)
                await update.message.reply_text(f"✅ Вы купили: {item['name']}")
                context.user_data['shop_confirm_buy'] = None
                await show_shop_menu(update, context, player, context.user_data.get('current_shop_items', []))
            else:
                await update.message.reply_text("❌ Не хватает золота!")
        return

    # --- Selling Logic ---
    if context.user_data.get('shop_confirm_sell'):
        if text == "✅ Подтвердить продажу":
            item_id = context.user_data['shop_confirm_sell']
            item = ITEMS[item_id]
            sell_price = max(1, int(item['price'] * 0.5))
            if item_id in player.inventory:
                player.inventory.remove(item_id)
                player.gold += sell_price
                await update.message.reply_text(f"✅ Вы продали {item['name']} за {sell_price}💰")
                context.user_data['shop_confirm_sell'] = None
                await show_sell_menu(update, context, player)
            else:
                 await update.message.reply_text("❌ Предмет уже продан или отсутствует.")
        return

    # --- Navigation Logic ---
    if text == "💰 Продать предметы":
        await show_sell_menu(update, context, player)
        return

    # Check clicked items in Sell Menu
    if context.user_data.get('in_shop_sell'):
        for item_id in set(player.inventory):
            item = ITEMS.get(item_id)
            if not item: continue
            sell_price = max(1, int(item['price'] * 0.5))
            count = player.inventory.count(item_id)
            if text == f"{item['name']} ({sell_price}💰) x{count}":
                await show_shop_item_details(update, context, player, item_id, is_selling=True)
                return
    else:
        # Check clicked items in Buy Menu
        shop_items = context.user_data.get('current_shop_items', [])
        selected = next((iid for iid in shop_items if ITEMS.get(iid) and text.startswith(ITEMS[iid]['name'])), None)
        if selected:
             await show_shop_item_details(update, context, player, selected, is_selling=False)

# --- TELEPORT & STATS (UNCHANGED) ---

async def show_city_teleport_menu(update, context, player):
    context.user_data['in_city_teleport'] = True
    buttons = []
    for city_id in player.unlocked_cities:
        if city_id != player.current_city:
            city_name = LOCATIONS[city_id]['name']
            buttons.append(KeyboardButton(f"📍 {city_name}"))
    buttons.append(KeyboardButton("⬅️ Назад"))
    layout = get_keyboard_layout(buttons, 2)
    await update.message.reply_text("🚀 **Телепортация**\nВыберите город:", parse_mode='Markdown', reply_markup=ReplyKeyboardMarkup(layout, resize_keyboard=True))

async def handle_city_teleport(update, context, player, text):
    if text == "⬅️ Назад":
        context.user_data['in_city_teleport'] = False
        await show_location(update, context, player, player.current_city)
        return
    for city_id in player.unlocked_cities:
        city_name = LOCATIONS[city_id]['name']
        if text == f"📍 {city_name}":
            context.user_data['in_city_teleport'] = False
            await update.message.reply_text(f"✨ Перемещение в {city_name}...")
            await show_location(update, context, player, city_id)
            return

async def show_stats(update, context, player):
    player.update_fatigue()
    stats = player.get_total_stats()
    loc_name = "Неизвестно"
    if player.location in LOCATIONS: loc_name = LOCATIONS[player.location]['name']
    time_msg = "\n⏳ Восстановление энергии: 100 ед. за 1 час."
    msg = (f"📊 **Герой** (Ур. {player.level})\n❤️ {stats['health']} ⚔️ {stats['attack']} 🛡️ {stats['defense']}\n💰 {player.gold} 😴 {int(player.fatigue)}%{time_msg}\n📍 {loc_name}\n📜 Квесты: {len(player.active_quests)}")
    if player.active_effects:
        msg += "\n\n🧪 **Активные эффекты:**"
        for e in player.active_effects: msg += f"\n• {e['name']} ({e['duration']} боев)"

    image_url = "https://i.imgur.com/3Vk5Q7a.jpeg"
    if player.class_name:
         c_data = CLASSES.get(player.class_name)
         if c_data and 'image' in c_data: image_url = c_data['image']

    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=image_url,
        caption=msg,
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("⬅️ Назад")]], resize_keyboard=True)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text
    user_id = update.effective_user.id
    player = get_player(user_id)

    if player.location == "player_camp":
        await update.message.reply_text("💤 Вы восстанавливаете силы...")
        return

    if player.location == "class_selection":
        await handle_class_selection(update, context, player, text)
        return
    if context.user_data.get('in_battle'):
        await handle_battle(update, context, player, text)
        return
    if context.user_data.get('in_story'):
        await handle_story_action(update, context, player, text)
        return
    if context.user_data.get('in_random_event'):
        await handle_random_event_action(update, context, player, text)
        return
    if context.user_data.get('in_city_teleport'):
        await handle_city_teleport(update, context, player, text)
        return
    if context.user_data.get('in_inventory'):
        await handle_inventory_action(update, context, player, text)
        return
    if context.user_data.get('in_shop') or context.user_data.get('in_shop_sell') or context.user_data.get('shop_confirm_buy') or context.user_data.get('shop_confirm_sell'):
        await handle_shop_action(update, context, player, text)
        return

    if text == "📊 Характеристики":
        await show_stats(update, context, player)
        return
    if text == "🎒 Инвентарь":
        await show_inventory_menu(update, context, player)
        return
    if text == "🚀 Телепортация":
        await show_city_teleport_menu(update, context, player)
        return
    if text == "⬅️ Назад":
        await generic_back_button(update, context, player)
        return
    if text == "🏠 В город":
        await show_location(update, context, player, player.current_city)
        return

    if not await handle_location_action(update, context, player, text):
        await show_location(update, context, player, player.location)

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("restart", restart))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()


