import discord
from discord import app_commands
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

def save_settings(power_diff):
    settings_ref.set({'power_diff_tolerance': power_diff})

def load_settings():
    data = settings_ref.get()
    if data and 'power_diff_tolerance' in data:
        return data['power_diff_tolerance']
    return 10

# --- Bot初期設定 ---
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
power_diff_tolerance = load_settings()

# --- ユーティリティ関数 ---
def extract_name(name_str):
    if name_str.startswith("<@") and name_str.endswith(">"):
        return name_str.strip("<@!>")
    return name_str

def get_display_name(guild, name):
    member = discord.utils.find(lambda m: m.name == name or str(m.id) == name, guild.members) if guild else None
    if member:
        return member.display_name
    return name

# --- Prefixコマンド群 ---

@bot.command(name="add_member")
async def add_member(ctx, *args):
    if len(args) % 2 != 0:
        await ctx.send("引数は「メンバー名 パワー」のペアで指定してください。")
        return
    guild = ctx.guild
    added = []
    failed = []
    for i in range(0, len(args), 2):
        name = extract_name(args[i])
        power_str = args[i+1]
        try:
            power = int(power_str)
        except:
            failed.append(args[i] + " " + power_str)
            continue
        members[name] = power
        added.append(name)
    save_members(members)
    msg = ""
    if added:
        display_names = [get_display_name(guild, n) for n in added]
        msg += f"登録・更新しました: {', '.join(display_names)}\n"
    if failed:
        msg += f"無効な入力: {', '.join(failed)}"
    await ctx.send(msg or "入力がありませんでした。")

@bot.command(name="remove_member")
async def remove_member(ctx, *args):
    guild = ctx.guild
    removed = []
    not_found = []
    for name_raw in args:
        name = extract_name(name_raw)
        if name in members:
            del members[name]
            removed.append(name)
        else:
            not_found.append(name)
    save_members(members)
    msg = ""
    if removed:
        display_names = [get_display_name(guild, n) for n in removed]
        msg += f"削除しました: {', '.join(display_names)}\n"
    if not_found:
        display_names = [get_display_name(guild, n) for n in not_found]
        msg += f"未登録メンバー: {', '.join(display_names)}"
    await ctx.send(msg or "名前を指定してください。")

@bot.command(name="join")
async def join(ctx, *args):
    guild = ctx.guild
    added = []
    failed = []
    for name_raw in args:
        name = extract_name(name_raw)
        if name not in members:
            failed.append(name)
            continue
        participants.add(name)
        added.append(name)
    msg = ""
    if added:
        display_names = [get_display_name(guild, n) for n in added]
        msg += f"参加表明しました: {', '.join(display_names)}\n"
    if failed:
        display_names = [get_display_name(guild, n) for n in failed]
        msg += f"未登録メンバー: {', '.join(display_names)}"
    await ctx.send(msg or "名前を指定してください。")

@bot.command(name="leave")
async def leave(ctx, *args):
    guild = ctx.guild
    removed = []
    not_found = []
    for name_raw in args:
        name = extract_name(name_raw)
        if name in participants:
            participants.remove(name)
            removed.append(name)
        else:
            not_found.append(name)
    msg = ""
    if removed:
        display_names = [get_display_name(guild, n) for n in removed]
        msg += f"参加表明を解除しました: {', '.join(display_names)}\n"
    if not_found:
        display_names = [get_display_name(guild, n) for n in not_found]
        msg += f"参加表明していません: {', '.join(display_names)}"
    await ctx.send(msg or "名前を指定してください。")

# --- スラッシュコマンド群 ---

@bot.tree.command(name="add_member", description="メンバーとパワーを登録します")
@app_commands.describe(name="メンバー名（メンションまたは文字列）", power="パワー（整数）")
async def slash_add_member(interaction: discord.Interaction, name: str, power: int):
    global members
    guild = interaction.guild
    key_name = extract_name(name)
    members[key_name] = power
    save_members(members)
    display_name = get_display_name(guild, key_name)
    await interaction.response.send_message(f"{display_name} のパワーを {power} に設定・保存しました。")

@bot.tree.command(name="remove_member", description="登録済みメンバーを削除します")
@app_commands.describe(name="メンバー名（メンションまたは文字列）")
async def slash_remove_member(interaction: discord.Interaction, name: str):
    global members
    guild = interaction.guild
    key_name = extract_name(name)
    display_name = get_display_name(guild, key_name)
    if key_name not in members:
        await interaction.response.send_message(f"{display_name} は登録されていません。")
        return
    del members[key_name]
    save_members(members)
    await interaction.response.send_message(f"{display_name} を登録から削除しました。")

@bot.tree.command(name="join", description="参加表明します")
@app_commands.describe(name="メンバー名（メンションまたは文字列）")
async def slash_join(interaction: discord.Interaction, name: str):
    global participants
    guild = interaction.guild
    key_name = extract_name(name)
    display_name = get_display_name(guild, key_name)
    if key_name not in members:
        await interaction.response.send_message(f"{display_name} は登録されていません。")
        return
    participants.add(key_name)
    await interaction.response.send_message(f"{display_name} が参加表明しました。")

@bot.tree.command(name="leave", description="参加表明を解除します")
@app_commands.describe(name="メンバー名（メンションまたは文字列）")
async def slash_leave(interaction: discord.Interaction, name: str):
    global participants
    guild = interaction.guild
    key_name = extract_name(name)
    display_name = get_display_name(guild, key_name)
    if key_name not in participants:
        await interaction.response.send_message(f"{display_name} は参加表明していません。")
        return
    participants.remove(key_name)
    await interaction.response.send_message(f"{display_name} の参加表明を解除しました。")

@bot.tree.command(name="reset_join", description="参加表明リストをリセットします")
async def reset_join(interaction: discord.Interaction):
    global participants
    participants.clear()
    await interaction.response.send_message("参加表明リストをリセットしました。")

@bot.tree.command(name="list_members", description="登録済みメンバーの一覧を表示します")
async def list_members(interaction: discord.Interaction):
    guild = interaction.guild
    sorted_members = sorted(members.items(), key=lambda item: item[1], reverse=True)
    text = "登録メンバー (パワー順):\n"
    for name, power in sorted_members:
        display_name = get_display_name(guild, name)
        text += f"{display_name}: {power}\n"
    await interaction.response.send_message(text)

@bot.tree.command(name="set_tolerance", description="パワー差許容値を設定します")
@app_commands.describe(value="許容するパワー差の最大値")
async def set_tolerance(interaction: discord.Interaction, value: int):
    global power_diff_tolerance
    if value < 0:
        await interaction.response.send_message("許容値は0以上の整数で指定してください。")
        return
    power_diff_tolerance = value
    save_settings(power_diff_tolerance)
    await interaction.response.send_message(f"パワー差の許容値を {power_diff_tolerance} に設定・保存しました。")

@bot.tree.command(name="show_tolerance", description="現在のパワー差許容値を表示します")
async def show_tolerance(interaction: discord.Interaction):
    await interaction.response.send_message(f"現在のパワー差許容値は {power_diff_tolerance} です。")

@bot.tree.command(name="recruit", description="参加者の募集を開始します")
async def recruit(interaction: discord.Interaction):
    global recruit_msg_id, recruit_channel_id, participants
    msg = await interaction.channel.send("LoLカスタム募集！")
    await msg.add_reaction("👍")
    await msg.add_reaction("✅")
    recruit_msg_id = msg.id
    recruit_channel_id = msg.channel.id
    participants.clear()
    await interaction.response.send_message("参加表明リストをリセットしました。")

# --- Bot起動 ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

if __name__ == "__main__":
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if not TOKEN:
        raise ValueError("環境変数DISCORD_TOKENがセットされていません")
    bot.run(TOKEN)
