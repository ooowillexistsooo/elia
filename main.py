import os, discord, asyncio, random, sqlite3, httpx
from groq import Groq
from quart import Quart, render_template, request, redirect, session, url_for
from collections import deque
from discord import app_commands

# --- CONFIGURATION ---
# Replace these with your actual keys or set them in your hosting env
TOKEN = os.getenv('DISCORD_TOKEN') or "YOUR_DISCORD_BOT_TOKEN"
GROQ_API_KEY = os.getenv('GROQ_API_KEY') or "YOUR_GROQ_API_KEY"
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')

client = Groq(api_key=GROQ_API_KEY)
app = Quart(__name__)
app.secret_key = "NEURO_ULTIMATE_SECRET_99"

# Initialize Discord Bot with all Intents
intents = discord.Intents.all()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# Global chat history (last 5 messages per channel)
chat_histories = {}

# --- DATABASE LOGIC ---
DB_PATH = 'neuro_data.db'

def db_query(query, args=(), one=False):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(query, args)
        rv = cur.fetchall()
        conn.commit()
        return (rv[0] if rv else None) if one else rv

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, user TEXT, content TEXT, response TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS filters (id INTEGER PRIMARY KEY, pattern TEXT, type TEXT);
            CREATE TABLE IF NOT EXISTS user_memory (user_id TEXT, fact TEXT);
            CREATE TABLE IF NOT EXISTS admins (user_id TEXT PRIMARY KEY);
        ''')
        conn.execute("INSERT OR IGNORE INTO config VALUES ('personality', 'You are an authentic, chaotic, and witty AI.')")
        conn.execute("INSERT OR IGNORE INTO config VALUES ('chance', '0.05')")
        conn.execute("INSERT OR IGNORE INTO config VALUES ('model_id', 'llama-3.3-70b-versatile')")

init_db()

# --- IN-DISCORD DASHBOARD UI ---
class DiscordDash(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        is_adm = db_query("SELECT 1 FROM admins WHERE user_id=?", (str(interaction.user.id),), one=True)
        if not is_adm:
            await interaction.response.send_message("❌ Unauthorized. Add your ID to the web dashboard first.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Toggle Model (70B/8B)", style=discord.ButtonStyle.primary)
    async def switch_model(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = db_query("SELECT value FROM config WHERE key='model_id'", one=True)[0]
        new_model = "llama-3.1-8b-instant" if "70b" in current else "llama-3.3-70b-versatile"
        db_query("UPDATE config SET value=? WHERE key='model_id'", (new_model,))
        await interaction.response.send_message(f"🧠 Brain Swapped to: **{new_model}**", ephemeral=True)

    @discord.ui.button(label="Cycle Chaos", style=discord.ButtonStyle.secondary)
    async def chaos_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = float(db_query("SELECT value FROM config WHERE key='chance'", one=True)[0])
        new_chance = 0.5 if current == 0.05 else 1.0 if current == 0.5 else 0.05
        db_query("UPDATE config SET value=? WHERE key='chance'", (new_chance,))
        await interaction.response.send_message(f"🎲 Chaos Factor: **{int(new_chance*100)}%**", ephemeral=True)

    @discord.ui.button(label="Wipe Context", style=discord.ButtonStyle.danger)
    async def wipe_hist(self, interaction: discord.Interaction, button: discord.ui.Button):
        chat_histories[interaction.channel_id] = deque(maxlen=5)
        await interaction.response.send_message("🧹 Local conversation history cleared.", ephemeral=True)

# --- AI BRAIN ---
async def get_ai_response(channel_id, user_id, user_input):
    try:
        pers = db_query("SELECT value FROM config WHERE key='personality'", one=True)[0]
        model = db_query("SELECT value FROM config WHERE key='model_id'", one=True)[0]
        mems = db_query("SELECT fact FROM user_memory WHERE user_id=?", (str(user_id),))
        mem_str = " | ".join([m[0] for m in mems])

        if channel_id not in chat_histories:
            chat_histories[channel_id] = deque(maxlen=5)
        
        history = "\n".join(chat_histories[channel_id])

        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": f"{pers}\nLong-term Memory: {mem_str}\nRecent Context: {history}"},
                {"role": "user", "content": user_input}
            ]
        )
        
        res = completion.choices[0].message.content
        chat_histories[channel_id].append(f"User: {user_input}")
        chat_histories[channel_id].append(f"AI: {res}")
        return res
    except Exception as e:
        print(f"AI ERROR: {e}")
        return f"⚠️ Error: {str(e)}"

# --- DISCORD EVENTS ---
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    
    is_pinged = bot.user.mentioned_in(message)
    chance = float(db_query("SELECT value FROM config WHERE key='chance'", one=True)[0])
    
    if is_pinged or random.random() < chance:
        async with message.channel.typing():
            res = await get_ai_response(message.channel.id, message.author.id, message.content)
            await message.channel.send(res)
            db_query("INSERT INTO logs (user, content, response) VALUES (?, ?, ?)", 
                     (str(message.author), message.content, res))

@tree.command(name="dashboard", description="Summon the Admin Panel")
async def summon_dash(interaction: discord.Interaction):
    is_adm = db_query("SELECT 1 FROM admins WHERE user_id=?", (str(interaction.user.id),), one=True)
    if not is_adm: return await interaction.response.send_message("Unauthorized.", ephemeral=True)
    
    embed = discord.Embed(title="🤖 Neuro-Admin Panel", color=discord.Color.blue())
    await interaction.response.send_message(embed=embed, view=DiscordDash())

# --- WEB DASHBOARD ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
async def login():
    if request.method == 'POST':
        form = await request.form
        if form.get('pw') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
    return '<body style="background:#0f172a;color:white;text-align:center;padding-top:100px;font-family:sans-serif;">' \
           '<form method="post"><h2>Unlock Dashboard</h2><input type="password" name="pw"><button>Login</button></form></body>'

@app.route('/')
async def index():
    if not session.get('logged_in'): return redirect(url_for('login'))
    logs = db_query("SELECT * FROM logs ORDER BY id DESC LIMIT 15")
    config = {r[0]:r[1] for r in db_query("SELECT * FROM config")}
    admins = db_query("SELECT * FROM admins")
    return await render_template('dashboard.html', logs=logs, config=config, admins=admins)

@app.route('/action/<cmd>', methods=['POST'])
async def action(cmd):
    if not session.get('logged_in'): return redirect(url_for('login'))
    f = await request.form
    if cmd == 'config':
        db_query("UPDATE config SET value=? WHERE key='personality'", (f['personality'],))
        db_query("UPDATE config SET value=? WHERE key='chance'", (f['chance'],))
    elif cmd == 'add_admin':
        db_query("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (f['user_id'],))
    elif cmd == 'remove_admin':
        db_query("DELETE FROM admins WHERE user_id=?", (f['user_id'],))
    return redirect(url_for('index'))

# --- STARTUP ---
async def start_all():
    port = int(os.environ.get("PORT", 5000))
    await asyncio.gather(
        bot.start(TOKEN),
        app.run_task(host='0.0.0.0', port=port)
    )

if __name__ == "__main__":
    asyncio.run(start_all())
