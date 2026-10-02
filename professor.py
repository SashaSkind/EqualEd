"""Tiny local web page the professor opens on their phone or laptop.

It only works on the same Wi-Fi, needs the secret link, and sends nothing
to the internet. The page shows each overload alert and has an
Acknowledge button that the student's screen then shows.
"""
import json, os, secrets, socket, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8765

PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>EqualEd · Teacher</title>
<link rel=preconnect href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Nunito+Sans:wght@400;600;700;800&family=Rubik:wght@500;600;700&display=swap" rel=stylesheet>
<style>
:root{--bg:#F4F2ED;--card:#FFFFFF;--ink:#14213D;--soft:#4B5768;--muted:#717C8B;--line:#E3E1DA;--accent:#13756C;--accent-bg:#DDF1EC;
--calm:#1F7A52;--calm-bg:#DFF3E8;--warn:#9A4A06;--warn-bg:#FCEBD3;--alert:#B42D27;--alert-bg:#FBE1DE;--chip:#EEF0F3;--shadow:0 1px 2px #14213D14,0 8px 24px #14213D0F}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0E1420;--card:#172131;--ink:#EAF0F7;--soft:#B6C2D2;--muted:#8D99AB;--line:#26324A;
--accent:#5CC9B8;--accent-bg:#14373A;--calm:#4CC38A;--calm-bg:#123326;--warn:#F2A65A;--warn-bg:#3A2A14;--alert:#FF7A70;--alert-bg:#3D1A1A;--chip:#22304A;--shadow:none}}
:root[data-theme=dark]{--bg:#0E1420;--card:#172131;--ink:#EAF0F7;--soft:#B6C2D2;--muted:#8D99AB;--line:#26324A;--accent:#5CC9B8;--accent-bg:#14373A;
--calm:#4CC38A;--calm-bg:#123326;--warn:#F2A65A;--warn-bg:#3A2A14;--alert:#FF7A70;--alert-bg:#3D1A1A;--chip:#22304A;--shadow:none}
*{box-sizing:border-box}html,body{margin:0}body{background:var(--bg);color:var(--ink);font:16px/1.45 'Nunito Sans',-apple-system,system-ui,sans-serif}
h1,h2,h3{font-family:Rubik,'Nunito Sans',sans-serif;margin:0}
.wrap{max-width:1240px;margin:0 auto;padding:20px 16px 48px}
header{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:18px}
.logo{display:flex;align-items:center;gap:10px;font:700 20px Rubik}.logo i{width:30px;height:30px;border-radius:9px;background:linear-gradient(135deg,#36C2B4,#3B5BDB)}
.cls{color:var(--muted);font-weight:600}.sp{flex:1}
.live{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--muted);background:var(--card);border:1px solid var(--line);border-radius:999px;padding:4px 10px}
.live b{width:8px;height:8px;border-radius:50%;background:var(--calm)}.live.off b{background:var(--muted)}
button{font:inherit;cursor:pointer;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink);padding:8px 14px}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:700}
.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}@media (max-width:700px){.summary{grid-template-columns:repeat(2,1fr)}}
.sum{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 16px}.sum .n{font:700 28px Rubik;font-variant-numeric:tabular-nums}.sum .t{font-size:13px;color:var(--muted)}
.main{display:grid;grid-template-columns:1fr 380px;gap:16px;align-items:start}@media (max-width:980px){.main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:var(--shadow)}
.label{font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:12px;display:flex;align-items:center;gap:8px}
.roster{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.st{text-align:left;border-radius:16px;border:1px solid var(--line);background:var(--card);padding:14px;display:flex;flex-direction:column;gap:10px;transition:box-shadow .2s,border-color .2s}
.st:hover{border-color:var(--accent)}.st.sel{outline:2px solid var(--accent)}.st.need{border-color:var(--alert);box-shadow:0 0 0 3px var(--alert-bg)}
.row{display:flex;align-items:center;gap:10px}.av{width:42px;height:42px;border-radius:12px;background:var(--accent-bg);color:var(--accent);display:grid;place-items:center;font:700 16px Rubik;flex:none}
.nm{font:600 17px Rubik}.nd{font-size:13px;color:var(--muted)}
.plan{margin-left:auto;font:700 12px Rubik;letter-spacing:.04em;border-radius:8px;padding:3px 8px;background:var(--chip);color:var(--soft)}.plan.iep{background:var(--accent-bg);color:var(--accent)}
.pill{font:700 13px Rubik;border-radius:999px;padding:4px 10px;display:inline-flex;gap:6px;align-items:center;width:max-content}.pill i{width:8px;height:8px;border-radius:50%;background:currentColor}
.calm{color:var(--calm);background:var(--calm-bg)}.warn{color:var(--warn);background:var(--warn-bg)}.alert{color:var(--alert);background:var(--alert-bg)}.idle{color:var(--muted);background:var(--chip)}
.mini{font-size:13px;color:var(--soft)}.tag{font-size:11px;color:var(--muted);border:1px dashed var(--line);border-radius:6px;padding:1px 6px}
.meter{height:8px;border-radius:999px;background:var(--chip);overflow:hidden}.meter>div{height:100%;border-radius:999px;transition:width .4s}
.feed{display:flex;flex-direction:column;gap:10px;max-height:560px;overflow:auto}
.note{border-radius:14px;border:1px solid var(--line);border-left:5px solid var(--alert);padding:12px 14px}.note.ack{border-left-color:var(--calm);opacity:.72}
.note .top{display:flex;gap:8px;font-size:13px;color:var(--muted);align-items:center}.note .k{font-weight:800;text-transform:uppercase;letter-spacing:.05em;font-size:11px;color:var(--alert)}
.note .msg{font-weight:700;margin:4px 0}.note .det{font-size:14px;color:var(--soft)}.note button{margin-top:8px;font-size:14px;padding:6px 12px}.note .done{color:var(--calm);font-weight:700;font-size:14px;margin-top:6px}
.empty{color:var(--muted);text-align:center;padding:24px 8px}
.detail{margin-top:16px}.dhead{display:flex;gap:14px;align-items:center;flex-wrap:wrap}.dhead .av{width:54px;height:54px;font-size:20px;border-radius:15px}
.feel{font-size:18px;margin:12px 0}.donow{border-radius:14px;padding:12px 14px;background:var(--accent-bg);margin:12px 0}.donow b{font-family:Rubik;display:block}
.accs{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}.acc{padding:12px;border-radius:12px;background:var(--bg);font-size:15px;display:flex;gap:10px;align-items:flex-start}
.acc svg{flex:none;color:var(--accent);margin-top:2px}.acc.on{outline:2px solid var(--accent);background:var(--accent-bg)}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{font-size:13px;font-weight:700;border-radius:999px;padding:4px 10px;background:var(--warn-bg);color:var(--warn)}.chip.hot{background:var(--alert-bg);color:var(--alert)}
#toast{position:fixed;left:50%;top:14px;transform:translate(-50%,-160%);transition:transform .35s;z-index:9;width:min(94vw,560px);border-radius:16px;padding:14px 18px;color:#fff;background:#B42D27;box-shadow:0 12px 40px #0006}
#toast.show{transform:translate(-50%,0)}#toast b{display:block;font:700 18px Rubik;margin-bottom:2px}
#flash{position:fixed;inset:0;pointer-events:none;box-shadow:inset 0 0 0 0 #B42D27;transition:box-shadow .3s;z-index:8}#flash.on{box-shadow:inset 0 0 0 10px #B42D27}
.foot{color:var(--muted);font-size:13px;margin-top:18px;text-align:center}
</style></head><body><div id=flash></div><div id=toast></div><div class=wrap>
<header><div class=logo><i></i>EqualEd</div><span class=cls id=cls>Teacher</span><span class=live id=live><b></b><span>connecting</span></span><span class=sp></span>
<button class=primary id=enable>Turn on alert sound</button></header>
<div class=summary><div class=sum><div class=n id=n1>–</div><div class=t>students</div></div><div class=sum><div class=n id=n2>0</div><div class=t>need you now</div></div>
<div class=sum><div class=n id=n3>0</div><div class=t>interventions today</div></div><div class=sum><div class=n id=n4>–</div><div class=t>with an IEP or 504 plan</div></div></div>
<div class=main>
 <div><section class=card><div class=label>Your class</div><div class=roster id=roster></div></section>
  <section class="card detail" id=detail></section></div>
 <section class=card><div class=label>Step in <span style="text-transform:none;letter-spacing:0;font-weight:600">only when a student needs you</span></div><div class=feed id=feed><p class=empty>Nothing needs you right now.</p></div></section>
</div>
<p class=foot>No video is shown or stored here. EqualEd only tells you when a student needs you, and which of their accommodations to use.</p></div>
<script>
const $=id=>document.getElementById(id);let ctx=null,seen=new Set(),first=true,tmr=null,C=null,SEL=null,ALERTS=[];
const INTERVENE=new Set(['overload','hectic','dwell']);
const I={sound:'<path d="M3 14v-2a9 9 0 0118 0v2"/><rect x="3" y="14" width="4" height="7" rx="1.5"/><rect x="17" y="14" width="4" height="7" rx="1.5"/>',
door:'<path d="M5 21V4a1 1 0 011-1h9l4 2v16"/><path d="M3 21h18"/><circle cx="13" cy="12" r="1"/>',seat:'<path d="M6 11V5a2 2 0 012-2h8a2 2 0 012 2v6"/><path d="M4 11h16v4H4z"/><path d="M6 15v6M18 15v6"/>',
clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',list:'<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
hand:'<path d="M7 11V5a1.5 1.5 0 013 0v5M10 10V3.5a1.5 1.5 0 013 0V10M13 10V5a1.5 1.5 0 013 0v7M16 9a1.5 1.5 0 013 0v4a8 8 0 01-8 8h-1a6 6 0 01-5-3l-2.5-4a1.5 1.5 0 012.5-1.6L7 14"/>',
book:'<path d="M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2z"/><path d="M4 19V5"/>',chat:'<path d="M4 5h16v11H8l-4 4z"/>'};
function icon(t){t=t.toLowerCase();const k=/headphone|noise/.test(t)?'sound':/break|door|separate room|tic/.test(t)?'door':/seat|partner/.test(t)?'seat':/time|warning|notice|schedule/.test(t)?'clock':
/touch|fidget|movement|motor|typing/.test(t)?'hand':/read|text|audio|notes|written/.test(t)?'book':/check-in|oral|present|communication|aide/.test(t)?'chat':'list';
return `<svg width=22 height=22 viewBox="0 0 24 24" fill=none stroke=currentColor stroke-width=1.8 stroke-linecap=round stroke-linejoin=round>${I[k]}</svg>`}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function ini(n){return n.split(/[ .]+/).filter(Boolean).map(w=>w[0]).join('').slice(0,2).toUpperCase()}
$('enable').onclick=async e=>{ctx=new (window.AudioContext||window.webkitAudioContext)();if(window.isSecureContext&&'Notification' in window){try{await Notification.requestPermission()}catch(_){}}e.target.textContent='Alerts on';e.target.classList.remove('primary')};
function chime(){if(!ctx)return;[[523.25,0],[659.25,.28]].forEach(([f,dt])=>{const o=ctx.createOscillator(),g=ctx.createGain();o.type='sine';o.frequency.value=f;const t=ctx.currentTime+dt;
g.gain.setValueAtTime(.0001,t);g.gain.exponentialRampToValueAtTime(.14,t+.04);g.gain.exponentialRampToValueAtTime(.0001,t+1.4);o.connect(g).connect(ctx.destination);o.start(t);o.stop(t+1.5)});if(navigator.vibrate)navigator.vibrate([120])}
const PLAY=[
 {when:s=>s.overload||s.reactions.length,title:'Go to them calmly now',text:'Offer the break pass and headphones. Speak quietly, give space, no touch.',acc:['break pass','headphones','touch']},
 {when:s=>has(s,['dwell','too_close','crowd'])||s.busy>=55,title:'Give them space',text:'Ask nearby students to step back or return to their seats.',acc:['seating']},
 {when:s=>has(s,['noise']),title:'Check the noise',text:'Lower the source if you can. Remind them headphones are OK.',acc:['headphones']},
 {when:s=>has(s,['stand','rush','chair']),title:'A transition is happening',text:'Give a heads-up and let them move last once the room settles.',acc:['transition']},
];
function has(s,k){return (s.active_trigger_keys||[]).some(x=>k.includes(x))}
function liveStatus(s){if(!s||!s.online)return['idle','Offline','Laptop not connected.'];
 if(s.overload||s.reactions.length)return['alert','Needs you now','Showing signs of overload'+(s.reactions.length?': '+s.reactions.join(', ').toLowerCase():'')+'.'];
 if(s.busy>=55||has(s,['dwell','too_close','crowd']))return['warn','Getting overwhelmed','A lot is happening close to them'+(s.busy_parts.length?': '+s.busy_parts.join(', '):'')+'.'];
 return['calm','Calm','Settled. Nothing that needs you.']}
function statusOf(st){if(st.live)return liveStatus(st.live_state);return st.status==='offline'?['idle','Not in class','No device connected today.']:['calm','Calm','Settled. Nothing that needs you.']}
function render(){if(!C)return;const ss=C.students;$('cls').textContent=C.class_name;
 const live=ss.find(s=>s.live);const L=live&&live.live_state;$('live').className='live'+(L&&L.online?'':' off');$('live').lastChild.textContent=L&&L.online?'Live':'Offline';
 const need=ss.filter(s=>statusOf(s)[0]==='alert'||statusOf(s)[0]==='warn').length;
 $('n1').textContent=ss.length;$('n2').textContent=need;$('n4').textContent=ss.filter(s=>s.plan).length;
 $('roster').innerHTML=ss.map((s,i)=>{const [c,t]=statusOf(s);const busy=s.live&&L?Math.round(L.busy||0):null;
  return `<button class="st ${SEL===i?'sel':''} ${c==='alert'?'need':''}" onclick="SEL=${i};render()"><div class=row><div class=av>${ini(s.name)}</div><div><div class=nm>${esc(s.name)}</div><div class=nd>${esc(s.needs)}</div></div>
  <span class="plan ${s.plan==='IEP'?'iep':''}">${esc(s.plan||'')}</span></div><div class=row><span class="pill ${c}"><i></i>${esc(t)}</span>${s.live?'':'<span class=tag>sample</span>'}</div>
  ${busy!==null?`<div class=meter title="How busy it is around them"><div style="width:${busy}%;background:${busy>=55?'var(--alert)':busy>=30?'var(--warn)':'var(--calm)'}"></div></div>`:''}
  <div class=mini>${esc((s.accommodations||[]).slice(0,2).join(' · '))}${(s.accommodations||[]).length>2?' · +'+((s.accommodations||[]).length-2)+' more':''}</div></button>`}).join('');
 const s=ss[SEL??ss.findIndex(x=>x.live)]||ss[0];if(!s)return;const [c,t,feel]=statusOf(s);const st=s.live?L:null;
 const play=st?PLAY.find(p=>p.when(st)):null;const on=a=>play&&play.acc.some(x=>a.toLowerCase().includes(x));
 const chips=st?[...st.reactions.map(r=>`<span class="chip hot">${esc(r)}</span>`),...st.active_triggers.map(x=>`<span class=chip>${esc(x)}</span>`)]:[];
 $('detail').innerHTML=`<div class=dhead><div class=av>${ini(s.name)}</div><div><h2 style="font-size:24px">${esc(s.name)}</h2><div class=nd>${esc([s.grade,s.plan+' plan',s.needs].filter(Boolean).join(' · '))}</div></div>
  <span class="pill ${c}" style="margin-left:auto"><i></i>${esc(t)}</span></div><p class=feel>${esc(feel)}</p>
  ${chips.length?`<div class=chips style="margin-bottom:6px">${chips.join('')}</div>`:''}
  ${play?`<div class=donow><b>${esc(play.title)}</b>${esc(play.text)}</div>`:''}
  <div class=label style="margin-top:14px">${esc(s.plan||'')} accommodations</div><div class=accs>${(s.accommodations||[]).map(a=>`<div class="acc ${on(a)?'on':''}">${icon(a)}<span>${esc(a)}</span></div>`).join('')}</div>`;}
function head(x){return {hectic:'Very busy around them',dwell:'Someone staying close',overload:'Signs of overload'}[x.kind]||'Needs you'}
function toast(x){const t=$('toast');t.className='show';t.innerHTML=`<b>${esc(x.student)} needs you</b>${esc(x.reason)}`;$('flash').className='on';setTimeout(()=>$('flash').className='',1500);
 clearTimeout(tmr);tmr=setTimeout(()=>t.className='',9000);chime();if(window.isSecureContext&&window.Notification&&Notification.permission==='granted'){try{new Notification('EqualEd: '+x.student+' needs you',{body:x.reason})}catch(_){}}}
async function ack(id){await fetch('ack?id='+id,{method:'POST'});loadAlerts()}
async function loadAlerts(){try{const a=(await (await fetch('alerts.json',{cache:'no-store'})).json()).filter(x=>INTERVENE.has(x.kind));
 const fresh=a.filter(x=>!seen.has(x.id));fresh.forEach(x=>seen.add(x.id));if(!first&&fresh.length)toast(fresh[fresh.length-1]);first=false;$('n3').textContent=a.length;
 $('feed').innerHTML=a.length?a.slice().reverse().map(x=>`<div class="note ${x.ack?'ack':''}"><div class=top><span class=k>${esc(head(x))}</span><span>· ${esc(x.student)} · ${esc(x.time)}</span></div>
  <div class=msg>${esc(x.reason)}</div>${x.cosmos?`<div class=det><b>NVIDIA Cosmos:</b> ${esc(x.cosmos)}</div>`:''}${x.triggers&&x.triggers.length?`<div class=det>Just before: ${esc(x.triggers.join(', '))}</div>`:''}
  ${x.ack?'<div class=done>You are on your way</div>':`<button onclick="ack(${x.id})">I'm on my way</button>`}</div>`).join(''):'<p class=empty>Nothing needs you right now.</p>'}catch(e){}}
async function loadClass(){try{C=await (await fetch('class.json',{cache:'no-store'})).json();render()}catch(e){}}
loadClass();loadAlerts();setInterval(loadClass,1000);setInterval(loadAlerts,1000);
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
