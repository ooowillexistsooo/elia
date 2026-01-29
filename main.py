import os, discord, asyncio, random, sqlite3, httpx
from groq import Groq
from quart import Quart, render_template, request, redirect, session, url_for
from duckduckgo_search import DDGS
from discord import app_commands

# --- CONFIG ---
TOKEN = os.getenv('DISCORD_TOKEN') or "YOUR_TOKEN_HERE"
GROQ_API_KEY = os.getenv('GROQ_API_KEY') or "YOUR_GROQ_KEY_HERE"
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')

client = Groq(api_key=GROQ_API_KEY)
app = Quart(__name__)
app.secret_key = "NEURO_PERMANENT_KEY_99" # Hardcoded for stability
# CRITICAL: Enable all intents
intents = discord.Intents.all()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# --- DB HELPERS ---
def db_query(query, args=(), one=False):
    with sqlite3.connect('neuro_data.db') as conn:
        cur = conn.execute(query, args)
        rv = cur.fetchall()
        conn.commit()
        return (rv[0] if rv else None) if one else rv

# Initialize Database
with sqlite3.connect('neuro_data.db') as conn:
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY, user TEXT, content TEXT, response TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS filters (id INTEGER PRIMARY KEY, pattern TEXT, type TEXT);
        CREATE TABLE IF NOT EXISTS user_memory (user_id TEXT, fact TEXT);
        CREATE TABLE IF NOT EXISTS admins (user_id TEXT PRIMARY KEY);
    ''')
    conn.execute("INSERT OR IGNORE INTO config VALUES ('personality', 'You are a witty AI.')")
    conn.execute("INSERT OR IGNORE INTO config VALUES ('chance', '0.05')")

# --- AI BRAIN ---
async def get_ai_response(user_id, user_input):
    try:
        pers = db_query("SELECT value FROM config WHERE key='personality'", one=True)[0]
        mems = db_query("SELECT fact FROM user_memory WHERE user_id=?", (str(user_id),))
        mem_str = " | ".join([m[0] for m in mems])

        completion = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[
                {"role": "system", "content": f"{pers}\nMemories: {mem_str}"},
                {"role": "user", "content": user_input}
            ]
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Brain Error: {str(e)}"

# --- DISCORD EVENTS ---
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ BOT LOGGED IN AS: {bot.user}")
    print(f"🟢 Message Content Intent is {'ENABLED' if bot.intents.message_content else 'DISABLED'}")

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    
    # DEBUG: See every message in console
    print(f"📩 Message from {message.author}: {message.content}")

    is_pinged = bot.user.mentioned_in(message)
    chance = float(db_query("SELECT value FROM config WHERE key='chance'", one=True)[0])
    
    if is_pinged or random.random() < chance:
        print(f"🤖 Responding to: {message.author}...")
        async with message.channel.typing():
            res = await get_ai_response(message.author.id, message.content)
            await message.channel.send(res)
            db_query("INSERT INTO logs (user, content, response) VALUES (?, ?, ?)", 
                     (str(message.author), message.content, res))

# --- DASHBOARD LOGIC ---
@app.route('/login', methods=['GET', 'POST'])
async def login():
    if request.method == 'POST':
        form = await request.form
        typed_pw = form.get('pw')
        print(f"🔑 Login attempt: Received '{typed_pw}', Expected '{ADMIN_PASSWORD}'")
        
        if typed_pw == ADMIN_PASSWORD:
            session['logged_in'] = True
            print("✅ Login Successful")
            return redirect(url_for('index'))
        else:
            print("❌ Login Failed")
            return "Wrong password. <a href='/login'>Try again</a>"
            
    return '''
    <style>body{background:#0f172a;color:white;font-family:sans-serif;text-align:center;padding:50px;}</style>
    <form method="post">
        <h2>Neuro-Max Unlock</h2>
        <input type="password" name="pw" placeholder="Password" style="padding:10px;">
        <button type="submit" style="padding:10px;cursor:pointer;">Unlock Dashboard</button>
    </form>
    '''

@app.route('/')
async def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    logs = db_query("SELECT * FROM logs ORDER BY id DESC LIMIT 10")
    config = {r[0]:r[1] for r in db_query("SELECT * FROM config")}
    return await render_template('dashboard.html', logs=logs, config=config)

# ... (Include the /action routes from the previous script) ...

async def startup():
    port = int(os.environ.get("PORT", 5000))
    # Run both
    await asyncio.gather(
        bot.start(TOKEN),
        app.run_task(host='0.0.0.0', port=port)
    )

if __name__ == "__main__":
    try:
        asyncio.run(startup())
    except KeyboardInterrupt:
        pass
