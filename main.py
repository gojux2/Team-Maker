import discord
from discord.ext import commands
import itertools
import os
import random
import threading
from flask import Flask
import base64
import firebase_admin
from firebase_admin import credentials, db

# --- Flaskによるスリープ対策サーバー ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask).start()

# --- Firebase認証情報の復号とファイル作成 ---
firebase_cred_base64 = os.environ.get("FIREBASE_CRED_BASE64")
firebase_cred_path = "serviceAccountKey.json"

if not firebase_cred_base64:
    raise ValueError("環境変数 FIREBASE_CRED_BASE64 が設定されていません")

with open(firebase_cred_path, "wb") as f:
    f.write(base64.b64decode(firebase_cred_base64))

firebase_db_url = os.environ.get("FIREBASE_DB_URL")
if not firebase_db_url:
    raise ValueError("環境変数 FIREBASE_DB_URL が設定されていません")

# --- Firebase初期化 ---
cred = credentials.Certificate(firebase_cred_path)
firebase_admin.initialize_app(cred, {
    'databaseURL': firebase_db_url
})

ref = db.reference('members')
history_ref = db.reference('history')
settings_ref = db.reference('settings')

def save_members(members_dict):
    ref.set(members_dict)

def get_members():
    data = ref.get()
    return data if data else {}

def save_history(history_list):
    history_ref.set(history_list)

def get_history():
    data = history_ref.get()
    return data if data else []

def save_settings(settings_dict):
    settings_ref.set(settings_dict)

def load_settings():
    return settings_ref.get() or {}

def check_participants_minimum(min_required=10):
    current_count = len(participants)
    if current_count < min_required:
        return min_required - current_count
    return 0

def validate_participant_count_message():
    count = len(participants)
    if count < 10:
        return f"参加者があと{10 - count}人必要です。"
    if count > 10:
        return f"参加者が{count}人います。"
    return None

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

class TeamBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()

bot = TeamBot()

members = get_members()
participants = set()
raw_history = get_history()
history = [(frozenset(t[0]), frozenset(t[1])) for t in raw_history]

settings = load_settings()
power_diff_tolerance = settings.get('power_diff_tolerance', 10)
initial_power = settings.get('initial_power', 50)

def extract_name(name_str):
    if name_str.startswith("<@") and name_str.endswith(">"):
        return name_str.strip("<@!>")
    return name_str

def get_display_name(guild, name):
    member = discord.utils.find(lambda m: m.name == name or str(m.id) == name, guild.members) if guild else None
    if member:
        return member.display_name
    return name

def normalize_pair(t1, t2):
    t1_sorted = frozenset(sorted(t1))
    t2_sorted = frozenset(sorted(t2))
    return (t1_sorted, t2_sorted) if t1_sorted < t2_sorted else (t2_sorted, t1_sorted)

def member_repeat_score(t1, t2):
    score = 0
    weights = [100, 10, 5, 2, 1]  # 直近履歴の重み付け強化
    current = normalize_pair(t1, t2)
    for idx, past in enumerate(history[::-1]):
        past_norm = normalize_pair(past[0], past[1])
        weight = weights[idx] if idx < len(weights) else 1
        if current[0] == past_norm[0] and current[1] == past_norm[1]:
            score += weight * len(t1.intersection(past[0]))
            score += weight * len(t2.intersection(past[1]))
        elif current[0] == past_norm[1] and current[1] == past_norm[0]:
            score += weight * len(t1.intersection(past[1]))
            score += weight * len(t2.intersection(past[0]))
    return score

def count_overlap(set1, set2):
    return len(set1.intersection(set2))

def decide_swap(team1, team2, prev_team1, prev_team2):
    overlap_normal = count_overlap(team1, prev_team1) + count_overlap(team2, prev_team2)
    overlap_swapped = count_overlap(team1, prev_team2) + count_overlap(team2, prev_team1)
    if overlap_swapped < overlap_normal:
        return team2, team1  # スワップしたほうが重複少ないなら切り替える
    else:
        return team1, team2

async def handle_participation_add(guild, name, channel):
    global participants, members, initial_power
    key_name = extract_name(name)
    notice = ""
    if key_name not in members:
        members[key_name] = initial_power
        save_members(members)
        notice = f"(未登録のためパワー{initial_power}で登録しました)"
    participants.add(key_name)
    display_name = get_display_name(guild, key_name)

    if notice:
        await channel.send(f"{display_name} が参加しました。\n{notice}")
    else:
        await channel.send(f"{display_name} が参加しました。")

@bot.command(name="make_teams")
async def make_teams_cmd(ctx, *args):
    msg = validate_participant_count_message()
    if msg is not None:
        await ctx.send(msg)
        return

    global participants, members, history, power_diff_tolerance

    names = list(participants)
    if len(names) != 10:
        await ctx.send("参加者が10人ではありません。")
        return

    full_candidates = []

    for comb in itertools.combinations(names, 5):
        team1 = frozenset(comb)
        team2 = frozenset(n for n in names if n not in comb)

        sum1 = sum(members.get(n, 0) for n in team1)
        sum2 = sum(members.get(n, 0) for n in team2)
        diff = abs(sum1 - sum2)

        repeat_score = member_repeat_score(team1, team2)

        candidate = {
            'team1': team1,
            'team2': team2,
            'diff': diff,
            'repeat_score': repeat_score
        }
        full_candidates.append(candidate)

    full_candidates.sort(key=lambda c: (c['repeat_score'], c['diff']))
    selected = random.choice(full_candidates[:min(5, len(full_candidates))])

    team1 = selected['team1']
    team2 = selected['team2']

    if history:
        prev_team1, prev_team2 = history[-1]
        team1, team2 = decide_swap(team1, team2, prev_team1, prev_team2)

    history.append((team1, team2))
    if len(history) > 10:
        history.pop(0)
    save_history([(list(t[0]), list(t[1])) for t in history])

    sorted_team1 = sorted(team1, key=lambda n: members.get(n, 0), reverse=True)
    sorted_team2 = sorted(team2, key=lambda n: members.get(n, 0), reverse=True)

    display_team1 = [get_display_name(ctx.guild, n) for n in sorted_team1]
    display_team2 = [get_display_name(ctx.guild, n) for n in sorted_team2]

    embed = discord.Embed(color=0xffa500)
    embed.add_field(
        name=f"チーム1 (合計: {sum(members.get(n, 0) for n in team1)})",
        value=" ".join(f"[ {name} ]" for name in display_team1),
        inline=False)
    embed.add_field(
        name=f"チーム2 (合計: {sum(members.get(n, 0) for n in team2)})",
        value=" ".join(f"[ {name} ]" for name in display_team2),
        inline=False)

    if selected['diff'] > power_diff_tolerance:
        await ctx.send(f"パワー差許容範囲内（{power_diff_tolerance}）のチーム分けが見つかりませんでした。")

    await ctx.send(embed=embed)

@bot.tree.command(name="make_teams", description="10人の参加者を5v5に分ける標準的なチーム分け")
async def slash_make_teams(interaction: discord.Interaction):
    msg = validate_participant_count_message()
    if msg is not None:
        await interaction.response.send_message(msg)
        return

    global participants, members, history, power_diff_tolerance

    names = list(participants)
    if len(names) != 10:
        await interaction.response.send_message("参加者が10人ではありません。")
        return

    full_candidates = []

    for comb in itertools.combinations(names, 5):
        team1 = frozenset(comb)
        team2 = frozenset(n for n in names if n not in comb)

        sum1 = sum(members.get(n, 0) for n in team1)
        sum2 = sum(members.get(n, 0) for n in team2)
        diff = abs(sum1 - sum2)

        repeat_score = member_repeat_score(team1, team2)

        candidate = {
            'team1': team1,
            'team2': team2,
            'diff': diff,
            'repeat_score': repeat_score
        }
        full_candidates.append(candidate)

    full_candidates.sort(key=lambda c: (c['repeat_score'], c['diff']))
    selected = random.choice(full_candidates[:min(5, len(full_candidates))])

    team1 = selected['team1']
    team2 = selected['team2']

    if history:
        prev_team1, prev_team2 = history[-1]
        team1, team2 = decide_swap(team1, team2, prev_team1, prev_team2)

    history.append((team1, team2))
    if len(history) > 10:
        history.pop(0)
    save_history([(list(t[0]), list(t[1])) for t in history])

    sorted_team1 = sorted(team1, key=lambda n: members.get(n, 0), reverse=True)
    sorted_team2 = sorted(team2, key=lambda n: members.get(n, 0), reverse=True)

    display_team1 = [get_display_name(interaction.guild, n) for n in sorted_team1]
    display_team2 = [get_display_name(interaction.guild, n) for n in sorted_team2]

    embed = discord.Embed(color=0xffa500)
    embed.add_field(
        name=f"チーム1 (合計: {sum(members.get(n, 0) for n in team1)})",
        value=" ".join(f"[ {name} ]" for name in display_team1),
        inline=False)
    embed.add_field(
        name=f"チーム2 (合計: {sum(members.get(n, 0) for n in team2)})",
        value=" ".join(f"[ {name} ]" for name in display_team2),
        inline=False)

    if selected['diff'] > power_diff_tolerance:
        await interaction.response.send_message(f"パワー差許容範囲内（{power_diff_tolerance}）のチーム分けが見つかりませんでした。")
        return

    await interaction.response.send_message(embed=embed)

# ... (他のコマンドやイベント処理は省略しませんが、この部分が今回のご要望の中心です)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

if __name__ == "__main__":
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if not TOKEN:
        raise ValueError("環境変数DISCORD_TOKENがセットされていません")
    bot.run(TOKEN)
