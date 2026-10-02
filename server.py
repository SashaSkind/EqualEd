"""Local web pages (same Wi-Fi only, secret links, nothing goes to the internet).

/p/<professor token>/   professor alerts page (phone or laptop)
/s/<student token>/     student dashboard: risk meter, predictions, feedback,
                        trigger profile, lecture rewind chat, reading assistant
"""
import json, os, secrets, socket, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from professor import PAGE as PROFESSOR_PAGE

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("EQUALED_PORT", "8765"))


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # no packet is sent; this just picks the Wi-Fi address
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def token(name):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        open(p, "w").write(secrets.token_urlsafe(6))
    return open(p).read().strip()


class Server:
    """bridge must provide: state_json(), feedback(id, verdict), ask(q), say(text),
    settings(dict), simulate(what)."""

    def __init__(self, student_name, bridge):
        self.student, self.bridge = student_name, bridge
        self.ptoken, self.stoken = token("professor_token.txt"), token("student_token.txt")
        self.alerts, self.lock = [], threading.Lock()
        ip = lan_ip()
        self.prof_url = f"http://{ip}:{PORT}/p/{self.ptoken}/"
        self.student_url = f"http://{ip}:{PORT}/s/{self.stoken}/"
        self._serve()

    # professor alerts ------------------------------------------------------
    def notify(self, reason, triggers, sound, kind="overload"):
        with self.lock:
            a = {"id": len(self.alerts) + 1, "kind": kind, "time": time.strftime("%I:%M:%S %p").lstrip("0"),
                 "student": self.student, "reason": reason, "triggers": triggers, "sound": sound, "ack": False}
            self.alerts.append(a)
            return a["id"]

    def update_alert(self, aid, **fields):
        with self.lock:
            for a in self.alerts:
                if a["id"] == aid:
                    a.update(fields)

    def acked(self, aid):
        with self.lock:
            return any(a["id"] == aid and a["ack"] for a in self.alerts)

    # http ------------------------------------------------------------------
    def _serve(self):
        srv_self = self
        pbase, sbase = f"/p/{self.ptoken}/", f"/s/{self.stoken}/"

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="text/html; charset=utf-8"):
                b = body.encode() if isinstance(body, str) else body
                self.send_response(code); self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

            def _json(self, obj):
                self._send(200, json.dumps(obj), "application/json")

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    return json.loads(self.rfile.read(n) or b"{}")
                except Exception:
                    return {}

            def do_GET(self):
                p = self.path.split("?")[0]
                if p in (pbase, pbase.rstrip("/")):
                    return self._send(200, PROFESSOR_PAGE)
                if p == pbase + "alerts.json":
                    with srv_self.lock:
                        return self._json(srv_self.alerts)
                if p in (sbase, sbase.rstrip("/")):
                    return self._send(200, STUDENT_PAGE)
                if p == sbase + "state.json":
                    return self._send(200, srv_self.bridge.state_json(), "application/json")
                self._send(404, "not found")

            def do_POST(self):
                p = self.path.split("?")[0]
                if self.path.startswith(pbase + "ack?id="):
                    try:
                        aid = int(self.path.split("=")[1])
                    except ValueError:
                        return self._send(400, "bad id")
                    with srv_self.lock:
                        for a in srv_self.alerts:
                            if a["id"] == aid:
                                a["ack"] = True
                    return self._send(200, "ok", "text/plain")
                if not p.startswith(sbase):
                    return self._send(404, "not found")
                d, route, b = self._body(), p[len(sbase):], srv_self.bridge
                if route == "feedback":
                    b.feedback(int(d.get("id", 0)), d.get("verdict", "")); return self._json({"ok": True})
                if route == "ask":
                    ans, src = b.ask(str(d.get("question", ""))[:500]); return self._json({"answer": ans, "source": src})
                if route == "say":
                    where = b.say(str(d.get("text", ""))[:3000]); return self._json({"played_on": where})
                if route == "settings":
                    b.settings(d); return self._json({"ok": True})
                if route == "archive_scan":
                    return self._json(b.archive_scan())
                if route == "footage_find":
                    return self._json(b.footage_find())
                if route == "play":
                    return self._json(b.play_source(str(d.get("source", ""))))
                if route == "archive_ask":
                    return self._json(b.archive_ask(str(d.get("question", ""))[:500]))
                if route == "simulate":
                    b.simulate(str(d.get("what", ""))); return self._json({"ok": True})
                self._send(404, "not found")

        try:
            srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            print("professor page:", self.prof_url, flush=True)
            print("student dashboard:", self.student_url, flush=True)
        except OSError as e:
            self.prof_url = self.student_url = f"(web pages failed to start: {e})"
            print(self.prof_url, flush=True)


STUDENT_PAGE = r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>EqualEd</title><style>
:root{--bg:#f6f7f9;--card:#fff;--text:#14171c;--muted:#5d6675;--line:#e3e6eb;--accent:#3b6ef5;
--red:#d93a3f;--orange:#e07b14;--green:#1f9d5c;--chip:#eef1f6;--bar:#e9ecf1}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1115;--card:#181b22;--text:#e9edf3;--muted:#98a2b3;
--line:#272c36;--accent:#7aa2ff;--red:#ff6369;--orange:#ffa94d;--green:#4cc38a;--chip:#232833;--bar:#262b35}}
:root[data-theme=dark]{--bg:#0f1115;--card:#181b22;--text:#e9edf3;--muted:#98a2b3;--line:#272c36;--accent:#7aa2ff;
--red:#ff6369;--orange:#ffa94d;--green:#4cc38a;--chip:#232833;--bar:#262b35}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,system-ui,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px}
.wrap{max-width:1100px;margin:0 auto}h1{font-size:19px;margin:0}.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{background:var(--chip);border-radius:999px;padding:3px 10px;font-size:12.5px;color:var(--muted)}
.chip.ok{color:var(--green)}.chip.bad{color:var(--red)}.chip.warn{color:var(--orange)}
nav{display:flex;gap:4px;margin-top:10px;overflow-x:auto}nav button{border:0;background:none;color:var(--muted);font:inherit;
padding:7px 12px;border-radius:8px;cursor:pointer;white-space:nowrap}nav button.on{background:var(--chip);color:var(--text);font-weight:600}
main{padding:16px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.card h2{font-size:14px;margin:0 0 10px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.big{font-size:34px;font-weight:700;font-variant-numeric:tabular-nums}.muted{color:var(--muted)}.small{font-size:13px}
.meter{height:14px;background:var(--bar);border-radius:999px;overflow:hidden;margin:8px 0}
.meter>div{height:100%;border-radius:999px;transition:width .3s,background .3s}
.banner{border-radius:12px;padding:12px 14px;margin-bottom:14px;font-weight:600;display:none}
.banner.show{display:block}.banner.warn{background:color-mix(in srgb,var(--orange) 18%,transparent);color:var(--orange)}
.banner.bad{background:color-mix(in srgb,var(--red) 16%,transparent);color:var(--red)}
.row{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--line)}.row:last-child{border:0}
.dot{width:10px;height:10px;border-radius:50%;flex:none;background:var(--green)}.dot.on{background:var(--red)}.dot.off{background:var(--muted);opacity:.5}
.grow{flex:1;min-width:0}.right{margin-left:auto;text-align:right}
button.b{border:1px solid var(--line);background:var(--chip);color:var(--text);font:inherit;font-size:13px;padding:5px 10px;border-radius:8px;cursor:pointer}
button.b.red{color:var(--red)}button.b.green{color:var(--green)}button.b.primary{background:var(--accent);color:#fff;border-color:transparent}
.ev{padding:8px 0;border-bottom:1px solid var(--line)}.ev:last-child{border:0}.ev .t{font-size:12.5px;color:var(--muted)}
.tag{font-size:11.5px;padding:1px 7px;border-radius:999px;background:var(--chip);color:var(--muted)}
.prof{display:grid;grid-template-columns:150px 1fr 52px;gap:8px;align-items:center;padding:4px 0}
.pb{height:10px;background:var(--bar);border-radius:999px;overflow:hidden;display:flex}.pb .x{background:var(--red)}.pb .y{background:var(--green)}
.tl{position:relative;height:22px;background:var(--bar);border-radius:6px;overflow:hidden;margin:8px 0}
.tl span{position:absolute;top:0;bottom:0;background:var(--red);opacity:.75}
.tx{padding:4px 6px;border-radius:6px}.tx.miss{background:color-mix(in srgb,var(--red) 14%,transparent)}
textarea,input[type=text]{width:100%;font:inherit;color:var(--text);background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:10px}
.answer{white-space:pre-wrap;margin-top:10px}.para{padding:10px 12px;border-radius:10px;cursor:pointer;border:2px solid transparent;font-size:18px;line-height:1.6}
.para.cur{border-color:var(--accent)}.para.reading{background:color-mix(in srgb,var(--accent) 14%,transparent)}
.hide{display:none}label.sw{display:flex;gap:10px;align-items:center;padding:6px 0}
@media (max-width:600px){.prof{grid-template-columns:110px 1fr 44px}.big{font-size:28px}}
</style></head><body>
<header><div class=wrap><h1>EqualEd · <span id=who></span></h1><div class=chips id=chips></div>
<nav id=nav><button data-t=live class=on>Live</button><button data-t=profile>Trigger profile</button>
<button data-t=lecture>Lecture rewind (ADHD)</button><button data-t=reading>Reading (dyslexia)</button><button data-t=archive>Sensory map (VAST)</button><button data-t=settings>Settings</button></nav></div></header>
<main class=wrap>
<div id=bHeads class="banner warn"></div><div id=bOver class="banner bad"></div>

<section id=t-live><div class=grid>
 <div class=card><h2>Loud-moment risk</h2><div class=big id=riskV>0%</div><div class=meter><div id=riskBar></div></div>
  <div class=muted id=riskWhy>Calm</div></div>
 <div class=card><h2>Predicted before the sound</h2><div class=big id=hits>0</div>
  <div class=muted id=hitTxt>No loud sounds yet</div><div class="small muted" id=lastHit></div></div>
 <div class=card><h2>Sound in the room</h2><div class=big id=db>--</div><div class=meter><div id=dbBar></div></div><div class=muted id=snd></div></div>
 <div class=card><h2>Busy around the student</h2><div class=big id=hv>0</div><div class=meter><div id=hb></div></div>
  <div class=muted id=hw>Raise both hands in front of the camera for 1 second to lock onto a student.</div></div>
 <div class=card><h2>NVIDIA Cosmos3-Reason sees</h2><div id=cz class=muted>Waiting for Cosmos...</div></div>
 <div class=card><h2>Overload support</h2><div id=over class=muted>No overload moments yet</div>
  <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap"><button class="b" onclick="post('simulate',{what:'overload'})">Simulate overload</button>
  <button class="b" onclick="post('simulate',{what:'stop'})">Stop calming sound</button></div></div>
 <div class=card><h2>Sensory triggers</h2><div id=trigs></div></div>
 <div class=card><h2>Student reactions</h2><div id=reacts></div></div>
 <div class=card style="grid-column:1/-1"><h2>Recent moments: tell it what bothered you</h2><div id=events class=muted>Nothing yet.</div></div>
</div></section>

<section id=t-profile class=hide><div class=card><h2>Personal trigger profile</h2>
 <p class="muted small">Built from "Bothered me" and "Was fine" taps. Things that bother this student make the risk meter react sooner.</p>
 <div id=profile class=muted>No feedback yet. Tap the buttons on the Live tab.</div></div></section>

<section id=t-lecture class=hide><div class=grid>
 <div class=card><h2>Attention right now</h2><div class=big id=att>--</div><div class=muted id=attWhy></div>
  <div class="small muted" id=attPct></div></div>
 <div class=card><h2>Focus timeline</h2><div class=tl id=tl></div><div class="small muted" id=drops>No attention drops yet</div></div>
 <div class=card style="grid-column:1/-1"><h2>What did I miss?</h2>
  <div style="display:flex;gap:8px"><input type=text id=q placeholder="e.g. What did I miss about mitochondria?">
  <button class="b primary" id=askB onclick=ask()>Ask</button></div><div class=answer id=ans></div></div>
 <div class=card style="grid-column:1/-1"><h2>Live lecture transcript</h2><div class="small muted" id=tStatus></div>
  <div id=tx class=small style="max-height:360px;overflow:auto"></div></div>
</div></section>

<section id=t-reading class=hide><div class=card><h2>Reading assistant</h2>
 <p class="muted small">Lean in toward the camera when a paragraph is hard, and it reads that paragraph aloud in your AirPods. Tap a paragraph to choose it, or press Read.</p>
 <label class=sw><input type=checkbox id=rOn onchange="post('settings',{reading:this.checked})"> Read aloud when I lean in</label>
 <div class=small id=rStat></div>
 <div style="display:flex;gap:8px;margin:8px 0"><button class="b primary" onclick=readCur()>Read current paragraph</button>
 <button class=b onclick="post('simulate',{what:'lean'})">Simulate lean-in</button></div>
 <div id=paras></div></div></section>

<section id=t-archive class=hide><div class=grid>
 <div class=card style="grid-column:1/-1"><h2>Sensory map of the video archive</h2>
  <p class="muted small">Searches the team's VAST archive (indexed by NVIDIA Cosmos3-Reason, YOLO11 and Cosmos Embed1) for sensory triggers,
  then ranks every camera and place from most overwhelming to calmest. Use it to plan a calmer route or schedule for a student.</p>
  <button class="b primary" id=scanB onclick=scan()>Scan the archive</button> <span class="small muted" id=scanStat></span>
  <div id=places style="margin-top:12px"></div></div>
 <div class=card style="grid-column:1/-1"><h2>Hackathon footage: people crowding a person</h2>
  <p class="muted small">Searches the organizers' indexed footage for crowding, surrounding and closing-in moments, downloads the best
  clips to this Mac, and lets you run EqualEd on them instead of the webcam. Now showing: <b id=src>webcam</b></p>
  <button class="b primary" id=ffB onclick=findFootage()>Find and download clips</button>
  <button class=b onclick="post('play',{source:'webcam'})">Back to webcam</button> <span class="small muted" id=ffStat></span>
  <div id=footage style="margin-top:10px"></div></div>
 <div class=card style="grid-column:1/-1"><h2>Strongest matching moments</h2><div id=clips class="small muted">Run a scan first.</div></div>
 <div class=card style="grid-column:1/-1"><h2>Ask the archive</h2>
  <div style="display:flex;gap:8px"><input type=text id=aq placeholder="e.g. Where is it usually most crowded?">
  <button class="b primary" id=aqB onclick=askArchive()>Ask</button></div><div class=answer id=aans></div></div>
 <div class=card style="grid-column:1/-1"><h2>Re-ingest prompt for sensory search</h2>
  <p class="muted small">Cosmos only writes down what its prompt asks about. To make the archive searchable for sensory load,
  on the workshop VM ask Cursor: "re-ingest the smart-spaces video with this custom prompt".</p>
  <textarea id=ip rows=5 readonly></textarea><button class=b style="margin-top:6px" onclick="navigator.clipboard.writeText($('ip').value)">Copy prompt</button></div>
</div></section>

<section id=t-settings class=hide><div class=card><h2>Settings</h2>
 <label class=sw><input type=checkbox id=spk onchange="post('settings',{allow_speakers:this.checked})"> Play sounds on the laptop speakers too (for stage demos)</label>
 <p class="small muted">Off by default so the class never hears the calming sound. Only the student's AirPods play it.</p>
 <p class=small>Professor link: <span id=plink></span></p></div></section>
</main><script>
const $=id=>document.getElementById(id);let S=null,tab='live',cur=0,lastLean=-1,readingIdx=-1;
const PARAS=["Photosynthesis is how plants make their own food. They take in sunlight, water, and carbon dioxide, and turn them into sugar and oxygen.",
"This happens inside tiny parts of the leaf called chloroplasts. Chloroplasts contain chlorophyll, the green substance that captures light energy.",
"The process has two stages. In the light-dependent reactions, light energy splits water and releases oxygen. In the Calvin cycle, the plant uses that stored energy to build sugar from carbon dioxide.",
"Almost all life on Earth depends on photosynthesis, because it produces the oxygen we breathe and the food at the bottom of nearly every food chain."];
document.querySelectorAll('#nav button').forEach(b=>b.onclick=()=>{tab=b.dataset.t;document.querySelectorAll('#nav button').forEach(x=>x.classList.toggle('on',x==b));
 document.querySelectorAll('main section').forEach(s=>s.classList.toggle('hide',s.id!='t-'+tab));});
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
async function post(r,d){try{const x=await fetch(r,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});return await x.json();}catch(e){return {}}}
function color(v){return v>=60?'var(--red)':v>=35?'var(--orange)':'var(--green)';}
function chip(t,c){return `<span class="chip ${c||''}">${esc(t)}</span>`}
function renderParas(){$('paras').innerHTML=PARAS.map((p,i)=>`<p class="para ${i==cur?'cur':''} ${i==readingIdx?'reading':''}" onclick="cur=${i};renderParas()">${esc(p)}</p>`).join('');}
async function readCur(){readingIdx=cur;renderParas();const r=await post('say',{text:PARAS[cur]});
 $('rStat').textContent=r.played_on?('Reading paragraph '+(cur+1)+' on '+r.played_on):'Held back: connect AirPods, or allow speakers in Settings.';
 cur=Math.min(cur+1,PARAS.length-1);}
async function scan(){$('scanB').disabled=true;$('scanStat').textContent='Searching the archive (about 30 s)...';
 const r=await post('archive_scan',{});$('scanB').disabled=false;
 if(r.error){$('scanStat').textContent=r.error;return;}$('scanStat').textContent='Scanned at '+r.time;renderArchive(r);}
function renderArchive(r){if(!r||!r.places)return;const mx=Math.max(0.01,...r.places.map(p=>Math.abs(p.score)));
 $('places').innerHTML=r.places.length?r.places.map((p,i)=>`<div class=row><span class=grow><b>${i+1}. ${esc(p.place)}</b><br><span class="small muted">${esc(p.top||'calm')}</span>
  <div class=meter><div style="width:${Math.max(3,100*Math.max(0,p.score)/mx)}%;background:${p.score>mx*.6?'var(--red)':p.score>mx*.3?'var(--orange)':'var(--green)'}"></div></div></span>
  <span class="right small">${p.score>0?'load '+p.score:'calm'}</span></div>`).join(''):'No matches. Try re-ingesting with the sensory prompt below.';
 $('clips').innerHTML=r.clips.length?r.clips.map(c=>`<div class=ev><div class=t>${esc(c.trigger)} · ${esc(c.place)} · match ${c.similarity}</div><div>${esc(c.caption)}</div></div>`).join(''):'None.';}
async function findFootage(){$('ffB').disabled=true;$('ffStat').textContent='Searching and downloading (1 to 2 minutes)...';
 const r=await post('footage_find',{});$('ffB').disabled=false;$('ffStat').textContent=r.error||('Found '+(r.clips||[]).length+' clips');}
function renderFootage(list){$('footage').innerHTML=(list&&list.length)?list.map(c=>`<div class=ev><div class=t>${esc(c.location||'?')} · ${esc(c.camera_id||'?')} · match ${c.similarity} · "${esc(c.query)}"</div>
 <div class=small>${esc(c.caption)}</div><button class="b" style="margin-top:4px" onclick='post("play",{source:${JSON.stringify(c.file)}})'>Run EqualEd on this clip</button></div>`).join(''):'<span class="small muted">No clips downloaded yet.</span>';}
async function askArchive(){const q=$('aq').value.trim();if(!q)return;$('aqB').disabled=true;$('aans').textContent='Asking the archive...';
 const r=await post('archive_ask',{question:q});$('aans').textContent=r.answer||'No answer';$('aqB').disabled=false;}
async function ask(){const q=$('q').value.trim();if(!q)return;$('askB').disabled=true;$('ans').textContent='Thinking...';
 const r=await post('ask',{question:q});$('ans').textContent=(r.answer||'No answer')+(r.source?'\n\n— answered by '+r.source:'');$('askB').disabled=false;}
$('q').addEventListener('keydown',e=>{if(e.key==='Enter')ask();});
function render(){if(!S)return;$('who').textContent=S.student;
 const so=S.sound_out;$('chips').innerHTML=chip(S.fps+' FPS','ok')+chip(S.mic.ok?'Mic on':'Mic off: '+S.mic.error,S.mic.ok?'ok':'bad')
  +chip(so.headphones?'Sound: '+so.name:(so.allow_speakers?'Speakers allowed':'Put in AirPods (now '+so.name+')'),so.headphones||so.allow_speakers?'ok':'warn')
  +chip('Cosmos: '+(S.vast.gpu?S.vast.status.cosmos:'add key'),S.vast.status.cosmos=='connected'?'ok':(S.vast.gpu?'bad':'warn'))
  +chip('Archive: '+(S.vast.archive?S.vast.status.archive:'add login'),S.vast.status.archive=='connected'?'ok':'warn')
  +chip('W&B: '+(S.vast.wandb?'ready':'add key'),S.vast.wandb?'ok':'warn')+chip('Student: '+S.mode)+(S.recording?chip('● Recording','bad'):'');
 const r=Math.round(S.risk.value*100);$('riskV').textContent=r+'%';$('riskBar').style.width=r+'%';$('riskBar').style.background=color(r);
 $('riskWhy').textContent=S.risk.reason?('Because: '+S.risk.reason):'Calm';
 $('bHeads').className='banner warn'+(S.risk.prearmed?' show':'');$('bHeads').textContent='Heads up: '+S.risk.prearm_reason+'. Calming sound started early.';
 const P=S.predictions;$('hits').textContent=P.hits;$('hitTxt').textContent=(P.hits+P.misses)?`caught early out of ${P.hits+P.misses} loud sounds`+(P.hits?`, ${P.avg_lead.toFixed(1)} s early on average`:''):'No loud sounds yet';
 $('lastHit').textContent=P.last||'';
 const db=S.mic.db;$('db').textContent=S.mic.ok?Math.round(db)+' dB':'--';const dbp=Math.max(0,Math.min(100,(db+70)*1.6));$('dbBar').style.width=dbp+'%';$('dbBar').style.background=color(dbp);
 $('snd').textContent=S.mic.label?('Hearing: '+S.mic.label):'';
 const HC=S.hectic;$('hv').textContent=HC.value+' / 100';$('hb').style.width=HC.value+'%';$('hb').style.background=color(HC.value);
 $('hw').textContent=HC.locked?(HC.lost?'Looking for '+HC.name+'... raise both hands to re-lock.':'Locked on '+HC.name+'. '+(HC.parts.length?'Now: '+HC.parts.join(', '):'Calm around them.')+' Teacher is alerted at 55 for 3 of 5 s.'):'Raise both hands in front of the camera for 1 second to lock onto a student.';
 const C=S.vast.cosmos;$('cz').innerHTML=!S.vast.gpu?'Paste your team GPU key into <b>vast.env</b> to turn on live reasoning by NVIDIA Cosmos3-Reason.'
  :C?`<div class=big style="font-size:22px">${esc(C.what||'nothing risky')}</div><div class=meter><div style="width:${Math.round(C.risk*100)}%;background:${color(C.risk*100)}"></div></div>
   <div>${esc(C.why)}</div><div class="small muted">risk ${Math.round(C.risk*100)}% · answered in ${C.latency}s · ${S.vast.cosmos_calls} reads · ${S.vast.cosmos_video?'video':'still frames'}</div>`
  :(S.vast.cosmos_error?'Error: '+esc(S.vast.cosmos_error):'Watching... first read in a few seconds.');
 $('ip').value=S.vast.ingest_prompt;$('src').textContent=S.source;
 const fk=JSON.stringify((S.footage||[]).map(c=>c.file));if(fk!==window._fk){window._fk=fk;renderFootage(S.footage);}if(S.archive&&!$('places').innerHTML)renderArchive(S.archive);
 const O=S.overload;$('over').innerHTML=O.active?`<b style="color:var(--red)">${esc(O.reason)}</b><br>${esc(O.sound)}${S.overload_cosmos?'<br><b>Cosmos:</b> '+esc(S.overload_cosmos):''}<br>Professor: ${O.acked?'<b style="color:var(--green)">on the way</b>':'notified, waiting'}`:(O.count?`${O.count} overload moment(s) so far. Last: ${esc(O.reason)}`:'No overload moments yet');
 $('bOver').className='banner bad'+(O.active?' show':'');$('bOver').textContent='Overload support active: '+O.reason+(O.acked?' · professor on the way':' · professor notified');
 $('trigs').innerHTML=S.triggers.map(t=>`<div class=row><span class="dot ${!t.live?'off':t.alerting?'on':''}"></span><span class=grow>${esc(t.label)}<br><span class="small muted">${esc(t.value)}</span></span><span class="right small muted">${t.count?'×'+t.count:''}</span></div>`).join('');
 $('reacts').innerHTML=S.reactions.map(t=>`<div class=row><span class="dot ${t.alerting?'on':''}"></span><span class=grow>${esc(t.label)}</span><span class="right small muted">${t.count?'×'+t.count:''}</span></div>`).join('');
 $('events').innerHTML=S.events.length?S.events.map(e=>`<div class=ev><div class=t>${esc(e.time)} · <span class=tag>${esc(e.kind)}</span></div><div>${esc(e.label)}${e.detail?' <span class="muted small">'+esc(e.detail)+'</span>':''}</div>
   ${e.feedback?`<div class="small" style="color:${e.feedback=='bothered'?'var(--red)':'var(--green)'}">${e.feedback=='bothered'?'Bothered me':'Was fine'}</div>`:
   `<div style="display:flex;gap:6px;margin-top:4px"><button class="b red" onclick="post('feedback',{id:${e.id},verdict:'bothered'})">Bothered me</button><button class="b green" onclick="post('feedback',{id:${e.id},verdict:'fine'})">Was fine</button></div>`}</div>`).join(''):'Nothing yet.';
 $('profile').innerHTML=S.profile.length?S.profile.map(p=>{const t=p.bothered+p.fine||1;return `<div class=prof><span class=small>${esc(p.label)}</span><div class=pb><div class=x style="width:${100*p.bothered/t}%"></div><div class=y style="width:${100*p.fine/t}%"></div></div><span class="small muted right">×${p.mult.toFixed(1)}</span></div>`}).join('')
   +'<p class="small muted">Red = bothered, green = fine. The number is how much more (or less) sensitive the risk meter is to it.</p>':'No feedback yet. Tap the buttons on the Live tab.';
 const A=S.attention;$('att').textContent=A.state=='focused'?'Focused':'Away';$('att').style.color=A.state=='focused'?'var(--green)':'var(--orange)';
 $('attWhy').textContent=A.reason;$('attPct').textContent=Math.round(A.focused_pct)+'% focused this session';
 const t0=A.session_start,span=Math.max(1,S.t-t0);$('tl').innerHTML=A.drops.map(d=>`<span style="left:${100*(d.start-t0)/span}%;width:${Math.max(.6,100*((d.end||S.t)-d.start)/span)}%"></span>`).join('');
 $('drops').textContent=A.drops.length?A.drops.map(d=>d.label).join(' · '):'No attention drops yet';
 $('tStatus').textContent='Speech-to-text: '+S.transcriber;
 const near=$('tx').scrollTop+$('tx').clientHeight>=$('tx').scrollHeight-20;
 $('tx').innerHTML=S.transcript.length?S.transcript.map(s=>`<div class="tx ${s.missed?'miss':''}"><span class=muted>${esc(s.time)}</span> ${esc(s.text)}${s.missed?' <span class=tag>missed</span>':''}</div>`).join(''):'<span class=muted>Nothing transcribed yet. Play or give a lecture near the Mac.</span>';
 if(near)$('tx').scrollTop=$('tx').scrollHeight;
 $('rOn').checked=S.reading.active;$('spk').checked=so.allow_speakers;$('plink').textContent=S.professor_url;
 if(S.reading.lean_count!==lastLean){if(lastLean>=0&&S.reading.active)readCur();lastLean=S.reading.lean_count;}
}
async function load(){try{const r=await fetch('state.json',{cache:'no-store'});S=await r.json();render();}catch(e){}}
renderParas();load();setInterval(load,700);
</script></body></html>"""
