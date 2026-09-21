/* TRIBES v2 - Telegram Mini App frontend */
const tg = window.Telegram && window.Telegram.WebApp;
if (tg) { try { tg.ready(); tg.expand(); tg.setHeaderColor && tg.setHeaderColor('#0b0a10'); } catch(e){} }
const START_PARAM = (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param) || '';
const INIT = (tg && tg.initData) ? tg.initData
  : ('user_id=dev-' + Math.floor(Math.random()*9000+1000) + '&first_name=Explorer');

let STATE = null;

function hdrs(){ return { 'Content-Type':'application/json', 'X-Init-Data': INIT }; }
async function api(path, method, body){
  const opt = { method: method||'GET', headers: hdrs() };
  if (method === 'POST') opt.body = JSON.stringify(Object.assign({ initData: INIT }, body||{}));
  const r = await fetch(path, opt);
  let data = {}; try { data = await r.json(); } catch(e){}
  if (!r.ok) throw new Error(data.detail || ('error ' + r.status));
  return data;
}
function haptic(t){ try{ tg.HapticFeedback.impactOccurred(t||'light'); }catch(e){} }
function toast(msg){
  const el = document.getElementById('toast');
  el.textContent = msg; el.classList.add('show');
  clearTimeout(el._t); el._t = setTimeout(()=>el.classList.remove('show'), 2200);
}
function esc(s){ return String(s==null?'':s).replace(/[&<>\"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c])); }
function fmt(n){ n=Number(n||0); return n>=1000? (n/1000).toFixed(n%1000?1:0)+'k' : ''+n; }
function ic(id, cls){ return '<svg class="'+(cls||'')+'"><use href="#'+id+'"/></svg>'; }
const ART = {ward:'ic-ward',eternal:'ic-ward',crest:'ic-crest',warpaint:'ic-warpaint',
  rekindle:'ic-rekindle',cache:'ic-cache',relic:'ic-relic',star:'ic-star'};
function artIcon(a){ return ic(ART[a]||'ic-relic','art floaty'); }
const RANKIC = {ashborn:'ic-flame',emberkin:'ic-flame',flamewarden:'ic-crest',pyrarch:'ic-rank',firstflame:'ic-rank'};
function rankBadge(rk){
  if(!rk) return '';
  return '<span class="rank '+esc(rk.id)+'">'+ic(RANKIC[rk.id]||'ic-rank')+esc(rk.name)+'</span>';
}

/* ---------- ember particle canvas ---------- */
(function(){
  const cv = document.getElementById('embers'), cx = cv.getContext('2d');
  let W,H,parts=[];
  function size(){ W=cv.width=innerWidth; H=cv.height=innerHeight; }
  size(); addEventListener('resize', size);
  function spawn(){ return {x:Math.random()*W, y:H+10, r:Math.random()*2.4+0.6,
    vy:-(Math.random()*0.7+0.25), vx:(Math.random()-0.5)*0.4, a:Math.random()*0.6+0.2, life:0}; }
  for(let i=0;i<48;i++){ const p=spawn(); p.y=Math.random()*H; parts.push(p); }
  function tick(){
    cx.clearRect(0,0,W,H);
    const frost = document.body.getAttribute('data-age')==='frost';
    for(const p of parts){
      p.y+=p.vy; p.x+=p.vx; p.life+=0.01;
      if(p.y< -10){ Object.assign(p, spawn()); }
      const col = frost? '200,235,255' : '255,'+(140+Math.floor(Math.random()*60))+',60';
      cx.beginPath(); cx.arc(p.x,p.y,p.r,0,7); 
      cx.fillStyle='rgba('+col+','+(p.a*(0.6+0.4*Math.sin(p.life*3)))+')'; cx.fill();
    }
    requestAnimationFrame(tick);
  }
  tick();
})();

/* ---------- routing ---------- */
let TAB = 'home';
document.getElementById('tabs').addEventListener('click', e=>{
  const b = e.target.closest('button'); if(!b) return;
  document.querySelectorAll('#tabs button').forEach(x=>x.classList.remove('active'));
  b.classList.add('active'); TAB = b.dataset.tab; haptic();
  render();
});

function applyState(s){
  STATE = s;
  const age = s.age||{};
  document.body.setAttribute('data-age', age.id||'fire');
  document.getElementById('ageChip').textContent = age.name||'Age of First Fire';
  document.getElementById('forgeTab').hidden = !(s.user && s.user.is_admin);
}

/* ---------- boot + refresh ---------- */
async function boot(){
  try{
    const s = await api('/api/start','POST',{start_param:START_PARAM});
    applyState(s); render();
  }catch(e){
    document.getElementById('view').innerHTML =
      '<div class="empty">Could not reach the fire.<br><small>'+esc(e.message)+'</small></div>';
  }
}
async function refresh(){ const s = await api('/api/state'); applyState(s); render(); }
async function act(fn){ try{ await fn(); }catch(e){ toast(e.message); } }

/* ---------- render dispatch ---------- */
function render(){
  if(!STATE) return;
  const v = document.getElementById('view');
  if(TAB==='home'){ v.innerHTML = renderHome(); bindHome(); }
  else if(TAB==='tribe'){ v.innerHTML='<div class="loader">\u2026</div>'; renderTribe(v); }
  else if(TAB==='lands'){ v.innerHTML='<div class="loader">\u2026</div>'; renderLands(v); }
  else if(TAB==='store'){ v.innerHTML='<div class="loader">\u2026</div>'; renderStore(v); }
  else if(TAB==='bag'){ v.innerHTML='<div class="loader">\u2026</div>'; renderBag(v); }
  else if(TAB==='forge'){ v.innerHTML='<div class="loader">\u2026</div>'; renderForge(v); }
}

/* ---------- HOME (the Fire) ---------- */
function renderHome(){
  const u = STATE.user, t = STATE.tribe, tasks = STATE.tasks||[];
  const stateLabel = {active:'Your fire burns bright',cooling:'Your fire is cooling',fading:'Your fire is fading'}[u.state]||'';
  let h = '';
  h += '<div class="hero card">'+
    '<svg class="bigflame"><use href="#ic-flame"/></svg>'+
    '<div class="name">'+esc(u.name)+(u.title?' <span class="chip best">'+esc(u.title)+'</span>':'')+'</div>'+
    '<div class="state">'+esc(stateLabel)+(u.rank?' \u00b7 #'+u.rank.position+' in tribe':'')+'</div>'+
    (u.rank?'<div style="margin-top:8px">'+rankBadge(u.rank)+'</div>':'')+
    '<div class="stat-row">'+
      '<div class="stat"><div class="v">'+u.streak+'</div><div class="l">Day Streak</div></div>'+
      '<div class="stat"><div class="v">'+fmt(u.kindle)+'</div><div class="l">Kindle</div></div>'+
      '<div class="stat"><div class="v">'+fmt(u.ember)+'</div><div class="l">Ember</div></div>'+
    '</div>'+
    '<div class="bar" style="margin-top:14px"><i style="width:'+Math.min(100,u.streak/30*100)+'%"></i></div>'+
    '<div class="mini">Kindle Score feeds your tribe Loyalty and sets your rank.</div>'+
    '<button class="btn" id="checkinBtn" style="margin-top:12px">'+ic('ic-flame')+'Tend the Campfire</button>'+
  '</div>';
  if(t){
    h += '<div class="card" data-go="tribe" style="cursor:pointer">'+
      '<h2>'+esc(t.name)+' <span class="chip">'+esc(t.stage)+'</span></h2>'+
      '<div class="sub">Shared Loyalty pool \u2014 the whole tribe rises together</div>'+
      '<div class="stat-row">'+
        '<div class="stat"><div class="v">'+fmt(t.loyalty)+'</div><div class="l">Loyalty</div></div>'+
        '<div class="stat"><div class="v">'+t.members+'</div><div class="l">Kin</div></div>'+
        '<div class="stat"><div class="v">'+fmt(t.embertide)+'</div><div class="l">Embertide</div></div>'+
      '</div>'+
      (t.fading? '<div class="mini" style="margin-top:8px;color:var(--fire)">'+t.fading+' kin fading \u2014 Ashfall bleeds Loyalty. Rekindle them in Tribe.</div>':'')+
    '</div>';
  } else {
    h += '<div class="card"><h2>You walk alone</h2>'+
      '<div class="sub">Wanderers earn Ember but no Loyalty, rank or land. Join or found a tribe.</div>'+
      '<button class="btn teal small" data-go="tribe">Find or found a tribe</button></div>';
  }
  h += '<div class="section-title">'+ic('ic-relic')+'Daily Rites</div>';
  h += '<div class="card"><div class="kin"><div class="avatar">'+ic('ic-relic')+'</div>'+
    '<div class="who"><div class="nm">Seek a Relic</div><div class="meta">A shard for your Satchel + Ember</div></div>'+
    '<button class="btn small teal" id="relicBtn">Seek</button></div>';
  for(const tk of tasks){
    h += '<div class="kin"><div class="pos">'+(tk.complete?'\u2713':'\u00b7')+'</div>'+
      '<div class="who"><div class="nm">'+esc(tk.title)+'</div><div class="meta">'+esc(tk.hint)+' \u00b7 +'+tk.reward+' Ember</div></div>'+
      (tk.complete?'<span class="chip">done</span>':'<button class="btn small" data-task="'+esc(tk.id)+'">Do</button>')+'</div>';
  }
  h += '</div>';
  h += '<div class="section-title">'+ic('ic-referral')+'Bloodline</div>';
  h += '<div class="card"><div class="sub">Invite kin \u2014 '+STATE.referral.count+' have answered your call.</div>'+
    '<button class="btn ghost small" id="inviteBtn">'+ic('ic-referral')+'Share invite link</button></div>';
  return h;
}

function bindHome(){
  const v = document.getElementById('view');
  v.querySelectorAll('[data-go]').forEach(el=>el.onclick=()=>{
    TAB=el.dataset.go;
    document.querySelectorAll('#tabs button').forEach(x=>x.classList.toggle('active',x.dataset.tab===TAB));
    render();
  });
  const cb=v.querySelector('#checkinBtn'); if(cb) cb.onclick=()=>act(async()=>{
    cb.disabled=true; const r=await api('/api/checkin','POST');
    haptic('medium'); toast(r.already?'Already tended today':'The fire grows. +Kindle');
    applyState(r); render();
  });
  const rb=v.querySelector('#relicBtn'); if(rb) rb.onclick=()=>act(async()=>{
    const r=await api('/api/relic/find','POST'); toast(r.already?'No relic today':'Relic found!'); applyState(r); render();
  });
  v.querySelectorAll('[data-task]').forEach(b=>b.onclick=()=>act(async()=>{
    const r=await api('/api/tasks/complete','POST',{task_id:b.dataset.task});
    toast(r.already?'Already done':'Rite complete'); applyState(r); render();
  }));
  const ib=v.querySelector('#inviteBtn'); if(ib) ib.onclick=()=>{
    const link=STATE.referral.link;
    const share='https://t.me/share/url?url='+encodeURIComponent(link)+'&text='+encodeURIComponent('Join my tribe in Tribes. We rise together.');
    if(tg&&tg.openTelegramLink) tg.openTelegramLink(share); else { navigator.clipboard&&navigator.clipboard.writeText(link); toast('Invite link copied'); }
  };
}

/* ---------- TRIBE ---------- */
async function renderTribe(v){
  const d = await api('/api/tribe');
  if(!d.tribe){ renderNoTribe(v); return; }
  const t=d.tribe, roster=d.roster||[], fading=d.fading||[], isChief=d.is_chief;
  const pct = t.next_cost? Math.min(100, t.loyalty/t.next_cost*100) : 100;
  let h='';
  h += '<div class="card tribe-head">'+
    '<div class="crest">'+ic('ic-crest')+'</div>'+
    '<h2>'+esc(t.name)+' <span class="chip">'+esc(t.stage)+'</span></h2>'+
    (t.war_cry?'<div class="warcry">\u201c'+esc(t.war_cry)+'\u201d</div>':'')+
    '<div class="stat-row">'+
      '<div class="stat"><div class="v">'+fmt(t.loyalty)+'</div><div class="l">Loyalty</div></div>'+
      '<div class="stat"><div class="v">'+t.members+'/'+t.max_members+'</div><div class="l">Kin</div></div>'+
      '<div class="stat"><div class="v">'+fmt(t.embertide)+'</div><div class="l">Embertide</div></div>'+
    '</div>'+
    '<div class="pips"><span class="pip active">'+t.active+' active</span>'+
      '<span class="pip cool">'+t.cooling+' cooling</span>'+
      '<span class="pip fade">'+t.fading+' fading</span></div>';
  if(t.next_stage){
    h+='<div class="upgrade"><div class="mini">Next: '+esc(t.next_stage)+' \u00b7 '+fmt(t.next_cost)+' Loyalty</div>'+
      '<div class="bar"><i style="width:'+pct+'%"></i></div>'+
      (isChief?'<button class="btn small" id="upgradeBtn"'+(t.loyalty<t.next_cost?' disabled':'')+'>Advance the tribe</button>':'')+'</div>';
  }
  h+='<div class="row2" style="margin-top:10px">'+
    (isChief?'<button class="btn ghost small" id="warcryBtn">Set war cry</button>':'')+
    '<button class="btn ghost small danger" id="leaveBtn">Leave tribe</button></div>';
  h+='</div>';

  if(fading.length){
    h+='<div class="section-title">'+ic('ic-rekindle')+'Fading kin \u2014 Rekindle them</div><div class="card">';
    for(const f of fading){
      h+='<div class="kin"><div class="avatar fade">'+ic('ic-flame')+'</div>'+
        '<div class="who"><div class="nm">'+esc(f.name)+'</div><div class="meta">idle '+f.idle_days+'d \u00b7 '+fmt(f.kindle)+' Kindle bleeding Ashfall</div></div>'+
        '<button class="btn small teal" data-rekindle="'+esc(f.user_id)+'">Rekindle</button></div>';
    }
    h+='</div>';
  }

  h+='<div class="section-title">'+ic('ic-rank')+'Ranks by effort</div><div class="card">';
  for(const m of roster){
    h+='<div class="kin"><div class="pos">'+m.position+'</div>'+
      '<div class="avatar '+esc(m.state)+'">'+ic('ic-flame')+'</div>'+
      '<div class="who"><div class="nm">'+esc(m.name)+(m.user_id===STATE.user.id?' <span class="chip">you</span>':'')+'</div>'+
      '<div class="meta">'+rankBadge(m.rank)+' \u00b7 '+fmt(m.kindle)+' Kindle</div></div>'+
      '<div class="pip '+(m.state==='active'?'active':m.state==='cooling'?'cool':'fade')+'">'+esc(m.state)+'</div></div>';
  }
  h+='</div>';
  v.innerHTML=h;
  bindTribe(v, isChief);
}

function bindTribe(v, isChief){
  const up=v.querySelector('#upgradeBtn'); if(up) up.onclick=()=>act(async()=>{
    const r=await api('/api/tribe/upgrade','POST'); toast('The tribe advances!'); applyState(r); render();
  });
  const wc=v.querySelector('#warcryBtn'); if(wc) wc.onclick=()=>{
    const txt=prompt('War cry (max 80 chars):'); if(txt==null) return;
    act(async()=>{ const r=await api('/api/tribe/warcry','POST',{text:txt}); toast('War cry set'); applyState(r); render(); });
  };
  const lv=v.querySelector('#leaveBtn'); if(lv) lv.onclick=()=>{
    if(!confirm('Leave your tribe? You become a Wanderer.')) return;
    act(async()=>{ const r=await api('/api/tribe/leave','POST'); toast('You walk alone now'); applyState(r); render(); });
  };
  v.querySelectorAll('[data-rekindle]').forEach(b=>b.onclick=()=>act(async()=>{
    if(STATE.dev_mode){
      const r=await api('/api/rekindle','POST',{user_id:b.dataset.rekindle});
      haptic('medium'); toast('Kin rekindled \u2014 their fire returns'); applyState(r); render();
    } else {
      const inv=await api('/api/store/invoice','POST',{item_id:'rekindle_token',target:b.dataset.rekindle});
      if(tg&&tg.openInvoice) tg.openInvoice(inv.invoice_link,()=>refresh()); else toast('Open in Telegram to pay');
    }
  }));
}

/* ---------- NO TRIBE: found or join ---------- */
async function renderNoTribe(v){
  const d = await api('/api/tribes');
  const tribes = d.tribes||[];
  let h='<div class="card"><h2>Found your own tribe</h2>'+
    '<div class="sub">Become chief. Your first fire seeds the tribe Loyalty.</div>'+
    '<input id="tname" class="inp" maxlength="32" placeholder="Name your tribe" />'+
    '<button class="btn" id="foundBtn" style="margin-top:10px">'+ic('ic-crest')+'Found the tribe</button></div>';
  h+='<div class="section-title">'+ic('ic-rank')+'Join an existing tribe</div><div class="card">';
  if(!tribes.length) h+='<div class="empty">No tribes yet \u2014 be the first.</div>';
  for(const t of tribes){
    h+='<div class="kin"><div class="avatar">'+ic('ic-crest')+'</div>'+
      '<div class="who"><div class="nm">'+esc(t.name)+'</div><div class="meta">'+fmt(t.loyalty_earned)+' Loyalty \u00b7 '+t.members+'/'+t.max_members+' kin</div></div>'+
      '<button class="btn small teal" data-join="'+esc(t.tribe_id)+'"'+(t.members>=t.max_members?' disabled':'')+'>'+(t.members>=t.max_members?'Full':'Join')+'</button></div>';
  }
  h+='</div>';
  v.innerHTML=h;
  const fb=v.querySelector('#foundBtn'); fb.onclick=()=>{
    const nm=v.querySelector('#tname').value.trim(); if(!nm){ toast('Name your tribe first'); return; }
    act(async()=>{ const r=await api('/api/tribe/found','POST',{name:nm}); haptic('medium'); toast('Your tribe is born'); applyState(r); render(); });
  };
  v.querySelectorAll('[data-join]').forEach(b=>b.onclick=()=>act(async()=>{
    const r=await api('/api/tribe/join','POST',{tribe_id:b.dataset.join}); toast('You joined the tribe'); applyState(r); render();
  }));
}

/* ---------- LANDS ---------- */
async function renderLands(v){
  const d = await api('/api/lands');
  const lands=d.lands||[], mine=d.my_tribe;
  let h='<div class="card"><h2>The Lands</h2><div class="sub">Stake Embertide to claim ground. Held land feeds your tribe Loyalty daily. Invade rivals to seize theirs.</div></div>';
  h+='<div class="lands">';
  for(const l of lands){
    const held=!!l.owner, ours=l.owner===mine;
    const cls = ours?'ours':(held?'enemy':'wild');
    h+='<div class="land '+cls+'">'+
      '<div class="land-ic">'+ic('ic-land')+'</div>'+
      '<div class="land-nm">'+esc(l.name)+'</div>'+
      '<div class="land-meta">'+(held?esc(l.owner_name)+' \u00b7 '+fmt(l.staked)+' staked':'Unclaimed')+'</div>'+
      (l.contested?'<div class="chip best">Contested \u00b7 '+fmt(l.attacker_staked)+' vs '+fmt(l.staked)+'</div>':'')+
      '<div class="land-act">'+
        (!mine?'<span class="mini">join a tribe</span>':
          ours?'<button class="btn small" data-stake="'+esc(l.land_id)+'">Reinforce</button>':
          held?'<button class="btn small danger" data-invade="'+esc(l.land_id)+'">Invade</button>':
          '<button class="btn small teal" data-stake="'+esc(l.land_id)+'">Claim</button>')+
      '</div></div>';
  }
  h+='</div>';
  v.innerHTML=h;
  const doStake=(lid,inv)=>{
    const amt=parseInt(prompt((inv?'Invade with how much':'Stake how much')+' Embertide?'),10);
    if(!amt||amt<=0) return;
    act(async()=>{ const r=await api(inv?'/api/lands/invade':'/api/lands/stake','POST',{land_id:lid,amount:amt});
      haptic('medium'); toast(inv?'Invasion launched':'Ground staked'); applyState(r); render(); });
  };
  v.querySelectorAll('[data-stake]').forEach(b=>b.onclick=()=>doStake(b.dataset.stake,false));
  v.querySelectorAll('[data-invade]').forEach(b=>b.onclick=()=>doStake(b.dataset.invade,true));
}

/* ---------- STORE ---------- */
async function renderStore(v){
  const d = await api('/api/store');
  const sections=d.sections||[], items=d.items||[], live=d.payments_live;
  let h='<div class="card"><h2>The Trading Post</h2>'+
    '<div class="sub">Everything here is cosmetic, convenience or kinship \u2014 never Loyalty, rank, land or allocation. The airdrop stays fair.</div>'+
    '<div class="chip">Ash Wards held: '+d.wards+'</div>'+
    (live?'':'<div class="chip best" style="margin-top:6px">Demo mode \u2014 purchases are free to test</div>')+'</div>';
  for(const s of sections){
    const its=items.filter(i=>i.section===s.id);
    if(!its.length) continue;
    h+='<div class="section-title">'+esc(s.title)+'</div>';
    if(s.blurb) h+='<div class="mini" style="margin:-4px 4px 8px">'+esc(s.blurb)+'</div>';
    h+='<div class="card">';
    for(const i of its){
      h+='<div class="kin"><div class="avatar">'+artIcon(i.art)+'</div>'+
        '<div class="who"><div class="nm">'+esc(i.title)+'</div><div class="meta">'+esc(i.desc||'')+'</div></div>'+
        '<button class="btn small" data-buy="'+esc(i.id)+'">'+ic('ic-star')+i.stars+'</button></div>';
    }
    h+='</div>';
  }
  v.innerHTML=h;
  v.querySelectorAll('[data-buy]').forEach(b=>b.onclick=()=>act(async()=>{
    const id=b.dataset.buy;
    if(STATE.dev_mode){
      const r=await api('/api/store/buy_demo','POST',{item_id:id}); haptic('medium'); toast('Granted (demo)'); applyState(r); render();
    } else {
      const inv=await api('/api/store/invoice','POST',{item_id:id});
      if(tg&&tg.openInvoice) tg.openInvoice(inv.invoice_link,st=>{ if(st==='paid'){ toast('Thank you!'); refresh(); } });
      else toast('Open in Telegram to pay with Stars');
    }
  }));
}

/* ---------- BAG: Satchel + Tribe Cache + Bloodline + Wallet ---------- */
async function renderBag(v){
  const [inv, blood] = await Promise.all([api('/api/inventory'), api('/api/bloodline')]);
  let h='<div class="section-title">'+ic('ic-cache')+'Your Satchel</div><div class="card">';
  h+='<div class="kin"><div class="avatar">'+ic('ic-ward')+'</div><div class="who"><div class="nm">Ash Wards</div>'+
    '<div class="meta">Auto-save a missed day</div></div><div class="chip">x'+inv.wards+'</div></div>';
  if(!(inv.satchel||[]).length && !inv.wards) h+='<div class="empty">Empty \u2014 seek relics and complete rites.</div>';
  for(const it of (inv.satchel||[])){
    h+='<div class="kin"><div class="avatar">'+artIcon(it.art)+'</div>'+
      '<div class="who"><div class="nm">'+esc(it.title)+'</div><div class="meta">'+esc(it.desc||'')+'</div></div>'+
      '<div class="chip">x'+it.qty+'</div></div>';
  }
  h+='</div>';
  if((inv.tribe_cache||[]).length){
    h+='<div class="section-title">'+ic('ic-cache')+'Tribe Cache</div><div class="card">';
    for(const it of inv.tribe_cache){
      h+='<div class="kin"><div class="avatar">'+artIcon(it.art)+'</div>'+
        '<div class="who"><div class="nm">'+esc(it.title)+'</div><div class="meta">'+esc(it.desc||'')+'</div></div>'+
        '<div class="chip">x'+it.qty+'</div></div>';
    }
    h+='</div>';
  }
  h+='<div class="section-title">'+ic('ic-referral')+'Bloodline \u00b7 '+blood.count+'</div><div class="card">';
  h+='<button class="btn ghost small" id="inviteBtn2">'+ic('ic-referral')+'Share invite link</button>';
  if(!(blood.bloodline||[]).length) h+='<div class="empty">No kin yet. Invite explorers to grow your line.</div>';
  for(const b of (blood.bloodline||[])){
    h+='<div class="kin"><div class="avatar">'+ic('ic-flame')+'</div>'+
      '<div class="who"><div class="nm">'+esc(b.name||'Explorer')+'</div>'+
      '<div class="meta">'+(b.joined_tribe?'joined a tribe':'answered your call')+'</div></div></div>';
  }
  h+='</div>';
  h+='<div class="section-title">'+ic('ic-relic')+'Wallet</div><div class="card">'+
    '<div class="sub">Link a wallet for the future airdrop claim.</div>'+
    '<input id="waddr" class="inp" maxlength="80" placeholder="Wallet address" value="'+esc(STATE.user.wallet||'')+'" />'+
    '<button class="btn small" id="walletBtn" style="margin-top:10px">Save wallet</button></div>';
  v.innerHTML=h;
  const ib=v.querySelector('#inviteBtn2'); ib.onclick=()=>{
    const link=STATE.referral.link;
    const share='https://t.me/share/url?url='+encodeURIComponent(link)+'&text='+encodeURIComponent('Join my tribe in Tribes.');
    if(tg&&tg.openTelegramLink) tg.openTelegramLink(share); else { navigator.clipboard&&navigator.clipboard.writeText(link); toast('Invite link copied'); }
  };
  v.querySelector('#walletBtn').onclick=()=>act(async()=>{
    const a=v.querySelector('#waddr').value.trim();
    const r=await api('/api/wallet','POST',{address:a}); toast('Wallet saved'); applyState(r); render();
  });
}

/* ---------- FORGE: Elders' admin panel ---------- */
async function renderForge(v){
  let d;
  try{ d = await api('/api/admin/config'); }
  catch(e){ v.innerHTML='<div class="empty">Elders only.</div>'; return; }
  const c=d.config||{}, ages=(c.age&&c.age.ages)||{}, cur=(c.age&&c.age.current)||'fire';
  const tasks=c.tasks||[], items=(c.store&&c.store.items)||[];
  let h='<div class="card"><h2>'+ic('ic-rank')+'Elders\u2019 Forge</h2>'+
    '<div class="sub">Tune the world live. Every change persists.</div></div>';
  // Ages
  h+='<div class="section-title">Ages</div><div class="card"><div class="row2">';
  for(const id of Object.keys(ages)){
    h+='<button class="btn small '+(id===cur?'':'ghost')+'" data-age="'+esc(id)+'">'+esc(ages[id].name||id)+(id===cur?' \u2713':'')+'</button>';
  }
  h+='</div><button class="btn ghost small danger" id="ashNow" style="margin-top:10px">Run Ashfall now</button></div>';
  // Bot username
  h+='<div class="section-title">Referral bot</div><div class="card">'+
    '<div class="sub">Set the bot username so invite links resolve.</div>'+
    '<input id="botu" class="inp" placeholder="YourBot (no @)" value="'+esc(d.bot_username||'')+'" />'+
    '<button class="btn small" id="botuBtn" style="margin-top:10px">Save</button></div>';
  // Grant
  h+='<div class="section-title">Grant / adjust</div><div class="card">'+
    '<div class="sub">Tribe: id + Loyalty/Embertide. Kin: user_id + Kindle/Ember.</div>'+
    '<input id="gT" class="inp" placeholder="tribe_id (optional)" />'+
    '<div class="row2"><input id="gL" class="inp" placeholder="+/- Loyalty" /><input id="gE" class="inp" placeholder="+/- Embertide" /></div>'+
    '<input id="gU" class="inp" placeholder="user_id (optional)" style="margin-top:8px" />'+
    '<div class="row2"><input id="gK" class="inp" placeholder="+/- Kindle" /><input id="gEm" class="inp" placeholder="+/- Ember" /></div>'+
    '<button class="btn small" id="grantBtn" style="margin-top:10px">Apply</button></div>';
  // Quests
  h+='<div class="section-title">Quests</div><div class="card">';
  for(const t of tasks){
    h+='<div class="kin"><div class="who"><div class="nm">'+esc(t.title)+'</div>'+
      '<div class="meta">'+esc(t.id)+' \u00b7 +'+(t.reward||0)+' Ember</div></div>'+
      '<button class="btn ghost small danger" data-taskdel="'+esc(t.id)+'">Remove</button></div>';
  }
  h+='<div class="row2" style="margin-top:8px"><input id="qId" class="inp" placeholder="id" /><input id="qTitle" class="inp" placeholder="title" /></div>'+
    '<div class="row2"><input id="qHint" class="inp" placeholder="hint" /><input id="qReward" class="inp" placeholder="reward Ember" /></div>'+
    '<button class="btn small" id="qAdd" style="margin-top:8px">Add / update quest</button></div>';
  // Store
  h+='<div class="section-title">Store items & Star prices</div><div class="card">';
  for(const i of items){
    h+='<div class="kin"><div class="who"><div class="nm">'+esc(i.title)+'</div>'+
      '<div class="meta">'+esc(i.id)+' \u00b7 '+ic('ic-star')+i.stars+'</div></div>'+
      '<button class="btn ghost small danger" data-storedel="'+esc(i.id)+'">Remove</button></div>';
  }
  h+='<div class="row2" style="margin-top:8px"><input id="sId" class="inp" placeholder="id" /><input id="sTitle" class="inp" placeholder="title" /></div>'+
    '<div class="row2"><input id="sStars" class="inp" placeholder="Stars price" /><input id="sSection" class="inp" placeholder="section (wards/kinship/identity/bundles)" /></div>'+
    '<input id="sDesc" class="inp" placeholder="description" style="margin-top:8px" />'+
    '<input id="sKind" class="inp" placeholder="kind (freeze/cosmetic_user/cosmetic_tribe/rekindle/bundle)" style="margin-top:8px" />'+
    '<button class="btn small" id="sAdd" style="margin-top:8px">Add / update item</button></div>';
  v.innerHTML=h;
  bindForge(v);
}

function bindForge(v){
  const val=id=>{ const e=v.querySelector(id); return e?e.value.trim():''; };
  v.querySelectorAll('[data-age]').forEach(b=>b.onclick=()=>act(async()=>{
    await api('/api/admin/age','POST',{age:b.dataset.age}); toast('Age changed'); await refresh();
  }));
  v.querySelector('#ashNow').onclick=()=>act(async()=>{ const r=await api('/api/admin/ashfall','POST'); toast('Ashfall ran ('+((r.changed||[]).length)+' tribes hit)'); });
  v.querySelector('#botuBtn').onclick=()=>act(async()=>{ await api('/api/admin/bot_username','POST',{bot_username:val('#botu')}); toast('Bot username saved'); });
  v.querySelector('#grantBtn').onclick=()=>act(async()=>{
    const body={};
    if(val('#gT')){ body.tribe_id=val('#gT'); if(val('#gL'))body.loyalty=parseInt(val('#gL'),10); if(val('#gE'))body.embertide=parseInt(val('#gE'),10); }
    if(val('#gU')){ body.user_id=val('#gU'); if(val('#gK'))body.kindle=parseInt(val('#gK'),10); if(val('#gEm'))body.ember=parseInt(val('#gEm'),10); }
    await api('/api/admin/grant','POST',body); toast('Applied'); await refresh();
  });
  v.querySelectorAll('[data-taskdel]').forEach(b=>b.onclick=()=>act(async()=>{ await api('/api/admin/tasks','POST',{op:'remove',id:b.dataset.taskdel}); toast('Quest removed'); await refresh(); }));
  v.querySelector('#qAdd').onclick=()=>act(async()=>{
    const t={id:val('#qId'),title:val('#qTitle'),hint:val('#qHint'),reward:parseInt(val('#qReward')||'0',10),kind:'quest',repeat:'weekly'};
    if(!t.id||!t.title){ toast('id + title needed'); return; }
    await api('/api/admin/tasks','POST',{op:'add',task:t}); toast('Quest saved'); await refresh();
  });
  v.querySelectorAll('[data-storedel]').forEach(b=>b.onclick=()=>act(async()=>{ await api('/api/admin/store','POST',{op:'remove',id:b.dataset.storedel}); toast('Item removed'); await refresh(); }));
  v.querySelector('#sAdd').onclick=()=>act(async()=>{
    const i={id:val('#sId'),title:val('#sTitle'),stars:parseInt(val('#sStars')||'0',10),section:val('#sSection')||'wards',desc:val('#sDesc'),kind:val('#sKind')||'freeze',art:'relic'};
    if(!i.id||!i.title){ toast('id + title needed'); return; }
    await api('/api/admin/store','POST',{op:'add',item:i}); toast('Item saved'); await refresh();
  });
}

/* ---------- go ---------- */
boot();
