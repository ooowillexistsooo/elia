import os, discord, asyncio, random, sqlite3, httpx
from groq import Groq
from quart import Quart, render_template, request, redirect, session, url_for
from duckduckgo_search import DDGS
from discord import app_commands

# --- CONFIGURATION ---
TOKEN = os.getenv('DISCORD_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')

client = Groq(api_key=GROQ_API_KEY)
app = Quart(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'neuro_secret_55')
intents = discord.Intents.all()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# --- DATABASE LOGIC ---
def db_query(query, args=(), one=False):
    with sqlite3.connect('neuro_data.db') as conn:
        cur = conn.execute(query, args)
        rv = cur.fetchall()
        conn.commit()
        return (rv[0] if rv else None) if one else rv

def init_db():
    db_query('''CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, user TEXT, content TEXT, response TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    db_query('''CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)''')
    db_query('''CREATE TABLE IF NOT EXISTS filters (id INTEGER PRIMARY KEY, pattern TEXT, type TEXT)''')
    db_query('''CREATE TABLE IF NOT EXISTS user_memory (user_id TEXT, fact TEXT)''')
    db_query('''CREATE TABLE IF NOT EXISTS admins (user_id TEXT PRIMARY KEY)''')
    db_query("INSERT OR IGNORE INTO config VALUES ('personality', 'You are a witty, chaotic AI.')")
    db_query("INSERT OR IGNORE INTO config VALUES ('chance', '0.05')")

init_db()

# --- AI & SEARCH ---
async def web_search(query):
    try:
        with DDGS() as ddgs:
            return "\n".join([r['body'] for r in ddgs.text(query, max_results=2)])
    except: return "No search data found."

async def get_ai_response(user_id, user_input):
    # Input Filter
    filters = db_query("SELECT pattern FROM filters WHERE type='input'")
    if any(f[0].lower() in user_input.lower() for f in filters):
        return "System: That input is blacklisted."

    # Context & Memory
    mems = db_query("SELECT fact FROM user_memory WHERE user_id=?", (str(user_id),))
    mem_str = " | ".join([m[0] for m in mems])
    pers = db_query("SELECT value FROM config WHERE key='personality'", one=True)[0]
    
    # Optional Search
    context = ""
    if any(x in user_input.lower() for x in ["who", "news", "latest", "what is"]):
        context = f"\nSearch Results: {await web_search(user_input)}"

    completion = client.chat.completions.create(
        model="llama3-70b-8192",
        messages=[
            {"role": "system", "content": f"{pers}\nUser Memories: {mem_str}\n{context}"},
            {"role": "user", "content": user_input}
        ]
    )
    res = completion.choices[0].message.content
    
    # Output Filter
    out_f = db_query("SELECT pattern FROM filters WHERE type='output'")
    if any(f[0].lower() in res.lower() for f in out_f):
        return "[Response Filtered]"
    return res

# --- DISCORD SLASH COMMANDS ---
@tree.command(name="admin_status", description="Check bot health")
async def status(interaction: discord.Interaction):
    is_adm = db_query("SELECT 1 FROM admins WHERE user_id=?", (str(interaction.user.id),), one=True)
    if not is_adm: return await interaction.response.send_message("Unauthorized.", ephemeral=True)
    await interaction.response.send_message(f"✅ Online. Brain: Groq Llama-3.")

# --- DISCORD EVENTS ---
@bot.event
async def on_ready():
    await tree.sync()
    print(f"Bot {bot.user} is live!")

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    chance = float(db_query("SELECT value FROM config WHERE key='chance'", one=True)[0])
    if bot.user.mentioned_in(message) or random.random() < chance:
        async with message.channel.typing():
            res = await get_ai_response(message.author.id, message.content)
            await message.channel.send(res)
            db_query("INSERT INTO logs (user, content, response) VALUES (?, ?, ?)", (str(message.author), message.content, res))

# --- DASHBOARD ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
async def login():
    if request.method == 'POST':
        if (await request.form).get('pw') == ADMIN_PASSWORD:
            session['auth'] = True
            return redirect(url_for('index'))
    return '<form method="post">Password: <input type="password" name="pw"><button>Login</button></form>'

@app.route('/')
async def index():
    if not session.get('auth'): return redirect(url_for('login'))
    return await render_template('dashboard.html', 
        logs=db_query("SELECT * FROM logs ORDER BY id DESC LIMIT 15"),
        config={r[0]:r[1] for r in db_query("SELECT * FROM config")},
        filters=db_query("SELECT * FROM filters"),
        admins=db_query("SELECT * FROM admins"),
        mems=db_query("SELECT * FROM user_memory LIMIT 20"))

@app.route('/action/<cmd>', methods=['POST'])
async def action(cmd):
    if not session.get('auth'): return redirect(url_for('login'))
    f = await request.form
    if cmd == 'config':
        db_query("UPDATE config SET value=? WHERE key='personality'", (f['personality'],))
        db_query("UPDATE config SET value=? WHERE key='chance'", (f['chance'],))
    elif cmd == 'add_filter':
        db_query("INSERT INTO filters (pattern, type) VALUES (?, ?)", (f['pattern'], f['type']))
    elif cmd == 'add_admin':
        db_query("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (f['user_id'],))
    return redirect(url_for('index'))

async def main():
    port = int(os.environ.get("PORT", 5000))
    await asyncio.gather(bot.start(TOKEN), app.run_task(host='0.0.0.0', port=port))

if __name__ == "__main__":
    asyncio.run(main())
