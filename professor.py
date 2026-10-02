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
<title>EqualEd alerts</title><style>
:root{--bg:#0f1115;--card:#1b1f27;--text:#e9edf3;--muted:#98a2b3;--red:#e5484d;--orange:#f59e0b;--green:#30a46c}
body{margin:0;background:var(--bg);color:var(--text);font:16px -apple-system,system-ui,sans-serif}
main{max-width:680px;margin:0 auto;padding:20px 16px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 14px}
button{font:inherit;border:0;border-radius:10px;padding:10px 16px;cursor:pointer}
#enable{background:#2b3240;color:var(--text);width:100%;margin-bottom:16px}
.card{background:var(--card);border-left:6px solid var(--red);border-radius:12px;padding:14px 16px;margin-bottom:12px}
.card.trigger{border-color:var(--orange)}.card.ack{border-color:var(--green);opacity:.65}
.who{font-weight:700;font-size:18px}.time{color:var(--muted);font-size:14px}
.why{margin:8px 0}.ackbtn{background:var(--red);color:#fff}.done{color:var(--green);font-weight:600}
.tag{font-size:12px;padding:2px 8px;border-radius:999px;background:#2b3240;color:var(--muted);margin-left:6px}
.empty{color:var(--muted);text-align:center;padding:40px 0}
#toast{position:fixed;left:50%;top:16px;transform:translate(-50%,-140%);transition:transform .35s;z-index:9;
 width:min(92vw,620px);background:var(--red);color:#fff;border-radius:14px;padding:16px 18px;box-shadow:0 10px 40px #0009}
#toast.show{transform:translate(-50%,0)}#toast.trigger{background:#b45309}#toast b{font-size:19px;display:block;margin-bottom:4px}
#flash{position:fixed;inset:0;pointer-events:none;box-shadow:inset 0 0 0 0 var(--red);transition:box-shadow .3s}
#flash.on{box-shadow:inset 0 0 0 10px var(--red)}
</style></head><body><div id=flash></div><div id=toast></div><main>
<h1>EqualEd · classroom alerts</h1><p class=sub>Live from the student's device. Nothing leaves this Wi-Fi.</p>
<button id=enable>Tap once to turn on alert sound and pop-ups</button>
<div id=list><p class=empty>No alerts yet.</p></div></main><script>
let ctx=null, seen=new Set(), first=true, tmr=null;
const KIND={hectic:'needs help: very busy around them',dwell:'someone is staying close to them',overload:'may be overwhelmed',trigger:'sensory trigger'};
document.getElementById('enable').onclick=async e=>{ctx=new (window.AudioContext||window.webkitAudioContext)();
 if(window.isSecureContext&&'Notification' in window){try{await Notification.requestPermission();}catch(_){}}
 e.target.textContent='Alerts on: sound + pop-ups'+(window.isSecureContext&&window.Notification&&Notification.permission==='granted'?' + system notifications':'');};
function chime(urgent){if(!ctx)return;(urgent?[880,660,880]:[660]).forEach((f,i)=>{const o=ctx.createOscillator(),g=ctx.createGain();o.frequency.value=f;
g.gain.setValueAtTime(0.0001,ctx.currentTime+i*.22);g.gain.exponentialRampToValueAtTime(.3,ctx.currentTime+i*.22+.03);
g.gain.exponentialRampToValueAtTime(0.0001,ctx.currentTime+i*.22+.5);o.connect(g).connect(ctx.destination);o.start(ctx.currentTime+i*.22);o.stop(ctx.currentTime+i*.22+.6);});
if(navigator.vibrate)navigator.vibrate(urgent?[300,100,300]:[150]);}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function popup(x){const t=document.getElementById('toast'),urgent=x.kind!=='trigger';
 t.className=(urgent?'':'trigger')+' show';t.innerHTML=`<b>${esc(x.student)}: ${esc(KIND[x.kind]||'alert')}</b>${esc(x.reason)}`;
 const f=document.getElementById('flash');if(urgent){f.className='on';setTimeout(()=>f.className='',1500);}
 clearTimeout(tmr);tmr=setTimeout(()=>t.className=t.className.replace(' show',''),urgent?9000:5000);chime(urgent);
 if(window.isSecureContext&&window.Notification&&Notification.permission==='granted'){try{new Notification('EqualEd: '+x.student,{body:x.reason});}catch(_){}}}
async function ack(id){await fetch('ack?id='+id,{method:'POST'});load();}
async function load(){try{const r=await fetch('alerts.json',{cache:'no-store'});const a=await r.json();
 const fresh=a.filter(x=>!seen.has(x.id));fresh.forEach(x=>seen.add(x.id));
 if(!first&&fresh.length){const pick=fresh.find(x=>x.kind!=='trigger')||fresh[fresh.length-1];popup(pick);}first=false;
 const L=document.getElementById('list');if(!a.length){L.innerHTML='<p class=empty>No alerts yet.</p>';return;}
 L.innerHTML=a.slice().reverse().map(x=>`<div class="card ${x.kind==='trigger'?'trigger':''} ${x.ack?'ack':''}">
 <div class=who>${esc(x.student)} ${esc(KIND[x.kind]||'')}<span class=tag>${esc(x.kind||'alert')}</span></div>
 <div class=time>${esc(x.time)}</div><div class=why>${esc(x.reason)}</div>
 ${x.triggers&&x.triggers.length?`<div class=time>Details: ${esc(x.triggers.join(', '))}</div>`:''}
 ${x.cosmos?`<div class=why><b>NVIDIA Cosmos:</b> ${esc(x.cosmos)}</div>`:''}
 ${x.sound?`<div class=time>${esc(x.sound)}</div>`:''}
 <div style="margin-top:10px">${x.ack?'<span class=done>Acknowledged</span>':`<button class=ackbtn onclick="ack(${x.id})">I'm on my way</button>`}</div></div>`).join('');}catch(e){}}
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
