"""Local Live Desk prototype. Dashboard reads never initiate a chain scan."""
import json
import re
import secrets
import sqlite3
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
DB = Path(os.environ.get('RUGBUSTER_DESK_DATA', str(Path(__file__).resolve().parent))) / 'desk.sqlite3'
API = 'https://rugbuster-solana-api-production.up.railway.app'
MINT = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
TOKEN = secrets.token_urlsafe(32)
PORT = 8767
prices = {}
price_lock = threading.Lock()
scan_lock = threading.Lock()
browser_lock = threading.Lock()
browser_fetch_lock = threading.Lock()
browser_token = None
browser_seen = 0
BRIDGE_TOKEN = ''
patrol_attempts = {}

@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=10)
    try:
        with db:
            yield db
    finally:
        db.close()

def init():
    global BRIDGE_TOKEN
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS watches (mint TEXT PRIMARY KEY, data TEXT NOT NULL, scanned REAL NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS baselines (mint TEXT PRIMARY KEY, data TEXT NOT NULL, started REAL NOT NULL)')
        db.execute('INSERT OR IGNORE INTO baselines SELECT mint,data,scanned FROM watches')
        db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, mint TEXT, data TEXT, retrieved REAL)')
        db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
        db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', ('bridge', secrets.token_urlsafe(32)))
        db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', ('patrol', 'on'))
        BRIDGE_TOKEN = db.execute("SELECT value FROM settings WHERE key='bridge'").fetchone()[0]

def patrol_enabled():
    with connect() as db:
        return db.execute("SELECT value FROM settings WHERE key='patrol'").fetchone()[0] == 'on'

def changes(before, after):
    result = []
    for key, title in [('risk_score', 'Risk score'), ('label', 'Risk category')]:
        a,b = before.get(key),after.get(key)
        if a is not None and b is not None and a != b:
            result.append(dict(title=title, before=a, after=b))
    a,b = before.get('creator_position') or {},after.get('creator_position') or {}
    for key,title in [('status','Creator status'), ('current_share_pct','Creator share (%)')]:
        av,bv = a.get(key),b.get(key)
        if av is not None and bv is not None and av != bv:
            result.append(dict(title=title,before=av,after=bv))
    return result

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'RugBuster-Live-Desk/0.1'})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)

def watches():
    with connect() as db:
        rows = db.execute('SELECT mint,data,scanned FROM watches ORDER BY scanned DESC').fetchall()
        baselines = {m:dict(scan=json.loads(d),started_at=t) for m,d,t in db.execute('SELECT mint,data,started FROM baselines')}
        events = {}
        for m,d,t in db.execute('SELECT mint,data,retrieved FROM events ORDER BY id DESC'):
            events.setdefault(m,[]).append(dict(**json.loads(d),retrieved_at=t))
    with price_lock:
        return [dict(mint=m, scan=json.loads(d), scanned_at=t, price=prices.get(m), baseline=baselines.get(m), events=events.get(m,[])[:30]) for m,d,t in rows]

def scan(mint, existing_only=False):
    if not MINT.fullmatch(mint):
        raise ValueError('Paste a valid Solana mint address.')
    with scan_lock:
        return _scan(mint, existing_only)

def read_scan(mint):
    data = fetch(f'{API}/score?address={mint}')
    if data.get('ok') is False or data.get('address') != mint:
        raise ValueError(data.get('error') or 'The API did not confirm this mint.')
    return data

def _scan(mint, existing_only=False):
    data = read_scan(mint)
    with connect() as db:
        previous = db.execute('SELECT data FROM watches WHERE mint=?',(mint,)).fetchone()
        if existing_only and not previous:
            return  # token removed while the background request was in flight
        if not previous and db.execute('SELECT count(*) FROM watches').fetchone()[0] >= 20:
            raise ValueError('This local desk supports 20 tokens.')
        now = time.time()
        db.execute('INSERT OR IGNORE INTO baselines VALUES (?,?,?)',(mint,json.dumps(data),now))
        if previous:
            for change in changes(json.loads(previous[0]),data):
                change['observed_at'] = data.get('observed_at')
                db.execute('INSERT INTO events (mint,data,retrieved) VALUES (?,?,?)',(mint,json.dumps(change),now))
            db.execute('DELETE FROM events WHERE mint=? AND id NOT IN (SELECT id FROM events WHERE mint=? ORDER BY id DESC LIMIT 200)',(mint,mint))
        db.execute('INSERT INTO watches VALUES (?,?,?) ON CONFLICT(mint) DO UPDATE SET data=excluded.data, scanned=excluded.scanned', (mint,json.dumps(data),time.time()))

def follow_browser(mint):
    global browser_token,browser_seen
    if not MINT.fullmatch(mint):
        raise ValueError('Invalid Solana mint')
    with browser_fetch_lock:
        with browser_lock:
            if browser_token and browser_token['mint'] == mint and time.time()-browser_seen < 30:
                browser_seen = time.time()
                return
        saved = next((x for x in watches() if x['mint'] == mint),None)
        data = saved['scan'] if saved else read_scan(mint)
        with browser_lock:
            browser_token = dict(mint=mint,scan=data,scanned_at=time.time(),preview=True)
            browser_seen = time.time()

# --- Ask RugBuster: a research chat about the selected token -------------------
# The model starts from the token's own scan and may look further with tools:
# a wallet's recent activity (Helius parsed history), a token's market and links
# (DexScreener), a search for related tokens, and a RugBuster scan of any other
# mint. It explains what it found; it never advises buying, selling or holding.
# DeepSeek because it is the cheapest model we already use; keep `deepseek-chat`
# (deepseek-flash thinks by default and returns empty answers at small limits).
DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions'
DEEPSEEK_MODEL = 'deepseek-chat'
HELIUS_TX = 'https://api.helius.xyz/v0/addresses/{}/transactions?api-key={}&limit={}'
MAX_TOOL_ROUNDS = 6
ASK_KEYS = ('token_name', 'token_symbol', 'label', 'risk_score', 'verdict_summary', 'verdict_basis', 'risk_flags',
            'creator_position', 'launch_snipe', 'deployer_history', 'chain_checks', 'name_copies',
            'not_established', 'observed_at', 'retrieved_at')
ASK_RULES = (
    "You are RugBuster's research assistant inside the Live Desk app. The user is looking at one Solana token; "
    "its RugBuster scan is below. Talk like a helpful analyst. When the scan does not answer the question, use the "
    "tools to look further: the creator's or funder's wallet activity, the token's market, website and social links, "
    "related tokens with the same name, or a RugBuster scan of another mint. Say what you looked at, what you "
    "found, and what you could not find. Never invent addresses, numbers or links; only use what the scan or a tool "
    "returned. Never tell the user to buy, sell or hold, and never predict price; describe risk and evidence. Give "
    "Solscan links for transactions (https://solscan.io/tx/<signature>) and accounts "
    "(https://solscan.io/account/<address>). Always reply in plain, simple English, whatever language the question is in. Keep it readable: short paragraphs and '- ' bullets, bold with **; no tables, no headings."
)
TOOLS = [
    {'type': 'function', 'function': {
        'name': 'wallet_activity',
        'description': 'Recent parsed transactions of a Solana wallet (transfers, swaps, token creations), newest first, '
                       'with the mint, name and symbol of every token each transaction touched. Use it to see where a '
                       'creator or funder moved SOL or tokens and which other tokens they made or traded.',
        'parameters': {'type': 'object', 'properties': {
            'address': {'type': 'string', 'description': 'Solana wallet address'},
            'limit': {'type': 'integer', 'description': 'How many transactions, 1-50'}},
            'required': ['address']}}},
    {'type': 'function', 'function': {
        'name': 'token_market',
        'description': 'Market data for a Solana token from DexScreener: price, liquidity, volume, pairs, age, and '
                       'the website and social links the project listed.',
        'parameters': {'type': 'object', 'properties': {'mint': {'type': 'string'}}, 'required': ['mint']}}},
    {'type': 'function', 'function': {
        'name': 'search_tokens',
        'description': 'Search Solana tokens on DexScreener by name, symbol or address, to find related or copycat '
                       'tokens.',
        'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}}},
    {'type': 'function', 'function': {
        'name': 'rugbuster_scan',
        'description': 'The RugBuster scan of any Solana token mint: verdict, what the creator bought and sold, bots, '
                       'funding, holders, copies of the name.',
        'parameters': {'type': 'object', 'properties': {'mint': {'type': 'string'}}, 'required': ['mint']}}},
]


def _key(name, env):
    key = os.environ.get(env, '').strip()
    if not key:
        path = DB.parent / name
        key = path.read_text(encoding='utf-8').strip() if path.exists() else ''
    return key


def deepseek_key():
    return _key('deepseek.key', 'DEEPSEEK_API_KEY')


def helius_key():
    return _key('helius.key', 'HELIUS_API_KEY')


def ask_context(scan_data):
    picked = {k: scan_data.get(k) for k in ASK_KEYS if scan_data.get(k) not in (None, [], {})}
    return json.dumps(picked, ensure_ascii=False, default=str)[:12000]


def _pair_summary(p):
    info = p.get('info') or {}
    return {'pair': p.get('pairAddress'), 'dex': p.get('dexId'), 'base': p.get('baseToken') or {},
            'price_usd': p.get('priceUsd'), 'liquidity_usd': (p.get('liquidity') or {}).get('usd'),
            'volume_24h': (p.get('volume') or {}).get('h24'), 'fdv': p.get('fdv'),
            'created_at_ms': p.get('pairCreatedAt'), 'txns_24h': (p.get('txns') or {}).get('h24'),
            'websites': [w.get('url') for w in info.get('websites') or []],
            'socials': [{'type': x.get('type'), 'url': x.get('url')} for x in info.get('socials') or []]}


WSOL = 'So11111111111111111111111111111111111111112'
HELIUS_RPC = 'https://mainnet.helius-rpc.com/?api-key={}'

def token_names(mints, key):
    """{mint: {'name', 'symbol'}} for up to 50 mints, from Helius DAS; {} on any failure."""
    if not mints or not key:
        return {}
    try:
        body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'getAssetBatch', 'params': {'ids': mints}}).encode()
        req = urllib.request.Request(HELIUS_RPC.format(key), body, {'Content-Type': 'application/json',
                                                                    'User-Agent': 'RugBuster-Live-Desk/0.1'})
        with urllib.request.urlopen(req, timeout=25) as response:
            assets = json.load(response).get('result') or []
        out = {}
        for a in assets:
            meta = ((a or {}).get('content') or {}).get('metadata') or {}
            if a and a.get('id'):
                out[a['id']] = {'name': meta.get('name'), 'symbol': meta.get('symbol')}
        return out
    except Exception:
        return {}

def run_tool(name, args):
    """One tool call. Returns plain data for the model; a failure comes back as data too."""
    try:
        if name == 'wallet_activity':
            address = str(args.get('address', '')).strip()
            if not MINT.fullmatch(address):
                return {'error': 'not a Solana address'}
            key = helius_key()
            if not key:
                return {'error': 'wallet history is not set up on this PC'}
            limit = max(1, min(50, int(args.get('limit') or 25)))
            rows = [t for t in fetch(HELIUS_TX.format(address, key, limit)) if isinstance(t, dict)]
            # which tokens each transaction touched, with their names: the parsed
            # description alone gives only amounts, so the model could not name them
            mints = []
            for t in rows:
                for x in t.get('tokenTransfers') or []:
                    m = x.get('mint')
                    if m and m != WSOL and m not in mints:
                        mints.append(m)
            names = token_names(mints[:50], key)
            out = []
            for t in rows:
                tokens = []
                for x in t.get('tokenTransfers') or []:
                    m = x.get('mint')
                    if not m or m == WSOL or any(k['mint'] == m for k in tokens):
                        continue
                    direction = 'in' if x.get('toUserAccount') == address else 'out' if x.get('fromUserAccount') == address else 'other'
                    tokens.append({'mint': m, **names.get(m, {}), 'amount': x.get('tokenAmount'), 'direction': direction})
                out.append({'when': t.get('timestamp'), 'type': t.get('type'), 'source': t.get('source'),
                            'what': (t.get('description') or '')[:240], 'tokens': tokens, 'signature': t.get('signature')})
            return out
        if name == 'token_market':
            mint = str(args.get('mint', '')).strip()
            if not MINT.fullmatch(mint):
                return {'error': 'not a Solana mint'}
            pairs = fetch('https://api.dexscreener.com/tokens/v1/solana/' + mint)
            return [_pair_summary(p) for p in pairs[:5]] or {'note': 'no market on DexScreener'}
        if name == 'search_tokens':
            query = urllib.parse.quote(str(args.get('query', ''))[:60])
            data = fetch('https://api.dexscreener.com/latest/dex/search?q=' + query)
            pairs = [p for p in data.get('pairs') or [] if p.get('chainId') == 'solana']
            return [_pair_summary(p) for p in pairs[:8]] or {'note': 'nothing found'}
        if name == 'rugbuster_scan':
            mint = str(args.get('mint', '')).strip()
            if not MINT.fullmatch(mint):
                return {'error': 'not a Solana mint'}
            return ask_context(read_scan(mint))[:8000]
        return {'error': 'unknown tool'}
    except Exception as error:  # a failed lookup is an answer, not a crash
        return {'error': f'lookup failed: {str(error)[:80]}'}


def _clean_history(history):
    out = []
    for m in (history or [])[-12:]:
        if not isinstance(m, dict):
            continue
        role, content = m.get('role'), str(m.get('content', '')).strip()
        if role in ('user', 'assistant') and content:
            out.append({'role': role, 'content': content[:4000]})
    if not out or out[-1]['role'] != 'user':
        raise ValueError('Type a question about this token.')
    if len(out[-1]['content']) > 1000:
        raise ValueError('Keep the question under 1,000 characters.')
    return out


def ask(mint, history, post=None, tool=run_tool):
    """history: the chat so far, ending with the user's new message. Returns (answer, tools used)."""
    if isinstance(history, str):
        history = [{'role': 'user', 'content': history}]
    messages = _clean_history(history)
    key = deepseek_key()
    if not key:
        raise ValueError('AI chat is not set up on this PC yet.')
    saved = next((x for x in watches() if x['mint'] == mint), None)
    scan_data = saved['scan'] if saved else read_scan(mint)
    convo = [{'role': 'system',
              'content': f'{ASK_RULES}\n\nSELECTED TOKEN MINT: {mint}\nSCAN:\n{ask_context(scan_data)}'}] + messages
    if post is None:
        def post(data):
            req = urllib.request.Request(DEEPSEEK_URL, data, {'Content-Type': 'application/json',
                                                              'Authorization': f'Bearer {key}',
                                                              'User-Agent': 'RugBuster-Live-Desk/0.1'})
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.load(response)
    looked = []
    for round_ in range(MAX_TOOL_ROUNDS + 1):
        payload = {'model': DEEPSEEK_MODEL, 'temperature': 0.3, 'max_tokens': 1600, 'messages': convo}
        if round_ < MAX_TOOL_ROUNDS:
            payload['tools'] = TOOLS
        reply = post(json.dumps(payload).encode())
        message = (reply.get('choices') or [{}])[0].get('message') or {}
        calls = message.get('tool_calls') or []
        if not calls:
            answer = (message.get('content') or '').strip()
            if not answer:
                raise RuntimeError('empty answer')
            return answer, looked
        convo.append({'role': 'assistant', 'content': message.get('content') or '', 'tool_calls': calls})
        for call in calls:
            fn = call.get('function') or {}
            try:
                args = json.loads(fn.get('arguments') or '{}')
            except ValueError:
                args = {}
            looked.append(fn.get('name'))
            convo.append({'role': 'tool', 'tool_call_id': call.get('id'),
                          'content': json.dumps(tool(fn.get('name'), args), ensure_ascii=False, default=str)[:10000]})
    raise RuntimeError('too many lookups')


def patrol_once():
    if not patrol_enabled():
        return
    for item in watches():
        if time.time()-max(item['scanned_at'],patrol_attempts.get(item['mint'],0)) < 300:
            continue
        patrol_attempts[item['mint']] = time.time()
        try:
            scan(item['mint'],existing_only=True)
        except Exception:
            pass  # preserve last retrieval time so failures remain visible

def patrol_loop():
    while True:
        patrol_once()
        time.sleep(30)

def price_loop():
    while True:
        try:
            items = watches()
            with browser_lock:
                if browser_token and not any(x['mint'] == browser_token['mint'] for x in items):
                    items.append({'mint':browser_token['mint']})
            for offset in range(0,len(items),30):
                batch = items[offset:offset+30]
                data = fetch('https://api.dexscreener.com/tokens/v1/solana/' + ','.join(i['mint'] for i in batch))
                for item in batch:
                    pairs = [p for p in data if p.get('chainId') == 'solana' and (p.get('baseToken') or {}).get('address') == item['mint'] and p.get('priceUsd') is not None]
                    best = max(pairs,key=lambda p: float((p.get('liquidity') or {}).get('usd') or 0),default=None)
                    with price_lock:
                        prices[item['mint']] = dict(usd=best['priceUsd'], fetched_at=time.time(),pair=best.get('pairAddress'),source='DexScreener') if best else None
        except Exception:
            pass  # old prices retain their timestamps, UI marks them stale
        time.sleep(60)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, data, mime='application/json'):
        payload = json.dumps(data).encode() if mime == 'application/json' else data
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length',str(len(payload)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        if self.extension_origin():
            self.send_header('Access-Control-Allow-Origin',self.headers['Origin'])
            self.send_header('Vary','Origin')
        self.end_headers()
        self.wfile.write(payload)

    def allowed_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{PORT}',f'localhost:{PORT}')

    def extension_origin(self):
        return bool(re.fullmatch(r'chrome-extension://[a-p]{32}',self.headers.get('Origin','')))

    def do_OPTIONS(self):
        if not self.allowed_host() or not self.extension_origin() or urlparse(self.path).path != '/api/browser':
            return self.send(403,{'error':'Invalid origin'})
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin',self.headers['Origin'])
        self.send_header('Access-Control-Allow-Methods','POST')
        self.send_header('Access-Control-Allow-Headers','Content-Type, X-Desk-Bridge')
        self.end_headers()

    def do_GET(self):
        if not self.allowed_host():
            return self.send(403,{'error':'Invalid host'})
        path = urlparse(self.path).path
        if path == '/api/dashboard':
            if self.headers.get('Origin') and self.headers['Origin'] not in (f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'):
                return self.send(403,{'error':'Invalid origin'})
            with browser_lock:
                current = dict(browser_token,seen_at=browser_seen) if browser_token else None
            if current:
                with price_lock:
                    current['price'] = prices.get(current['mint'])
            return self.send(200,{'items':watches(),'browser':current,'bridge_token':BRIDGE_TOKEN,'patrol':patrol_enabled(),'token':TOKEN,'mode':'local','sync_available':False})
        file = {'/':'index.html','/app.js':'app.js','/style.css':'style.css'}.get(path)
        if file:
            mime = {'index.html':'text/html; charset=utf-8','app.js':'text/javascript; charset=utf-8','style.css':'text/css; charset=utf-8'}[file]
            return self.send(200,(ROOT/'web'/file).read_bytes(),mime)
        self.send(404,{'error':'Not found'})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/api/browser':
            origin = self.headers.get('Origin')
            if not self.allowed_host() or (origin and not self.extension_origin()) or not secrets.compare_digest(self.headers.get('X-Desk-Bridge',''),BRIDGE_TOKEN) or not BRIDGE_TOKEN:
                return self.send(403,{'error':'Pair the extension with Live Desk first.'})
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 256:
                    raise ValueError('Invalid request size')
                body = json.loads(self.rfile.read(length))
                follow_browser(str(body.get('mint','')))
                return self.send(200,{'ok':True})
            except ValueError as e:
                return self.send(400,{'error':str(e)})
            except Exception:
                return self.send(502,{'error':'Desktop preview unavailable. Try again.'})
        if not self.allowed_host() or self.headers.get('X-Desk-Token') != TOKEN:
            return self.send(403,{'error':'Reload Live Desk and try again.'})
        origin = self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'):
            return self.send(403,{'error':'Invalid origin'})
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 65536:
                raise ValueError('Invalid request size')
            body = json.loads(self.rfile.read(length))
            if path == '/api/patrol':
                with connect() as db:
                    db.execute("UPDATE settings SET value=? WHERE key='patrol'",('on' if body.get('enabled') is True else 'off',))
                return self.send(200,{'ok':True})
            mint = str(body.get('mint','')).strip()
            if not MINT.fullmatch(mint):
                raise ValueError('Paste a valid Solana mint address.')
            path = urlparse(self.path).path
            if path == '/api/ask':
                try:
                    answer, looked = ask(mint, body.get('history') or str(body.get('question', '')))
                    return self.send(200, {'ok': True, 'answer': answer, 'looked': looked})
                except ValueError:
                    raise
                except Exception:
                    return self.send(502, {'error': 'The AI did not answer. Try again in a moment.'})
            if path == '/api/track':
                with connect() as db:
                    count = db.execute('SELECT count(*) FROM watches').fetchone()[0]
                    exists = db.execute('SELECT 1 FROM watches WHERE mint=?',(mint,)).fetchone()
                if count >= 20 and not exists:
                    raise ValueError('This local preview supports 20 tokens.')
                scan(mint)
            elif path == '/api/remove':
                with connect() as db:
                    db.execute('DELETE FROM watches WHERE mint=?',(mint,))
                    db.execute('DELETE FROM baselines WHERE mint=?',(mint,))
                    db.execute('DELETE FROM events WHERE mint=?',(mint,))
            else:
                return self.send(404,{'error':'Not found'})
            self.send(200,{'ok':True})
        except ValueError as e:
            self.send(400,{'error':str(e)})
        except Exception:
            self.send(502,{'error':'Could not reach the RugBuster API. Your saved tokens are unchanged.'})

if __name__ == '__main__':
    init()
    httpd = ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    threading.Thread(target=price_loop,daemon=True).start()
    threading.Thread(target=patrol_loop,daemon=True).start()
    print(f'Live Desk: http://127.0.0.1:{PORT}',flush=True)
    httpd.serve_forever()
