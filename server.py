"""Railway-ready study app; SQLite needs a mounted /data volume in production."""
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
QUESTIONS = json.loads((ROOT / 'questions.json').read_text(encoding='utf-8'))
LOOKUP = {q['id']: q for q in QUESTIONS}
DB = os.getenv('DATABASE_PATH', '/data/takken.sqlite3' if Path('/data').exists() else str(ROOT / 'takken.sqlite3'))
Path(DB).parent.mkdir(parents=True, exist_ok=True)
PREFECTURES = '北海道 青森県 岩手県 宮城県 秋田県 山形県 福島県 茨城県 栃木県 群馬県 埼玉県 千葉県 東京都 神奈川県 新潟県 富山県 石川県 福井県 山梨県 長野県 岐阜県 静岡県 愛知県 三重県 滋賀県 京都府 大阪府 兵庫県 奈良県 和歌山県 鳥取県 島根県 岡山県 広島県 山口県 徳島県 香川県 愛媛県 高知県 福岡県 佐賀県 長崎県 熊本県 大分県 宮崎県 鹿児島県 沖縄県'.split()
ROLES = ['宅建業従事者', '中学生', '高校生', '大学生', '社会人', 'その他', '未設定']
AGE_BANDS = ['非公開', '13〜15歳', '16〜17歳', '18〜19歳', '20代', '30代', '40代', '50代以上']
AVATARS = ['🏠', '🧑‍💼', '👩‍🎓', '🧑‍🎓', '🦊', '🐻', '🐈', '🏯', '🏢', '🌳']
ITEMS = {'house': {'name':'小さな家','icon':'🏠','cost':8}, 'tree':{'name':'街路樹','icon':'🌳','cost':6}, 'shop':{'name':'商店','icon':'🏪','cost':18}, 'apartment':{'name':'マンション','icon':'🏢','cost':28}, 'park':{'name':'公園','icon':'⛲','cost':20}, 'tower':{'name':'タワー','icon':'🏙️','cost':42}, 'castle':{'name':'お城','icon':'🏯','cost':62}, 'convenience':{'name':'コンビニ','icon':'🏪','cost':16}, 'shrine':{'name':'神社','icon':'⛩️','cost':34}, 'manor':{'name':'洋館','icon':'🏛️','cost':30}, 'pagoda':{'name':'中華楼','icon':'🏮','cost':35}}
STYLES = ['和風','ヨーロッパ風','メルヘン','アジア風','中華風']
ROADS = {'土の道':0,'アスファルト':8,'石畳':12,'レンガ':14}
NEWS = [{'date':'2026-09-25','title':'2026年度の試験は10月18日（日）13:00〜15:00','url':'https://www.retio.or.jp/exam/schedule/','source':'不動産適正取引推進機構'}, {'date':'2026-09-25','title':'受験票の発送予定日は10月2日（金）','url':'https://www.retio.or.jp/exam/schedule/','source':'不動産適正取引推進機構'}, {'date':'2026-09-25','title':'公式サイトで年度別の問題・正解番号を確認できます','url':'https://www.retio.or.jp/exam/past_ques_ans/other/','source':'不動産適正取引推進機構'}]
FAILED = {}
LOCK = threading.Lock()

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def tokhash(token): return hashlib.sha256(token.encode()).hexdigest()
def password_hash(password, salt): return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260000).hex()
def connection():
    db = sqlite3.connect(DB, timeout=20, isolation_level=None)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA foreign_keys=ON')
    return db

def init():
    with connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS users (token TEXT PRIMARY KEY, created_at TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, token TEXT NOT NULL, question_id INTEGER NOT NULL, choice INTEGER NOT NULL, correct INTEGER NOT NULL, created_at TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY, login TEXT NOT NULL UNIQUE COLLATE NOCASE, salt TEXT NOT NULL, password_hash TEXT NOT NULL, display_name TEXT NOT NULL, prefecture TEXT NOT NULL DEFAULT "", role TEXT NOT NULL DEFAULT "未設定", age_band TEXT NOT NULL DEFAULT "非公開", avatar TEXT NOT NULL DEFAULT "🏠", public_rank INTEGER NOT NULL DEFAULT 0, points INTEGER NOT NULL DEFAULT 0, coins INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, last_seen TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE, expires_at TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS ranked_attempts (id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id), question_id INTEGER NOT NULL, choice_json TEXT NOT NULL, correct INTEGER NOT NULL, earned INTEGER NOT NULL, coins INTEGER NOT NULL, created_at TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS ranked_user_question ON ranked_attempts(account_id,question_id,id)')
        db.execute('CREATE TABLE IF NOT EXISTS buildings (id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id), item TEXT NOT NULL, tile INTEGER NOT NULL, created_at TEXT NOT NULL, UNIQUE(account_id,tile))')
        # Existing accounts predate public city sharing; keep them private on migration.
        if not any(r['name']=='public_city' for r in db.execute('PRAGMA table_info(accounts)')):
            db.execute('ALTER TABLE accounts ADD COLUMN public_city INTEGER NOT NULL DEFAULT 0')
        for table, columns in {'accounts':{'city_slots':'INTEGER NOT NULL DEFAULT 12','road_style':'TEXT NOT NULL DEFAULT "土の道"','sidewalk':'INTEGER NOT NULL DEFAULT 0'},'buildings':{'floors':'INTEGER NOT NULL DEFAULT 1','style':'TEXT NOT NULL DEFAULT "和風"'}}.items():
            existing={r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
            for col,definition in columns.items():
                if col not in existing:db.execute(f'ALTER TABLE {table} ADD COLUMN {col} {definition}')
        if not any(r['name']=='test_builder' for r in db.execute('PRAGMA table_info(accounts)')):
            db.execute('ALTER TABLE accounts ADD COLUMN test_builder INTEGER NOT NULL DEFAULT 0')
        if not any(r['name']=='test_until' for r in db.execute('PRAGMA table_info(accounts)')):
            db.execute('ALTER TABLE accounts ADD COLUMN test_until TEXT')
        if not any(r['name']=='city_xp' for r in db.execute('PRAGMA table_info(accounts)')):
            db.execute('ALTER TABLE accounts ADD COLUMN city_xp INTEGER NOT NULL DEFAULT 0')
            db.execute('UPDATE accounts SET city_xp=points')
        db.execute('CREATE TABLE IF NOT EXISTS plot_events (account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE, tile INTEGER NOT NULL, hazard TEXT NOT NULL, ready_at TEXT, PRIMARY KEY(account_id,tile))')
        db.execute('CREATE TABLE IF NOT EXISTS city_events (id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE, detail TEXT NOT NULL, created_at TEXT NOT NULL)')

def public(q): return {k:q.get(k) for k in ('id','topic','question','choices','difficulty','format','origin','year')}
def profile(row, personal=False):
    data={'id':row['id'],'displayName':row['display_name'],'prefecture':row['prefecture'],'role':row['role'],'avatar':row['avatar'],'points':row['points']}
    if personal:data.update(login=row['login'],ageBand=row['age_band'],publicRank=bool(row['public_rank']),publicCity=bool(row['public_city']),coins=row['coins'],cityXp=row['city_xp'],testBuilder=test_access(row),testUntil=row['test_until'])
    data.update(citySlots=row['city_slots'],roadStyle=row['road_style'],sidewalk=bool(row['sidewalk']))
    return data

def city_points(buildings):
    """Public city score is determined only by owned buildings, never by repeat answers."""
    return sum(ITEMS[b['item']]['cost']*10+(b['floors']-1)*80 for b in buildings) + len({b['item'] for b in buildings})*15 + len(buildings)*5

def buildings_for(db, account_id):
    return [dict(r) for r in db.execute('SELECT item,tile,floors,style FROM buildings WHERE account_id=? ORDER BY tile',(account_id,))]

def plots_for(db, account_id):
    return [dict(r) for r in db.execute('SELECT tile,hazard,ready_at FROM plot_events WHERE account_id=? ORDER BY tile',(account_id,))]

def level(points,score):
    return min(99,1+(points+score)//100)

def city_tier(value):
    for minimum, name in ((99,'グローバル都市'),(90,'未来都市'),(70,'世界都市'),(50,'メガシティ'),(40,'大都市'),(30,'中核都市'),(20,'市'),(10,'町'),(1,'村')):
        if value>=minimum:return name

def test_access(row):
    return bool(row['test_builder'] and row['test_until'] and row['test_until']>now())

class Handler(BaseHTTPRequestHandler):
    def respond(self, data, status=200, cookie=None, clear=False):
        body=json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        for k,v in [('Content-Type','application/json; charset=utf-8'),('Content-Length',str(len(body))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')]:self.send_header(k,v)
        if cookie or clear:
            secure='; Secure' if self.headers.get('X-Forwarded-Proto','').split(',')[0].strip()=='https' else ''
            self.send_header('Set-Cookie',f'takken_session={cookie or ""}; HttpOnly; SameSite=Lax; Path=/; Max-Age={0 if clear else 2592000}{secure}')
        self.end_headers();self.wfile.write(body)
    def body(self):
        if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':raise ValueError('JSONで送信してください')
        size=int(self.headers.get('Content-Length','0'))
        if size<2 or size>4096:raise ValueError('送信内容が長すぎます')
        obj=json.loads(self.rfile.read(size))
        if not isinstance(obj,dict):raise ValueError('送信内容が正しくありません')
        return obj
    def account(self,db):
        cookies=SimpleCookie()
        try:cookies.load(self.headers.get('Cookie',''))
        except Exception:return None
        c=cookies.get('takken_session')
        if not c or not re.fullmatch(r'[0-9a-f]{64}',c.value):return None
        row=db.execute('SELECT a.* FROM sessions s JOIN accounts a ON a.id=s.account_id WHERE s.token_hash=? AND s.expires_at>?',(tokhash(c.value),now())).fetchone()
        if row:db.execute('UPDATE accounts SET last_seen=? WHERE id=?',(now(),row['id']))
        return row
    def require(self,db):
        row=self.account(db)
        if row is None:raise PermissionError('アカウントにログインしてください')
        return row
    def csrf(self):
        origin=self.headers.get('Origin')
        host=self.headers.get('X-Forwarded-Host') or self.headers.get('Host','')
        if origin and not origin.lower().endswith('://'+host.lower()):raise PermissionError('送信元を確認できません')
    def session(self,db,account_id):
        token=secrets.token_hex(32)
        expires=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=30)).isoformat()
        db.execute('INSERT INTO sessions VALUES (?,?,?)',(tokhash(token),account_id,expires))
        return token
    def do_GET(self):
        path=self.path.split('?')[0]
        if path=='/health':return self.respond({'ok':True})
        if path in ('/','/index.html'):
            body=(ROOT/'static'/'index.html').read_bytes()
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-cache');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();return self.wfile.write(body)
        if path=='/city3d.js':
            body=(ROOT/'static'/'city3d.js').read_bytes()
            self.send_response(200);self.send_header('Content-Type','application/javascript; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-cache');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();return self.wfile.write(body)
        if path=='/api/state':
            with connection() as db:
                me=self.account(db)
                rows=db.execute('SELECT question_id,correct FROM ranked_attempts WHERE account_id=? ORDER BY id',(me['id'],)).fetchall() if me else []
                latest={}
                for r in rows:latest[r['question_id']]=bool(r['correct'])
                buildings=buildings_for(db,me['id']) if me else []
                online=db.execute('SELECT COUNT(*) FROM accounts WHERE last_seen > ?',( (dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=5)).isoformat(),)).fetchone()[0]
                today=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
                days=max(0,(dt.date(2026,10,18)-today).days)
                city_level=level(me['city_xp'],city_points(buildings)) if me else 1
                return self.respond({'me':profile(me,True) if me else None,'questions':[public(q) for q in QUESTIONS],'attempts':latest,'answered':len(rows),'correct':sum(r['correct'] for r in rows),'buildings':buildings,'plots':plots_for(db,me['id']) if me else [],'cityPoints':city_points(buildings),'cityLevel':city_level,'cityTier':city_tier(city_level),'items':ITEMS,'styles':STYLES,'roads':ROADS,'online':online,'daysLeft':days,'prefectures':PREFECTURES,'roles':ROLES,'ages':AGE_BANDS,'avatars':AVATARS,'news':NEWS,'pastSource':'https://www.retio.or.jp/exam/past_ques_ans/other/'})
        if path=='/api/cities':
            from urllib.parse import parse_qs,urlsplit
            params=parse_qs(urlsplit(self.path).query)
            try: requested=int(params.get('id',['0'])[0])
            except ValueError:return self.respond({'error':'街を見つけられません'},400)
            with connection() as db:
                me=self.account(db)
                if requested:
                    owner=db.execute('SELECT * FROM accounts WHERE id=?',(requested,)).fetchone()
                    if not owner or not(owner['public_city'] or (me and me['id']==requested)):
                        return self.respond({'error':'この街は公開されていません'},404)
                    buildings=buildings_for(db,requested)
                    city_level=level(owner['city_xp'],city_points(buildings))
                    return self.respond({'owner':profile(owner),'buildings':buildings,'plots':plots_for(db,requested),'cityPoints':city_points(buildings),'cityLevel':city_level,'cityTier':city_tier(city_level),'isMine':bool(me and me['id']==requested)})
                rows=db.execute('SELECT id,display_name,prefecture,avatar FROM accounts WHERE public_city=1').fetchall()
                cities=[]
                for owner in rows:
                    buildings=buildings_for(db,owner['id'])
                    if not buildings:continue
                    cities.append({'id':owner['id'],'displayName':owner['display_name'],'prefecture':owner['prefecture'],'avatar':owner['avatar'],'cityPoints':city_points(buildings),'buildingCount':len(buildings)})
                cities.sort(key=lambda c:(-c['cityPoints'],-c['buildingCount'],c['id']))
                return self.respond({'cities':cities[:50],'meId':me['id'] if me else None})
        if path=='/api/live':
            with connection() as db:
                online=db.execute('SELECT COUNT(*) FROM accounts WHERE last_seen > ?',((dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=5)).isoformat(),)).fetchone()[0]
                recent=db.execute('SELECT a.id,a.display_name,a.avatar,b.item,b.created_at FROM buildings b JOIN accounts a ON a.id=b.account_id WHERE a.public_city=1 ORDER BY b.id DESC LIMIT 5').fetchall()
                return self.respond({'online':online,'builds':[{'id':r['id'],'name':r['display_name'],'avatar':r['avatar'],'item':r['item'],'createdAt':r['created_at']} for r in recent]})
        if path=='/api/rankings':
            from urllib.parse import parse_qs,urlsplit
            params=parse_qs(urlsplit(self.path).query)
            scope=params.get('scope',['national'])[0]
            if scope not in ('national','prefecture','weekly'):return self.respond({'error':'範囲が不正です'},400)
            with connection() as db:
                me=self.account(db)
                if scope=='prefecture' and (not me or not me['prefecture']):return self.respond({'rows':[],'scope':scope,'message':'プロフィールで都道府県を選択してください'})
                if scope=='weekly':
                    start=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=7)).isoformat()
                    rows=db.execute('SELECT a.id,a.display_name,a.prefecture,a.role,a.avatar,COALESCE(SUM(r.earned),0) score FROM accounts a LEFT JOIN ranked_attempts r ON r.account_id=a.id AND r.created_at>=? WHERE a.public_rank=1 GROUP BY a.id HAVING score>0 ORDER BY score DESC,a.id LIMIT 50',(start,)).fetchall()
                elif scope=='prefecture':rows=db.execute('SELECT id,display_name,prefecture,role,avatar,points score FROM accounts WHERE public_rank=1 AND prefecture=? AND points>0 ORDER BY points DESC,id LIMIT 50',(me['prefecture'],)).fetchall()
                else:rows=db.execute('SELECT id,display_name,prefecture,role,avatar,points score FROM accounts WHERE public_rank=1 AND points>0 ORDER BY points DESC,id LIMIT 50').fetchall()
                return self.respond({'rows':[dict(r) for r in rows],'scope':scope,'meId':me['id'] if me else None})
        return self.respond({'error':'見つかりません'},404)
    def do_POST(self):
        try:
            self.csrf();data=self.body();path=self.path.split('?')[0]
            with connection() as db:
                if path=='/api/register':
                    login=str(data.get('login','')).strip().lower();pw=data.get('password','');name=str(data.get('name','')).strip()
                    if not re.fullmatch(r'[a-z0-9_]{4,24}',login):raise ValueError('ログインIDは英小文字・数字・_で4〜24文字にしてください')
                    if not isinstance(pw,str) or len(pw)<10 or len(pw)>128:raise ValueError('パスワードは10〜128文字にしてください')
                    if not 2<=len(name)<=18 or any(ord(c)<32 for c in name):raise ValueError('表示名は2〜18文字で入力してください')
                    if not data.get('terms'):raise ValueError('利用上の注意に同意してください')
                    if data.get('ageBand')=='13〜15歳' and not data.get('guardian'):raise ValueError('15歳以下の方は保護者の確認が必要です')
                    salt=secrets.token_hex(16);n=now()
                    try:
                        cur=db.execute('INSERT INTO accounts(login,salt,password_hash,display_name,created_at,last_seen,coins,age_band) VALUES (?,?,?,?,?,?,?,?)',(login,salt,password_hash(pw,salt),name,n,n,0,data.get('ageBand') if data.get('ageBand') in AGE_BANDS else '非公開'))
                    except sqlite3.IntegrityError:raise ValueError('そのログインIDは使用されています')
                    token=self.session(db,cur.lastrowid)
                    return self.respond({'ok':True},cookie=token)
                if path=='/api/login':
                    ip=self.client_address[0]
                    with LOCK:
                        recent=[t for t in FAILED.get(ip,[]) if time.time()-t<900]
                        FAILED[ip]=recent
                        if len(recent)>=12:return self.respond({'error':'しばらくしてから試してください'},429)
                    login=str(data.get('login','')).lower();pw=data.get('password','')
                    row=db.execute('SELECT * FROM accounts WHERE login=?',(login,)).fetchone()
                    valid=row and isinstance(pw,str) and hmac.compare_digest(password_hash(pw,row['salt']),row['password_hash'])
                    if not valid:
                        with LOCK:FAILED.setdefault(ip,[]).append(time.time())
                        raise ValueError('IDまたはパスワードが違います')
                    with LOCK:FAILED.pop(ip,None)
                    token=self.session(db,row['id'])
                    return self.respond({'ok':True},cookie=token)
                if path=='/api/logout':
                    cookies=SimpleCookie()
                    try:cookies.load(self.headers.get('Cookie',''))
                    except Exception:pass
                    c=cookies.get('takken_session')
                    if c:db.execute('DELETE FROM sessions WHERE token_hash=?',(tokhash(c.value),))
                    return self.respond({'ok':True},clear=True)
                me=self.require(db)
                if path=='/api/delete-account':
                    pw=data.get('password','')
                    if not isinstance(pw,str) or not hmac.compare_digest(password_hash(pw,me['salt']),me['password_hash']):raise ValueError('パスワードが違います')
                    db.execute('BEGIN IMMEDIATE')
                    db.execute('DELETE FROM buildings WHERE account_id=?',(me['id'],))
                    db.execute('DELETE FROM plot_events WHERE account_id=?',(me['id'],))
                    db.execute('DELETE FROM city_events WHERE account_id=?',(me['id'],))
                    db.execute('DELETE FROM ranked_attempts WHERE account_id=?',(me['id'],))
                    db.execute('DELETE FROM sessions WHERE account_id=?',(me['id'],))
                    db.execute('DELETE FROM accounts WHERE id=?',(me['id'],))
                    return self.respond({'ok':True},clear=True)
                if path=='/api/profile':
                    name=str(data.get('displayName','')).strip();pref=data.get('prefecture','');role=data.get('role','未設定');age=data.get('ageBand','非公開');avatar=data.get('avatar','🏠')
                    if not 2<=len(name)<=18 or any(ord(c)<32 for c in name):raise ValueError('表示名は2〜18文字で入力してください')
                    if pref and pref not in PREFECTURES:raise ValueError('都道府県を選んでください')
                    if role not in ROLES or age not in AGE_BANDS or avatar not in AVATARS:raise ValueError('プロフィールの選択が正しくありません')
                    if age=='13〜15歳' and not data.get('guardian'):raise ValueError('15歳以下の方は保護者の確認が必要です')
                    db.execute('UPDATE accounts SET display_name=?,prefecture=?,role=?,age_band=?,avatar=?,public_rank=?,public_city=? WHERE id=?',(name,pref,role,age,avatar,int(data.get('publicRank') is True),int(data.get('publicCity') is True),me['id']))
                    return self.respond({'ok':True})
                if path=='/api/claim-test-builder':
                    code=data.get('code');secret=os.getenv('OWNER_TEST_CODE','')
                    if not secret or not isinstance(code,str) or not hmac.compare_digest(code,secret):raise ValueError('コードを確認してください')
                    db.execute('BEGIN IMMEDIATE')
                    if db.execute('SELECT id FROM accounts WHERE test_builder=1 LIMIT 1').fetchone():raise ValueError('テスト用アカウントはすでに設定されています')
                    until=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(hours=24)).isoformat()
                    db.execute('UPDATE accounts SET test_builder=1,test_until=? WHERE id=?',(until,me['id']))
                    return self.respond({'ok':True,'until':until})
                if path=='/api/answer':
                    qid=data.get('id');choices=data.get('choices')
                    if type(qid)!=int or qid not in LOOKUP or not isinstance(choices,list) or any(type(x)!=int for x in choices):raise ValueError('回答が正しくありません')
                    q=LOOKUP[qid]
                    if len(set(choices))!=len(choices) or not choices or any(x<0 or x>=len(q['choices']) for x in choices):raise ValueError('回答が正しくありません')
                    if q['format']=='四肢択一' and len(choices)!=1:raise ValueError('一つ選んでください')
                    correct=sorted(choices)==sorted(q['answer'])
                    db.execute('BEGIN IMMEDIATE')
                    first=db.execute('SELECT id FROM ranked_attempts WHERE account_id=? AND question_id=? LIMIT 1',(me['id'],qid)).fetchone() is None
                    today=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
                    today_utc=dt.datetime.combine(today,dt.time(),dt.timezone(dt.timedelta(hours=9))).astimezone(dt.timezone.utc).isoformat()
                    practiced_today=db.execute('SELECT id FROM ranked_attempts WHERE account_id=? AND question_id=? AND correct=1 AND created_at>=? LIMIT 1',(me['id'],qid,today_utc)).fetchone() is not None
                    multiplier={'初級':1,'中級':2,'上級':3}[q['difficulty']]
                    earned=10*multiplier if correct and first else 0
                    coins=3*multiplier if correct and first else 0
                    xp=earned if earned else (2 if correct and not practiced_today else 0)
                    db.execute('INSERT INTO ranked_attempts(account_id,question_id,choice_json,correct,earned,coins,created_at) VALUES (?,?,?,?,?,?,?)',(me['id'],qid,json.dumps(choices),int(correct),earned,coins,now()))
                    if earned or xp:db.execute('UPDATE accounts SET points=points+?,coins=coins+?,city_xp=city_xp+? WHERE id=?',(earned,coins,xp,me['id']))
                    return self.respond({'correct':correct,'answer':q['answer'],'explanation':q['explanation'],'source':q['source'],'earned':earned,'coins':coins,'xp':xp,'first':first})
                if path=='/api/build':
                    item=data.get('item');tile=data.get('tile')
                    if item not in ITEMS or type(tile)!=int or tile<0 or tile>=24:raise ValueError('区画または建物が不正です')
                    db.execute('BEGIN IMMEDIATE')
                    owner=db.execute('SELECT coins,city_slots FROM accounts WHERE id=?',(me['id'],)).fetchone()
                    if tile>=owner['city_slots']:raise ValueError('この区画はまだ購入されていません')
                    current=owner['coins']
                    if current<ITEMS[item]['cost'] and not test_access(me):raise ValueError('コインが足りません。問題を解いて増やしましょう')
                    if db.execute('SELECT id FROM buildings WHERE account_id=? AND tile=?',(me['id'],tile)).fetchone():raise ValueError('この区画には既に建物があります')
                    hazard=db.execute('SELECT hazard,ready_at FROM plot_events WHERE account_id=? AND tile=?',(me['id'],tile)).fetchone()
                    if hazard and hazard['hazard']!='clear':
                        if hazard['hazard']=='survey' and hazard['ready_at']<=now():db.execute('UPDATE plot_events SET hazard="clear",ready_at=NULL WHERE account_id=? AND tile=?',(me['id'],tile))
                        else:raise ValueError('調査・撤去が終わるまで建築できません')
                    db.execute('INSERT INTO buildings(account_id,item,tile,created_at) VALUES (?,?,?,?)',(me['id'],item,tile,now()))
                    if not test_access(me):db.execute('UPDATE accounts SET coins=coins-? WHERE id=?',(ITEMS[item]['cost'],me['id']))
                    db.execute('INSERT INTO city_events(account_id,detail,created_at) VALUES (?,?,?)',(me['id'],ITEMS[item]['name']+'が完成',now()))
                    return self.respond({'ok':True})
                if path=='/api/city-action':
                    action=data.get('action');tile=data.get('tile')
                    db.execute('BEGIN IMMEDIATE')
                    owner=db.execute('SELECT coins,city_slots,sidewalk FROM accounts WHERE id=?',(me['id'],)).fetchone()
                    cost=0;message='街が更新されました'
                    if action=='expand':
                        if owner['city_slots']>=24:raise ValueError('敷地は最大24区画です')
                        cost=12+((owner['city_slots']-12)//4)*8
                        if owner['coins']<cost and not test_access(me):raise ValueError('拡張コインが足りません')
                        old=owner['city_slots'];db.execute('UPDATE accounts SET city_slots=city_slots+4 WHERE id=?',(me['id'],))
                        # An occasional surprise affects only one newly unlocked plot.
                        if secrets.randbelow(4)==0:
                            affected=old+secrets.randbelow(4);hazard='heritage' if secrets.randbelow(2) else 'underground'
                            db.execute('INSERT INTO plot_events(account_id,tile,hazard) VALUES (?,?,?)',(me['id'],affected,hazard))
                            message=f'4区画拡張！ 区画{affected+1}で'+('埋蔵文化財が見つかりました' if hazard=='heritage' else '地中埋設物が見つかりました')
                        else:message='4区画拡張しました！'
                    elif action in ('demolish','renovate','add_floor','survey','clear_obstruction'):
                        if type(tile)!=int or not 0<=tile<owner['city_slots']:raise ValueError('区画が不正です')
                        building=db.execute('SELECT * FROM buildings WHERE account_id=? AND tile=?',(me['id'],tile)).fetchone()
                        hazard=db.execute('SELECT * FROM plot_events WHERE account_id=? AND tile=?',(me['id'],tile)).fetchone()
                        if action=='demolish':
                            if not building:raise ValueError('この区画に建物はありません')
                            cost=5+building['floors']*3;db.execute('DELETE FROM buildings WHERE id=?',(building['id'],));message='解体が完了しました'
                        elif action=='renovate':
                            style=data.get('style')
                            if not building or style not in STYLES or style==building['style']:raise ValueError('改築する建物と様式を選んでください')
                            cost=7;db.execute('UPDATE buildings SET style=? WHERE id=?',(style,building['id']));message=style+'に改築しました'
                        elif action=='add_floor':
                            if not building or building['item'] not in ('house','shop','apartment','tower','convenience','manor') or building['floors']>=12:raise ValueError('この建物は増築できません')
                            cost=6+building['floors']*4;db.execute('UPDATE buildings SET floors=floors+1 WHERE id=?',(building['id'],));message=f'{building["floors"]+1}階に増築しました'
                        elif action=='survey':
                            if not hazard or hazard['hazard']!='heritage':raise ValueError('調査が必要な区画ではありません')
                            cost=9;ready=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=3)).isoformat()
                            db.execute('UPDATE plot_events SET hazard="survey",ready_at=? WHERE account_id=? AND tile=?',(ready,me['id'],tile));message='調査を開始。3分後に建築できます'
                        elif action=='clear_obstruction':
                            if not hazard or hazard['hazard']!='underground':raise ValueError('撤去が必要な区画ではありません')
                            cost=6;db.execute('UPDATE plot_events SET hazard="clear" WHERE account_id=? AND tile=?',(me['id'],tile));message='地中埋設物を撤去しました'
                    elif action=='road':
                        style=data.get('style')
                        if style not in ROADS:raise ValueError('道路の種類を選んでください')
                        cost=ROADS[style];db.execute('UPDATE accounts SET road_style=? WHERE id=?',(style,me['id']));message=style+'を整備しました'
                    elif action=='sidewalk':
                        if owner['sidewalk']:raise ValueError('歩道は整備済みです')
                        cost=10;db.execute('UPDATE accounts SET sidewalk=1 WHERE id=?',(me['id'],));message='歩道を整備しました'
                    else:raise ValueError('操作が不正です')
                    if owner['coins']<cost and not test_access(me):raise ValueError('コインが足りません。問題を解いて増やしましょう')
                    if not test_access(me):db.execute('UPDATE accounts SET coins=coins-? WHERE id=?',(cost,me['id']))
                    db.execute('INSERT INTO city_events(account_id,detail,created_at) VALUES (?,?,?)',(me['id'],message,now()))
                    return self.respond({'ok':True,'cost':cost,'message':message})
                return self.respond({'error':'見つかりません'},404)
        except PermissionError as exc:return self.respond({'error':str(exc)},401)
        except (ValueError,TypeError,OverflowError,json.JSONDecodeError) as exc:return self.respond({'error':str(exc) or '入力を確認してください'},400)
        except sqlite3.IntegrityError:return self.respond({'error':'既に登録されています'},409)

if __name__=='__main__':
    init()
    ThreadingHTTPServer(('0.0.0.0',int(os.getenv('PORT','8000'))),Handler).serve_forever()
