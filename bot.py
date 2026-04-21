import os
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord.ext import commands, tasks
from discord import app_commands
from zoneinfo import ZoneInfo
from datetime import time, datetime
# =========================
# CONFIG
# =========================

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1381856917772701696      # optional but recommended for faster slash command sync
CHANNEL_ID = 1495997921110261840    # channel where the daily shop will post

DATA_DIR = Path("bot_data")
DATA_DIR.mkdir(exist_ok=True)

PLAYERS_FILE = DATA_DIR / "players.json"
STATE_FILE = DATA_DIR / "shop_state.json"

# Rarity weights tuned to your target averages for the 4-item shared shop:
# ~ Epic every other day
# ~ Legendary twice a week
# ~ Mythic once a week
RARITY_WEIGHTS = {
    "Common": 26.79,
    "Uncommon": 28.00,
    "Rare": 22.00,
    "Epic": 12.50,
    "Legendary": 7.14,
    "Mythic": 3.57,
}

ITEMS = {
    "Common": [
        {"name": "Steak Bundle", "price": lambda r: f"{r.randint(4,6)} shells"},
        {"name": "Builder Crate", "price": lambda r: f"{r.randint(4,6)} shells"},
        {"name": "Light Pack", "price": lambda r: f"{r.randint(2,4)} shells"},
        {"name": "Regeneration Brew", "price": lambda r: f"{r.randint(6,8)} shells"},
    ],

    "Uncommon": [
        {"name": "Swiftstep Boots (Iron)", "price": lambda r: f"{r.randint(16,20)} shells"},
        {"name": "Luck Potion", "price": lambda r: f"{r.randint(16,18)} shells"},
        {"name": "Archer Bundle", "price": lambda r: f"{r.randint(10,12)} shells"},
    ],

    "Rare": [
        {"name": "Quarry Pick", "price": lambda r: f"{r.randint(48,64)} shells"},
        {"name": "Villager Spawn Egg", "price": lambda r: f"{r.randint(48,52)} shells"},
        {"name": "Skycaller Boots", "price": lambda r: f"{r.randint(44,64)} shells"},
        {"name": "Jump Pad", "price": lambda r: f"{r.randint(58,64)} shells"},
        {"name": "Totem of Undying", "price": lambda r: f"{r.randint(32,40)} shells"},
    ],

    "Epic": [
        {"name": "Edgeblade", "price": lambda r: f"{r.randint(160,180)} shells"},
        {"name": "Swiftstep Boots (Diamond)", "price": lambda r: f"{r.randint(192,208)} shells"},
        {"name": "Warlord Blade", "price": lambda r: f"{r.randint(224,248)} shells"},
        {"name": "Excavator Core", "price": lambda r: f"{r.randint(224,248)} shells"},
        {"name": "Iron Skin Charm", "price": lambda r: f"{r.randint(264,300)} shells"},
    ],

    "Legendary": [
        {"name": "Heart Sigil", "price": "640 shells"},
        {"name": "Loot Magnet", "price": "512 shells"},
        {"name": "Blood Pact", "price": "480 shells"},
        {"name": "Storm Charm", "price": "512 shells"},

        {"name": "Blaze Spawn Egg", "price": "512 shells"},
        {"name": "Enderman Spawn Egg", "price": "512 shells"},
        {"name": "Skeleton Spawn Egg", "price": "512 shells"},
        {"name": "Cow Spawn Egg", "price": "512 shells"},
        {"name": "Pig Spawn Egg", "price": "512 shells"},
        {"name": "Creeper Spawn Egg", "price": "512 shells"},
    ],

    "Mythic": [
        {"name": "Crown Core", "price": "800 shells"},
        {"name": "Crown Frame", "price": "800 shells"},
        {"name": "Crown Gems", "price": "800 shells"},

        {"name": "Black Flash Charm", "price": "1600 shells"},
    ],
}


# =========================
# FILE HELPERS
# =========================

def load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_players() -> list[str]:
    return load_json(PLAYERS_FILE, ["EnzerYT"])

def save_players(players: list[str]) -> None:
    save_json(PLAYERS_FILE, sorted(set(players), key=str.lower))

def load_state() -> dict:
    return load_json(STATE_FILE, {})

def save_state(state: dict) -> None:
    save_json(STATE_FILE, state)


# =========================
# SHOP LOGIC
# =========================

def today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def weighted_rarity(rng: random.Random) -> str:
    rarities = list(RARITY_WEIGHTS.keys())
    weights = list(RARITY_WEIGHTS.values())
    return rng.choices(rarities, weights=weights, k=1)[0]

def pick_item_from_rarity(rng: random.Random, rarity: str, used_names: set[str]) -> dict:
    pool = [item for item in ITEMS[rarity] if item["name"] not in used_names]
    if not pool:
        pool = ITEMS[rarity][:]

    chosen = rng.choice(pool)

    price = chosen["price"]
    if callable(price):
        price = price(rng)

    return {
        "rarity": rarity,
        "name": chosen["name"],
        "price": price
    }

def generate_shop(seed_text: str, players: list[str]) -> tuple[list[dict], dict[str, dict]]:
    rng = random.Random(seed_text)
    used_names: set[str] = set()

    shop_items = []
    for _ in range(4):
        rarity = weighted_rarity(rng)
        item = pick_item_from_rarity(rng, rarity, used_names)
        used_names.add(item["name"])
        shop_items.append(item)

    personal_items = {}
    for player in players:
        rarity = weighted_rarity(rng)
        item = pick_item_from_rarity(rng, rarity, used_names)
        used_names.add(item["name"])
        personal_items[player] = item

    return shop_items, personal_items

def force_generate_shop(seed_text: str | None = None) -> tuple[list[dict], dict[str, dict], str]:
    players = load_players()
    if not seed_text:
        seed_text = today_key()
    shop_items, personal_items = generate_shop(seed_text, players)
    state = {
        "last_posted_day": today_key(),
        "last_seed": seed_text,
        "shop_items": shop_items,
        "personal_items": personal_items,
    }
    save_state(state)
    return shop_items, personal_items, seed_text

def next_refresh_dt() -> datetime:
    now = datetime.now(TORONTO_TZ)
    target = now.replace(hour=20, minute=0, second=0, microsecond=0)

    if now >= target:
        from datetime import timedelta
        target = target + timedelta(days=1)

    return target

def discord_relative_timestamp(dt: datetime) -> str:
    return f"<t:{int(dt.timestamp())}:R>"

def discord_full_timestamp(dt: datetime) -> str:
    return f"<t:{int(dt.timestamp())}:F>"

def build_embed(shop_items: list[dict], personal_items: dict[str, dict], label: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"Daily Shop — {label}",
        description="4 shared items + 1 personal item per player",
        colour=discord.Colour.purple(),
    )

    refresh = next_refresh_dt()
    embed.add_field(
        name="Next Refresh",
        value=f"{discord_relative_timestamp(refresh)}\n{discord_full_timestamp(refresh)}",
        inline=False,
    )
    
    shop_lines = []
    for i, item in enumerate(shop_items, start=1):
        shop_lines.append(
            f"**{i}. {item['name']}**\n"
            f"Rarity: {item['rarity']}\n"
            f"Price: {item['price']}"
        )
    embed.add_field(name="Shared Shop", value="\n\n".join(shop_lines) or "No items", inline=False)

    personal_lines = []
    for player, item in personal_items.items():
        personal_lines.append(
            f"**{player}** → {item['name']} ({item['rarity']}) — {item['price']}"
        )
    embed.add_field(
        name="Personal Daily Items",
        value="\n".join(personal_lines) or "No players configured",
        inline=False,
    )

    embed.set_footer(text="Refreshes every 24 hours")
    return embed


# =========================
# DISCORD BOT
# =========================

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

def is_admin(interaction: discord.Interaction) -> bool:
    user = interaction.user
    if not isinstance(user, discord.Member):
        return False
    return user.guild_permissions.manage_guild or user.guild_permissions.administrator

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")

    guild_obj = discord.Object(id=GUILD_ID) if GUILD_ID else None
    try:
        if guild_obj:
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            print(f"Synced {len(synced)} guild commands.")
        else:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} global commands.")
    except Exception as e:
        print(f"Command sync failed: {e}")

    # 🔥 SEND SHOP ON START
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        day = today_key()
        shop_items, personal_items, _ = force_generate_shop(day)
        embed = build_embed(shop_items, personal_items, day)
        await channel.send(embed=embed)
        print("Posted shop on startup")

    # START DAILY LOOP
    if not post_daily_shop.is_running():
        post_daily_shop.start()

TORONTO_TZ = ZoneInfo("America/Toronto")

@tasks.loop(time=time(hour=20, minute=0, tzinfo=TORONTO_TZ))
async def post_daily_shop():
    await bot.wait_until_ready()

    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        print("Channel not found.")
        return

    state = load_state()
    day = today_key()
    if state.get("last_posted_day") == day:
        return

    shop_items, personal_items, seed = force_generate_shop(day)
    embed = build_embed(shop_items, personal_items, day)
    await channel.send(embed=embed)
    print(f"Posted shop for {day} with seed {seed}")

@post_daily_shop.before_loop
async def before_daily_shop():
    await bot.wait_until_ready()


# =========================
# SLASH COMMANDS
# =========================

@bot.tree.command(name="shop", description="Show today's shop")
async def shop(interaction: discord.Interaction):
    day = today_key()
    shop_items, personal_items, _ = force_generate_shop(day)
    embed = build_embed(shop_items, personal_items, day)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="players", description="List configured player names")
async def players(interaction: discord.Interaction):
    current_players = load_players()
    text = "\n".join(f"- {p}" for p in current_players) or "No players configured."
    await interaction.response.send_message(f"Configured players:\n{text}")

@bot.tree.command(name="addplayer", description="Add a player name to the personal roll list")
@app_commands.describe(name="Minecraft player name")
async def addplayer(interaction: discord.Interaction, name: str):
    if not is_admin(interaction):
        await interaction.response.send_message("You need Manage Server or Administrator for this.", ephemeral=True)
        return

    current_players = load_players()
    if name in current_players:
        await interaction.response.send_message(f"`{name}` is already in the list.", ephemeral=True)
        return

    current_players.append(name)
    save_players(current_players)
    await interaction.response.send_message(f"Added `{name}`.")

@bot.tree.command(name="removeplayer", description="Remove a player name from the personal roll list")
@app_commands.describe(name="Minecraft player name")
async def removeplayer(interaction: discord.Interaction, name: str):
    if not is_admin(interaction):
        await interaction.response.send_message("You need Manage Server or Administrator for this.", ephemeral=True)
        return

    current_players = load_players()
    if name not in current_players:
        await interaction.response.send_message(f"`{name}` is not in the list.", ephemeral=True)
        return

    current_players.remove(name)
    save_players(current_players)
    await interaction.response.send_message(f"Removed `{name}`.")

@bot.tree.command(name="forceshop", description="Post today's shop to the configured channel right now")
async def forceshop(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("You need Manage Server or Administrator for this.", ephemeral=True)
        return

    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        await interaction.response.send_message("Configured channel not found.", ephemeral=True)
        return

    day = today_key()
    shop_items, personal_items, _ = force_generate_shop(day)
    embed = build_embed(shop_items, personal_items, day)
    await channel.send(embed=embed)
    await interaction.response.send_message("Posted today's shop.", ephemeral=True)

@bot.tree.command(name="rerollshop", description="Reroll today's shop and post the new version")
async def rerollshop(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("You need Manage Server or Administrator for this.", ephemeral=True)
        return

    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        await interaction.response.send_message("Configured channel not found.", ephemeral=True)
        return

    reroll_seed = f"{today_key()}-reroll-{random.randint(100000, 999999)}"
    shop_items, personal_items, seed = force_generate_shop(reroll_seed)
    embed = build_embed(shop_items, personal_items, f"{today_key()} (rerolled)")
    await channel.send(embed=embed)
    await interaction.response.send_message(f"Rerolled and posted. Seed: `{seed}`", ephemeral=True)

bot.run(TOKEN)
