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
<link rel=preconnect href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel=stylesheet>
<style>
:root{--bg:#EEEEEC;--page:#F6F6F4;--card:#FFFFFF;--ink:#111214;--soft:#55585E;--muted:#9A9DA3;--line:#E7E7E4;
--blue:#2D5BFF;--blue2:#7FA2FF;--blue-bg:#E8EEFF;--green:#18A957;--green-bg:#E3F6EA;--pink:#EC4D93;--pink-bg:#FCE7F1;--amber:#E08A00;--amber-bg:#FFF1DA;
--pill:#1C1D20;--shadow:0 1px 1px #0000000a,0 10px 30px #0000000d;--glass:0 2px 6px #0000000f,0 0 0 1px #ffffffcc inset}
*{box-sizing:border-box}html,body{margin:0}body{background:var(--bg);color:var(--ink);font:15px/1.45 Inter,'SF Pro Text',-apple-system,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
h1,h2,h3{margin:0;font-weight:500;letter-spacing:-.02em}
.wrap{max-width:1280px;margin:16px auto;padding:28px 28px 40px;background:var(--page);border-radius:32px;box-shadow:0 1px 0 #fff inset}
header{display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-bottom:22px}
.logo{display:none}
.cls{font-size:56px;line-height:1;font-weight:400;letter-spacing:-.035em;color:var(--ink)}
.live{display:inline-flex;align-items:center;gap:8px;font-size:13px;color:var(--soft);background:var(--card);border-radius:999px;padding:7px 12px;box-shadow:var(--glass);margin-bottom:8px}
.live b{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 0 3px var(--green-bg)}.live.off b{background:var(--muted);box-shadow:none}
.sp{flex:1}
button{font:inherit;cursor:pointer;border-radius:999px;border:0;background:var(--card);color:var(--ink);padding:9px 16px;box-shadow:var(--glass)}
button.primary{background:var(--pill);color:#fff;font-weight:500;box-shadow:0 6px 16px #0000002e}
.summary{display:grid;grid-template-columns:repeat(4,1fr);background:var(--card);border-radius:28px;box-shadow:var(--shadow);padding:22px 8px;margin-bottom:18px}
@media (max-width:760px){.summary{grid-template-columns:repeat(2,1fr);row-gap:18px}}
.sum{padding:0 20px;border-left:1px solid var(--line)}.sum:first-child{border-left:0}
.sum .t{order:-1;font-size:13px;color:var(--muted);display:block;margin-bottom:6px}.sum{display:flex;flex-direction:column}
.sum .n{font-size:46px;font-weight:300;letter-spacing:-.03em;line-height:1.05;font-variant-numeric:tabular-nums}
.main{display:grid;grid-template-columns:1fr 390px;gap:18px;align-items:start}@media (max-width:1000px){.main{grid-template-columns:1fr}}
.card{background:var(--card);border-radius:28px;padding:22px;box-shadow:var(--shadow)}
.label{font-size:22px;font-weight:500;letter-spacing:-.02em;margin-bottom:16px;display:flex;align-items:center;gap:10px;color:var(--ink)}
.label span{font-size:13px;color:var(--muted);font-weight:400;letter-spacing:0}
.roster{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:14px}
.st{text-align:left;border-radius:22px;background:var(--page);padding:16px;display:flex;flex-direction:column;gap:12px;box-shadow:none;transition:transform .15s,box-shadow .2s}
.st:hover{transform:translateY(-1px);box-shadow:var(--shadow);background:var(--card)}.st.sel{background:var(--card);box-shadow:0 0 0 1.5px var(--ink),var(--shadow)}
.st.need{background:linear-gradient(180deg,#fff,#FFF4F8);box-shadow:0 0 0 1.5px var(--pink),0 10px 30px #ec4d9326}
.row{display:flex;align-items:center;gap:12px}
.av{width:44px;height:44px;border-radius:14px;background:linear-gradient(135deg,#E8EEFF,#F3E9FF);color:var(--blue);display:grid;place-items:center;font-weight:600;font-size:15px;flex:none}
.nm{font-size:17px;font-weight:500;letter-spacing:-.01em}.nd{font-size:13px;color:var(--muted)}
.plan{margin-left:auto;font-size:12px;font-weight:600;border-radius:999px;padding:4px 10px;background:var(--card);color:var(--soft);box-shadow:var(--glass)}.plan.iep{color:var(--blue)}
.pill{font-size:13px;font-weight:500;border-radius:999px;padding:5px 11px;display:inline-flex;gap:7px;align-items:center;width:max-content;background:var(--card);box-shadow:var(--glass)}
.pill i{width:7px;height:7px;border-radius:50%;background:currentColor}
.calm{color:var(--green)}.warn{color:var(--amber)}.alert{color:var(--pink)}.idle{color:var(--muted)}
.mini{font-size:13px;color:var(--soft)}.tag{font-size:11px;color:var(--muted);border-radius:999px;padding:2px 8px;background:#EFEFEC}
.meter{height:12px;border-radius:999px;background:#EFEFEC;overflow:hidden}.meter>div{height:100%;border-radius:999px;transition:width .4s;background-size:auto!important}
.hatch-green{background:repeating-linear-gradient(135deg,#18A957 0 3px,#8FE0B1 3px 6px)!important}
.hatch-amber{background:repeating-linear-gradient(135deg,#E08A00 0 3px,#FFD18A 3px 6px)!important}
.hatch-pink{background:repeating-linear-gradient(135deg,#EC4D93 0 3px,#F9B5D3 3px 6px)!important}
.feed{display:flex;flex-direction:column;gap:12px;max-height:620px;overflow:auto;padding:2px}
.note{border-radius:20px;padding:14px 16px;background:var(--page);position:relative;overflow:hidden}
.note::before{content:"";position:absolute;left:0;top:0;bottom:0;width:6px;background:repeating-linear-gradient(135deg,#EC4D93 0 3px,#F9B5D3 3px 6px)}
.note.ack::before{background:repeating-linear-gradient(135deg,#18A957 0 3px,#8FE0B1 3px 6px)}.note.ack{opacity:.75}
.note .top{display:flex;gap:8px;font-size:12px;color:var(--muted);align-items:center;padding-left:6px}
.note .k{font-weight:600;color:var(--pink);font-size:12px}.note .msg{font-weight:500;font-size:15px;margin:6px 0 2px;padding-left:6px}
.note .det{font-size:13px;color:var(--soft);padding-left:6px}.note button{margin:10px 0 0 6px;font-size:13px;padding:7px 14px;background:var(--pill);color:#fff;box-shadow:none}
.note .done{color:var(--green);font-weight:600;font-size:13px;margin:8px 0 0 6px}
.empty{color:var(--muted);text-align:center;padding:30px 8px}
.detail{margin-top:18px}.dhead{display:flex;gap:16px;align-items:center;flex-wrap:wrap}.dhead .av{width:58px;height:58px;font-size:19px;border-radius:18px}
.dhead h2{font-size:30px!important;font-weight:400!important;letter-spacing:-.03em}
.feel{font-size:26px;line-height:1.25;font-weight:300;letter-spacing:-.02em;margin:18px 0 14px;color:var(--ink)}
.donow{border-radius:22px;padding:18px 20px;margin:16px 0;color:#14213D;background:radial-gradient(120% 140% at 10% 0%,#CFE0FF 0%,#E9F0FF 45%,#F7F9FF 100%);box-shadow:0 0 0 1px #DCE6FF inset,0 12px 30px #2d5bff1f}
.donow b{display:flex;align-items:center;gap:8px;font-size:16px;font-weight:600;margin-bottom:6px}
.donow b::before{content:"✦";color:var(--blue)}
.accs{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px}
.acc{padding:13px 14px;border-radius:16px;background:var(--page);font-size:14px;display:flex;gap:10px;align-items:flex-start}
.acc svg{flex:none;color:var(--blue);margin-top:1px}.acc.on{background:var(--card);box-shadow:0 0 0 1.5px var(--blue),0 8px 20px #2d5bff1f}
.chips{display:flex;flex-wrap:wrap;gap:8px}.chip{font-size:13px;font-weight:500;border-radius:999px;padding:6px 12px;background:var(--card);color:var(--amber);box-shadow:var(--glass)}
.chip.hot{color:var(--pink)}
.insight{margin-top:18px;border-radius:28px;padding:22px;color:#fff;min-height:170px;position:relative;overflow:hidden;
background:radial-gradient(90% 120% at 0% 0%,#F2A27A 0%,transparent 60%),radial-gradient(120% 120% at 100% 100%,#2F6FD6 0%,transparent 60%),linear-gradient(135deg,#E9A27F,#7E9CC9 55%,#2C66C9)}
.insight::after{content:"";position:absolute;inset:0;opacity:.18;mix-blend-mode:overlay;background-image:radial-gradient(#fff 1px,transparent 1px);background-size:3px 3px}
.insight .tagp{display:inline-flex;gap:6px;align-items:center;font-size:13px;background:#ffffff40;border-radius:999px;padding:6px 12px;backdrop-filter:blur(6px)}
.insight .big{font-size:64px;font-weight:300;letter-spacing:-.04em;line-height:1;margin-top:28px}.insight .cap{font-size:14px;opacity:.9;margin-top:6px}
#toast{position:fixed;left:50%;top:16px;transform:translate(-50%,-160%);transition:transform .35s;z-index:9;width:min(94vw,560px);border-radius:22px;padding:16px 20px;color:var(--ink);background:#fff;box-shadow:0 0 0 1.5px var(--pink),0 20px 50px #0000002e}
#toast.show{transform:translate(-50%,0)}#toast b{display:block;font-size:17px;font-weight:600;margin-bottom:2px;color:var(--pink)}
#flash{position:fixed;inset:0;pointer-events:none;box-shadow:inset 0 0 0 0 #EC4D93;transition:box-shadow .3s;z-index:8}#flash.on{box-shadow:inset 0 0 0 8px #EC4D9399}
.foot{color:var(--muted);font-size:13px;margin-top:20px;text-align:center}
</style></head><body><div id=flash></div><div id=toast></div><div class=wrap>
<header><div class=logo><i></i>EqualEd</div><span class=cls id=cls>Teacher</span><span class=live id=live><b></b><span>connecting</span></span><span class=sp></span>
</header>
<div class=summary><div class=sum><div class=n id=n1>–</div><div class=t>students</div></div><div class=sum><div class=n id=n2>0</div><div class=t>need you now</div></div>
<div class=sum><div class=n id=n3>0</div><div class=t>interventions today</div></div><div class=sum><div class=n id=n4>–</div><div class=t>with an IEP or 504 plan</div></div></div>
<div class=main>
 <div><section class=card><div class=label>Your class</div><div class=roster id=roster></div></section>
  <section class="card detail" id=detail></section>
  <section class=insight><span class=tagp>💡 Insights</span><div class=big id=ins>–</div><div class=cap id=inscap>of the lesson focused, across students with live devices</div></section></div>
 <section class=card><div class=label>Step in <span>only when a student needs you</span></div><div class=feed id=feed><p class=empty>Nothing needs you right now.</p></div></section>
</div>
<p class=foot>No video is shown or stored here. EqualEd only tells you when a student needs you, and which of their accommodations to use.</p></div>
<script>
const $=id=>document.getElementById(id);let seen=new Set(),first=true,tmr=null,C=null,SEL=null,ALERTS=[];
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

function chime(){}  // silent on purpose: alerts are visual only
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
 const live=ss.find(s=>s.live);const L=live&&live.live_state;
 if(L){$('ins').textContent=Math.round(L.focused_pct??100)+'%'}$('live').className='live'+(L&&L.online?'':' off');$('live').lastChild.textContent=L&&L.online?'Live':'Offline';
 const need=ss.filter(s=>statusOf(s)[0]==='alert'||statusOf(s)[0]==='warn').length;
 $('n1').textContent=ss.length;$('n2').textContent=need;$('n4').textContent=ss.filter(s=>s.plan).length;
 $('roster').innerHTML=ss.map((s,i)=>{const [c,t]=statusOf(s);const busy=s.live&&L?Math.round(L.busy||0):null;
  return `<button class="st ${SEL===i?'sel':''} ${c==='alert'?'need':''}" onclick="SEL=${i};render()"><div class=row><div class=av>${ini(s.name)}</div><div><div class=nm>${esc(s.name)}</div><div class=nd>${esc(s.needs)}</div></div>
  <span class="plan ${s.plan==='IEP'?'iep':''}">${esc(s.plan||'')}</span></div><div class=row><span class="pill ${c}"><i></i>${esc(t)}</span>${s.live?'':'<span class=tag>sample</span>'}</div>
  ${busy!==null?`<div class=meter title="How busy it is around them"><div class="${busy>=55?'hatch-pink':busy>=30?'hatch-amber':'hatch-green'}" style="width:${Math.max(busy,3)}%"></div></div>`:''}
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
 clearTimeout(tmr);tmr=setTimeout(()=>t.className='',9000);chime();}
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
