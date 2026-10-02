"""The VM app's web page. Same look as the laptop app's student dashboard (server.py)."""

PAGE = r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>EqualEd · VM</title><style>
:root{--bg:#f6f7f9;--card:#fff;--text:#14171c;--muted:#5d6675;--line:#e3e6eb;--accent:#3b6ef5;
--red:#d93a3f;--orange:#e07b14;--green:#1f9d5c;--purple:#8a5cf6;--chip:#eef1f6;--bar:#e9ecf1}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1115;--card:#181b22;--text:#e9edf3;--muted:#98a2b3;
--line:#272c36;--accent:#7aa2ff;--red:#ff6369;--orange:#ffa94d;--green:#4cc38a;--purple:#b197fc;--chip:#232833;--bar:#262b35}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,system-ui,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px}
.wrap{max-width:1180px;margin:0 auto}h1{font-size:19px;margin:0}h1 span{color:var(--muted);font-weight:500}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{background:var(--chip);border-radius:999px;padding:3px 10px;font-size:12.5px;color:var(--muted)}
.chip.ok{color:var(--green)}.chip.bad{color:var(--red)}.chip.warn{color:var(--orange)}
nav{display:flex;gap:4px;margin-top:10px;overflow-x:auto}nav button{border:0;background:none;color:var(--muted);font:inherit;
padding:7px 12px;border-radius:8px;cursor:pointer;white-space:nowrap}nav button.on{background:var(--chip);color:var(--text);font-weight:600}
main{padding:16px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;min-width:0}
.card h2{font-size:14px;margin:0 0 10px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.wide{grid-column:span 2}.full{grid-column:1/-1}@media (max-width:700px){.wide{grid-column:auto}}
.big{font-size:34px;font-weight:700;font-variant-numeric:tabular-nums}.muted{color:var(--muted)}.small{font-size:13px}
.meter{height:14px;background:var(--bar);border-radius:999px;overflow:hidden;margin:8px 0}
.meter>div{height:100%;border-radius:999px;transition:width .3s,background .3s}
.banner{border-radius:12px;padding:12px 14px;margin-bottom:14px;font-weight:600;display:none}
.banner.show{display:block}.banner.warn{background:color-mix(in srgb,var(--orange) 18%,transparent);color:var(--orange)}
.banner.bad{background:color-mix(in srgb,var(--red) 16%,transparent);color:var(--red)}
.row{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--line)}.row:last-child{border:0}
.dot{width:10px;height:10px;border-radius:50%;flex:none;background:var(--green)}.dot.on{background:var(--red)}.dot.off{background:var(--muted);opacity:.5}
.dot.rush{background:var(--orange)}.grow{flex:1;min-width:0}.right{margin-left:auto;text-align:right}
button.b{border:1px solid var(--line);background:var(--chip);color:var(--text);font:inherit;font-size:13px;padding:5px 10px;border-radius:8px;cursor:pointer}
button.b.primary{background:var(--accent);color:#fff;border-color:transparent}button.b:disabled{opacity:.55;cursor:wait}
.ev{padding:8px 0;border-bottom:1px solid var(--line)}.ev:last-child{border:0}.ev .t{font-size:12.5px;color:var(--muted)}
.tag{font-size:11.5px;padding:1px 7px;border-radius:999px;background:var(--chip);color:var(--muted)}
.tag.close{color:var(--red)}.tag.rush{color:var(--orange)}.tag.loud{color:var(--purple)}.tag.space{color:var(--green)}
input[type=text],select{font:inherit;color:var(--text);background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:9px 10px}
input[type=text]{width:100%}select{max-width:100%}
.frame{width:100%;aspect-ratio:16/9;object-fit:contain;background:#000;border-radius:10px;display:block}
video{width:100%;aspect-ratio:16/9;background:#000;border-radius:10px;display:block}
svg.tl{width:100%;height:120px;display:block;background:var(--bar);border-radius:10px;margin-top:10px}
.answer{white-space:pre-wrap;margin-top:10px}.hide{display:none}.btns{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.hit{cursor:pointer}.hit.on{background:color-mix(in srgb,var(--accent) 10%,transparent);border-radius:8px}
.score{font-weight:700;color:var(--accent);font-variant-numeric:tabular-nums}
</style></head><body>
<header><div class=wrap><h1>EqualEd <span>· spotting sensory overload before it happens</span></h1><div class=chips id=chips></div>
<nav id=nav><button data-t=live class=on>Live</button><button data-t=search>Search the archive (VAST)</button>
<button data-t=map>Sensory map (VAST)</button></nav></div></header>
<main class=wrap>
<div id=bRisk class="banner warn"></div><div id=bClose class="banner bad"></div>

<section id=t-live><div class=grid>
 <div class="card wide"><h2>Camera</h2><img class=frame id=frame alt="analyzed video">
  <div style="display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap">
   <select id=clip title="Pick a clip"><option>loading clips…</option></select>
   <span class="small muted" id=clipstatus></span></div></div>
 <div class=card><h2>Sensory risk · NVIDIA Cosmos3-Reason</h2><div class=big id=riskV>--</div>
  <div class=meter><div id=riskBar></div></div><div id=riskWhy class=muted>Waiting for the first 2-second window…</div>
  <div class="small muted" id=riskMeta></div></div>
 <div class=card><h2>Seen it coming</h2><div class=big id=hits>0</div><div class=muted id=hitTxt>No busy moments yet</div>
  <div class="small muted" id=lastHit></div></div>
 <div class=card><h2>Busy around a person</h2><div class=big id=busyV>0</div><div class=meter><div id=busyBar></div></div>
  <div class=muted id=busyTxt></div></div>
 <div class=card><h2>Sound in the clip</h2><div class=big id=db>--</div><div class=meter><div id=dbBar></div></div>
  <div class=muted id=snd></div></div>
 <div class="card full"><h2>Risk over time</h2><div class="small muted">Bars: Cosmos risk per 2 s of video. Lines: busy moments
  (<span style="color:var(--red)">too close</span>, <span style="color:var(--orange)">rushing</span>, <span style="color:var(--purple)">loud</span>).
  Blue band: how early Cosmos warned.</div><svg class=tl id=tl viewBox="0 0 1000 120" preserveAspectRatio="none"></svg>
  <div id=moments class=small style="margin-top:6px"></div></div>
 <div class=card><h2>Things closing in</h2><div id=closing class=muted>Nothing tracked yet</div></div>
 <div class=card><h2>Rushing</h2><div id=rushing class=muted>Nobody rushing right now</div></div>
 <div class="card full"><h2>Recent moments</h2><div id=events class=muted>Nothing yet.</div></div>
</div></section>

<section id=t-search class=hide><div class=grid>
 <div class="card full"><h2>Search the VAST archive for triggers</h2>
  <p class="muted small">Searches the team's indexed footage (NVIDIA Cosmos3-Reason captions, YOLO11 counts, Cosmos Embed1)
  for moments that could overwhelm an autistic student. Click a result to play it, or analyze the whole chunk on the Live tab.</p>
  <form id=f style="display:flex;gap:8px"><input type=text id=q placeholder="e.g. crowd of people crossing the street" autocomplete=off>
   <button class="b primary" id=go>Search</button></form>
  <div class=btns id=presets></div><div class="small muted" id=smeta style="margin-top:8px"></div></div>
 <div class=card><h2>Moments</h2><div id=hitsList class="small muted">Pick a preset or type a trigger.</div></div>
 <div class=card><h2>Clip</h2><video id=player controls muted playsinline></video><div class="small muted" id=pmeta style="margin-top:6px"></div>
  <h2 style="margin-top:16px">Summary · W&amp;B Inference</h2>
  <button class=b id=sum disabled>Summarize these moments</button><div class=answer id=summary></div></div>
</div></section>

<section id=t-map class=hide><div class=grid>
 <div class="card full"><h2>Sensory map of the video archive</h2>
  <p class="muted small">Every archive clip labeled for sensory load from its Cosmos caption and YOLO counts, then ranked by place
  from most overwhelming to calmest. Use it to plan a calmer route or schedule.</p>
  <div class="small muted" id=mapMeta></div><div id=places style="margin-top:8px">Loading…</div></div>
 <div class="card full"><h2>Clip</h2><video id=mplayer controls muted playsinline></video><div class="small muted" id=mpmeta style="margin-top:6px">Pick a clip above.</div></div>
</div></section>
</main><script>
const BASE=location.pathname.startsWith('/app')?'/app':'';
const $=id=>document.getElementById(id);let S=null,tab=location.pathname.endsWith('/search')?'search':'live';
function showTab(t){tab=t;document.querySelectorAll('#nav button').forEach(x=>x.classList.toggle('on',x.dataset.t==t));
 document.querySelectorAll('main section').forEach(s=>s.classList.toggle('hide',s.id!='t-'+t));if(t=='map')loadMap();}
document.querySelectorAll('#nav button').forEach(b=>b.onclick=()=>showTab(b.dataset.t));showTab(tab);
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function post(r,d){const x=await fetch(BASE+'/api/'+r,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});
 const j=await x.json();if(!x.ok)throw new Error(j.error||x.status);return j;}
function color(v){return v>=60?'var(--red)':v>=35?'var(--orange)':'var(--green)';}
function chip(t,c){return `<span class="chip ${c||''}">${esc(t)}</span>`}
function meter(id,pct){$(id).style.width=Math.max(0,Math.min(100,pct))+'%';$(id).style.background=color(pct);}
const KIND={invasion:['too close','close'],sudden:['rushing','rush'],loud:['loud','loud'],clear:['space again','space']};

/* ---------------- clip picker */
let clipStatus=null;
async function loadClips(){try{const j=await (await fetch(BASE+'/api/clips',{cache:'no-store'})).json();
 const opt=(v,l,cur)=>`<option value="${esc(v)}"${cur?' selected':''}>${esc(l)}</option>`;
 $('clip').innerHTML=(j.local.length?`<optgroup label="On this machine">${j.local.map(c=>opt('path:'+c.path,c.name,c.name===j.current)).join('')}</optgroup>`:'')
  +`<optgroup label="VAST archive (downloads once)">${j.archive.map(c=>opt('source:'+c.source,c.label+(c.cached?'':' (download)'),c.source.split('/').pop()===j.current)).join('')}</optgroup>`;}catch(e){}}
$('clip').onchange=e=>{const v=e.target.value,i=v.indexOf(':');$('clipstatus').textContent='switching…';
 post('switch',{[v.slice(0,i)]:v.slice(i+1)}).catch(err=>$('clipstatus').textContent=err.message);};
loadClips();

/* ---------------- live tab */
function timeline(C,now){
 const tl=C.timeline||[],ms=C.moments||[],D=Math.max(10,now,...tl.map(w=>w.t1)),W=1000,top=8,base=104;
 const X=t=>(t/D*W).toFixed(1),Y=r=>(base-(r/10)*(base-top)).toFixed(1);
 const level=ms.length?ms[0].level:Math.min(Math.max((C.baseline||0)+2,3),6);
 let g=`<line x1=0 x2=${W} y1=${Y(level)} y2=${Y(level)} stroke="var(--orange)" stroke-dasharray="6 6" opacity=.6 />`;
 for(const w of tl){const x=+X(w.t0),bw=Math.max(2,+X(w.t1)-x-3);
  if(w.risk==null){g+=`<rect x=${x} y=${top} width=${bw} height=${base-top} fill=none stroke="var(--muted)" stroke-dasharray="3 4" opacity=.5 />`;continue;}
  g+=`<rect x=${x} y=${Y(w.risk)} width=${bw} height=${(base-+Y(w.risk)).toFixed(1)} rx=3 fill="${color(w.risk*10)}" opacity=.85><title>${w.t0}-${w.t1}s · risk ${w.risk}: ${esc(w.reason)}</title></rect>`;}
 for(const m of ms){const col=m.kinds.includes('invasion')?'var(--red)':m.kinds.includes('loud')?'var(--purple)':'var(--orange)';
  if(m.lead!=null)g+=`<rect x=${X(m.rise_t)} y=${base+3} width=${(+X(m.t)-+X(m.rise_t)).toFixed(1)} height=9 rx=3 fill="var(--accent)" opacity=.55 />`;
  g+=`<line x1=${X(m.t)} x2=${X(m.t)} y1=${top} y2=${base+12} stroke="${col}" stroke-width=2.5><title>${m.t}s ${esc(m.what)}</title></line>`;}
 g+=`<line x1=${X(now)} x2=${X(now)} y1=0 y2=120 stroke="var(--text)" opacity=.35 />`;
 $('tl').innerHTML=g;
 $('moments').innerHTML=ms.length?ms.slice(-5).reverse().map(m=>{const k=KIND[m.kinds.includes('invasion')?'invasion':m.kinds.includes('loud')?'loud':'sudden'];
  return `<div class=ev><span class="tag ${k[1]}">${k[0]}</span> <b>${m.t}s</b> ${m.events>1?`<span class=muted>(${m.events} events)</span>`:''} · `+
  (m.lead!=null?`Cosmos risk ${m.rise_risk} at ${m.rise_t}s, <b style="color:var(--accent)">${m.lead}s early</b>`:m.predictable?'<span class=muted>no risk rise before it</span>':'<span class=muted>before the first Cosmos answer</span>')+'</div>';}).join(''):'<span class=muted>No busy moments yet.</span>';
}
function renderLive(){
 const s=S.summary||{},a=S.audio||{},C=S.cosmos||{},sv=S.services||{};
 $('chips').innerHTML=chip((S.fps||0)+' FPS','ok')+chip('Clip: '+(S.video||'none'))+chip('t '+(S.video_t||0)+'s')
  +chip(a.has_audio?'Audio on':'No audio track',a.has_audio?'ok':'warn')
  +chip('Cosmos: '+(C.enabled?(C.errors?C.errors+' errors':'connected'):(C.reason||'off')),C.enabled?(C.errors?'warn':'ok'):'bad')
  +chip('Archive: '+(sv.archive||'?'),sv.archive=='connected'?'ok':'warn')
  +chip('W&B: '+(sv.wandb||'?'),sv.wandb=='ready'?'ok':'warn')+(sv.weave?chip('Weave: '+sv.weave,sv.weave.startsWith('tracing')?'ok':'warn'):'');
 if(S.clip_status!==clipStatus){clipStatus=S.clip_status;$('clipstatus').textContent=clipStatus||'';loadClips();}
 const L=C.latest;
 if(!C.enabled){$('riskV').textContent='off';$('riskWhy').textContent=C.reason||'';meter('riskBar',0);}
 else if(L){$('riskV').textContent=L.risk+' / 10';meter('riskBar',L.risk*10);$('riskWhy').textContent='Because: '+L.reason;
  $('riskMeta').textContent=`${L.t0}–${L.t1}s · answered in ${L.latency}s · ${C.calls} reads · ${C.pending} pending`;}
 const level=(C.moments&&C.moments.length)?C.moments[0].level:6;
 $('bRisk').className='banner warn'+(L&&L.risk>=level?' show':'');if(L)$('bRisk').textContent=`Heads up: Cosmos rates the last 2 s ${L.risk}/10. ${L.reason}`;
 $('hits').textContent=C.predicted||0;
 $('hitTxt').textContent=C.moments_n?`busy moments warned early out of ${C.moments_n}`+(C.predicted?`, ${C.lead_median}s early (median), best ${C.lead_best}s`:''):'No busy moments yet';
 const lm=(C.moments||[]).filter(m=>m.lead!=null).pop();$('lastHit').textContent=lm?`Last: ${lm.what} at ${lm.t}s, ${lm.lead}s early`:'';
 const close=s.invaded||0,rush=s.sudden||0,busy=Math.min(100,close*30+rush*20+(s.people||0)*3);
 $('busyV').textContent=close?close+' too close':'calm';meter('busyBar',busy);
 $('busyTxt').textContent=`${s.people||0} people · ${(s.robots||0)-(s.agvs||0)} humanoid robots · ${s.agvs||0} AGVs · ${rush} rushing`;
 $('bClose').className='banner bad'+(close?' show':'');$('bClose').textContent=close?`Too close right now: something is closing in on ${close} ${close>1?'people':'person'}`:'';
 if(!a.has_audio){$('db').textContent='--';meter('dbBar',0);$('snd').textContent=a.reason||'no audio track';}
 else{$('db').textContent=Math.round(a.db)+' dB';meter('dbBar',(a.db+70)*1.6);
  $('snd').textContent=a.alerting?('Loud: '+(a.last_event||'')):(a.label?'Hearing: '+a.label:'listening · normal level '+a.baseline+' dB');}
 timeline(C,+S.video_t||0);
 const R=S.robots||[];
 $('closing').innerHTML=R.length?R.map(r=>r.status=='agv'
  ?`<div class=row><span class="dot off"></span><span class=grow>${esc(r.label)} · AGV<br><span class="small muted">can close in on a humanoid · has no personal space</span></span><span class="right small muted">${r.sudden?'rushing':''}</span></div>`
  :`<div class=row><span class="dot ${r.invaded?'on':''}"></span><span class=grow>${esc(r.label)} · ${r.invaded?'<b style="color:var(--red)">too close</b>':'has space'}<br>
   <span class="small muted">${r.closest!=null?'nearest '+esc(r.closest_label)+' at '+r.closest+' body-lengths':'nobody near'}</span></span>
   <span class="right small muted">${r.invasion_count?'×'+r.invasion_count:''}</span></div>`).join(''):'Nothing tracked yet';
 const Rs=[...R,...(S.people||[])].filter(x=>x.sudden);
 $('rushing').innerHTML=Rs.length?Rs.map(x=>`<div class=row><span class="dot rush"></span><span class=grow>${esc(x.label)} · ${esc(x.subtype)}</span><span class="right small muted">${x.speed} body-lengths/s</span></div>`).join(''):'Nobody rushing right now';
 const E=S.events||[];
 $('events').innerHTML=E.length?E.slice(0,20).map(e=>{const k=KIND[e.kind]||[e.kind,''];
  return `<div class=ev><div class=t>video ${esc(e.t)}s · ${esc(e.wall)} · <span class="tag ${k[1]}">${esc(k[0])}</span></div><div>${esc(e.robot||e.agent||'')} ${esc(e.detail)}</div></div>`;}).join(''):'Nothing yet.';
}
async function load(){try{const r=await fetch(BASE+'/api/state',{cache:'no-store'});S=await r.json();if(tab=='live'){renderLive();$('frame').src=BASE+'/api/frame.jpg?ts='+Date.now();}}catch(e){}}
load();setInterval(load,700);

/* ---------------- search tab */
let last=null;
function play(vid,meta,src,label){$(vid).src=BASE+'/api/clip?source='+encodeURIComponent(src);$(vid).play().catch(()=>{});$(meta).textContent=label;}
async function search(q){q=(q||'').trim();if(!q)return;$('q').value=q;$('go').disabled=true;$('sum').disabled=true;
 $('smeta').textContent='Searching the archive…';$('hitsList').innerHTML='';
 try{const j=await post('search',{query:q});last=j;
  $('smeta').textContent=`${j.hits.length} moments for "${j.query}" in ${j.secs}s`;
  $('hitsList').innerHTML=j.hits.length?j.hits.map((h,i)=>`<div class="ev hit" data-i=${i}>
   <div class=t><span class=score>${h.score.toFixed(2)}</span> · ${esc(h.location)} · ${esc(h.camera_id)} · ${h.start}–${h.end}s · ${h.people??0} people</div>
   <div>${esc(h.caption.slice(0,200))}${h.caption.length>200?'…':''}</div>
   ${h.original_video?`<div class=btns><button class=b data-a=${i}>Analyze this chunk on Live</button></div>`:''}</div>`).join(''):'No moments above the similarity threshold.';
  document.querySelectorAll('.hit').forEach(el=>el.onclick=()=>{document.querySelectorAll('.hit').forEach(x=>x.classList.remove('on'));el.classList.add('on');
   const h=j.hits[+el.dataset.i];play('player','pmeta',h.source,`${h.location} · ${h.camera_id} · ${h.video}`);});
  document.querySelectorAll('[data-a]').forEach(b=>b.onclick=async ev=>{ev.stopPropagation();b.disabled=true;b.textContent='loading chunk…';
   await post('switch',{source:j.hits[+b.dataset.a].original_video}).catch(()=>{});showTab('live');});
  if(j.hits.length){$('sum').disabled=false;document.querySelector('.hit').click();}
 }catch(e){$('smeta').textContent='Search failed: '+e.message;}
 $('go').disabled=false;}
$('f').onsubmit=e=>{e.preventDefault();search($('q').value);};
$('sum').onclick=async()=>{if(!last)return;$('sum').disabled=true;$('summary').textContent='Asking Llama 3.3 70B on W&B Inference…';
 try{const j=await post('summarize',{query:last.query,hits:last.hits});
  $('summary').textContent=j.summary+`\n\n— ${j.model} · ${j.secs}s`+(j.weave?` · traced in Weave (${j.weave_project})`:'');}
 catch(e){$('summary').textContent='Summary failed: '+e.message;}$('sum').disabled=false;};
fetch(BASE+'/api/presets').then(r=>r.json()).then(ps=>{$('presets').innerHTML=ps.map(p=>`<button type=button class=b>${esc(p)}</button>`).join('');
 document.querySelectorAll('#presets button').forEach(b=>b.onclick=()=>search(b.textContent));});

/* ---------------- sensory map tab */
let mapLoaded=false;
async function loadMap(){if(mapLoaded)return;mapLoaded=true;
 try{const j=await (await fetch(BASE+'/api/sensory_map')).json();
  if(!j.available){$('places').textContent=j.reason;return;}
  $('mapMeta').textContent=`${j.clips_labeled} clips labeled ${j.labeled_at} · ${j.levels.high} high · ${j.levels.moderate} moderate · ${j.levels.calm} calm`;
  $('places').innerHTML=j.places.map((p,pi)=>`<div class=row><span class=grow><b>${pi+1}. ${esc(p.location.replace(/_/g,' '))}</b> <span class="small muted">${esc(p.camera_id)} · ${p.clips} clips</span><br>
   <span class="small muted">${p.high_pct}% high · ${p.calm_pct}% calm · ${esc(p.main_triggers)}</span>
   <div class=meter><div style="width:${Math.max(3,p.avg_load*10)}%;background:${color(p.avg_load*10)}"></div></div>
   ${p.top_clips.length?`<div class=btns style="margin:0 0 6px">${p.top_clips.map((c,ci)=>`<button class=b data-p=${pi} data-c=${ci}>▶ ${c.start_sec}s · load ${c.load} · ${esc(c.triggers)}</button>`).join('')}</div>`:''}</span>
   <span class="right small">load ${p.avg_load}/10</span></div>`).join('');
  document.querySelectorAll('#places [data-p]').forEach(b=>b.onclick=()=>{const c=j.places[+b.dataset.p].top_clips[+b.dataset.c];
   play('mplayer','mpmeta',c.source,`${c.location} · ${c.camera_id} · load ${c.load} (${c.triggers}): ${c.caption}`);});
 }catch(e){$('places').textContent='Sensory map failed to load';mapLoaded=false;}}
</script></body></html>"""
