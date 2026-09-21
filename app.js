/* Tribes \u2014 Telegram Mini App frontend */
const tg = window.Telegram && window.Telegram.WebApp;
if (tg) { try { tg.ready(); tg.expand(); } catch (e) {} }
const INIT = (tg && tg.initData) ? tg.initData : ("user_id=dev-" + Math.floor(Math.random()*9999) + "&first_name=Explorer");
const EMO = cp => String.fromCodePoint(cp);

function hdrs(){ return { "Content-Type":"application/json", "X-Init-Data": INIT }; }
async function api(path, method, body){
  const opt = { method: method||"GET", headers: hdrs() };
  if (method === "POST") opt.body = JSON.stringify(Object.assign({ initData: INIT }, body||{}));
  const r = await fetch(path, opt);
  return r.json();
}
function haptic(t){ try{ tg.HapticFeedback.impactOccurred(t||"medium"); }catch(e){} }
let toastT;
function toast(msg){ const t=document.getElementById("toast"); t.textContent=msg; t.classList.add("show");
  clearTimeout(toastT); toastT=setTimeout(()=>t.classList.remove("show"),2200); }

let STATE = null;

/* ---------- embers backdrop ---------- */
(function embers(){ const box=document.getElementById("embers");
  for(let i=0;i<26;i++){ const s=document.createElement("i"); s.className="spark";
    s.style.left=Math.random()*100+"%"; s.style.animationDuration=(5+Math.random()*7)+"s";
    s.style.animationDelay=(Math.random()*8)+"s"; s.style.width=s.style.height=(3+Math.random()*4)+"px";
    box.appendChild(s);} })();

/* ---------- navigation ---------- */
document.querySelectorAll(".nav").forEach(b=>b.addEventListener("click",()=>{
  haptic("light");
  document.querySelectorAll(".nav").forEach(x=>x.classList.remove("active"));
  b.classList.add("active");
  const scr=b.dataset.screen;
  document.querySelectorAll(".screen").forEach(s=>s.classList.remove("active"));
  document.getElementById("screen-"+scr).classList.add("active");
  if(scr==="tribe") loadTribe();
  if(scr==="ranks") loadBoard(curBoard);
  if(scr==="lands") loadLands();
  if(scr==="sky") renderSky();
  if(scr==="claim") loadClaim();
}));

/* ---------- HOME ---------- */
async function refresh(){ STATE = await api("/api/state"); renderHome(); }
function renderHome(){
  const s=STATE; if(!s) return;
  document.getElementById("emberTop").textContent=s.ember;
  document.getElementById("emberVal").textContent=s.ember;
  document.getElementById("streakVal").textContent=s.streak;
  document.getElementById("shareVal").textContent=(s.allocation?s.allocation.share_pct:0)+"%";
  document.getElementById("agePill").textContent=(s.age&&s.age.name)||"Age of First Fire";
  const t=s.tribe||{};
  document.getElementById("stageName").textContent=t.stage||"Campfire";
  document.getElementById("stageMembers").textContent=(t.members||1)+" / "+(t.max_members||5)+" kin";
  scaleFire(t.level||1);
  // check-in button
  const btn=document.getElementById("checkinBtn");
  if(s.today){ btn.textContent="Fire is lit today \u2713"; btn.classList.add("done"); }
  else { btn.textContent="Tend the Campfire"; btn.classList.remove("done"); }
  // heat
  const heat=document.getElementById("heat"); heat.innerHTML="";
  (s.heatmap||[]).forEach(d=>{ const i=document.createElement("i"); if(d.active)i.classList.add("on"); heat.appendChild(i); });
  // hunt
  const h=s.hunt||{progress:0,target:1,won:false};
  const pct=Math.min(100, h.target?Math.round(h.progress/h.target*100):0);
  document.getElementById("huntBar").style.width=pct+"%";
  document.getElementById("huntState").textContent=h.won?"Won \u2705":(h.progress+"/"+h.target);
  document.getElementById("huntText").textContent=h.won?"Today's hunt is won \u2014 Loyalty added to the Hearth!":"Every kin who tends the fire feeds today's hunt.";
  // tasks
  const tw=document.getElementById("tasks"); tw.innerHTML="";
  (s.tasks||[]).forEach(t=>{
    const row=document.createElement("div"); row.className="task"+(t.done?" done":"");
    row.innerHTML=`<div class="t-i">${t.done?"\u2713":"\u25CB"}</div><div class="t-b"><b>${esc(t.title)}</b><span>${esc(t.hint||"")}</span></div>`;
    const right=document.createElement("div");
    if(t.done){ right.className="rw"; right.textContent="+"+(t.reward||0); }
    else if(t.kind==="manual"||t.kind==="link"){ const c=document.createElement("button"); c.className="chip"; c.textContent="Do"; c.onclick=()=>doTask(t); right.appendChild(c); }
    else { right.className="rw"; right.textContent="+"+(t.reward||0); }
    row.appendChild(right); tw.appendChild(row);
  });
  // relics
  const rw=document.getElementById("relics"); rw.innerHTML="";
  const RELICS=["r_spear","r_flint","r_shell","r_bone","r_ochre","r_tooth"];
  const glyph={r_spear:EMO(0x1F3F9),r_flint:EMO(0x1FAA8),r_shell:EMO(0x1F41A),r_bone:EMO(0x1F9B4),r_ochre:EMO(0x1F3FA),r_tooth:EMO(0x1F9B7)};
  RELICS.forEach(id=>{ const found=(s.relics||[]).includes(id);
    const d=document.createElement("div"); d.className="relic"+(found?" found":"");
    d.textContent=found?glyph[id]:"?"; if(!found) d.onclick=()=>findRelic(id,d); rw.appendChild(d); });
}
function scaleFire(level){
  const f=document.getElementById("fire"); const sc=1+Math.min(level-1,10)*0.06;
  f.style.transform="scale("+sc+")";
  const set=document.getElementById("settlementVisual");
  const huts=Math.min(level,8);
  let html="";
  for(let i=0;i<huts;i++){ const x=12+i*(76/Math.max(1,huts)); const hgt=18+((i*7)%14);
    html+=`<span style="position:absolute;bottom:0;left:${x}%;width:16px;height:${hgt}px;background:linear-gradient(#5a3418,#3a2110);border-radius:3px 3px 0 0;opacity:.85"></span>`; }
  set.innerHTML=html;
}
function esc(s){ return (s||"").replace(/[&<>\"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'\"':"&quot;","'":"&#39;"}[c])); }

document.getElementById("checkinBtn").addEventListener("click",async()=>{
  if(STATE&&STATE.today){ toast("The fire already burns today"); return; }
  haptic("heavy"); STATE=await api("/api/checkin","POST"); renderHome();
  toast("\ud83d\udd25 Fire tended \u2014 Ember earned");
});
async function doTask(t){ haptic("light");
  if(t.id==="war_cry"){ document.querySelector('.nav[data-screen="tribe"]').click(); setTimeout(openWarCry,300); return; }
  if(t.id==="beat_drum"){ document.querySelector('.nav[data-screen="tribe"]').click(); return; }
  if(t.id==="connect_wallet"){ document.querySelector('.nav[data-screen="claim"]').click(); return; }
  STATE=await api("/api/tasks/complete","POST",{task_id:t.id}); renderHome(); toast("Quest logged");
}
async function findRelic(id,el){ haptic("medium"); el.classList.add("found");
  STATE=await api("/api/relic/find","POST",{relic_id:id}); renderHome(); toast("\ud83d\uddff A relic! Hidden Ember found"); }

/* ---------- TRIBE ---------- */
async function loadTribe(){
  const d=await api("/api/tribe"); const t=d.tribe||{};
  document.getElementById("tribeName").textContent=t.name||"Your Tribe";
  document.getElementById("tribeCrest").textContent=t.crest||EMO(0x1F525);
  document.getElementById("warCry").textContent=t.war_cry?("\u201c"+t.war_cry+"\u201d"):"\u201cAdd your tribe's War Cry.\u201d";
  document.getElementById("hearthBal").textContent=(t.loyalty_bal||0).toLocaleString();
  document.getElementById("hearthAvg").textContent="avg "+(t.avg_loyalty||0)+" / kin";
  document.getElementById("memCount").textContent=(t.members||0)+" / "+(t.max_members||0);
  // upgrade
  const nx=t.next; const ub=document.getElementById("upgBtn"); const ut=document.getElementById("upgText");
  if(nx){ const pct=Math.min(100,Math.round((t.loyalty_bal||0)/nx.cost*100));
    document.getElementById("upgBar").style.width=pct+"%";
    ut.textContent="\u2192 "+nx.stage+": "+nx.cost.toLocaleString()+" Loyalty";
    ub.disabled=(t.loyalty_bal||0)<nx.cost; ub.onclick=doUpgrade;
  } else { document.getElementById("upgBar").style.width="100%"; ut.textContent="Empire \u2014 max settlement"; ub.disabled=true; }
  // roster
  const rw=document.getElementById("roster"); rw.innerHTML="";
  (d.roster||[]).forEach(m=>{ const row=document.createElement("div"); row.className="member";
    const flame=m.supporter?' <span class="flame-tag">\ud83d\udd25</span>':"";
    row.innerHTML=`<div class="av">${esc((m.name||"K")[0])}</div><div class="m-b"><b>${esc(m.name)}${m.you?" (you)":""}${flame}</b><span>${m.ember} Ember \u00b7 ${m.streak}\ud83d\udd25</span></div><span class="role ${m.role}">${m.role}</span>`;
    rw.appendChild(row); });
  // cave wall
  const cw=document.getElementById("caveWall"); cw.innerHTML="";
  if(!(d.cave_wall||[]).length) cw.innerHTML='<p class="muted">No marks yet \u2014 paint the first.</p>';
  (d.cave_wall||[]).forEach(c=>{ const el=document.createElement("div"); el.className="cave";
    el.innerHTML=`<b>${esc(c.author)}</b> \u00b7 ${esc(c.text)}`; cw.appendChild(el); });
}
async function doUpgrade(){ haptic("heavy"); const r=await api("/api/tribe/upgrade","POST");
  if(r.ok){ toast("\ud83c\udf07 The settlement grows!"); } else { toast(r.error==="not_enough"?"Not enough Loyalty yet":"Cannot upgrade"); }
  loadTribe(); refresh();
}
document.getElementById("drumBtn").addEventListener("click",async()=>{ haptic("medium");
  const r=await api("/api/drum","POST");
  if(r.ok){ toast("\ud83e\udd41 The drum sounds \u2014 mates summoned!"); } else { toast("No drum calls left today"); }
});
document.getElementById("caveBtn").addEventListener("click",()=>openSheet("Paint the Cave Wall",
  `<textarea id="caveInput" rows="3" placeholder="A great moment for the tribe..."></textarea><button class="cta" id="caveSave">Paint it</button>`,
  ()=>{ document.getElementById("caveSave").onclick=async()=>{ const v=document.getElementById("caveInput").value.trim();
    if(!v){ toast("Say something first"); return; } await api("/api/tribe/cave","POST",{text:v}); closeSheet(); toast("Painted on the wall"); loadTribe(); }; }));
function openWarCry(){ openSheet("Your War Cry",
  `<input id="wcInput" maxlength="120" placeholder="For the fire that never dies!"/><button class="cta" id="wcSave">Raise the cry</button>`,
  ()=>{ document.getElementById("wcSave").onclick=async()=>{ const v=document.getElementById("wcInput").value.trim();
    if(!v){ toast("Write your cry"); return; } STATE=await api("/api/tribe/warcry","POST",{text:v}); closeSheet(); toast("War Cry raised!"); loadTribe(); renderHome(); }; }); }

/* ---------- RANKS ---------- */
let curBoard="tribes";
document.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>{
  document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active")); b.classList.add("active");
  curBoard=b.dataset.board; loadBoard(curBoard); }));
async function loadBoard(kind){
  const box=document.getElementById("board"); const rival=document.getElementById("rivalBox"); rival.innerHTML="";
  box.innerHTML='<p class="muted">Loading...</p>';
  if(kind==="tribes"){
    const d=await api("/api/leaderboard/tribes");
    if(d.rival){ rival.innerHTML=`<div class="rival">Rival Tribe: <b>${d.rival.crest||""} ${esc(d.rival.name)}</b> \u00b7 avg ${d.rival.avg_loyalty} \u2014 catch them!</div>`; }
    box.innerHTML=""; (d.board||[]).forEach(e=>{
      const r=document.createElement("div"); r.className="rank-row"+(e.you?" you":"");
      r.innerHTML=`<div class="num ${e.rank<=3?"top":""}">${e.rank}</div><div class="nm">${e.crest||""} ${esc(e.name)}${e.you?" (you)":""}<small>${e.stage} \u00b7 ${e.members} kin \u00b7 ${esc(e.land||"")}</small></div><div class="val">${e.avg_loyalty}</div>`;
      box.appendChild(r); });
  } else {
    const d=await api("/api/leaderboard/kin");
    box.innerHTML=""; (d.board||[]).forEach(e=>{
      const r=document.createElement("div"); r.className="rank-row"+(e.you?" you":"");
      const flame=e.supporter?" \ud83d\udd25":"";
      r.innerHTML=`<div class="num ${e.rank<=3?"top":""}">${e.rank}</div><div class="nm">${esc(e.name)}${flame}${e.you?" (you)":""}<small>${e.streak} day streak</small></div><div class="val">${e.ember}</div>`;
      box.appendChild(r); });
  }
}

/* ---------- LANDS ---------- */
async function loadLands(){ const d=await api("/api/lands"); const g=document.getElementById("landsGrid"); g.innerHTML="";
  (d.lands||[]).forEach(l=>{ const el=document.createElement("div"); const held=!!l.holder;
    el.className="land"+(held?"":" free"); const color=held?l.holder.color:"#2fe0c8";
    el.innerHTML=`<div class="glow" style="background:radial-gradient(circle at 30% 20%,${color},transparent 70%)"></div>`+
      `<div class="lname">${esc(l.land)}</div>`+
      `<div class="holder">${held?((l.holder.crest||"")+" "+esc(l.holder.name)):"Unclaimed \u2014 up for grabs"}</div>`;
    g.appendChild(el); }); }

/* ---------- SKY ---------- */
function renderSky(){ const sky=document.getElementById("sky"); sky.innerHTML="";
  const earned=(STATE&&STATE.tribe)?(STATE.tribe.loyalty_earned||0):0;
  const n=Math.min(40, 4+Math.floor(earned/1500));
  for(let i=0;i<n;i++){ const s=document.createElement("i"); s.className="star";
    s.style.left=(6+Math.random()*88)+"%"; s.style.top=(8+Math.random()*80)+"%";
    s.style.animationDelay=(Math.random()*2.4)+"s"; s.style.transform="scale("+(0.6+Math.random())+")"; sky.appendChild(s); }
  renderStore();
}

/* ---------- STORE (Telegram Stars) ---------- */
function renderStore(){ const s=STATE; if(!s) return;
  document.getElementById("starBal").textContent=s.payments_live?"pay with Stars":(s.stars_demo+" \u2b50 demo");
  const box=document.getElementById("store"); box.innerHTML="";
  (s.store||[]).forEach(it=>{
    const owned=(it.kind==="cosmetic_user"&&s.supporter);
    const row=document.createElement("div"); row.className="store-item";
    row.innerHTML=`<div class="s-i">${it.icon||"\u2b50"}</div><div class="s-b"><b>${esc(it.title)}</b><span>${esc(it.desc)}</span></div>`;
    const b=document.createElement("button"); b.className="buy"+(owned?" owned":"");
    b.textContent=owned?"Owned":(it.stars+" \u2b50"); if(!owned) b.onclick=()=>buy(it);
    row.appendChild(b); box.appendChild(row);
  });
}
async function buy(it){ haptic("medium");
  if(it.kind==="cosmetic_tribe"){ pickCrest(it); return; }
  await purchase(it,"");
}
function pickCrest(it){ const opts=[0x1F43A,0x1F981,0x1F43B,0x1F98C,0x1FAB6,0x1F989,0x1F42E,0x1F406].map(EMO);
  let sel=opts[0];
  const html=`<div class="emoji-pick">${opts.map((e,i)=>`<button data-e="${e}" class="${i===0?"sel":""}">${e}</button>`).join("")}</div><button class="cta" id="crestBuy">Buy for ${it.stars} \u2b50</button>`;
  openSheet("Choose your tribe crest",html,()=>{
    document.querySelectorAll("#sheetBody .emoji-pick button").forEach(b=>b.onclick=()=>{
      document.querySelectorAll("#sheetBody .emoji-pick button").forEach(x=>x.classList.remove("sel")); b.classList.add("sel"); sel=b.dataset.e; });
    document.getElementById("crestBuy").onclick=async()=>{ closeSheet(); await purchase(it,sel); };
  });
}
async function purchase(it,value){
  if(STATE && STATE.payments_live){
    // real Telegram Stars invoice
    const r=await api("/api/store/invoice","POST",{item:it.id,value});
    if(r.ok && r.invoice_link && tg && tg.openInvoice){
      tg.openInvoice(r.invoice_link, status=>{ if(status==="paid"){ toast("\u2b50 Purchased!"); setTimeout(()=>{refresh(); renderStore();},1200); } else if(status==="failed"){ toast("Payment failed"); } });
    } else { toast("Could not start payment"); }
  } else {
    const r=await api("/api/store/buy_demo","POST",{item:it.id,value});
    if(r.ok){ STATE=r; toast("\u2b50 Purchased (demo)"); renderStore(); renderHome(); } else { toast("Not enough demo Stars"); }
  }
}

/* ---------- CLAIM + TON Connect ---------- */
let tonUI=null;
async function loadClaim(){
  const d=await api("/api/claim");
  document.getElementById("claimShare").textContent=(d.allocation?d.allocation.share_pct:0)+"%";
  const ws=document.getElementById("walletState");
  ws.textContent=d.wallet?("Bound: "+d.wallet):"No wallet bound yet.";
  initTon();
}
function initTon(){
  if(tonUI || !window.TON_CONNECT_UI) { if(!window.TON_CONNECT_UI){ document.getElementById("tonBtn").innerHTML='<p class="muted">TON Connect unavailable offline.</p>'; } return; }
  try{
    tonUI=new TON_CONNECT_UI.TonConnectUI({ manifestUrl: location.origin+"/tonconnect-manifest.json", buttonRootId:"tonBtn" });
    tonUI.onStatusChange(async w=>{
      if(w && w.account){ await api("/api/wallet","POST",{address:w.account.address}); document.getElementById("walletState").textContent="Bound: "+w.account.address; toast("Wallet bound \u2705"); refresh(); }
      else { await api("/api/wallet","POST",{address:""}); document.getElementById("walletState").textContent="No wallet bound yet."; }
    });
  }catch(e){ document.getElementById("tonBtn").innerHTML='<p class="muted">TON Connect failed to load.</p>'; }
}

/* ---------- sheet ---------- */
function openSheet(title,body,after){ document.getElementById("sheetTitle").textContent=title;
  document.getElementById("sheetBody").innerHTML=body; document.getElementById("sheet").classList.add("show");
  if(after) after(); }
function closeSheet(){ document.getElementById("sheet").classList.remove("show"); }
document.getElementById("sheetClose").addEventListener("click",closeSheet);
document.getElementById("sheet").addEventListener("click",e=>{ if(e.target.id==="sheet") closeSheet(); });

/* ---------- boot ---------- */
refresh().then(()=>{ if(STATE && STATE.dev_mode){ const n=document.createElement("div"); n.className="dev-note"; n.textContent="DEV MODE \u2014 demo data (set BOT_TOKEN for production)"; document.body.appendChild(n); } });
