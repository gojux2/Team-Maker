import discord
from discord import app_commands
from discord.ext import commands
import itertools
import json
import os
import random
from flask import Flask
import threading

# === Flaskによるスリープ対策サーバー（KoyebやReplit等で有効） ===
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run).start()

# === Discord Bot本体 ===

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

RECRUIT_EMOJI = "👍"
CHECK_EMOJI = "✅"

class TeamBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()

bot = TeamBot()

DATA_FILE = 'members.json'

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"members": {}, "power_diff_tolerance": 10, "history": []}
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"members": {}, "power_diff_tolerance": 10, "history": []}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

data = load_data()
members = data.get("members", {})
power_diff_tolerance = data.get("power_diff_tolerance", 10)
participants = set()
last_team = None
raw_history = data.get("history", [])
history = [(frozenset(t[0]), frozenset(t[1])) for t in raw_history]

recruit_msg_id = None
recruit_channel_id = None

def get_display_name(guild, name):
    if guild:
        member = discord.utils.find(lambda m: m.name == name, guild.members)
        if member:
            return member.display_name
    return name

def teams_equal(t1a, t1b, t2a, t2b):
    return (t1a == t2a and t1b == t2b) or (t1a == t2b and t1b == t2a)

def extract_name_from_arg(ctx, arg: str) -> str:
    if arg.startswith("<@") and arg.endswith(">"):
        user_id = arg.strip("<@!>")
        member = ctx.guild.get_member(int(user_id))
        if member:
            return member.name
        return arg
    else:
        return arg.lstrip("@")

@bot.tree.command(name="add_member", description="メンバーとパワーを登録します")
@app_commands.describe(name="メンバー名（メンションまたは文字列）", power="パワー（整数）")
async def add_member(interaction: discord.Interaction, name: str, power: int):
    guild = interaction.guild
    key_name = extract_name_from_arg(interaction, name)
    members[key_name] = power
    data["members"] = members
    save_data(data)
    display_name = get_display_name(guild, key_name)
    await interaction.response.send_message(f"{display_name} のパワーを {power} に設定・保存しました。")

@bot.tree.command(name="list_members", description="登録済みメンバーとパワーの一覧を表示します")
async def list_members(interaction: discord.Interaction):
    guild = interaction.guild
    sorted_members = sorted(members.items(), key=lambda item: item[1], reverse=True)
    text = "登録メンバー (パワー順):\n"
    for name, power in sorted_members:
        display_name = get_display_name(guild, name)
        text += f"{display_name}: {power}\n"
    await interaction.response.send_message(text)

@bot.tree.command(name="join", description="参加表明します")
@app_commands.describe(name="メンバー名（メンションまたは文字列）")
async def join(interaction: discord.Interaction, name: str):
    guild = interaction.guild
    key_name = extract_name_from_arg(interaction, name)
    display_name = get_display_name(guild, key_name)
    if key_name not in members:
        await interaction.response.send_message(f"{display_name} は登録されていません。`/add_member`で登録してください。")
        return
    participants.add(key_name)
    await interaction.response.send_message(f"{display_name} が参加表明しました。")

@bot.tree.command(name="leave", description="参加表明を解除します")
@app_commands.describe(name="メンバー名（メンションまたは文字列）")
async def leave(interaction: discord.Interaction, name: str):
    guild = interaction.guild
    key_name = extract_name_from_arg(interaction, name)
    display_name = get_display_name(guild, key_name)
    if key_name not in participants:
        await interaction.response.send_message(f"{display_name} は現在参加表明していません。")
        return
    participants.remove(key_name)
    await interaction.response.send_message(f"{display_name} が参加表明から退出しました。")

@bot.tree.command(name="reset_join", description="参加表明リストをリセットします")
async def reset_join(interaction: discord.Interaction):
    participants.clear()
    await interaction.response.send_message("参加表明リストをリセットしました。")

@bot.tree.command(name="set_tolerance", description="パワー差の許容値を設定します")
@app_commands.describe(value="許容するパワー差の最大値")
async def set_tolerance(interaction: discord.Interaction, value: int):
    global power_diff_tolerance
    if value < 0:
        await interaction.response.send_message("許容値は0以上の整数で指定してください。")
        return
    power_diff_tolerance = value
    data["power_diff_tolerance"] = power_diff_tolerance
    save_data(data)
    await interaction.response.send_message(f"パワー差の許容値を {power_diff_tolerance} に設定しました。")

@bot.tree.command(name="show_tolerance", description="現在のパワー差許容値を表示します")
async def show_tolerance(interaction: discord.Interaction):
    await interaction.response.send_message(f"現在のパワー差許容値は {power_diff_tolerance} です。")

@bot.tree.command(name="remove_member", description="登録済みメンバーを削除します")
@app_commands.describe(name="削除するメンバー名（メンションまたは文字列）")
async def remove_member(interaction: discord.Interaction, name: str):
    guild = interaction.guild
    def extract_name(name_arg: str) -> str:
        if name_arg.startswith("<@") and name_arg.endswith(">"):
            user_id = name_arg.strip("<@!>")
            member = guild.get_member(int(user_id)) if guild else None
            return member.name if member else name_arg
        else:
            return name_arg.lstrip("@")
    key_name = extract_name(name)
    display_name = get_display_name(guild, key_name)
    if key_name not in members:
        await interaction.response.send_message(f"{display_name} は登録されていません。")
        return
    del members[key_name]
    data["members"] = members
    save_data(data)
    if key_name in participants:
        participants.remove(key_name)
    await interaction.response.send_message(f"{display_name} の登録を削除しました。")

@bot.tree.command(name="recruit", description="参加者の募集を開始します")
async def recruit(interaction: discord.Interaction):
    global recruit_msg_id, recruit_channel_id
    msg = await interaction.channel.send("LoLカスタム募集！")
    await msg.add_reaction(RECRUIT_EMOJI)
    await msg.add_reaction(CHECK_EMOJI)
    recruit_msg_id = msg.id
    recruit_channel_id = msg.channel.id
    participants.clear()
    await interaction.response.send_message("参加表明リストをリセットしました。")

@bot.event
async def on_reaction_add(reaction, user):
    global recruit_msg_id, recruit_channel_id
    if user.bot:
        return
    if reaction.message.id != recruit_msg_id or reaction.message.channel.id != recruit_channel_id:
        return

    guild = reaction.message.guild
    name = user.name
    display_name = get_display_name(guild, name)

    if str(reaction.emoji) == RECRUIT_EMOJI:
        if name not in members:
            await reaction.message.channel.send(f"{display_name} さんはメンバー登録されていません。`/add_member`で先に登録をお願いします。")
            return
        participants.add(name)

    elif str(reaction.emoji) == CHECK_EMOJI:
        if len(participants) != 10:
            await reaction.message.channel.send(f"参加表明メンバーが10人ではありません（{len(participants)}人）。チーム分けできません。")
            return

        names = list(participants)
        candidates = []

        for comb in itertools.combinations(names, 5):
            team1 = frozenset(comb)
            team2 = frozenset(n for n in names if n not in comb)

            sum1 = sum(members[n] for n in team1)
            sum2 = sum(members[n] for n in team2)
            diff = abs(sum1 - sum2)
            if diff > power_diff_tolerance:
                continue

            duplicate_in_history = any(
                teams_equal(team1, team2, past_team[0], past_team[1]) for past_team in history
            )
            if duplicate_in_history:
                continue

            def member_repeat_score(t1, t2):
                score = 0
                for past_team in history:
                    score += len(t1.intersection(past_team[0]))
                    score += len(t2.intersection(past_team[1]))
                return score

            repeat_score = member_repeat_score(team1, team2)
            candidates.append({
                'team1': team1,
                'team2': team2,
                'diff': diff,
                'repeat_score': repeat_score
            })

        if not candidates:
            await reaction.message.channel.send("条件に合うチーム分けが見つかりませんでした。")
            return

        candidates.sort(key=lambda c: (c['repeat_score'], c['diff']))
        top_candidates = candidates[:min(5, len(candidates))]
        selected = random.choice(top_candidates)
        team1 = selected['team1']
        team2 = selected['team2']
        history.append((team1, team2))
        if len(history) > 10:
            history.pop(0)
        data["history"] = [(list(t[0]), list(t[1])) for t in history]
        save_data(data)
        sorted_team1 = sorted(team1, key=lambda n: members[n], reverse=True)
        sorted_team2 = sorted(team2, key=lambda n: members[n], reverse=True)
        display_team1 = [get_display_name(guild, n) for n in sorted_team1]
        display_team2 = [get_display_name(guild, n) for n in sorted_team2]

        # 埋め込み（Embed）メッセージ形式で出力
        embed = discord.Embed(color=0x00ff00)
        embed.add_field(
            name=f"チーム1 (合計: {sum(members[n] for n in team1)})",
            value=" ".join(f"[ {name} ]" for name in display_team1),
            inline=False)
        embed.add_field(
            name=f"チーム2 (合計: {sum(members[n] for n in team2)})",
            value=" ".join(f"[ {name} ]" for name in display_team2),
            inline=False)

        await reaction.message.channel.send(embed=embed)

@bot.event
async def on_reaction_remove(reaction, user):
    global recruit_msg_id, recruit_channel_id
    if user.bot:
        return
    if str(reaction.emoji) != RECRUIT_EMOJI:
        return
    if reaction.message.id == recruit_msg_id and reaction.message.channel.id == recruit_channel_id:
        name = user.name
        if name in participants:
            participants.remove(name)

@bot.tree.command(name="make_teams", description="参加者を5v5にチーム分けします")
async def make_teams(interaction: discord.Interaction):
    if len(participants) != 10:
        await interaction.response.send_message("参加表明したメンバーが10人必要です。")
        return

    names = list(participants)
    candidates = []

    for comb in itertools.combinations(names, 5):
        team1 = frozenset(comb)
        team2 = frozenset(n for n in names if n not in comb)

        sum1 = sum(members[n] for n in team1)
        sum2 = sum(members[n] for n in team2)
        diff = abs(sum1 - sum2)
        if diff > power_diff_tolerance:
            continue

        duplicate_in_history = any(
            teams_equal(team1, team2, past_team[0], past_team[1]) for past_team in history
        )
        if duplicate_in_history:
            continue

        def member_repeat_score(t1, t2):
            score = 0
            for past_team in history:
                score += len(t1.intersection(past_team[0]))
                score += len(t2.intersection(past_team[1]))
            return score

        repeat_score = member_repeat_score(team1, team2)
        candidates.append({
            'team1': team1,
            'team2': team2,
            'diff': diff,
            'repeat_score': repeat_score
        })

    if not candidates:
        await interaction.response.send_message("条件に合うチーム分けが見つかりませんでした。")
        return

    candidates.sort(key=lambda c: (c['repeat_score'], c['diff']))
    top_candidates = candidates[:min(5, len(candidates))]
    selected = random.choice(top_candidates)
    team1 = selected['team1']
    team2 = selected['team2']
    history.append((team1, team2))
    if len(history) > 10:
        history.pop(0)
    data["history"] = [(list(t[0]), list(t[1])) for t in history]
    save_data(data)
    sorted_team1 = sorted(team1, key=lambda n: members[n], reverse=True)
    sorted_team2 = sorted(team2, key=lambda n: members[n], reverse=True)
    display_team1 = [get_display_name(interaction.guild, n) for n in sorted_team1]
    display_team2 = [get_display_name(interaction.guild, n) for n in sorted_team2]

    # 埋め込み（Embed）メッセージ形式で出力
    embed = discord.Embed(color=0x00ff00)
    embed.add_field(
        name=f"チーム1 (合計: {sum(members[n] for n in team1)})",
        value=" ".join(f"[ {name} ]" for name in display_team1),
        inline=False)
    embed.add_field(
        name=f"チーム2 (合計: {sum(members[n] for n in team2)})",
        value=" ".join(f"[ {name} ]" for name in display_team2),
        inline=False)

    await interaction.response.send_message(embed=embed)

if __name__ == "__main__":
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if not TOKEN:
        raise ValueError("環境変数DISCORD_TOKENがセットされていません")
    bot.run(TOKEN)