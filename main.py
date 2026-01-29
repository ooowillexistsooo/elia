import os
import discord
import asyncio
import random
import sqlite3
from groq import Groq
from quart import Quart, render_template, request, redirect, session
from duckduckgo_search import DDGS

# --- CONFIG (Use Environment Variables for Security) ---
TOKEN = os.getenv('DISCORD_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123') # Change this!

client = Groq(api_key=GROQ_API_KEY)
app = Quart(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'super-secret-key')
intents = discord.Intents.all()
bot = discord.Client(intents=intents)

# --- DATABASE & FILTERS (Same as before) ---
def db_query(query, args=(), one=False):
    with sqlite3.connect('neuro.db') as conn:
        cur = conn.execute(query, args)
        rv = cur.fetchall()
        return (rv[0] if rv else None) if one else rv

# --- BRAIN LOGIC (Using Groq) ---
async def get_ai_response(user_id, user_input):
    # Filter Checks
    filters = db_query("SELECT pattern FROM filters")
    if any(f[0].lower() in user_input.lower() for f in filters):
        return "I can't talk about that."

    # Memory Retrieval
    mems = db_query("SELECT fact FROM user_memory WHERE user_id=?", (str(user_id),))
    mem_str = " | ".join([m[0] for m in mems])
    pers = db_query("SELECT value FROM config WHERE key='personality'", one=True)[0]

    # Groq API Call
    completion = client.chat.completions.create(
        model="llama3-70b-8192",
        messages=[
            {"role": "system", "content": f"{pers}\nMemories of user: {mem_str}"},
            {"role": "user", "content": user_input}
        ]
    )
    return completion.choices[0].message.content

# --- DASHBOARD WITH PASSWORD ---
@app.route('/login', methods=['GET', 'POST'])
async def login():
    if request.method == 'POST':
        form = await request.form
        if form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect('/')
    return '''
        <form method="post" style="text-align:center; margin-top:100px;">
            <h2>Elia Secure Login</h2>
            <input type="password" name="password">
            <button type="submit">Unlock</button>
        </form>
    '''

@app.route('/')
async def index():
    if not session.get('logged_in'):
        return redirect('/login')
    # ... (Return your existing dashboard HTML here) ...
    return await render_template('dashboard.html', 
                                 logs=db_query("SELECT * FROM logs LIMIT 10"), 
                                 config={r[0]:r[1] for r in db_query("SELECT * FROM config")})

# --- RUNNER ---
async def main():
    # Render requires a specific port
    port = int(os.environ.get("PORT", 5000))
    await asyncio.gather(
        bot.start(TOKEN),
        app.run_task(host='0.0.0.0', port=port)
    )

if __name__ == "__main__":
    asyncio.run(main())
