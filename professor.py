"""Tiny local web page the professor opens on their phone or laptop.

It only works on the same Wi-Fi, needs the secret link, and sends nothing
to the internet. The page shows each overload alert and has an
Acknowledge button that the student's screen then shows.
"""
import json, os, secrets, socket, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8765

PAGE = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Classroom alerts</title><style>
:root{--bg:#0f1115;--card:#1b1f27;--text:#e9edf3;--muted:#98a2b3;--red:#e5484d;--green:#30a46c}
body{margin:0;background:var(--bg);color:var(--text);font:16px -apple-system,system-ui,sans-serif}
main{max-width:640px;margin:0 auto;padding:20px 16px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 18px}
button{font:inherit;border:0;border-radius:10px;padding:10px 16px;cursor:pointer}
#enable{background:#2b3240;color:var(--text);width:100%;margin-bottom:16px}
.card{background:var(--card);border-left:6px solid var(--red);border-radius:12px;padding:14px 16px;margin-bottom:12px}
.card.ack{border-color:var(--green);opacity:.7}
.who{font-weight:700;font-size:18px}.time{color:var(--muted);font-size:14px}
.why{margin:8px 0}.ackbtn{background:var(--red);color:#fff}.done{color:var(--green);font-weight:600}
.empty{color:var(--muted);text-align:center;padding:40px 0}
</style></head><body><main>
<h1>Classroom support alerts</h1><p class=sub>Live from the student's device. Nothing leaves this Wi-Fi.</p>
<button id=enable>Tap once to turn on alert sound</button>
<div id=list><p class=empty>No alerts yet.</p></div></main><script>
let ctx=null, seen=new Set(), first=true;
document.getElementById('enable').onclick=e=>{ctx=new (window.AudioContext||window.webkitAudioContext)();e.target.textContent='Alert sound on';};
function chime(){if(!ctx)return;[660,880].forEach((f,i)=>{const o=ctx.createOscillator(),g=ctx.createGain();o.frequency.value=f;
g.gain.setValueAtTime(0.0001,ctx.currentTime+i*.25);g.gain.exponentialRampToValueAtTime(.3,ctx.currentTime+i*.25+.03);
g.gain.exponentialRampToValueAtTime(0.0001,ctx.currentTime+i*.25+.6);o.connect(g).connect(ctx.destination);o.start(ctx.currentTime+i*.25);o.stop(ctx.currentTime+i*.25+.7);});
if(navigator.vibrate)navigator.vibrate([200,100,200]);}
async function ack(id){await fetch('ack?id='+id,{method:'POST'});load();}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
async function load(){try{const r=await fetch('alerts.json',{cache:'no-store'});const a=await r.json();
let fresh=false;a.forEach(x=>{if(!seen.has(x.id)){seen.add(x.id);if(!first)fresh=true;}});first=false;if(fresh)chime();
const L=document.getElementById('list');if(!a.length){L.innerHTML='<p class=empty>No alerts yet.</p>';return;}
L.innerHTML=a.slice().reverse().map(x=>`<div class="card ${x.ack?'ack':''}"><div class=who>${esc(x.student)} may be overwhelmed</div>
<div class=time>${esc(x.time)}</div><div class=why>${esc(x.reason)}</div>
${x.triggers.length?`<div class=time>Just before: ${esc(x.triggers.join(', '))}</div>`:''}
<div class=time>${esc(x.sound)}</div><div style="margin-top:10px">${x.ack?'<span class=done>Acknowledged</span>':`<button class=ackbtn onclick="ack(${x.id})">I'm on my way</button>`}</div></div>`).join('');}catch(e){}}
load();setInterval(load,1000);
</script></body></html>"""


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # no packet is sent; this just picks the Wi-Fi address
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class Professor:
    def __init__(self, student_name):
        self.student = student_name
        tok_file = os.path.join(HERE, "professor_token.txt")
        if not os.path.exists(tok_file):
            open(tok_file, "w").write(secrets.token_urlsafe(6))
        self.token = open(tok_file).read().strip()
        self.alerts, self.lock = [], threading.Lock()
        self.url = f"http://{lan_ip()}:{PORT}/p/{self.token}/"
        self._serve()

    def notify(self, reason, triggers, sound):
        with self.lock:
            a = {"id": len(self.alerts) + 1, "time": time.strftime("%I:%M:%S %p").lstrip("0"),
                 "student": self.student, "reason": reason, "triggers": triggers, "sound": sound, "ack": False}
            self.alerts.append(a)
            return a["id"]

    def acked(self, aid):
        with self.lock:
            return any(a["id"] == aid and a["ack"] for a in self.alerts)

    def _serve(self):
        prof = self
        base = f"/p/{self.token}/"

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="text/html; charset=utf-8"):
                b = body.encode()
                self.send_response(code); self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

            def do_GET(self):
                if self.path in (base, base.rstrip("/")):
                    return self._send(200, PAGE)
                if self.path.startswith(base + "alerts.json"):
                    with prof.lock:
                        return self._send(200, json.dumps(prof.alerts), "application/json")
                self._send(404, "not found")

            def do_POST(self):
                if self.path.startswith(base + "ack?id="):
                    try:
                        aid = int(self.path.split("=")[1])
                    except ValueError:
                        return self._send(400, "bad id")
                    with prof.lock:
                        for a in prof.alerts:
                            if a["id"] == aid:
                                a["ack"] = True
                    return self._send(200, "ok", "text/plain")
                self._send(404, "not found")

        try:
            srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            print("professor page:", self.url, flush=True)
        except OSError as e:
            self.url = f"(page failed to start: {e})"
            print(self.url, flush=True)
