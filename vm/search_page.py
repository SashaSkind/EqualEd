"""HTML for the "Search triggers" page (VAST archive search + sensory map + W&B summary)."""

SEARCH_PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EqualEd · Search triggers</title>
<style>
:root{
  --bg:#0e1412; --panel:#15201c; --ink:#e8f0ea; --muted:#8aa396;
  --line:#24352e; --ok:#3dbe7a; --bad:#e4574d; --warn:#e0a23a; --accent:#5ec4a2;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
  --sans:"IBM Plex Sans",system-ui,sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:
  radial-gradient(1200px 600px at 10% -10%,#1a3a2e 0%,transparent 55%),
  radial-gradient(900px 500px at 100% 0%,#2a2418 0%,transparent 50%),
  var(--bg);color:var(--ink);font:15px/1.45 var(--sans);min-height:100vh}
header{padding:18px 22px 8px;display:flex;flex-wrap:wrap;gap:12px;align-items:end;justify-content:space-between}
.brand{font-size:28px;font-weight:700;letter-spacing:-.02em}
.brand span{color:var(--accent)}
.sub{color:var(--muted);font-size:13px;margin-top:4px}
nav a{color:var(--muted);text-decoration:none;font:13px var(--mono);margin-left:14px}
nav a.on{color:var(--accent)}
main{padding:8px 22px 28px;display:grid;grid-template-columns:1.1fr 1fr;gap:16px}
@media(max-width:960px){main{grid-template-columns:1fr}}
.stack{display:flex;flex-direction:column;gap:16px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.panel h2{margin:0;padding:12px 14px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--line)}
.pad{padding:12px 14px}
form{display:flex;gap:8px}
input[type=text]{flex:1;background:#0b110f;border:1px solid var(--line);border-radius:8px;color:var(--ink);padding:9px 12px;font:15px var(--sans)}
button{background:#1d2c26;border:1px solid var(--line);border-radius:8px;color:var(--ink);padding:8px 12px;font:13px var(--sans);cursor:pointer}
button:hover{border-color:var(--accent)}
button.primary{background:color-mix(in srgb,var(--accent) 25%,#1d2c26)}
button:disabled{opacity:.5;cursor:wait}
.presets{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.presets button{font-size:12px;padding:5px 9px}
.hit{display:grid;grid-template-columns:58px 1fr;gap:10px;padding:10px 14px;border-bottom:1px solid var(--line);cursor:pointer}
.hit:hover,.hit.on{background:#1a2722}
.score{font:600 14px var(--mono);color:var(--accent)}
.where{font:12px var(--mono);color:var(--muted)}
.cap{font-size:13px;margin-top:3px;color:#c9d6cf}
.results{max-height:560px;overflow:auto}
video{width:100%;display:block;background:#000;aspect-ratio:16/9}
.meta{padding:8px 14px;font:12px var(--mono);color:var(--muted)}
.summary{white-space:pre-wrap;font-size:14px}
.place{padding:10px 14px;border-bottom:1px solid var(--line)}
.place .bar{height:8px;border-radius:4px;background:#0b110f;margin:6px 0;overflow:hidden}
.place .bar i{display:block;height:100%}
.place .clips{display:flex;gap:6px;flex-wrap:wrap;margin-top:4px}
.place .clips button{font:11px var(--mono);padding:3px 7px}
.empty{color:var(--muted);padding:14px}
.muted{color:var(--muted);font-size:12.5px}
</style></head><body>
<header>
  <div>
    <div class="brand">equal<span>Ed</span> · search triggers</div>
    <div class="sub">Find overwhelming moments in the VAST archive, see which places are calmest</div>
  </div>
  <nav><a id="nav-live" href="#">live shield</a><a id="nav-search" class="on" href="#">search triggers</a></nav>
</header>
<main>
  <div class="stack">
    <section class="panel">
      <h2>Search the archive (VSS)</h2>
      <div class="pad">
        <form id="f"><input id="q" type="text" placeholder="e.g. crowd of people crossing the street" autocomplete="off">
          <button class="primary" id="go">Search</button></form>
        <div class="presets" id="presets"></div>
      </div>
      <div class="meta" id="smeta">Pick a preset or type a trigger.</div>
      <div class="results" id="hits"></div>
    </section>
  </div>
  <div class="stack">
    <section class="panel">
      <h2>Clip</h2>
      <video id="player" controls muted playsinline></video>
      <div class="meta" id="pmeta">Click a result or a sensory-map clip to play it.</div>
    </section>
    <section class="panel">
      <h2>Summary · W&amp;B Inference</h2>
      <div class="pad">
        <button id="sum" disabled>Summarize these results</button>
        <div class="summary" id="summary" style="margin-top:10px"><span class="muted">Search first, then summarize the top hits in plain language.</span></div>
      </div>
    </section>
    <section class="panel">
      <h2>Sensory map · most overwhelming to calmest</h2>
      <div id="map"><div class="empty">Loading…</div></div>
    </section>
  </div>
</main>
<script>
const BASE = location.pathname.startsWith('/app') ? '/app' : '';
const $ = id => document.getElementById(id);
$('nav-live').href = BASE + '/'; $('nav-search').href = BASE + '/search';
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
let last = null;
function play(source, label, start){
  const v=$('player');
  v.src = BASE + '/api/clip?source=' + encodeURIComponent(source);
  v.play().catch(()=>{});
  $('pmeta').textContent = label + (start!=null?` · segment starts at ${start}s in its chunk`:'');
}
async function search(q){
  q=(q||'').trim(); if(!q) return;
  $('q').value=q; $('go').disabled=true; $('sum').disabled=true;
  $('smeta').textContent='Searching…'; $('hits').innerHTML='';
  try{
    const r=await fetch(BASE+'/api/search',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:q})});
    const j=await r.json(); if(!r.ok) throw new Error(j.error||r.status);
    last=j;
    $('smeta').textContent=`${j.hits.length} moments for "${j.query}" in ${j.secs}s (min similarity 0.2)`;
    $('hits').innerHTML = j.hits.length ? j.hits.map((h,i)=>`<div class="hit" data-i="${i}">
      <div class="score">${h.score.toFixed(2)}</div>
      <div><div class="where">${esc(h.location)} · ${esc(h.camera_id)} · ${h.start}–${h.end}s · ${h.people??0} people</div>
      <div class="cap">${esc(h.caption.slice(0,220))}${h.caption.length>220?'…':''}</div>
      ${h.original_video?`<button class="analyze" data-i="${i}" style="margin-top:6px;font-size:11.5px;padding:3px 8px">analyze this chunk in live shield →</button>`:''}</div></div>`).join('')
      : '<div class="empty">No moments above the similarity threshold.</div>';
    document.querySelectorAll('.analyze').forEach(b=>b.onclick=async ev=>{
      ev.stopPropagation(); b.disabled=true; b.textContent='loading chunk…';
      await fetch(BASE+'/api/switch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source:j.hits[+b.dataset.i].original_video})});
      location.href = BASE + '/';
    });
    document.querySelectorAll('.hit').forEach(el=>el.onclick=()=>{
      document.querySelectorAll('.hit').forEach(x=>x.classList.remove('on')); el.classList.add('on');
      const h=j.hits[+el.dataset.i]; play(h.source, `${h.location} · ${h.camera_id} · ${h.video}`, h.start);
    });
    if(j.hits.length){ $('sum').disabled=false; const h=j.hits[0]; play(h.source, `${h.location} · ${h.camera_id} · ${h.video}`, h.start); document.querySelector('.hit').classList.add('on'); }
  }catch(e){ $('smeta').textContent='Search failed: '+e.message; }
  $('go').disabled=false;
}
$('f').onsubmit = e => { e.preventDefault(); search($('q').value); };
$('sum').onclick = async () => {
  if(!last) return;
  $('sum').disabled=true; $('summary').innerHTML='<span class="muted">Asking W&amp;B Inference…</span>';
  try{
    const r=await fetch(BASE+'/api/summarize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:last.query,hits:last.hits})});
    const j=await r.json(); if(!r.ok) throw new Error(j.error||r.status);
    $('summary').innerHTML = esc(j.summary) + `<div class="muted" style="margin-top:8px">${esc(j.model)} · ${j.secs}s${j.weave?` · traced in Weave (${esc(j.weave_project)})`:''}</div>`;
  }catch(e){ $('summary').textContent='Summary failed: '+e.message; }
  $('sum').disabled=false;
};
function loadColor(x){return x>=5?'var(--bad)':x>=3?'var(--warn)':'var(--ok)';}
async function loadMap(){
  try{
    const j=await (await fetch(BASE+'/api/sensory_map')).json();
    if(!j.available){ $('map').innerHTML=`<div class="empty">${esc(j.reason)}</div>`; return; }
    $('map').innerHTML = `<div class="meta">${j.clips_labeled} clips labeled ${esc(j.labeled_at)} · high ${j.levels.high} · moderate ${j.levels.moderate} · calm ${j.levels.calm}</div>` +
      j.places.map((p,pi)=>`<div class="place">
        <div><b>${esc(p.location.replace('_',' '))}</b> <span class="where">${esc(p.camera_id)} · ${p.clips} clips</span>
          <span style="float:right;font:600 14px var(--mono);color:${loadColor(p.avg_load)}">${p.avg_load}/10</span></div>
        <div class="bar"><i style="width:${p.avg_load*10}%;background:${loadColor(p.avg_load)}"></i></div>
        <div class="muted">${p.high_pct}% high · ${p.calm_pct}% calm · ${esc(p.main_triggers)}</div>
        ${p.top_clips.length?`<div class="clips">${p.top_clips.map((c,ci)=>`<button data-p="${pi}" data-c="${ci}">▶ ${c.start_sec}s · load ${c.load} · ${esc(c.triggers)}</button>`).join('')}</div>`:''}
      </div>`).join('');
    document.querySelectorAll('.place .clips button').forEach(b=>b.onclick=()=>{
      const c=j.places[+b.dataset.p].top_clips[+b.dataset.c];
      play(c.source, `${c.location} · ${c.camera_id} · load ${c.load} (${c.triggers}): ${c.caption}`, c.start_sec);
    });
  }catch(e){ $('map').innerHTML='<div class="empty">Sensory map failed to load</div>'; }
}
fetch(BASE+'/api/presets').then(r=>r.json()).then(ps=>{
  $('presets').innerHTML = ps.map(p=>`<button type="button">${esc(p)}</button>`).join('');
  document.querySelectorAll('#presets button').forEach(b=>b.onclick=()=>search(b.textContent));
});
loadMap();
</script></body></html>
"""
