#!/usr/bin/env python3
import http.server
import socketserver
import json
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.parse
import sys

# Forçar output imediato para o log do systemd
def log(msg): print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

MPV_SOCKET = "/tmp/mpv-ytmusic"
QUEUE_FILE = os.path.expanduser("~/.ytmusic_queue.json")
PORT = 8080

# State
state = {
    "queue": [],      
    "current_idx": -1,
    "loop": True,
    "shuffle": False,
    "status": "stopped",
    "title": "",
    "volume": 80,
    "infinite_mode": True,
    "last_query": "gym workout mix"
}
mpv_proc = None
lock = threading.Lock()
refill_lock = False

def save_state():
    try:
        with open(QUEUE_FILE, "w") as f:
            json.dump({
                "queue": state["queue"],
                "current_idx": state["current_idx"],
                "loop": state["loop"],
                "shuffle": state["shuffle"],
                "volume": state["volume"],
                "infinite_mode": state["infinite_mode"],
                "last_query": state["last_query"]
            }, f)
    except Exception as e: log(f"ERRO save_state: {e}")

def load_state():
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, "r") as f:
                data = json.load(f)
                state["queue"] = data.get("queue", [])
                state["current_idx"] = data.get("current_idx", -1)
                state["loop"] = data.get("loop", True)
                state["shuffle"] = data.get("shuffle", False)
                state["volume"] = data.get("volume", 80)
                state["infinite_mode"] = data.get("infinite_mode", True)
                state["last_query"] = data.get("last_query", "gym workout mix")
            log(f"Estado carregado. Fila: {len(state['queue'])}. Inf: {state['infinite_mode']}")
        except Exception as e: log(f"ERRO load_state: {e}")

def mpv_command(*args):
    try:
        log(f"Enviando mpv_command: {args}")
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(MPV_SOCKET)
        cmd = json.dumps({"command": list(args)}) + "\n"
        s.sendall(cmd.encode())
        resp = s.recv(4096).decode().strip()
        s.close()
        log(f"Resposta mpv_command: {resp[:100]}...")
        return json.loads(resp) if resp else {}
    except Exception as e: 
        log(f"AVISO mpv_command falhou (mpv pode estar morto): {e}")
        return {"error": str(e)}

def mpv_get_property(prop):
    data = mpv_command("get_property", prop)
    return data.get("data") if data else None

def get_yt_info(query_or_url, is_playlist_search=False):
    log(f"Busca yt-dlp: '{query_or_url}' (modo_playlist={is_playlist_search})")
    if "youtube.com" in query_or_url or "youtu.be" in query_or_url: target = query_or_url
    else:
        q = query_or_url
        if is_playlist_search: target = f"ytsearch30:{q} playlist music"
        else: target = f"ytsearch30:{q}"

    cmd = ["yt-dlp", "--flat-playlist", "--print", "%(id)s|||%(title)s|||%(duration_string)s", target]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        results = []
        if r.returncode != 0: log(f"ERRO yt-dlp: {r.stderr}")
        for line in r.stdout.strip().split("\n"):
            if "|||" in line:
                p = line.split("|||")
                results.append({"id": p[0], "title": p[1].strip(), "duration": p[2] if len(p)>2 else "", "url": f"https://www.youtube.com/watch?v={p[0]}"})
        log(f"Busca OK: {len(results)} itens.")
        return results
    except Exception as e: log(f"ERRO get_yt_info: {e}"); return []

def refill_queue():
    global refill_lock
    try:
        log(f"THREADS - refill_queue para '{state['last_query']}'")
        items = get_yt_info(state["last_query"])
        if items:
            with lock:
                state["queue"].extend(items)
                save_state()
                log(f"THREADS - Refil OK: +{len(items)}")
    finally:
        refill_lock = False

def ensure_mpv():
    global mpv_proc
    with lock:
        if mpv_proc and mpv_proc.poll() is None: 
            return True
        log("Iniciando processo mpv...")
        # Limpeza agressiva do socket
        if os.path.exists(MPV_SOCKET) or os.path.islink(MPV_SOCKET):
            try: 
                os.remove(MPV_SOCKET)
                log(f"Socket antigo {MPV_SOCKET} removido.")
            except Exception as e: 
                log(f"Erro ao remover socket: {e}")
        cmd = [
            "mpv",
            "--no-video",
            "--input-ipc-server=" + MPV_SOCKET,
            "--cache=yes",
            "--demuxer-max-bytes=50M",
            "--demuxer-readahead-secs=30",
            "--ytdl-format=bestaudio[ext=m4a]/bestaudio/best",
            "--volume=" + str(state["volume"]),
            "--idle=yes",
            "--force-window=no"
        ]

        try:
            log(f"Executando mpv: {' '.join(cmd)}")
            mpv_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for i in range(50):
                if os.path.exists(MPV_SOCKET): 
                    log(f"Processo mpv OK (Socket criado em {i*0.1}s)")
                    return True
                time.sleep(0.1)
        except Exception as e:
            log(f"ERRO ao iniciar mpv: {e}")
        log("FALHA ao iniciar mpv (Socket nao encontrado apos 5s)")
        return False

def play_item(idx):
    if not (0 <= idx < len(state["queue"])): 
        log(f"play_item falhou: idx {idx} fora da fila ({len(state['queue'])})")
        return
    if ensure_mpv():
        state["current_idx"] = idx
        item = state["queue"][idx]
        log(f"AÇAO - TENTANDO TOCAR [{idx}]: {item['title']}")
        res = mpv_command("loadfile", item["url"])
        if "error" in res:
            log(f"ERRO play_item loadfile: {res['error']}")
        else:
            state["status"] = "playing"; state["title"] = item["title"]
            log(f"AÇAO - play_item TOCANDO OK")

def stop_playback():
    global mpv_proc
    log("AÇAO - stop_playback")
    mpv_command("quit")
    if mpv_proc: 
        try: mpv_proc.kill()
        except: pass
        mpv_proc = None
    state["status"] = "stopped"; state["title"] = ""; state["current_idx"] = -1

def monitor_thread():
    global refill_lock
    log("Monitor thread iniciada.")
    while True:
        try:
            # 1. Manter reprodução
            if state["status"] == "playing":
                idle = mpv_get_property("idle-active")
                if idle is True:
                    log("Monitor detectou idle (musica acabou). Seguindo...")
                    with lock:
                        n = state["current_idx"] + 1
                        if n >= len(state["queue"]):
                            if state["loop"]: n = 0
                            else: stop_playback(); n = -1
                        if n != -1: play_item(n)
            
            # 2. Refil Infinito
            if state["infinite_mode"] and not refill_lock:
                remaining = len(state["queue"]) - (state["current_idx"] + 1)
                if remaining < 5 and state["queue"]:
                    log(f"Monitor detectou fila baixa ({remaining}). Refill...")
                    refill_lock = True
                    threading.Thread(target=refill_queue, daemon=True).start()
                    
        except Exception as e: log(f"AVISO monitor_thread: {e}")
        time.sleep(3)

def get_sys_info():
    info = {"cpu": 0, "ram": 0, "internet": False, "source": "YT Music"}
    try:
        # PING rápido
        ping_cmd = ["ping", "-c", "1", "-W", "1", "8.8.8.8"] if sys.platform != "win32" else ["ping", "-n", "1", "-w", "1000", "8.8.8.8"]
        res = subprocess.run(ping_cmd, capture_output=True)
        info["internet"] = (res.returncode == 0)
        
        if sys.platform != "win32":
            # Check Source via systemctl
            if subprocess.run(["systemctl", "is-active", "go-librespot"], capture_output=True).returncode == 0:
                info["source"] = "Spotify"
            elif subprocess.run(["systemctl", "is-active", "mpd"], capture_output=True).returncode == 0:
                info["source"] = "MPD Offline"
            
            # Stats
            with open("/proc/loadavg", "r") as f: info["cpu"] = f.read().split()[0]
            with open("/proc/meminfo", "r") as f: 
                m = f.readlines()
                total = int(m[0].split()[1]); free = int(m[2].split()[1])
                info["ram"] = round(((total - free) / total) * 100, 1)
    except: pass
    return info

HTML_V3 = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no, viewport-fit=cover">
<title>Academia Espaço viva Infinite | Music Server</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #05060b;
  --glass: rgba(255, 255, 255, 0.03);
  --glass-border: rgba(255, 255, 255, 0.08);
  --accent: hsl(265, 89%, 60%);
  --accent-glow: hsla(265, 89%, 60%, 0.4);
  --secondary: hsl(300, 89%, 55%);
  --success: hsl(142, 71%, 45%);
  --warning: hsl(38, 92%, 50%);
  --danger: hsl(350, 89%, 60%);
  --text: #ffffff;
  --text-dim: rgba(255, 255, 255, 0.5);
  --safe-bottom: env(safe-area-inset-bottom);
}

* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color: transparent; }
body {
  font-family: 'Outfit', sans-serif;
  background: var(--bg);
  background: radial-gradient(circle at 50% -20%, hsl(265, 80%, 15%) 0%, var(--bg) 80%);
  color: var(--text);
  min-height: 100vh;
  padding-bottom: calc(180px + var(--safe-bottom));
  overflow-x: hidden;
}

.container { max-width: 600px; margin: 0 auto; padding: 20px; }

header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}
.brand h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.5px; background: linear-gradient(to right, #fff, var(--text-dim)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.sys-info { display: flex; gap: 12px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
.status-pill { background: var(--glass); border: 1px solid var(--glass-border); padding: 4px 8px; border-radius: 6px; display: flex; align-items: center; gap: 5px; }
.dot { width: 6px; height: 6px; border-radius: 50%; }
.dot-online { background: var(--success); box-shadow: 0 0 8px var(--success); }
.dot-offline { background: var(--danger); }

.card {
  background: var(--glass);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--glass-border);
  border-radius: 20px;
  padding: 20px;
  margin-bottom: 20px;
}

.card-title { font-size: 12px; font-weight: 700; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 16px; display: flex; justify-content: space-between; }

.search-box { position: relative; margin-bottom: 15px; }
input {
  width: 100%;
  background: rgba(0,0,0,0.3);
  border: 1px solid var(--glass-border);
  border-radius: 12px;
  padding: 14px 16px;
  color: #fff;
  font-size: 15px;
  outline: none;
  transition: all 0.3s;
}
input:focus { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-glow); }

.search-btn {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  background: var(--accent);
  border: none;
  border-radius: 8px;
  width: 36px;
  height: 36px;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}
.search-btn:active { transform: translateY(-50%) scale(0.9); }

.action-btns { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.btn {
  border: none;
  border-radius: 12px;
  padding: 12px;
  font-weight: 700;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: transform 0.2s, opacity 0.2s;
}
.btn:active { transform: scale(0.96); }
.btn-primary { background: var(--accent); color: #fff; }
.btn-secondary { background: var(--glass); border: 1px solid var(--glass-border); color: #fff; }
.btn-outline { background: transparent; border: 1px solid var(--glass-border); color: var(--text-dim); }

/* Quick Chips */
.chips-grid { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 15px; max-height: 120px; overflow-y: auto; padding-right: 5px; }
.chips-grid::-webkit-scrollbar { width: 4px; }
.chips-grid::-webkit-scrollbar-thumb { background: var(--glass-border); border-radius: 10px; }
.chip {
  background: var(--glass);
  border: 1px solid var(--glass-border);
  padding: 8px 14px;
  border-radius: 50px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s;
}
.chip:hover { background: var(--glass-border); border-color: var(--text-dim); }
.chip.active { background: var(--accent); border-color: var(--accent); }

/* Queue List */
.queue-list { display: flex; flex-direction: column; gap: 8px; }
.q-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: rgba(255,255,255,0.02);
  border-radius: 12px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.2s;
}
.q-item:hover { background: rgba(255,255,255,0.05); }
.q-item.playing {
  background: hsla(265, 89%, 60%, 0.1);
  border-color: var(--accent-glow);
}
.q-idx { font-size: 10px; font-weight: 700; color: var(--text-dim); width: 20px; }
.q-info { flex: 1; min-width: 0; }
.q-title { font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.q-meta { font-size: 11px; color: var(--text-dim); margin-top: 2px; }
.q-remove { color: var(--danger); padding: 8px; font-size: 18px; opacity: 0.6; }
.q-remove:hover { opacity: 1; }

/* Fixed Player Bar */
.player-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: rgba(7, 9, 18, 0.85);
  backdrop-filter: blur(25px);
  -webkit-backdrop-filter: blur(25px);
  border-top: 1px solid var(--glass-border);
  padding: 16px 20px calc(16px + var(--safe-bottom));
  z-index: 1000;
}
.now-playing { margin-bottom: 20px; }
.np-title { font-size: 15px; font-weight: 700; text-align: center; margin-bottom: 4px; color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.np-status { font-size: 10px; text-transform: uppercase; letter-spacing: 2px; font-weight: 700; text-align: center; color: var(--accent); }

.player-ctrls { display: flex; justify-content: center; align-items: center; gap: 24px; }
.p-btn { background: transparent; border: none; color: #fff; cursor: pointer; transition: all 0.2s; }
.p-btn-main {
  width: 60px;
  height: 60px;
  background: #fff;
  color: #000;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  box-shadow: 0 8px 24px rgba(255,255,255,0.2);
}
.p-btn-main:active { transform: scale(0.92); }

.inf-mode { display: flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 700; color: var(--text-dim); }
.toggle { width: 44px; height: 24px; background: var(--glass-border); border-radius: 20px; position: relative; cursor: pointer; transition: 0.3s; }
.toggle::after { content: ''; position: absolute; left: 2px; top: 2px; width: 20px; height: 20px; background: #fff; border-radius: 50%; transition: 0.3s; }
.toggle.active { background: var(--success); }
.toggle.active::after { left: calc(100% - 22px); }

/* Volume Slider */
.volume-ctrl { display: flex; align-items: center; gap: 10px; width: 100%; max-width: 200px; margin-top: 15px; }
.volume-slider { flex: 1; -webkit-appearance: none; height: 4px; background: var(--glass-border); border-radius: 2px; outline: none; }
.volume-slider::-webkit-slider-thumb { -webkit-appearance: none; width: 14px; height: 14px; background: #fff; border-radius: 50%; cursor: pointer; box-shadow: 0 0 10px rgba(255,255,255,0.3); }

/* Auth Overlay Rendering Header Only */
.auth-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: var(--bg);
  z-index: 10000;
  display: flex; align-items: center; justify-content: center;
  padding: 20px;
}
.auth-card { width: 100%; max-width: 320px; text-align: center; }
.auth-input { width: 100%; text-align: center; font-size: 20px; letter-spacing: 4px; margin-bottom: 20px; background: rgba(255,255,255,0.05); border: 1px solid var(--glass-border); border-radius: 12px; padding: 10px; color: #fff; outline:none; }

/* Animations */
@keyframes pulse { 0% { opacity: 0.4; } 50% { opacity: 1; } 100% { opacity: 0.4; } }
.is-loading { animation: pulse 1s infinite; pointer-events: none; opacity: 0.7; }

/* Mobile Adjustments */
@media (max-width: 480px) {
  .container { padding: 12px; }
  .brand h1 { font-size: 18px; }
  .sys-info { flex-wrap: wrap; gap: 6px; }
  .status-pill { font-size: 10px; padding: 3px 6px; }
  .card { padding: 15px; border-radius: 16px; }
  .action-btns { grid-template-columns: 1fr; }
  .np-title { font-size: 13px; }
  .player-ctrls { gap: 16px; }
  .p-btn-main { width: 50px; height: 50px; font-size: 20px; }
  .chips-grid { max-height: 160px; }
}

@media (min-width: 601px) {
  body { padding-top: 20px; }
}

</style>
</head>
<body>

<div id="auth" class="auth-overlay">
  <div class="auth-card">
    <div class="brand"><h1>Academia Espaço viva</h1></div>
    <p style="margin-bottom: 20px; opacity: 0.7;">Controle de Música</p>
    <input type="password" id="pass" class="auth-input" placeholder="SENHA" onkeydown="if(event.key==='Enter') login()">
    <button class="btn btn-primary" style="width: 100%;" onclick="login()">ENTRAR</button>
  </div>
</div>

<div class="container">
  <header>
    <div class="brand"><h1>Academia Espaço viva Infinite</h1></div>
    <div class="sys-info">
      <div class="status-pill"><div class="dot" id="dotNet"></div> <span id="netText">---</span></div>
      <div class="status-pill">CPU <span id="cpuText">0%</span></div>
    </div>
  </header>

  <div class="card">
    <div class="card-title">Busca Inteligente <span class="inf-mode" onclick="api('/infinite').then(refresh)">Auto-Refill</span></div>
    <div class="search-box">
      <input type="text" id="inp" placeholder="O que vamos ouvir hoje?" onkeydown="if(event.key==='Enter') add('track')">
      <button class="search-btn" onclick="add('track')">🔍</button>
    </div>
    <div class="action-btns">
      <button class="btn btn-primary" onclick="add('playlist')">📂 Playlists</button>
      <button class="btn btn-secondary" id="clearBtnMain" onclick="confirmClear(this)">🗑️ Limpar</button>
    </div>
    <div class="chips-grid">
        <div class="chip" onclick="quick('🔥 Cross Brutal (Hardstyle)')">🔥 Cross Brutal</div>
        <div class="chip" onclick="quick('⚡ Cardio Techno')">⚡ Cardio Techno</div>
        <div class="chip" onclick="quick('💣 PR Day Mix')">💣 PR Day</div>
        <div class="chip" onclick="quick('🇧🇷 Brasil Workout Remix')">🇧🇷 Brasil Remix</div>
        <div class="chip" onclick="quick('🎧 Pop Internacional Remix')">🎧 Pop Remix</div>
        <div class="chip" onclick="quick('🥊 Fight Training')">🥊 Fight Training</div>
        <div class="chip" onclick="quick('rock nacional brasileiro anos 80 90')">🎸 Rock BR</div>
        <div class="chip" onclick="quick('classic rock hits 70s 80s 90s')">🔥 Classic Rock</div>
    </div>
  </div>

  <div class="card" id="qCard" style="display:none">
    <div class="card-title">Fila de Reprodução <button class="btn btn-secondary" id="clearBtnQueue" style="padding: 4px 10px; font-size: 9px;" onclick="confirmClear(this)">LIMPAR</button></div>
    <div class="queue-list" id="qList"></div>
  </div>
</div>

<div class="player-bar">
  <div class="now-playing">
    <div class="np-title" id="npTitle">---</div>
    <div class="np-status" id="npStatus">Desconectado</div>
  </div>
  <div class="player-ctrls">
    <button class="p-btn" onclick="api('/prev').then(refresh)">⏮</button>
    <button class="p-btn p-btn-main" id="playBtn" onclick="api('/toggle').then(refresh)">▶</button>
    <button class="p-btn" onclick="api('/next').then(refresh)">⏭</button>
  </div>
  <div style="display:flex; justify-content:center;">
    <div class="volume-ctrl">
      <span>🔈</span>
      <input type="range" class="volume-slider" id="vol" min="0" max="100" oninput="setVol(this.value)">
      <span>🔊</span>
    </div>
  </div>
</div>

<script>
let lastState = null;

async function api(p, data={}) {
  const auth = localStorage.getItem('espacoviva_auth');
  if(!auth) return;
  try {
    const r = await fetch('/api'+p, { 
        method:'POST', 
        cache:'no-cache', 
        body: JSON.stringify(data),
        headers: { 
          'Content-Type': 'application/json',
          'X-Api-Key': auth
        }
    });
    if(r.status === 401) { logout(); return; }
    return r.json();
  } catch(e) { console.error('API Error', e); }
}

function login() {
  const p = document.getElementById('pass').value;
  if(p === 'espacoviva') {
    localStorage.setItem('espacoviva_auth', p);
    document.getElementById('auth').style.display = 'none';
    refresh();
  } else {
    alert('Senha incorreta!');
    document.getElementById('pass').value = '';
  }
}

function logout() {
  localStorage.removeItem('espacoviva_auth');
  location.reload();
}

if(localStorage.getItem('espacoviva_auth') === 'espacoviva') {
  document.getElementById('auth').style.display = 'none';
}

async function refresh() {
  const auth = localStorage.getItem('espacoviva_auth');
  if(!auth) return;
  try {
    const s = await fetch('/api/state?t=' + Date.now() + '&auth=' + auth).then(r=>r.json());
    document.getElementById('npTitle').textContent = s.title || (s.status === 'playing' ? 'Tocando...' : 'Pausado');
    document.getElementById('npStatus').textContent = s.status === 'playing' ? '● AO VIVO' : 'Pausado';
    document.getElementById('playBtn').textContent = s.status === 'playing' ? '⏸' : '▶';
    
    const qList = document.getElementById('qList');
    if(s.queue.length > 0) {
        document.getElementById('qCard').style.display = 'block';
        qList.innerHTML = s.queue.slice(0, 50).map((it, i) => `
            <div class="q-item ${s.current_idx == i ? 'playing' : ''}" onclick="play(${i})">
                <div class="q-idx">${i+1}</div>
                <div class="q-info">
                    <div class="q-title">${it.title}</div>
                    <div class="q-meta">${it.duration || '00:00'}</div>
                </div>
            </div>
        `).join('');
    } else {
        document.getElementById('qCard').style.display = 'none';
    }
    document.getElementById('dotNet').className = 'dot ' + (s.sys.internet ? 'dot-online' : 'dot-offline');
    document.getElementById('netText').textContent = s.sys.internet ? 'Online' : 'Offline';
    document.getElementById('cpuText').textContent = s.sys.cpu + '%';
  } catch(e) { 
      document.getElementById('npStatus').textContent = "Offline ⚠️";
  }
}

async function add(mode) {
  const v = document.getElementById('inp').value;
  if(!v) return;
  await api('/add', { q: v, mode: mode });
  document.getElementById('inp').value = '';
  setTimeout(refresh, 2000);
}

function quick(q) { document.getElementById('inp').value = q; add('playlist'); }
function play(idx) { api('/play', {i: idx}).then(refresh); }
function setVol(v) { api('/volume', {v: v}); }

function confirmClear(btn) {
  if (btn.dataset.conf === "1") {
    api('/clear').then(() => {
      btn.dataset.conf = "0";
      btn.textContent = btn.id === "clearBtnQueue" ? "LIMPAR" : "🗑️ Limpar";
      refresh();
    });
  } else {
    btn.dataset.conf = "1";
    btn.textContent = "CONFIRMAR?";
    setTimeout(() => { btn.dataset.conf = "0"; btn.textContent = btn.id === "clearBtnQueue" ? "LIMPAR" : "🗑️ Limpar"; }, 3000);       
  }
}

setInterval(refresh, 5000);
refresh();
</script>
</body>
</html>"""

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer): pass
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def check_auth(self):
        # Permitir index e assets sem senha
        if self.path == "/" or "/index.html" in self.path: return True
        # Check API Key
        key = self.headers.get("X-Api-Key")
        if not key:
            # Fallback for state via URL param (used in simple fetch)
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            key = params.get("auth", [None])[0]
        
        if key == "espacoviva": return True
        self._unauthorized()
        return False

    def _unauthorized(self):
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "unauthorized"}).encode())

    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Api-Key")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Api-Key")
        self.end_headers()

    def do_GET(self):
        if not self.check_auth(): return
        if self.path == "/" or "/index.html" in self.path: 
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_V3.encode('utf-8'))
        elif "/api/state" in self.path:
            t = mpv_get_property("media-title"); p = mpv_get_property("pause")
            st = "playing" if p is False else "stopped"
            state["title"] = t or state["title"]; state["status"] = st
            self._json({ **state, "sys": get_sys_info() })

    def do_POST(self):
        if not self.check_auth(): return
        try:
            cl = int(self.headers.get('Content-Length', 0)); data = json.loads(self.rfile.read(cl)) if cl else {}
            log(f"API RECEBIDA: {self.path} - DATA: {data}")
            if self.path == "/api/add":
                q = data.get("q")
                items = get_yt_info(q, is_playlist_search=("playlist" in data.get("mode", "")))
                with lock: 
                    state["queue"].extend(items); save_state()
                self._json({"ok": True, "count": len(items)})
            elif self.path == "/api/clear":
                with lock: stop_playback(); state["queue"] = []; state["current_idx"] = -1; save_state()
                self._json({"ok": True})
            elif self.path == "/api/remove":
                idx = int(data.get("i", -1))
                with lock:
                    if 0 <= idx < len(state["queue"]):
                        state["queue"].pop(idx)
                        if idx == state["current_idx"]: stop_playback()
                        elif idx < state["current_idx"]: state["current_idx"] -= 1
                        save_state()
                self._json({"ok": True})
            elif self.path == "/api/play": play_item(int(data.get("i", 0))); self._json({"ok": True})
            elif self.path == "/api/toggle":
                ensure_mpv()
                if state["status"] == "stopped" and state["queue"]: 
                    play_item(max(0, state["current_idx"]))
                else: 
                    mpv_command("cycle", "pause")
                self._json({"ok": True})
            elif self.path == "/api/next":
                with lock:
                    if state["current_idx"] + 1 < len(state["queue"]): play_item(state["current_idx"]+1)
                    elif state["loop"]: play_item(0)
                self._json({"ok": True})
            elif self.path == "/api/prev":
                with lock:
                    if state["current_idx"] > 0: play_item(state["current_idx"] - 1)
                self._json({"ok": True})
            elif self.path == "/api/infinite": state["infinite_mode"] = not state["infinite_mode"]; save_state(); self._json({"infinite": state["infinite_mode"]})
            elif self.path == "/api/volume":
                v = int(data.get("v", 80))
                state["volume"] = v; mpv_command("set_property", "volume", v); save_state()
                self._json({"ok": True})
        except Exception as e: log(f"ERRO API_POST: {e}"); self._json({"error": str(e)})

load_state()
# Auto-resume on startup if queue exists
log(f"Auto-resume DEBUG: queue_len={len(state['queue'])}, current_idx={state['current_idx']}")
if state["queue"] and state["current_idx"] >= 0:
    log(f"Auto-resume: iniciando reprodução do índice {state['current_idx']} em 5 segundos...")
    def auto_play():
        time.sleep(5)
        play_item(state["current_idx"])
    threading.Thread(target=auto_play, daemon=True).start()
else:
    log("Auto-resume: fila vazia, nada para tocar.")

threading.Thread(target=monitor_thread, daemon=True).start()
log(f"Academia Infinite Premium v4.0 iniciada na porta {PORT}")
ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
