const $ = id => document.getElementById(id);
let items = [], selected = null, demo = false, csrf = '', rotating = false;
let browserToken = null, patrol = true, lastBrowserMint = null;
const browserBridgeEnabled = false; // paused after restoring the standalone Chrome scanner
const demoItems = [
  {mint:'demo-aurora',scanned_at:Date.now()/1000,price:{usd:'0.004821',fetched_at:Date.now()/1000},scan:{token_symbol:'AURORA',token_name:'Aurora',label:'WARN',risk_score:42,creator_position:{status:'holding'},verdict_summary:'Creator still holds their allocation. Keep watching.'}},
  {mint:'demo-toastcat',scanned_at:Date.now()/1000,price:{usd:'0.0000172',fetched_at:Date.now()/1000},scan:{token_symbol:'TOASTCAT',label:'DANGER',risk_score:75,creator_position:{status:'sold'},verdict_summary:'Example layout: creator exit warning, with evidence available in the full trace.'}},
  {mint:'demo-orbit',scanned_at:Date.now()/1000,price:{usd:'0.01234',fetched_at:Date.now()/1000},scan:{token_symbol:'ORBIT',label:'UNKNOWN',risk_score:null,creator_position:{status:'unknown'},verdict_summary:'No current verdict. Missing evidence stays visible.'}}
];
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function money(v){const n=Number(v);return v == null || !Number.isFinite(n) ? '—' : '$'+n.toLocaleString('en-US',{maximumSignificantDigits:5});}
function age(t){if(!t)return 'NOT AVAILABLE';const seconds=Math.max(0,Math.floor(Date.now()/1000-t));return seconds<60?`${seconds}s ago`:seconds<3600?`${Math.floor(seconds/60)}m ago`:`${Math.floor(seconds/3600)}h ago`;}
function kind(s){return ({DANGER:'danger',WARN:'warn',GOOD:'good'})[s.label]||'';}
function creator(s){return ({holding:'HOLDING',sold:'SOLD OUT',none:'NO POSITION'})[s.creator_position?.status]||'UNKNOWN';}
function list(){return demo?demoItems:items;}
function render(){
 const data=list(); if(!data.some(x=>x.mint===selected) && selected!==browserToken?.mint) selected=data[0]?.mint||null;
 $('patrol-toggle').textContent='PATROL: '+(patrol?'ON':'PAUSED');
 $('keep-browser').hidden=!browserBridgeEnabled || !browserToken || items.some(x=>x.mint===browserToken.mint);
 $('pair-browser').disabled=!browserBridgeEnabled;
 $('pair-browser').textContent=browserBridgeEnabled?'CONNECT CHROME':'CHROME LINK PAUSED';
 $('browser-name').textContent=!browserBridgeEnabled?'Chrome scanner restored':browserToken?(browserToken.scan.token_symbol||browserToken.scan.token_name||browserToken.mint.slice(0,8)):'Follow your Chrome token';
 $('browser-detail').textContent=!browserBridgeEnabled?'Use right-click → Scan with RugBuster. Desktop pairing is temporarily paused.':browserToken?`Last browser token · ${age(browserToken.seen_at)} · ${browserToken.mint}`:'Pair the RugBuster extension to preview tokens from supported pages.';
 $('count').textContent=String(data.length).padStart(2,'0'); $('list-mode').textContent=demo?'SAMPLE DATA':'ON THIS PC';
 $('demo').textContent=demo?'EXIT DESIGN DEMO':'VIEW DESIGN DEMO';
 $('tokens').innerHTML=data.length?data.map(x=>{const s=x.scan, symbol=s.token_symbol||s.token_name||x.mint.slice(0,6);return `<button class="token ${selected===x.mint?'selected':''}" data-mint="${esc(x.mint)}" aria-pressed="${selected===x.mint}"><span class="token-title"><span class="coin">${esc(symbol.slice(0,1))}</span><span><span class="symbol">${esc(symbol)}</span><span class="address">${demo?'DESIGN SAMPLE':esc(x.mint.slice(0,4)+'…'+x.mint.slice(-4))}</span></span></span><span class="price">${money(x.price?.usd)}<small>${x.price?(Date.now()/1000-x.price.fetched_at>120?'STALE · ':'')+age(x.price.fetched_at):'NO PRICE YET'}</small></span><span class="risk ${kind(s)}">${esc(s.risk_score??'—')}<small>${esc(s.label||'UNKNOWN')}</small></span><span class="status ${s.creator_position?.status==='sold'?'danger':''}">${creator(s)}</span></button>`;}).join(''):'<div class="empty"><b>Your desk starts here.</b><p>Paste a Solana mint above. Or open the design demo to preview the display and warning states.</p></div>';
 $('tokens').querySelectorAll('button').forEach(b=>b.onclick=()=>{selected=b.dataset.mint;render();});
 renderDisplay();
}
function renderDisplay(){
 const item=list().find(x=>x.mint===selected)||(!demo&&browserToken?.mint===selected?browserToken:null), s=item?.scan;
 renderHistory(item);
 $('lcd-mode').textContent=demo?'SAMPLE DATA':item?.preview?'BROWSER PREVIEW':'API SNAPSHOT';
 if(!s){$('lcd-name').textContent='NO TOKEN';$('lcd-price').innerHTML='—<small>USD</small>';$('lcd-risk').innerHTML='—<em>/ 100</em>';$('lcd-creator').textContent='WAITING';$('lcd-alert').textContent='Add a token to your desk';$('lcd-age').textContent='NO OBSERVATION';$('lcd').classList.remove('alert');$('trace-summary').textContent='Know what happened behind the ticker.';$('trace-name').textContent='SELECT A TOKEN';$('trace-detail').textContent='Select a token to see the last RugBuster finding and its observation time.';$('trace-time').textContent='—';$('trace-link').hidden=true;return;}
 const sold=s.creator_position?.status==='sold', danger=s.label==='DANGER';
 $('lcd').classList.toggle('alert',sold||danger);
 $('lcd-name').textContent=s.token_symbol||s.token_name||item.mint.slice(0,6);
 $('lcd-price').innerHTML=money(item.price?.usd)+'<small>USD</small>';
 $('lcd-risk').innerHTML=esc(s.risk_score??'—')+'<em>/ 100</em>';$('lcd-risk').className=kind(s);
 $('lcd-creator').textContent=creator(s);$('lcd-creator').className=sold?'danger':'';
 $('lcd-alert').textContent=sold?'CREATOR EXIT REPORTED':danger?'HIGH RISK':s.label==='UNKNOWN'?'UNKNOWN / CHECK INCOMPLETE':demo?'WATCHING THE CREATOR':item.preview?'PREVIEW / NOT UNDER PATROL':'CREATOR STATUS / LAST SCAN';
 const observed=s.observed_at?Date.parse(s.observed_at)/1000:null;
 $('lcd-age').textContent=demo?'SAMPLE · '+age(item.scanned_at):observed?'EVIDENCE · '+age(observed):'EVIDENCE UNDATED · RETRIEVED '+age(item.scanned_at);
 $('trace-name').textContent=(demo?'DESIGN SAMPLE / ':'')+(s.token_symbol||s.token_name||item.mint.slice(0,6));
 $('trace-summary').textContent=s.verdict_summary||s.note||'The API returned no summary. Open the full evidence.';
 $('trace-detail').textContent=demo?'Illustrative values only. This is a display preview, not a new scan or a live alert.':`Evidence: ${s.observed_at||'observation timestamp unavailable'}. Creator status: ${creator(s).toLowerCase()}. ${item.preview?'Browser preview. Save it to keep watching.':patrol?'API check every 5 minutes; responses may be cached.':'Patrol paused.'}`;
 $('trace-time').textContent=new Date(item.scanned_at*1000).toLocaleTimeString('en-GB');
 $('trace-link').hidden=demo;$('trace-link').href='https://rugbuster-solana-api-production.up.railway.app/shield?mint='+encodeURIComponent(item.mint);
 if(!demo&&!item.preview){const remove=document.createElement('button');remove.textContent='REMOVE TOKEN';remove.className='text-button remove';remove.onclick=async()=>{await mutate('/api/remove',{mint:item.mint});};$('trace-detail').append(document.createElement('br'),remove);}
}
function renderHistory(item){
 const b=item?.baseline,s=item?.scan;
 if(!b){$('baseline').textContent=demo?'Design sample — history starts when you track a real token.':'Select a tracked token to compare with its first saved finding.';$('events').replaceChildren();return;}
 const fields=[['RISK SCORE',b.scan.risk_score,s.risk_score],['RISK CATEGORY',b.scan.label,s.label],['CREATOR SHARE',b.scan.creator_position?.current_share_pct,s.creator_position?.current_share_pct]];
 $('baseline').innerHTML=fields.map(([title,a,c])=>`<div><small>${title}</small><strong>${esc(a??'UNKNOWN')} <span>→</span> ${esc(c??'UNKNOWN')}</strong></div>`).join('')+`<div><small>STARTED ON THIS PC</small><strong>${esc(new Date(b.started_at*1000).toLocaleString())}</strong></div>`;
 $('events').innerHTML=(item.events||[]).map(e=>`<div class="event"><time>${esc(new Date(e.retrieved_at*1000).toLocaleString())}</time><b>${esc(e.title)}</b><span>${esc(e.before)} → ${esc(e.after)}</span><small>Evidence: ${esc(e.observed_at||'timestamp unavailable')}</small></div>`).join('')||'<p>No changes detected in retrieved API findings yet.</p>';
}
async function load(){try{const response=await fetch('/api/dashboard');if(!response.ok)throw Error('Connection unavailable');const d=await response.json();items=d.items;csrf=d.token;patrol=d.patrol;browserToken=d.browser;$('pair-code').value=d.bridge_token;if(browserToken&&browserToken.mint!==lastBrowserMint){lastBrowserMint=browserToken.mint;if(!demo)selected=browserToken.mint;}if($('message').dataset.offline){$('message').textContent='';delete $('message').dataset.offline;}render();}catch(e){$('message').textContent='OFFLINE · showing the last saved data. Connection will retry.';$('message').dataset.offline='true';}}
async function mutate(path,body){$('track').disabled=true;$('message').textContent=path==='/api/track'?'Reading the RugBuster API…':'';try{const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Desk-Token':csrf},body:JSON.stringify(body)});const d=await response.json();if(!response.ok)throw Error(d.error||'Request failed');demo=false;await load();$('message').textContent=path==='/api/track'?'Saved on this PC. Phone synchronization is not connected yet.':'';return true;}catch(e){$('message').textContent=e.message;return false;}finally{$('track').disabled=false;}}
 $('track-form').onsubmit=async e=>{e.preventDefault();const mint=$('mint').value.trim();if(await mutate('/api/track',{mint})){$('mint').value='';selected=mint;render();}};
 $('demo').onclick=()=>{demo=!demo;selected=null;$('message').textContent='';render();};
 $('pair-browser').onclick=()=>{$('pairing').hidden=!$('pairing').hidden;};
 $('copy-code').onclick=async()=>{try{await navigator.clipboard.writeText($('pair-code').value);$('message').textContent='Pairing code copied. Paste it in the Chrome extension.';}catch(_){$('pair-code').select();$('message').textContent='Select and copy the pairing code.';}};
 $('keep-browser').onclick=async()=>{if(browserToken){const mint=browserToken.mint;if(await mutate('/api/track',{mint})){selected=mint;render();}}};
 $('patrol-toggle').onclick=()=>mutate('/api/patrol',{enabled:!patrol});
 $('rotate').onclick=()=>{rotating=!rotating;$('rotate').textContent='AUTO ROTATE: '+(rotating?'ON':'OFF');};
 setInterval(()=>{if(!rotating)return;const data=list();if(data.length){const warnings=data.filter(x=>x.scan.creator_position?.status==='sold'||x.scan.label==='DANGER');const cycle=warnings.length?warnings:data;selected=cycle[(cycle.findIndex(x=>x.mint===selected)+1)%cycle.length].mint;render();}},8000);
 setInterval(()=>{$('clock').textContent=new Date().toLocaleTimeString('en-GB');},1000);
 setInterval(()=>{load();},5000);load();

// Ask RugBuster: a docked research chat, one conversation per token
const chats = {};
const TOOL_NAMES = {wallet_activity:'wallet history', token_market:'market & links', search_tokens:'token search', rugbuster_scan:'RugBuster scan'};
const SUGGEST = ['Did the creator sell? Show the proof.', 'Who funded the creator?', 'What other tokens did the creator make?', 'Does the project have a website or X account?'];
let chatBusy = false;
function md(t){
 let h = esc(t);
 h = h.replace(/\[([^\]]{1,60})\]\((https:\/\/[^\s)]+)\)/g,(m,label,u)=>`<a href="${u}" target="_blank" rel="noopener">${label}</a>`);
 h = h.replace(/(^|[\s(])(https:\/\/[^\s<)]+)/g,(m,pre,u)=>`${pre}<a href="${u}" target="_blank" rel="noopener">${u.length>44?u.slice(0,42)+'…':u}</a>`);
 h = h.replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/`([^`]{1,90})`/g,'<code>$1</code>').replace(/^#{1,4} (.+)$/gm,'<b>$1</b>');
 return h;
}
function tokenLabel(){
 const it = list().find(x=>x.mint===selected); const s = it?.scan || {};
 return it ? `${s.token_symbol||s.token_name||selected.slice(0,6)} · ${selected.slice(0,4)}…${selected.slice(-4)}` : 'No token selected';
}
function drawChat(){
 const box = $('chat-list'); $('chat-token').textContent = tokenLabel();
 const chat = chats[selected] || [];
 if (!chat.length){
  box.innerHTML = `<div class="chat-empty"><b>Ask anything about this token.</b><br>The AI starts from the RugBuster scan and looks further on its own.${selected&&!String(selected).startsWith('demo-')?SUGGEST.map(s=>`<button type="button" data-suggest="${esc(s)}">${esc(s)}</button>`).join(''):'<br><br>Track a token first.'}</div>`;
  return;
 }
 box.innerHTML = chat.map(m=>`<div class="bubble ${m.role}${m.wait?' wait':''}">${m.role==='assistant'&&m.looked&&m.looked.length?`<small>looked at: ${[...new Set(m.looked)].map(x=>TOOL_NAMES[x]||x).join(' · ')}</small>`:''}${m.wait?'Researching…':md(m.content)}</div>`).join('');
 const toEnd=()=>{ box.scrollTop = box.scrollHeight; }; toEnd(); requestAnimationFrame(toEnd); setTimeout(toEnd,60);
}
async function sendChat(q){
 q = (q||'').trim(); if(!q || chatBusy) return;
 if(demo||!selected||String(selected).startsWith('demo-')){ drawChat(); return; }
 const mint=selected; const chat=chats[mint]=chats[mint]||[];
 chat.push({role:'user',content:q}); const wait={role:'assistant',wait:true}; chat.push(wait);
 $('chat-q').value=''; $('chat-q').style.height=''; chatBusy=true; $('chat-send').disabled=true; drawChat();
 try{const history=chat.filter(m=>!m.wait).map(({role,content})=>({role,content}));
  const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json','X-Desk-Token':csrf},body:JSON.stringify({mint,history})});
  const d=await r.json(); if(!r.ok)throw Error(d.error||'Request failed');
  Object.assign(wait,{wait:false,content:d.answer,looked:d.looked||[]});}
 catch(err){Object.assign(wait,{wait:false,content:err.message});}
 finally{chatBusy=false; $('chat-send').disabled=false; if(selected===mint) drawChat(); $('chat-q').focus();}
}
$('chat-form').addEventListener('submit',e=>{e.preventDefault(); sendChat($('chat-q').value);});
$('chat-q').addEventListener('keydown',e=>{ if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); sendChat($('chat-q').value); } });
$('chat-q').addEventListener('input',e=>{ e.target.style.height='auto'; e.target.style.height=Math.min(160,e.target.scrollHeight)+'px'; });
$('chat-list').addEventListener('click',e=>{ const b=e.target.closest('[data-suggest]'); if(b) sendChat(b.dataset.suggest); });
$('chat-clear').addEventListener('click',()=>{ if(selected) delete chats[selected]; drawChat(); });
document.addEventListener('click',e=>{ if(e.target.closest('[data-mint]')) setTimeout(drawChat,0); });
setInterval(()=>{ if($('chat-token').textContent!==tokenLabel()) drawChat(); }, 1500);
drawChat();
