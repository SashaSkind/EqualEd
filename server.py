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
BUILD = str(int(time.time()))          # changes every time EqualEd starts: open pages reload themselves
RELOADER = ("<script>(async()=>{let b=null;setInterval(async()=>{try{const r=await fetch('build.json',{cache:'no-store'});"
            "const j=await r.json();if(b&&j.build!==b)location.reload();b=j.build}catch(e){}},4000)})()</script>")


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
        self.app_url = f"http://{ip}:{PORT}/s/{self.stoken}/app"
        self.camera_url = f"http://{ip}:{PORT}/s/{self.stoken}/camera"
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

    def teacher_view(self):
        """What the teacher sees: no video, no transcript, just how the student is doing."""
        try:
            st = json.loads(self.bridge.state_json() or "{}")
        except ValueError:
            st = {}
        try:
            cfg = json.load(open(os.path.join(HERE, "config.json")))
        except Exception:
            cfg = {}
        trig = [t for t in st.get("triggers", []) if t.get("alerting")]
        reac = [r for r in st.get("reactions", []) if r.get("alerting")]
        ov, hc = st.get("overload", {}), st.get("hectic", {})
        return json.dumps({
            "t": st.get("t"), "student": cfg.get("student_name", self.student),
            "grade": cfg.get("student_grade", ""), "plan": cfg.get("support_plan", ""),
            "accommodations": cfg.get("accommodations", []),
            "online": bool(st), "locked": hc.get("locked", False), "busy": hc.get("value", 0),
            "busy_parts": hc.get("parts", []), "active_triggers": [t["label"] for t in trig],
            "active_trigger_keys": [t["key"] for t in trig],
            "reactions": [r["label"] for r in reac], "overload": ov.get("active", False),
            "overload_reason": ov.get("reason", ""), "acked": ov.get("acked", False),
            "calming_sound": st.get("sound_out", {}).get("playing", False),
            "attention": st.get("attention", {}).get("state", ""),
            "focused_pct": st.get("attention", {}).get("focused_pct", 100),
            "trigger_counts": {t["label"]: t.get("count", 0) for t in st.get("triggers", []) if t.get("count")},
        })

    def class_view(self):
        """The whole class for the teacher: the live student from this laptop plus the roster."""
        live = json.loads(self.teacher_view())
        try:
            cfg = json.load(open(os.path.join(HERE, "config.json")))
        except Exception:
            cfg = {}
        roster = []
        for st in cfg.get("class", []):
            row = dict(st)
            if st.get("live"):
                row.update({"live_state": live, "status": None})
            roster.append(row)
        return json.dumps({"class_name": cfg.get("class_name", "My class"), "students": roster})

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

            def _mjpeg(self):
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                last = None
                try:
                    while True:
                        jpg = getattr(srv_self.bridge, "latest_jpeg", None)
                        if jpg is not None and jpg is not last:
                            self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                                             str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                            last = jpg
                        time.sleep(0.05)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return

            def do_GET(self):
                p = self.path.split("?")[0]
                if p in (pbase, pbase.rstrip("/")):
                    return self._send(200, PROFESSOR_PAGE.replace("</body>", RELOADER + "</body>"))
                if p in (pbase + "build.json", sbase + "build.json"):
                    return self._json({"build": BUILD})
                if p == pbase + "student.json":
                    return self._send(200, srv_self.teacher_view(), "application/json")
                if p == pbase + "class.json":
                    return self._send(200, srv_self.class_view(), "application/json")
                if p == pbase + "alerts.json":
                    with srv_self.lock:
                        return self._json(srv_self.alerts)
                if p in (sbase, sbase.rstrip("/")):
                    return self._send(200, STUDENT_PAGE.replace("</body>", RELOADER + "</body>"))
                if p == sbase + "app":
                    return self._send(200, APP_SHELL.replace("__TEACHER__", pbase).replace("__STUDENT__", sbase).replace("</body>", RELOADER + "</body>"))
                if p == sbase + "camera":
                    return self._send(200, CAMERA_PAGE.replace("</body>", RELOADER + "</body>"))
                if p == sbase + "live.mjpg":
                    return self._mjpeg()
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
                if route == "archive_summary":
                    return self._json(b.archive_summary())
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
<title>EqualEd</title><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel=stylesheet><style>
:root{--bg:#F6F6F4;--card:#fff;--text:#111214;--muted:#8E9197;--line:#E7E7E4;--accent:#2D5BFF;
--red:#EC4D93;--orange:#E08A00;--green:#18A957;--chip:#EFEFEC;--bar:#EFEFEC}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 Inter,-apple-system,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px}
.wrap{max-width:1100px;margin:0 auto}h1{font-size:30px;font-weight:400;letter-spacing:-.03em;margin:0}.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{background:var(--chip);border-radius:999px;padding:3px 10px;font-size:12.5px;color:var(--muted)}
.chip.ok{color:var(--green)}.chip.bad{color:var(--red)}.chip.warn{color:var(--orange)}
nav{display:flex;gap:4px;margin-top:10px;overflow-x:auto}nav button{border:0;background:none;color:var(--muted);font:inherit;
padding:7px 12px;border-radius:8px;cursor:pointer;white-space:nowrap}nav button.on{background:#1C1D20;color:#fff;font-weight:500;border-radius:999px}
main{padding:16px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.card{background:var(--card);border:0;border-radius:24px;padding:18px 20px;box-shadow:0 1px 1px #0000000a,0 10px 30px #0000000d}
.card h2{font-size:19px;margin:0 0 12px;color:var(--text);font-weight:500;letter-spacing:-.02em}
.big{font-size:44px;font-weight:300;letter-spacing:-.03em;font-variant-numeric:tabular-nums}.muted{color:var(--muted)}.small{font-size:13px}
.meter{height:14px;background:var(--bar);border-radius:999px;overflow:hidden;margin:8px 0}
.meter>div{height:100%;border-radius:999px;transition:width .3s,background .3s}
.banner{border-radius:12px;padding:12px 14px;margin-bottom:14px;font-weight:600;display:none}
.banner.show{display:block}.banner.warn{background:color-mix(in srgb,var(--orange) 18%,transparent);color:var(--orange)}
.banner.bad{background:color-mix(in srgb,var(--red) 16%,transparent);color:var(--red)}
.row{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--line)}.row:last-child{border:0}
.dot{width:10px;height:10px;border-radius:50%;flex:none;background:var(--green)}.dot.on{background:var(--red)}.dot.off{background:var(--muted);opacity:.5}
.grow{flex:1;min-width:0}.right{margin-left:auto;text-align:right}
button.b{border:1px solid var(--line);background:var(--chip);color:var(--text);font:inherit;font-size:13px;padding:5px 10px;border-radius:8px;cursor:pointer}
button.b.red{color:var(--red)}button.b.green{color:var(--green)}button.b.primary{background:#1C1D20;color:#fff;border-color:transparent;border-radius:999px}
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
  <button class="b primary" id=scanB onclick=scan()>Scan the archive</button>
  <button class=b id=sumB onclick=summarize()>Summarize with W&amp;B</button> <span class="small muted" id=scanStat></span>
  <div class=answer id=sumOut></div>
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
  <span class="right small">${'load '+p.score+'/10'}</span></div>`).join(''):'No matches. Try re-ingesting with the sensory prompt below.';
 $('clips').innerHTML=r.clips.length?r.clips.map(c=>`<div class=ev><div class=t>${esc(c.trigger)} · ${esc(c.place)} · load ${c.similarity}/10</div><div>${esc(c.caption)}</div></div>`).join(''):'None.';}
async function summarize(){$('sumB').disabled=true;$('sumOut').textContent='Asking Llama 3.3 70B on W&B Inference...';
 const r=await post('archive_summary',{});$('sumB').disabled=false;
 $('sumOut').textContent=r.error||(r.summary+'\n\n— '+r.source);}
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
  +chip('W&B: '+(S.vast.wandb?S.vast.status.wandb:'add key'),S.vast.wandb?'ok':'warn')
  +(S.vast.wandb?chip('Weave: '+S.vast.status.weave,S.vast.status.weave.startsWith('tracing')?'ok':'warn'):'')+chip('Student: '+S.mode)+(S.recording?chip('● Recording','bad'):'');
 const r=Math.round(S.risk.value*100);$('riskV').textContent=r+'%';$('riskBar').style.width=r+'%';$('riskBar').style.background=color(r);
 $('riskWhy').textContent=S.risk.reason?('Because: '+S.risk.reason):'Calm';
 $('bHeads').className='banner warn'+(S.risk.prearmed?' show':'');$('bHeads').textContent='Heads up: '+S.risk.prearm_reason+'. Watching for signs of distress.';
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
 $('ip').value=S.vast.ingest_prompt;if(S.archive&&S.archive.time&&!$('scanStat').textContent)$('scanStat').textContent='Labeled '+S.archive.time;$('src').textContent=S.source;
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


APP_SHELL = """<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>EqualEd</title><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel=stylesheet>
<style>
:root{--bg:#EEEEEC;--card:#FFFFFF;--ink:#111214;--muted:#8E9197;--pill:#1C1D20;--glass:0 2px 6px #0000000f,0 0 0 1px #ffffffcc inset}
*{box-sizing:border-box}html,body{margin:0;height:100%}body{background:var(--bg);color:var(--ink);font:15px/1.4 Inter,-apple-system,system-ui,sans-serif;display:flex;flex-direction:column;-webkit-font-smoothing:antialiased}
nav{display:flex;align-items:center;gap:6px;padding:14px 22px}
.logo{display:flex;align-items:center;gap:10px;font-size:24px;font-weight:500;letter-spacing:-.03em;margin-right:auto}
.logo i{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,#36C2B4,#3B5BDB);box-shadow:0 4px 12px #3b5bdb40}
.tabs{display:flex;gap:4px;padding:4px;border-radius:999px}
nav button{font:500 15px Inter,-apple-system,sans-serif;border:0;background:none;color:var(--ink);padding:10px 20px;border-radius:999px;cursor:pointer}
nav button:hover{background:#ffffff99}
nav button.on{background:var(--pill);color:#fff;box-shadow:0 6px 16px #0000002e}
.sp{margin-left:auto}.hint{font-size:12px;color:var(--muted);background:var(--card);border-radius:999px;padding:7px 12px;box-shadow:var(--glass)}
main{flex:1;position:relative}iframe{position:absolute;inset:0;width:100%;height:100%;border:0;display:none;background:var(--bg)}iframe.on{display:block}
#live{position:absolute;inset:0;display:none;padding:8px 22px 22px;gap:18px}#live.on{display:flex}
.view{flex:1;display:flex;align-items:center;justify-content:center;background:#0E0F12;border-radius:28px;overflow:hidden;min-width:0;box-shadow:0 10px 30px #0000001f}
.view img{max-width:100%;max-height:100%;object-fit:contain}
.side{width:280px;display:flex;flex-direction:column;gap:10px;background:var(--card);border-radius:28px;padding:20px;box-shadow:0 10px 30px #0000000d;align-self:flex-start}
.side h3{font-size:20px;font-weight:500;letter-spacing:-.02em;margin:4px 0 4px}
.side button{font:500 14px Inter,-apple-system,sans-serif;text-align:left;border:0;background:#F6F6F4;color:var(--ink);border-radius:16px;padding:13px 16px;cursor:pointer}
.side button:hover{background:#EFEFEC}.side button.warn{background:#FCE7F1;color:#C2316F}.side p{font-size:13px;color:var(--muted);margin:0 0 6px}
@media (max-width:800px){#live.on{flex-direction:column}.side{width:auto}}
</style></head><body>
<nav><div class=logo><i></i>EqualEd</div>
<div class=tabs><button data-p=teacher class=on>Teacher</button><button data-p=student>Student</button></div>
<span class=sp></span><span class=hint>No video in this window</span></nav>
<main>
<iframe id=teacher class=on src="__TEACHER__" title="Teacher dashboard"></iframe>
<iframe id=student src="__STUDENT__" title="Student dashboard"></iframe>
</main><script>
function show(p){document.querySelectorAll('nav button[data-p]').forEach(b=>b.classList.toggle('on',b.dataset.p===p));
 ['teacher','student'].forEach(id=>document.getElementById(id).classList.toggle('on',id===p));
 try{localStorage.setItem('eq_tab',p)}catch(e){}}
document.querySelectorAll('nav button[data-p]').forEach(b=>b.onclick=()=>show(b.dataset.p));
async function cmd(what){await fetch('simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({what})})}
let start='teacher';try{start=localStorage.getItem('eq_tab')||'teacher'}catch(e){}if(start==='live')start='teacher';show(start);
</script></body></html>"""


CAMERA_PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>EqualEd Camera</title><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel=stylesheet>
<style>
:root{--bg:#EEEEEC;--card:#FFFFFF;--ink:#111214;--muted:#8E9197;--glass:0 2px 6px #0000000f,0 0 0 1px #ffffffcc inset}
*{box-sizing:border-box}html,body{margin:0;height:100%}body{background:var(--bg);color:var(--ink);font:15px/1.4 Inter,-apple-system,system-ui,sans-serif;display:flex;flex-direction:column;-webkit-font-smoothing:antialiased}
header{display:flex;align-items:center;gap:10px;padding:14px 22px}
.logo{display:flex;align-items:center;gap:10px;font-size:22px;font-weight:500;letter-spacing:-.03em}.logo i{width:28px;height:28px;border-radius:8px;background:linear-gradient(135deg,#36C2B4,#3B5BDB)}
.logo span{color:var(--muted);font-weight:400}.sp{flex:1}.hint{font-size:12px;color:var(--muted);background:var(--card);border-radius:999px;padding:7px 12px;box-shadow:var(--glass)}
main{flex:1;display:flex;gap:18px;padding:4px 22px 22px;min-height:0}
.view{flex:1;display:flex;align-items:center;justify-content:center;background:#0E0F12;border-radius:28px;overflow:hidden;min-width:0;box-shadow:0 10px 30px #0000001f}
.view img{max-width:100%;max-height:100%;object-fit:contain}
.side{width:280px;display:flex;flex-direction:column;gap:10px;background:var(--card);border-radius:28px;padding:20px;box-shadow:0 10px 30px #0000000d;align-self:flex-start}
.side h3{font-size:20px;font-weight:500;letter-spacing:-.02em;margin:4px 0 4px}
.side button{font:500 14px Inter,-apple-system,sans-serif;text-align:left;border:0;background:#F6F6F4;color:var(--ink);border-radius:16px;padding:13px 16px;cursor:pointer}
.side button:hover{background:#EFEFEC}.side button.warn{background:#FCE7F1;color:#C2316F}.side p{font-size:13px;color:var(--muted);margin:0 0 6px}
@media (max-width:800px){main{flex-direction:column}.side{width:auto}}
</style></head><body>
<header><div class=logo><i></i>EqualEd <span>Camera</span></div><span class=sp></span><span class=hint>Only on this device. Not shown to the teacher.</span></header>
<main><div class=view><img id=feed alt="EqualEd camera view with people, the student's bubble and triggers drawn on it"></div>
<div class=side><h3>Student</h3>
<button onclick="cmd('lock')">Lock onto the student</button><button onclick="cmd('auto')">Unlock</button>
<p>Or raise both hands for 1 second in front of the camera.</p>
<h3>Demo</h3><button class=warn onclick="cmd('overload')">Simulate overload</button>
<button onclick="cmd('stop')">Stop calming sound</button><button onclick="cmd('lean')">Simulate lean-in (reading)</button></div></main>
<script>
const feed=document.getElementById('feed');function start(){feed.src='live.mjpg?'+Date.now()}feed.onerror=()=>setTimeout(start,1500);start();
async function cmd(what){await fetch('simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({what})})}
</script></body></html>"""
