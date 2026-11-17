"""Painel web do VICOPU: lives vigiadas, fila de clipes e ações (publicar, baixar, copiar, descartar, excluir).

A página atualiza sozinha por /api/estado, sem recarregar: o que você estiver digitando não se perde.
"""
import json
import os
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import credito as cfg_credito

PAGINA = r"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>VICOPU</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>✂️</text></svg>">
<style>
:root{--bg:#0b0b0f;--card:#16161d;--card2:#1e1e27;--borda:#2a2a36;--txt:#ececf1;--sub:#9a9aab;
--roxo:#8b5cf6;--verde:#22c55e;--amarelo:#f5a524;--vermelho:#ef4444;--azul:#3b82f6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:#93c5fd}
header{position:sticky;top:0;z-index:5;background:rgba(11,11,15,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--borda);
display:flex;align-items:center;gap:14px;padding:12px 22px}
.logo{font-weight:800;font-size:20px;letter-spacing:.5px}.logo span{color:var(--roxo)}
.modo{font-size:12px;padding:3px 9px;border-radius:99px;background:var(--card2);color:var(--sub)}
.modo b{color:var(--txt)}.cresce{flex:1}
.resumo{display:flex;gap:16px;color:var(--sub);font-size:13px}.resumo b{color:var(--txt);font-size:15px}
main{padding:18px 22px;max-width:1500px;margin:0 auto}
h2{font-size:13px;text-transform:uppercase;letter-spacing:1px;color:var(--sub);margin:6px 0 10px}
.lives{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px;margin-bottom:26px}
.live{background:var(--card);border:1px solid var(--borda);border-radius:14px;padding:12px 14px;display:flex;flex-direction:column;gap:8px}
.live .nome{display:flex;align-items:center;gap:8px;font-weight:700;font-size:15px}
.dot{width:9px;height:9px;border-radius:50%;background:#555;flex:none}.dot.on{background:var(--verde);box-shadow:0 0 0 4px rgba(34,197,94,.15)}
.plat{font-size:11px;font-weight:700;padding:2px 7px;border-radius:6px;color:#fff}
.plat.twitch{background:#9146ff}.plat.youtube{background:#e11d48}.plat.kick{background:#16a34a}.plat.arquivo{background:#555}
.nova{background:var(--card);border:1px dashed var(--borda);border-radius:14px;padding:10px 14px;margin-bottom:12px;font-size:13px;color:var(--txt)}
.nova summary{font-weight:700}.nova .form{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.nova input,.nova select{background:var(--card2);color:var(--txt);border:1px solid var(--borda);border-radius:9px;padding:8px 10px;font:inherit;min-width:0}
.nova .dica{color:var(--sub);font-size:12px;margin-top:8px}
.live .acoes2{display:flex;gap:8px;align-items:center}
.termo{height:6px;background:var(--card2);border-radius:4px;overflow:hidden}.termo i{display:block;height:100%;background:var(--azul);transition:width .5s}
.termo.quente i{background:var(--amarelo)}.termo.pico i{background:var(--vermelho)}
.live select,.filtro select,.ajuste input,.ajuste select{background:var(--card2);color:var(--txt);border:1px solid var(--borda);border-radius:8px;padding:5px 8px;font:inherit;font-size:12px}
.ajuste{margin-top:8px;font-size:12px;color:var(--sub)}.ajuste .lin{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:6px}
.ajuste input[type=number]{width:72px}.sino.on{background:var(--roxo);color:#fff}
#paradas{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:-14px 0 22px;font-size:12px;color:var(--sub)}
.parada{display:inline-flex;align-items:center;gap:6px;background:var(--card);border:1px solid var(--borda);border-radius:999px;padding:3px 4px 3px 10px;color:var(--txt)}
.parada .btn{padding:4px 8px;font-size:12px}
.nums{display:flex;flex-wrap:wrap;gap:12px;align-items:center;font-size:13px;margin-top:8px}.nums b{color:var(--txt)}
.nums .quando{color:var(--sub);font-size:11px}.nums .priv{background:var(--card2);border-radius:6px;padding:1px 6px;font-size:11px;color:var(--amarelo)}
.live .info{color:var(--sub);font-size:12px}
.btn{border:0;border-radius:9px;padding:8px 12px;font-weight:650;font-size:13px;cursor:pointer;color:var(--txt);background:var(--card2);
display:inline-flex;align-items:center;gap:6px;text-decoration:none;white-space:nowrap}
.btn:hover{filter:brightness(1.2)}.btn:disabled{opacity:.45;cursor:default;filter:none}
.btn.roxo{background:var(--roxo);color:#fff}.btn.verde{background:var(--verde);color:#06240f}
.btn.fant{background:transparent;color:var(--sub);padding:6px 8px}.btn.fant:hover{color:var(--txt)}
.btn.perigo:hover{color:var(--vermelho)}
.abas{display:flex;gap:6px;align-items:center;margin-bottom:14px;flex-wrap:wrap}
.aba{border:1px solid var(--borda);background:transparent;color:var(--sub);border-radius:99px;padding:6px 13px;cursor:pointer;font-weight:600}
.aba.ativa{background:var(--txt);color:#111;border-color:var(--txt)}
.aba .n{opacity:.7;margin-left:4px}
.grade{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}
.clip{background:var(--card);border:1px solid var(--borda);border-radius:16px;overflow:hidden;display:flex;flex-direction:column}
.clip.destaque{border-color:var(--amarelo)}
.midia{position:relative;background:#000;aspect-ratio:9/16;max-height:440px}
.midia video{width:100%;height:100%;object-fit:contain;display:block}
.midia .vazio{position:absolute;inset:0;display:grid;place-items:center;color:var(--sub);font-size:13px;text-align:center;padding:20px}
.selo{position:absolute;top:8px;left:8px;display:flex;gap:6px}
.selo span{background:rgba(0,0,0,.72);border-radius:7px;padding:3px 7px;font-size:12px;font-weight:700}
.nota.boa{color:#86efac}.nota.media{color:#fde68a}.nota.ruim{color:#fca5a5}
.corpo{padding:11px 12px 12px;display:flex;flex-direction:column;gap:8px}
.linha{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px;color:var(--sub)}
.status{font-size:11px;font-weight:800;padding:3px 8px;border-radius:99px;color:#111}
.st-pendente{background:var(--amarelo)}.st-publicado{background:var(--verde)}.st-erro{background:var(--vermelho);color:#fff}
.st-renderizando,.st-publicando{background:var(--azul);color:#fff}.st-pronto{background:#a5b4fc}
.st-descartado,.st-descartado_ia{background:#3f3f4a;color:#ddd}
textarea{width:100%;resize:vertical;min-height:52px;background:var(--bg);color:var(--txt);border:1px solid var(--borda);border-radius:9px;
padding:8px;font-family:inherit;font-weight:600;font-size:13px;line-height:1.35}textarea:focus{outline:2px solid var(--roxo);border-color:transparent}
.acoes{display:flex;gap:6px;flex-wrap:wrap}
details{font-size:12px;color:var(--sub)}summary{cursor:pointer;user-select:none}details p{margin:6px 0 0}
.res{font-size:12px;color:var(--sub);word-break:break-word}
.post{background:var(--bg);border:1px solid var(--borda);border-radius:9px;padding:8px 9px;font-size:12px;line-height:1.45;
display:flex;flex-direction:column;gap:6px;word-break:break-word}
.post .rot{font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:var(--sub);font-weight:700}
.post .desc{color:var(--txt)}.post .cred{color:#c4b5fd}.post .tags{color:#93c5fd}
.post details summary{color:var(--sub)}
.vazia{color:var(--sub);padding:40px;text-align:center;border:1px dashed var(--borda);border-radius:16px}
#toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%) translateY(30px);opacity:0;transition:.25s;
background:var(--txt);color:#111;padding:10px 16px;border-radius:10px;font-weight:700;z-index:9}
#toast.on{opacity:1;transform:translateX(-50%)}
.marca{position:absolute;top:8px;right:8px;z-index:2;width:26px;height:26px;border-radius:8px;border:2px solid rgba(255,255,255,.75);
background:rgba(0,0,0,.55);display:grid;place-items:center;cursor:pointer;font-weight:900;color:transparent;user-select:none}
.marca:hover{border-color:#fff}.clip.sel{border-color:var(--roxo);box-shadow:0 0 0 2px var(--roxo)}
.clip.sel .marca{background:var(--roxo);border-color:var(--roxo);color:#fff}
#lote{position:sticky;top:58px;z-index:4;display:none;align-items:center;gap:8px;flex-wrap:wrap;background:var(--card2);
border:1px solid var(--roxo);border-radius:12px;padding:8px 10px;margin-bottom:12px}
#lote.on{display:flex}#lote .qtd{font-weight:800;margin-right:4px}
@media(max-width:640px){header{flex-wrap:wrap;padding:10px 14px;gap:8px}.cresce{display:none}
.resumo{width:100%;justify-content:space-between;font-size:12px;gap:8px}.resumo span{white-space:nowrap}
main{padding:14px}.lives,.grade{grid-template-columns:1fr}}
</style></head><body>
<header><div class="logo">VI<span>CO</span>PU</div><div class="modo" id="modo"></div><div class="cresce"></div>
<div class="resumo" id="resumo"></div><button class="btn sino" id="sino" onclick="alternarAvisos()" title="Som e notificação quando cair clipe novo">🔔 Avisos</button></header>
<main>
<h2>Lives</h2>
<details id="nova" class="nova"><summary>➕ Adicionar live (sem parar as outras)</summary>
<div class="form"><input id="n_link" placeholder="Link da live: twitch.tv/..., kick.com/..., youtube.com/@..." style="flex:3 1 280px">
<input id="n_apelido" placeholder="Nome no crédito (opcional)" style="flex:1 1 160px">
<select id="n_sens"><option value="normal">sensibilidade normal</option><option value="alta">alta (chat calmo)</option><option value="baixa">baixa (streamer gigante)</option></select>
<select id="n_idioma"><option value="padrao">legenda: padrão</option><option value="pt">português</option><option value="en">inglês</option><option value="es">espanhol</option><option value="auto">detectar</option></select>
<button class="btn roxo" onclick="addLive()">Vigiar</button></div>
<div class="dica">Começa a vigiar na hora, com a cam automática. Publica no mesmo destino do primeiro canal do config. Fica salva pra próxima vez (em dados/canais_painel.yaml).</div></details>
<div class="lives" id="lives"></div><div id="paradas"></div>
<h2>Clipes</h2>
<div class="abas" id="abas"></div>
<div id="lote"><span class="qtd" id="lote_qtd"></span>
<button class="btn" onclick="selTodos()">Selecionar todos da aba</button>
<button class="btn verde" onclick="emLote('publicar')">Publicar</button>
<button class="btn" onclick="emLote('descartar')">Descartar</button>
<button class="btn perigo" onclick="emLote('excluir')">🗑 Excluir</button>
<span class="cresce"></span><button class="btn fant" onclick="limparSel()">✕ Limpar seleção</button></div>
<div class="grade" id="grade"></div>
</main><div id="toast"></div>
<script>
const NOMES={pendente:"Aguardando você",publicado:"Publicado",erro:"Erro ao publicar",renderizando:"Montando…",
publicando:"Publicando…",pronto:"Pronto",descartado:"Descartado",descartado_ia:"Descartado pela IA"};
const ABAS=[["pendentes","Aguardando você",s=>["pendente","pronto","erro"].includes(s)],
["andamento","Em andamento",s=>["renderizando","publicando"].includes(s)],
["publicados","Publicados",s=>s==="publicado"],["descartados","Descartados",s=>s.startsWith("descartado")],["todos","Todos",s=>true]];
let aba=localStorage.getItem("vicopu_aba")||"pendentes", estado=null, sel=new Set(), ultimoSel=null;
let filtroCanal=localStorage.getItem("vicopu_canal")||"", avisos=localStorage.getItem("vicopu_avisos")==="1", conhecidos=null;
function bip(){try{const ctx=new (window.AudioContext||window.webkitAudioContext)();[0,0.18].forEach((t,i)=>{const o=ctx.createOscillator(),g=ctx.createGain();
o.frequency.value=i?1046:784;g.gain.setValueAtTime(0.0001,ctx.currentTime+t);g.gain.exponentialRampToValueAtTime(0.25,ctx.currentTime+t+0.02);
g.gain.exponentialRampToValueAtTime(0.0001,ctx.currentTime+t+0.16);o.connect(g).connect(ctx.destination);o.start(ctx.currentTime+t);o.stop(ctx.currentTime+t+0.2)})}catch(e){}}
function pintarSino(){$("#sino").classList.toggle("on",avisos);$("#sino").textContent=avisos?"🔔 Avisos ligados":"🔕 Avisos"}
async function alternarAvisos(){avisos=!avisos;localStorage.setItem("vicopu_avisos",avisos?"1":"0");
if(avisos){if("Notification" in window&&Notification.permission==="default"){try{await Notification.requestPermission()}catch(e){}}bip();toast("🔔 Vai tocar um som quando cair clipe novo")}pintarSino()}
function avisarNovos(){const pend=estado.clipes.filter(c=>["pendente","pronto"].includes(c.status));const ids=new Set(pend.map(c=>c.id));
if(conhecidos===null){conhecidos=ids;return}const novos=pend.filter(c=>!conhecidos.has(c.id));conhecidos=ids;if(!novos.length||!avisos)return;
bip();toast(`🎬 ${novos.length} clipe(s) novo(s) pra revisar`);
if("Notification" in window&&Notification.permission==="granted"&&document.hidden){novos.slice(0,3).forEach(c=>{try{const n=new Notification("VICOPU: clipe de "+c.canal,{body:c.titulo||"",tag:c.id});n.onclick=()=>{window.focus();n.close()}}catch(e){}})}}
const $=s=>document.querySelector(s), esc=t=>String(t??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function toast(t){const e=$("#toast");e.textContent=t;e.classList.add("on");clearTimeout(e._t);e._t=setTimeout(()=>e.classList.remove("on"),2200)}
async function post(url,corpo){const r=await fetch(url,{method:"POST",body:corpo||""});const t=await r.text();if(!r.ok){toast("⚠ "+t);throw t}return t}
function ha(seg){const d=Math.max(0,Date.now()/1000-seg);if(d<60)return"agora";if(d<3600)return Math.floor(d/60)+" min";
if(d<86400)return Math.floor(d/3600)+" h";return Math.floor(d/86400)+" d"}
function nota(n){if(n==null)return"";const c=n>=7?"boa":n>=4?"media":"ruim";return`<span class="nota ${c}">IA ${n}/10</span>`}
function tagsDe(c){return[...new Set([...(c.hashtags_fixas||[]),...(c.hashtags||[])].map(t=>t.startsWith("#")?t:"#"+t))]}
function previa(c){if(!c.tem_video)return"";const tags=tagsDe(c).join(" ");
const curto=(c.credito_tiktok||"");const tiktok=[c.titulo,curto,tags].filter(x=>x).join(" ");
return`<div class="post"><div class="rot">Descrição no YouTube</div>
${c.descricao?`<div class="desc">${esc(c.descricao)}</div>`:""}${c.credito?`<div class="cred">${esc(c.credito)}</div>`:""}
${tags?`<div class="tags">${esc(tags)}</div>`:""}
<details><summary>Legenda no TikTok</summary><div class="desc" style="margin-top:4px">${esc(tiktok)}</div></details></div>`}
function resultados(r){return Object.entries(r||{}).map(([k,v])=>{v=String(v);if(v.startsWith("http")){
const m=v.match(/youtube\.com\/shorts\/([\w-]+)/);return`${esc(k)}: <a href="${esc(v)}" target="_blank">abrir</a>`+
(m?` · <a href="https://studio.youtube.com/video/${m[1]}/edit" target="_blank">abrir no Studio</a>`:"")}return`${esc(k)}: ${esc(v)}`}).join("<br>")}
function renderLives(){$("#lives").innerHTML=estado.lives.map(l=>{const n=estado.clipes.filter(c=>c.canal===l.nome).length;
return`<div class="live"><div class="nome"><span class="dot ${l.no_ar?"on":""}"></span>${esc(l.nome)}
<span class="plat ${esc(l.plataforma)}">${esc(l.plataforma)}</span></div>
<div class="info">${l.no_ar?"Ao vivo":"Offline / conectando"} · layout ${l.automatico?`<a href="/camauto/${encodeURIComponent(l.nome)}" target="_blank">${esc(l.layout)} (auto)</a>`:esc(l.layout)}
 · ${n} clipe${n==1?"":"s"}</div>
${termo(l)}
<div class="info">sensibilidade <select onchange="mudarSens('${esc(l.nome)}',this.value)">${["alta","normal","baixa"].map(o=>`<option ${o===l.sensibilidade?"selected":""}>${o}</option>`).join("")}</select></div>
<div class="acoes2"><button class="btn roxo" ${l.no_ar?"":"disabled"} onclick="cortar('${esc(l.nome)}')">✂ Cortar agora</button>
<button class="btn fant perigo" title="Parar de vigiar esta live" onclick="pararLive('${esc(l.nome)}')">⏹ Parar</button></div></div>`}).join("")||
`<div class="vazia">Nenhuma live: adicione uma acima.</div>`}
function termo(l){const t=l.termometro;if(!t)return"";if(t.aquecendo)return`<div class="info">🌡 aprendendo o ritmo do chat… (${t.msgs} msgs/${t.janela}s)</div>`;
const pct=Math.min(100,Math.round(100*t.score/t.limiar)),cls=pct>=100?"pico":pct>=70?"quente":"";
return`<div class="termo ${cls}" title="quão perto de virar corte"><i style="width:${pct}%"></i></div><div class="info">🌡 chat ${t.msgs} msgs/${t.janela}s (normal ${t.normal}) · ${pct}% do ponto de corte</div>`}
async function mudarSens(n,v){await post("/sensibilidade/"+encodeURIComponent(n),v);toast(`Sensibilidade de ${n}: ${v}`);document.activeElement.blur();atualizar()}
async function addLive(){const link=$("#n_link").value.trim();if(!link){toast("Cole o link da live");return}
const nome=await post("/live/adicionar",JSON.stringify({link,apelido:$("#n_apelido").value,sensibilidade:$("#n_sens").value,idioma:$("#n_idioma").value}));
$("#n_link").value="";$("#n_apelido").value="";toast("👀 Vigiando "+nome+". A cam é achada em ~1 min.");atualizar()}
async function pararLive(n){if(!confirm(`Parar de vigiar ${n}? Ela fica parada (mesmo reiniciando) até você clicar em "Vigiar de novo".`))return;
await post("/parar/"+encodeURIComponent(n));toast("⏹ "+n+" parada");atualizar()}
async function retomar(n){await post("/retomar/"+encodeURIComponent(n));toast("👀 Vigiando "+n+" de novo");atualizar()}
async function esquecer(n){if(!confirm(`Tirar ${n} da lista de vez?`))return;await post("/esquecer/"+encodeURIComponent(n));toast(n+" removida");atualizar()}
function renderParadas(){const p=estado.paradas||[];$("#paradas").innerHTML=p.length?`<span>Paradas:</span>`+p.map(l=>`<span class="parada">${esc(l.nome)}
<button class="btn" onclick="retomar('${esc(l.nome)}')">▶ Vigiar de novo</button>${l.do_painel?`<button class="btn fant perigo" title="Tirar da lista de vez" onclick="esquecer('${esc(l.nome)}')">✕</button>`:""}</span>`).join(""):""}
function ajuste(c){const [a,b]=c.corte,j=c.janela||b;
return`<details class="ajuste" id="aj_${c.id}"><summary>✂ Ajustar o corte</summary>
<div>O trecho gravado tem ${j.toFixed(0)} s. Hoje o clipe vai de ${a.toFixed(1)} s a ${b.toFixed(1)} s dele.</div>
<div class="lin">início <input type="number" id="ai_${c.id}" step="0.5" min="0" max="${j}" value="${a.toFixed(1)}">
fim <input type="number" id="af_${c.id}" step="0.5" min="0" max="${j}" value="${b.toFixed(1)}"></div>
<div class="lin"><button class="btn" onclick="marcar('${c.id}','ai')">⏮ início = ponto do vídeo</button><button class="btn" onclick="marcar('${c.id}','af')">fim = ponto do vídeo ⏭</button>
<button class="btn" onclick="mais('${c.id}',-5)">+5 s antes</button><button class="btn" onclick="mais('${c.id}',5)">+5 s depois</button></div>
<div class="lin">layout <select id="al_${c.id}">${["split","blur","centro"].map(o=>`<option ${o===c.layout?"selected":""}>${o}</option>`).join("")}</select>
<label><input type="checkbox" id="ag_${c.id}" ${c.legenda!==false?"checked":""}> legenda</label>
<button class="btn roxo" onclick="remontar('${c.id}')">Montar de novo</button></div></details>`}
function marcar(id,campo){const c=estado.clipes.find(x=>x.id===id),v=document.querySelector(`[data-id="${id}"] video`);if(!c||!v)return;
$("#"+campo+"_"+id).value=(c.corte[0]+v.currentTime).toFixed(1);toast("Marcado em "+(c.corte[0]+v.currentTime).toFixed(1)+" s")}
function mais(id,d){const c=estado.clipes.find(x=>x.id===id),j=c.janela;if(d<0){const e=$("#ai_"+id);e.value=Math.max(0,+e.value+d).toFixed(1)}
else{const e=$("#af_"+id);e.value=Math.min(j,+e.value+d).toFixed(1)}}
async function remontar(id){const ini=+$("#ai_"+id).value,fim=+$("#af_"+id).value;
if(!(fim>ini)){toast("O fim precisa vir depois do início");return}
await post("/remontar/"+id,JSON.stringify({inicio:ini,fim:fim,layout:$("#al_"+id).value,legenda:$("#ag_"+id).checked}));
toast("🎬 Montando de novo… (uns segundos)");document.activeElement.blur();$("#grade")._ass=null;atualizar()}
function fmt(n){return n>=1e6?(n/1e6).toFixed(1).replace(".0","")+" mi":n>=1e3?(n/1e3).toFixed(1).replace(".0","")+" mil":String(n)}
function numeros(c){const n=c.numeros;if(n)return`<div class="nums"><span title="visualizações">👁 <b>${fmt(n.views)}</b></span><span title="likes">👍 <b>${fmt(n.likes)}</b></span><span title="comentários">💬 <b>${fmt(n.comentarios)}</b></span>${n.privacidade&&n.privacidade!=="public"?`<span class="priv">${esc(n.privacidade)}</span>`:""}<span class="quando">atualizado há ${ha(n.atualizado)}</span></div>`;
if(c.numeros_erro)return`<div class="res">📊 ${esc(c.numeros_erro)}</div>`;
return Object.values(c.resultados||{}).some(v=>/youtube\.com\/shorts\//.test(String(v)))?`<div class="res">📊 números do YouTube chegam em alguns minutos</div>`:""}
async function atualizarNumeros(){toast("📊 Buscando números no YouTube…");const r=JSON.parse(await post("/numeros/atualizar"));
const e=Object.values(r.erros||{});toast(e.length?"⚠ "+e[0]:`📊 ${r.ok} clipe(s) atualizado(s)`);$("#grade")._ass=null;atualizar()}
function card(c){const st=c.status||"";const descartado=st.startsWith("descartado");
const podeEditar=["pendente","pronto","erro"].includes(st)||descartado;
const video=c.tem_video?`<video controls preload="metadata" src="/video/${c.id}?v=${c.versao||0}"></video>`:
`<div class="vazio">${st==="renderizando"?"Montando o clipe…":"Sem vídeo (não foi montado)"}</div>`;
return`<div class="clip ${st==="pendente"?"destaque":""} ${sel.has(c.id)?"sel":""}" data-id="${c.id}">
<div class="midia">${video}<div class="marca" title="Selecionar" onclick="alternar('${c.id}',event)">✓</div><div class="selo">${c.duracao?`<span>${Math.round(c.duracao)}s</span>`:""}${c.nota_ia!=null&&c.motivo_ia!=="sem IA"?`<span>${nota(c.nota_ia)}</span>`:""}</div></div>
<div class="corpo"><div class="linha"><span class="status st-${esc(st)}">${esc(NOMES[st]||st)}</span>
<b style="color:var(--txt)">${esc(c.canal)}</b> · há ${ha(c.criado)}${c.manual?" · manual":""}</div>
<textarea id="t_${c.id}" ${podeEditar?"":"readonly"} onchange="salvarTitulo('${c.id}')">${esc(c.titulo)}</textarea>
${descartado&&c.motivo_ia&&c.motivo_ia!=="sem IA"?`<div class="res">🤖 <b>Por que a IA descartou:</b> ${esc(c.motivo_ia)}</div>`:""}${descartado&&!c.tem_video?`<div class="res">Esse foi descartado antes da mudança que monta o vídeo dos descartados; não tem vídeo pra ver.</div>`:""}<div class="acoes">
${podeEditar&&c.tem_video?`<button class="btn verde" onclick="publicar('${c.id}')" ${c.destinos&&c.destinos.length?`title="Publicar em: ${esc(c.destinos.join(", "))}"`:"disabled"}>Publicar</button>`:""}
${c.tem_video?`<a class="btn" href="/baixar/${c.id}">⬇ Baixar</a>`:""}
<button class="btn" onclick="copiar('${c.id}')">📋 Copiar</button>
${podeEditar&&!descartado?`<button class="btn fant" onclick="descartar('${c.id}')">Descartar</button>`:""}
${["renderizando","publicando"].includes(st)?"":`<button class="btn fant perigo" title="Excluir do painel e do disco" onclick="excluir('${c.id}')">🗑</button>`}
</div>
${podeEditar&&c.tem_video&&!(c.destinos&&c.destinos.length)?`<div class="res">⚠ Sem destino pra publicar: coloque <b>publicar_em</b> no canal <b>${esc(c.canal)}</b> no config.yaml e reinicie. Ou use Baixar/Copiar e poste na mão.</div>`:""}
${c.destinos&&c.destinos.length&&podeEditar?`<div class="res">Vai pra: ${esc(c.destinos.join(", "))}</div>`:""}
${c.resultados&&Object.keys(c.resultados).length?`<div class="res">${resultados(c.resultados)}</div>`:""}
${st==="publicado"?numeros(c):""}
${podeEditar&&c.pode_ajustar&&c.corte?ajuste(c):""}
${previa(c)}
<details><summary>Por que esse clipe?</summary><p>${esc(c.motivo)}</p>${c.motivo_ia&&c.motivo_ia!=="sem IA"?`<p><b>IA:</b> ${esc(c.motivo_ia)}</p>`:""}</details>
</div></div>`}
function clipesF(){return estado.clipes.filter(c=>!filtroCanal||c.canal===filtroCanal)}
function filtrar(v){if(document.activeElement)document.activeElement.blur();filtroCanal=v;localStorage.setItem("vicopu_canal",v);sel.clear();$("#grade")._ass=null;render()}
function renderClipes(){const contagem=Object.fromEntries(ABAS.map(([k,,f])=>[k,clipesF().filter(c=>f(c.status||"")).length]));
if(!($("#abas").contains(document.activeElement)&&document.activeElement.tagName==="SELECT"))$("#abas").innerHTML=ABAS.map(([k,nome])=>`<button class="aba ${k===aba?"ativa":""}" onclick="trocar('${k}')">${nome}<span class="n">${contagem[k]}</span></button>`).join("")+
`<span class="filtro"><select onchange="filtrar(this.value)"><option value="">todas as lives</option>${[...new Set(estado.clipes.map(c=>c.canal))].sort().map(n=>`<option ${n===filtroCanal?"selected":""} value="${esc(n)}">${esc(n)}</option>`).join("")}</select></span>`+
(aba==="publicados"&&contagem.publicados?(()=>{const pub=clipesF().filter(c=>c.status==="publicado"&&c.numeros);const t=pub.reduce((a,c)=>a+c.numeros.views,0);
return`<span class="cresce"></span>${pub.length?`<span style="color:var(--sub);font-size:13px">👁 <b style="color:var(--txt)">${fmt(t)}</b> views no total</span>`:""}<button class="btn" onclick="atualizarNumeros()">🔄 Atualizar números</button>`})():"")+
(contagem.descartados&&aba!=="publicados"?`<span class="cresce"></span><button class="btn fant perigo" onclick="limpar()">🗑 Limpar descartados</button>`:"");
const f=ABAS.find(a=>a[0]===aba)[2];const lista=clipesF().filter(c=>f(c.status||""));
const grade=$("#grade");const foco=document.activeElement;
const abertos=[...grade.querySelectorAll("details[open]")].map(d=>d.id).filter(x=>x);
const reabrir=()=>abertos.forEach(i=>{const d=document.getElementById(i);if(d)d.open=true});
// não refaz cards cujo título está sendo editado nem os vídeos tocando
const vivos=new Set([...grade.querySelectorAll(".clip")].filter(el=>el.contains(foco)||[...el.querySelectorAll("video")].some(v=>!v.paused)).map(el=>el.dataset.id));
const assinatura=lista.map(c=>c.id+c.status+(c.titulo||"")+(c.descricao||"")+(c.credito||"")+JSON.stringify(c.resultados||{})+(c.versao||"")+JSON.stringify(c.numeros||c.numeros_erro||"")).join("|")+aba+filtroCanal;
if(grade._ass===assinatura)return;
if(vivos.size&&lista.every(c=>grade.querySelector(`[data-id="${c.id}"]`))){
lista.forEach(c=>{if(!vivos.has(c.id)){const el=grade.querySelector(`[data-id="${c.id}"]`);el.outerHTML=card(c)}});grade._ass=assinatura;reabrir();return}
grade.innerHTML=lista.length?lista.map(card).join(""):`<div class="vazia">Nada por aqui${aba==="pendentes"?" — quando sair um clipe, ele aparece aqui pra você aprovar.":"."}</div>`;
grade._ass=assinatura;reabrir()}
function render(){$("#modo").innerHTML=`modo <b>${esc(estado.modo)}</b>`;
const p=estado.clipes.filter(c=>["pendente","pronto","erro"].includes(c.status)).length,
pub=estado.clipes.filter(c=>c.status==="publicado").length,ao=estado.lives.filter(l=>l.no_ar).length;
$("#resumo").innerHTML=`<span><b>${ao}</b>/${estado.lives.length} ao vivo</span><span><b>${p}</b> aguardando</span><span><b>${pub}</b> publicados</span>`;
document.title=(p?`(${p}) `:"")+"VICOPU";const ids=new Set(estado.clipes.map(c=>c.id));
[...sel].forEach(id=>{if(!ids.has(id))sel.delete(id)});avisarNovos();pintarSino();if(!$("#lives").contains(document.activeElement))renderLives();renderParadas();renderClipes();pintarSel()}
async function atualizar(){try{estado=await (await fetch("/api/estado")).json();render()}catch(e){}}
function trocar(k){if(document.activeElement)document.activeElement.blur();aba=k;sel.clear();localStorage.setItem("vicopu_aba",k);$("#grade")._ass=null;render()}
async function cortar(n){const b=event&&event.target;if(b){b.disabled=true;b.textContent="✂ Pedido!"}
try{await post("/cortar/"+encodeURIComponent(n));toast("✂ Corte pedido em "+n+". Sai em ~1 min (no notebook pode levar mais).")}catch(e){}
setTimeout(atualizar,1500)}
async function salvarTitulo(id){await post("/titulo/"+id,$("#t_"+id).value.trim());toast("Título salvo")}
async function publicar(id){const t=$("#t_"+id).value.trim();await post("/aprovar/"+id,t);toast("Publicando…");atualizar()}
async function descartar(id){await post("/descartar/"+id);toast("Descartado");atualizar()}
async function excluir(id){if(!confirm("Excluir este clipe do painel e do disco?"))return;await post("/excluir/"+id);toast("Excluído");atualizar()}
async function limpar(){if(!confirm("Apagar do disco TODOS os clipes descartados?"))return;await post("/limpar/descartados");toast("Descartados apagados");atualizar()}
async function copiar(id){const c=estado.clipes.find(x=>x.id===id);
const txt=[$("#t_"+id).value.trim(),c.descricao||"",c.credito||"",tagsDe(c).join(" ")].filter(x=>x).join("\n\n");
try{await navigator.clipboard.writeText(txt)}catch(e){const a=document.createElement("textarea");a.value=txt;document.body.appendChild(a);a.select();document.execCommand("copy");a.remove()}
toast("📋 Título, descrição, crédito e hashtags copiados")}
function listaAba(){const f=ABAS.find(a=>a[0]===aba)[2];return clipesF().filter(c=>f(c.status||""))}
function pintarSel(){document.querySelectorAll(".clip").forEach(el=>el.classList.toggle("sel",sel.has(el.dataset.id)));
const n=sel.size;$("#lote").classList.toggle("on",n>0);$("#lote_qtd").textContent=n+" selecionado"+(n==1?"":"s")}
function alternar(id,ev){ev.stopPropagation();
if(ev.shiftKey&&ultimoSel){const ids=listaAba().map(c=>c.id),a=ids.indexOf(ultimoSel),b=ids.indexOf(id);
if(a>=0&&b>=0){ids.slice(Math.min(a,b),Math.max(a,b)+1).forEach(x=>sel.add(x));ultimoSel=id;pintarSel();return}}
sel.has(id)?sel.delete(id):sel.add(id);ultimoSel=id;pintarSel()}
function selTodos(){listaAba().forEach(c=>sel.add(c.id));pintarSel()}
function limparSel(){sel.clear();pintarSel()}
async function emLote(acao){const ids=[...sel];if(!ids.length)return;
const nomes={publicar:"Publicar",descartar:"Descartar",excluir:"EXCLUIR do painel e do disco"};
if(!confirm(`${nomes[acao]} ${ids.length} clipe(s)?`))return;
const r=JSON.parse(await post("/lote/"+acao,JSON.stringify(ids)));const p=Object.keys(r.pulados).length;
toast(`${r.feitos} feito(s)`+(p?` · ${p} pulado(s): ${[...new Set(Object.values(r.pulados))].join(", ")}`:""));
sel.clear();$("#grade")._ass=null;atualizar()}
document.addEventListener("keydown",e=>{if(e.key==="Escape"&&sel.size)limparSel()});
atualizar();setInterval(atualizar,4000);
</script></body></html>"""


def _seguro(nome):
    """Só letras, números, _ e - (evita sair da pasta de clipes)."""
    return re.sub(r"[^\w\-]", "", nome)


def iniciar(fabrica, central, host, porta):

    def estado():
        lives = [{"nome": v.canal["nome"], "plataforma": v.canal["plataforma"], "no_ar": v.no_ar(),
                  "layout": v.layout_atual, "automatico": v.automatico, "do_painel": bool(v.canal.get("do_painel")),
                  "termometro": v.termometro() if v.no_ar() else None,
                  "sensibilidade": v.canal.get("sensibilidade", "normal")} for v in central.lista()]
        clipes = []
        for m in fabrica.listar()[:200]:
            m = dict(m)
            m["tem_video"] = os.path.exists(m.get("video", "") or "")
            m["pode_ajustar"] = os.path.exists(os.path.join(fabrica.pasta, m["id"], "fonte.ts"))
            m["destinos"] = fabrica.destinos_atuais(m)
            canal = next((c for c in fabrica.cfg["canais"] if c["nome"] == m.get("canal")), None)
            m["credito"] = cfg_credito(fabrica.cfg, canal)
            pub = fabrica.cfg["publicacao"]
            m["credito_tiktok"] = cfg_credito({**fabrica.cfg, "publicacao": {**pub, "credito": pub.get("credito_tiktok")}}, canal)
            clipes.append(m)
        paradas = [{"nome": c["nome"], "plataforma": c["plataforma"], "do_painel": bool(c.get("do_painel"))}
                   for c in central.paradas()]
        return {"modo": fabrica.cfg["publicacao"]["modo"], "lives": lives, "paradas": paradas, "clipes": clipes}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _enviar(self, codigo, corpo, tipo="text/html; charset=utf-8", extra=None):
            dados = corpo.encode() if isinstance(corpo, str) else corpo
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(dados)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            try:
                self.wfile.write(dados)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass  # o navegador cancelou (normal com vídeo: ele pede pedaços e desiste de alguns)

        def do_GET(self):
            caminho = urllib.parse.urlparse(self.path).path
            if caminho.startswith("/video/"):
                return self._video(_seguro(urllib.parse.unquote(caminho[7:])))
            if caminho.startswith("/baixar/"):
                return self._video(_seguro(urllib.parse.unquote(caminho[8:])), baixar=True)
            if caminho.startswith("/camauto/"):
                nome = os.path.basename(urllib.parse.unquote(caminho[9:]))
                cam = os.path.join(fabrica.cfg["geral"]["pasta_trabalho"], "camauto", f"{nome}.jpg")
                if os.path.exists(cam):
                    with open(cam, "rb") as f:
                        return self._enviar(200, f.read(), "image/jpeg")
                return self._enviar(404, "Ainda não detectou a cam desta live.", "text/plain; charset=utf-8")
            if caminho in ("/api/estado", "/api/clipes"):
                dados = estado() if caminho == "/api/estado" else fabrica.listar()
                return self._enviar(200, json.dumps(dados, ensure_ascii=False), "application/json; charset=utf-8")
            if caminho in ("/", "/index.html"):
                return self._enviar(200, PAGINA)
            return self._enviar(404, "?", "text/plain")

        def do_POST(self):
            tam = int(self.headers.get("Content-Length") or 0)
            corpo = self.rfile.read(tam).decode("utf-8", errors="ignore") if tam else ""
            partes = urllib.parse.urlparse(self.path).path.strip("/").split("/", 1)
            if len(partes) != 2:
                return self._enviar(404, "?", "text/plain")
            acao, alvo = partes[0], urllib.parse.unquote(partes[1])
            try:
                if acao == "cortar":
                    vig = central.por_nome(alvo)
                    if not vig:
                        return self._enviar(404, "live não encontrada", "text/plain; charset=utf-8")
                    if not vig.no_ar():
                        return self._enviar(409, "essa live não está no ar", "text/plain; charset=utf-8")
                    falta = 20 - (time.time() - getattr(vig, "ultimo_manual", 0))
                    if falta > 0:
                        return self._enviar(409, "já pedi um corte dessa live agora há pouco; ele sai em ~1 min "
                                                 f"(dá pra pedir outro em {falta:.0f} s)", "text/plain; charset=utf-8")
                    vig.ultimo_manual = time.time()
                    vig.detector.manual("botão 'cortar agora' no painel")
                elif acao == "live" and alvo == "adicionar":
                    dados = json.loads(corpo or "{}")
                    nome = central.adicionar(dados if isinstance(dados, dict) else {})
                    return self._enviar(200, nome, "text/plain; charset=utf-8")
                elif acao == "parar":
                    central.remover(alvo)
                elif acao == "retomar":
                    central.retomar(alvo)
                elif acao == "esquecer":
                    central.esquecer(alvo)
                elif acao == "sensibilidade":
                    central.mudar_sensibilidade(alvo, corpo.strip())
                elif acao == "remontar":
                    d = json.loads(corpo or "{}")
                    meta = fabrica.ler(_seguro(alvo))
                    vig = central.por_nome(meta.get("canal", ""))
                    cam = vig.facecam_atual if vig else None
                    if not cam:
                        arq = os.path.join(fabrica.cfg["geral"]["pasta_trabalho"], "camauto", f"{meta.get('canal')}.json")
                        try:
                            with open(arq, encoding="utf-8") as f:
                                cam = json.load(f)
                        except (OSError, ValueError):
                            cam = None
                    fabrica.remontar(_seguro(alvo), d.get("inicio"), d.get("fim"), d.get("layout"),
                                     d.get("legenda", True), cam)
                elif acao == "aprovar":
                    fabrica.publicar_async(_seguro(alvo), corpo.strip() or None)
                elif acao == "titulo":
                    fabrica.mudar_titulo(_seguro(alvo), corpo.strip())
                elif acao == "descartar":
                    fabrica.descartar(_seguro(alvo))
                elif acao == "excluir":
                    fabrica.excluir(_seguro(alvo))
                elif acao == "lote":
                    ids = [_seguro(i) for i in json.loads(corpo or "[]") if isinstance(i, str)]
                    r = fabrica.lote(alvo, ids)
                    return self._enviar(200, json.dumps(r, ensure_ascii=False), "application/json; charset=utf-8")
                elif acao == "numeros" and alvo == "atualizar":
                    r = fabrica.atualizar_numeros()
                    return self._enviar(200, json.dumps(r, ensure_ascii=False), "application/json; charset=utf-8")
                elif acao == "limpar" and alvo == "descartados":
                    fabrica.limpar_descartados()
                else:
                    return self._enviar(404, "?", "text/plain")
            except FileNotFoundError:
                return self._enviar(404, "clipe não encontrado", "text/plain; charset=utf-8")
            except (RuntimeError, ValueError, TypeError) as e:  # json inválido também cai aqui
                return self._enviar(409, str(e), "text/plain; charset=utf-8")
            self._enviar(200, "ok", "text/plain")

        def _video(self, cid, baixar=False):
            try:
                meta = fabrica.ler(cid)
                caminho = meta["video"]
                tamanho = os.path.getsize(caminho)
            except (FileNotFoundError, KeyError):
                return self._enviar(404, "?", "text/plain")
            extra = {"Accept-Ranges": "bytes"}
            if baixar:
                extra["Content-Disposition"] = f'attachment; filename="{cid}.mp4"'
            ini, fim = 0, tamanho - 1
            m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "")) if not baixar else None
            if m:
                ini = int(m.group(1) or 0)
                fim = int(m.group(2)) if m.group(2) else fim
                fim = min(fim, tamanho - 1)
                extra["Content-Range"] = f"bytes {ini}-{fim}/{tamanho}"
            with open(caminho, "rb") as f:
                f.seek(ini)
                dados = f.read(fim - ini + 1)
            self._enviar(206 if m else 200, dados, "video/mp4", extra)

    srv = ThreadingHTTPServer((host, porta), H)
    threading.Thread(target=srv.serve_forever, daemon=True, name="painel").start()
    return srv
