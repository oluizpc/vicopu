"""Painel web do VICOPU: lives vigiadas, fila de clipes e ações (publicar, baixar, copiar, descartar, excluir).

A página atualiza sozinha por /api/estado, sem recarregar: o que você estiver digitando não se perde.
"""
import json
import os
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
.vazia{color:var(--sub);padding:40px;text-align:center;border:1px dashed var(--borda);border-radius:16px}
#toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%) translateY(30px);opacity:0;transition:.25s;
background:var(--txt);color:#111;padding:10px 16px;border-radius:10px;font-weight:700;z-index:9}
#toast.on{opacity:1;transform:translateX(-50%)}
@media(max-width:640px){header{flex-wrap:wrap;padding:10px 14px;gap:8px}.cresce{display:none}
.resumo{width:100%;justify-content:space-between;font-size:12px;gap:8px}.resumo span{white-space:nowrap}
main{padding:14px}.lives,.grade{grid-template-columns:1fr}}
</style></head><body>
<header><div class="logo">VI<span>CO</span>PU</div><div class="modo" id="modo"></div><div class="cresce"></div>
<div class="resumo" id="resumo"></div></header>
<main>
<h2>Lives</h2><div class="lives" id="lives"></div>
<h2>Clipes</h2>
<div class="abas" id="abas"></div>
<div class="grade" id="grade"></div>
</main><div id="toast"></div>
<script>
const NOMES={pendente:"Aguardando você",publicado:"Publicado",erro:"Erro ao publicar",renderizando:"Montando…",
publicando:"Publicando…",pronto:"Pronto",descartado:"Descartado",descartado_ia:"Descartado pela IA"};
const ABAS=[["pendentes","Aguardando você",s=>["pendente","pronto","erro"].includes(s)],
["andamento","Em andamento",s=>["renderizando","publicando"].includes(s)],
["publicados","Publicados",s=>s==="publicado"],["descartados","Descartados",s=>s.startsWith("descartado")],["todos","Todos",s=>true]];
let aba=localStorage.getItem("vicopu_aba")||"pendentes", estado=null;
const $=s=>document.querySelector(s), esc=t=>String(t??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function toast(t){const e=$("#toast");e.textContent=t;e.classList.add("on");clearTimeout(e._t);e._t=setTimeout(()=>e.classList.remove("on"),2200)}
async function post(url,corpo){const r=await fetch(url,{method:"POST",body:corpo||""});const t=await r.text();if(!r.ok){toast("⚠ "+t);throw t}return t}
function ha(seg){const d=Math.max(0,Date.now()/1000-seg);if(d<60)return"agora";if(d<3600)return Math.floor(d/60)+" min";
if(d<86400)return Math.floor(d/3600)+" h";return Math.floor(d/86400)+" d"}
function nota(n){if(n==null)return"";const c=n>=7?"boa":n>=4?"media":"ruim";return`<span class="nota ${c}">IA ${n}/10</span>`}
function resultados(r){return Object.entries(r||{}).map(([k,v])=>{v=String(v);if(v.startsWith("http")){
const m=v.match(/youtube\.com\/shorts\/([\w-]+)/);return`${esc(k)}: <a href="${esc(v)}" target="_blank">abrir</a>`+
(m?` · <a href="https://studio.youtube.com/video/${m[1]}/edit" target="_blank">abrir no Studio</a>`:"")}return`${esc(k)}: ${esc(v)}`}).join("<br>")}
function renderLives(){$("#lives").innerHTML=estado.lives.map(l=>{const n=estado.clipes.filter(c=>c.canal===l.nome).length;
return`<div class="live"><div class="nome"><span class="dot ${l.no_ar?"on":""}"></span>${esc(l.nome)}
<span class="plat ${esc(l.plataforma)}">${esc(l.plataforma)}</span></div>
<div class="info">${l.no_ar?"Ao vivo":"Offline / conectando"} · layout ${l.automatico?`<a href="/camauto/${encodeURIComponent(l.nome)}" target="_blank">${esc(l.layout)} (auto)</a>`:esc(l.layout)}
 · sensibilidade ${esc(l.sensibilidade)} · ${n} clipe${n==1?"":"s"}</div>
<div><button class="btn roxo" ${l.no_ar?"":"disabled"} onclick="cortar('${esc(l.nome)}')">✂ Cortar agora</button></div></div>`}).join("")||
`<div class="vazia">Nenhuma live no config.</div>`}
function card(c){const st=c.status||"";const podeEditar=["pendente","pronto","erro"].includes(st);
const video=c.tem_video?`<video controls preload="metadata" src="/video/${c.id}"></video>`:
`<div class="vazio">${st==="renderizando"?"Montando o clipe…":"Sem vídeo (não foi montado)"}</div>`;
return`<div class="clip ${st==="pendente"?"destaque":""}" data-id="${c.id}">
<div class="midia">${video}<div class="selo">${c.duracao?`<span>${Math.round(c.duracao)}s</span>`:""}${c.nota_ia!=null&&c.motivo_ia!=="sem IA"?`<span>${nota(c.nota_ia)}</span>`:""}</div></div>
<div class="corpo"><div class="linha"><span class="status st-${esc(st)}">${esc(NOMES[st]||st)}</span>
<b style="color:var(--txt)">${esc(c.canal)}</b> · há ${ha(c.criado)}${c.manual?" · manual":""}</div>
<textarea id="t_${c.id}" ${podeEditar?"":"readonly"} onchange="salvarTitulo('${c.id}')">${esc(c.titulo)}</textarea>
<div class="acoes">
${podeEditar&&c.tem_video?`<button class="btn verde" onclick="publicar('${c.id}')" ${c.destinos&&c.destinos.length?"":"disabled title='Nenhum destino em publicar_em'"}>Publicar</button>`:""}
${c.tem_video?`<a class="btn" href="/baixar/${c.id}">⬇ Baixar</a>`:""}
<button class="btn" onclick="copiar('${c.id}')">📋 Copiar</button>
${podeEditar?`<button class="btn fant" onclick="descartar('${c.id}')">Descartar</button>`:""}
${["renderizando","publicando"].includes(st)?"":`<button class="btn fant perigo" title="Excluir do painel e do disco" onclick="excluir('${c.id}')">🗑</button>`}
</div>
${c.resultados&&Object.keys(c.resultados).length?`<div class="res">${resultados(c.resultados)}</div>`:""}
<details><summary>Por que esse clipe?</summary><p>${esc(c.motivo)}</p>${c.motivo_ia&&c.motivo_ia!=="sem IA"?`<p><b>IA:</b> ${esc(c.motivo_ia)}</p>`:""}</details>
</div></div>`}
function renderClipes(){const contagem=Object.fromEntries(ABAS.map(([k,,f])=>[k,estado.clipes.filter(c=>f(c.status||"")).length]));
$("#abas").innerHTML=ABAS.map(([k,nome])=>`<button class="aba ${k===aba?"ativa":""}" onclick="trocar('${k}')">${nome}<span class="n">${contagem[k]}</span></button>`).join("")+
(contagem.descartados?`<span class="cresce"></span><button class="btn fant perigo" onclick="limpar()">🗑 Limpar descartados</button>`:"");
const f=ABAS.find(a=>a[0]===aba)[2];const lista=estado.clipes.filter(c=>f(c.status||""));
const grade=$("#grade");const foco=document.activeElement;
// não refaz cards cujo título está sendo editado nem os vídeos tocando
const vivos=new Set([...grade.querySelectorAll(".clip")].filter(el=>el.contains(foco)||[...el.querySelectorAll("video")].some(v=>!v.paused)).map(el=>el.dataset.id));
const assinatura=lista.map(c=>c.id+c.status+(c.titulo||"")+JSON.stringify(c.resultados||{})).join("|")+aba;
if(grade._ass===assinatura)return;
if(vivos.size&&lista.every(c=>grade.querySelector(`[data-id="${c.id}"]`))){
lista.forEach(c=>{if(!vivos.has(c.id)){const el=grade.querySelector(`[data-id="${c.id}"]`);el.outerHTML=card(c)}});grade._ass=assinatura;return}
grade.innerHTML=lista.length?lista.map(card).join(""):`<div class="vazia">Nada por aqui${aba==="pendentes"?" — quando sair um clipe, ele aparece aqui pra você aprovar.":"."}</div>`;
grade._ass=assinatura}
function render(){$("#modo").innerHTML=`modo <b>${esc(estado.modo)}</b>`;
const p=estado.clipes.filter(c=>["pendente","pronto","erro"].includes(c.status)).length,
pub=estado.clipes.filter(c=>c.status==="publicado").length,ao=estado.lives.filter(l=>l.no_ar).length;
$("#resumo").innerHTML=`<span><b>${ao}</b>/${estado.lives.length} ao vivo</span><span><b>${p}</b> aguardando</span><span><b>${pub}</b> publicados</span>`;
document.title=(p?`(${p}) `:"")+"VICOPU";renderLives();renderClipes()}
async function atualizar(){try{estado=await (await fetch("/api/estado")).json();render()}catch(e){}}
function trocar(k){aba=k;localStorage.setItem("vicopu_aba",k);$("#grade")._ass=null;render()}
async function cortar(n){await post("/cortar/"+encodeURIComponent(n));toast("✂ Corte pedido em "+n+". Sai em ~1 min.");setTimeout(atualizar,1500)}
async function salvarTitulo(id){await post("/titulo/"+id,$("#t_"+id).value.trim());toast("Título salvo")}
async function publicar(id){const t=$("#t_"+id).value.trim();await post("/aprovar/"+id,t);toast("Publicando…");atualizar()}
async function descartar(id){await post("/descartar/"+id);toast("Descartado");atualizar()}
async function excluir(id){if(!confirm("Excluir este clipe do painel e do disco?"))return;await post("/excluir/"+id);toast("Excluído");atualizar()}
async function limpar(){if(!confirm("Apagar do disco TODOS os clipes descartados?"))return;await post("/limpar/descartados");toast("Descartados apagados");atualizar()}
async function copiar(id){const c=estado.clipes.find(x=>x.id===id);const tags=[...(c.hashtags_fixas||[]),...(c.hashtags||[])]
.map(t=>t.startsWith("#")?t:"#"+t);const txt=($("#t_"+id).value.trim()+" "+[...new Set(tags)].join(" ")).trim();
try{await navigator.clipboard.writeText(txt)}catch(e){const a=document.createElement("textarea");a.value=txt;document.body.appendChild(a);a.select();document.execCommand("copy");a.remove()}
toast("📋 Título + hashtags copiados")}
atualizar();setInterval(atualizar,4000);
</script></body></html>"""


def _seguro(nome):
    """Só letras, números, _ e - (evita sair da pasta de clipes)."""
    return re.sub(r"[^\w\-]", "", nome)


def iniciar(fabrica, vigias, host, porta):
    por_nome = {v.canal["nome"]: v for v in vigias}

    def estado():
        lives = [{"nome": n, "plataforma": v.canal["plataforma"], "no_ar": v.no_ar(),
                  "layout": v.layout_atual, "automatico": v.automatico,
                  "sensibilidade": v.canal.get("sensibilidade", "normal")} for n, v in por_nome.items()]
        clipes = []
        for m in fabrica.listar()[:200]:
            m = dict(m)
            m["tem_video"] = os.path.exists(m.get("video", "") or "")
            clipes.append(m)
        return {"modo": fabrica.cfg["publicacao"]["modo"], "lives": lives, "clipes": clipes}

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
            self.wfile.write(dados)

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
                    if alvo not in por_nome:
                        return self._enviar(404, "live não encontrada", "text/plain; charset=utf-8")
                    if not por_nome[alvo].no_ar():
                        return self._enviar(409, "essa live não está no ar", "text/plain; charset=utf-8")
                    por_nome[alvo].detector.manual("botão 'cortar agora' no painel")
                elif acao == "aprovar":
                    fabrica.publicar_async(_seguro(alvo), corpo.strip() or None)
                elif acao == "titulo":
                    fabrica.mudar_titulo(_seguro(alvo), corpo.strip())
                elif acao == "descartar":
                    fabrica.descartar(_seguro(alvo))
                elif acao == "excluir":
                    fabrica.excluir(_seguro(alvo))
                elif acao == "limpar" and alvo == "descartados":
                    fabrica.limpar_descartados()
                else:
                    return self._enviar(404, "?", "text/plain")
            except FileNotFoundError:
                return self._enviar(404, "clipe não encontrado", "text/plain; charset=utf-8")
            except (RuntimeError, ValueError) as e:
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
