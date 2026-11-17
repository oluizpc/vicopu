"""Junta tudo: VIgia (captura + chat + detector) -> COrta -> PUblica."""
import glob
import json
import logging
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import corte, ia
from .captura import Buffer, Captura, volume_medio
from .chat import criar_leitor
from .detector import Detector
from .publicar import publicar


SENSIBILIDADES = {
    # alta: streamer pequeno (chat calmo) · baixa: streamer gigante (chat sempre lotado)
    "alta": {"minimo_mensagens_janela": 4, "multiplicador_pico": 2.5, "limiar_score": 0.9},
    "normal": {},
    "baixa": {"minimo_mensagens_janela": 15, "multiplicador_pico": 4.0, "limiar_score": 1.2},
}


def deteccao_do_canal(cfg, canal):
    """Regras de detecção do canal: as gerais + o atalho 'sensibilidade' + ajustes finos em 'deteccao'."""
    regras = dict(cfg["deteccao"])
    nivel = str(canal.get("sensibilidade", "normal")).lower()
    if nivel not in SENSIBILIDADES:
        raise ValueError(f"sensibilidade '{nivel}' inválida no canal {canal['nome']} (use alta, normal ou baixa)")
    regras.update(SENSIBILIDADES[nivel])
    regras.update(canal.get("deteccao") or {})
    return regras


class Vigia:
    def __init__(self, canal, cfg, fabrica):
        self.canal = canal
        self.cfg = cfg
        g = cfg["geral"]
        self.buffer = Buffer(g["buffer_minutos"] * 60)
        self.detector = Detector(canal["nome"], deteccao_do_canal(cfg, canal), self._momento)
        self.fabrica = fabrica
        self.captura = Captura(canal, cfg, self.buffer, self._segmento)
        self.chat = criar_leitor(canal, cfg, self.detector.nova_msg)
        self.log = logging.getLogger(f"vigia.{canal['nome']}")
        # layout "auto": começa no blur e troca pro split quando achar a webcam
        self.automatico = canal["layout"] == "auto" or canal.get("facecam") == "auto"
        self.layout_atual = "blur" if self.automatico else canal["layout"]
        self.facecam_atual = None if self.automatico else canal.get("facecam")

    def iniciar(self):
        self.captura.start()
        if self.chat:
            self.chat.start()
        if self.automatico:
            threading.Thread(target=self._detectar_cam_sempre, daemon=True,
                             name=f"camauto-{self.canal['nome']}").start()

    def _detectar_cam_sempre(self):
        """Procura a webcam quando a live entra no ar e de novo a cada 15 min (o streamer pode mudar a cena)."""
        from . import camauto
        while not self.captura.parar_evt.is_set():
            agora = time.time()
            if not self.no_ar() or agora - self.buffer.ultimo_fim() > 10:
                self.captura.parar_evt.wait(10)
                continue
            segs = self.buffer.pegar(agora - 60, agora)
            if len(segs) < 5:  # espera ter uns 20 s de live no replay
                self.buffer.soltar(segs)
                self.captura.parar_evt.wait(10)
                continue
            try:
                caixa = camauto.detectar(self.cfg, [s.caminho for s in segs], self.canal["nome"])
            except Exception as e:
                self.log.warning("Detecção da cam falhou: %s", e)
                caixa = None
            finally:
                self.buffer.soltar(segs)
            if caixa:
                self.layout_atual, self.facecam_atual = "split", caixa
            else:
                self.layout_atual, self.facecam_atual = "blur", None
            self.log.info("Layout automático: %s", self.layout_atual)
            self.captura.parar_evt.wait(15 * 60)

    def parar(self):
        self.captura.parar()
        if self.chat:
            self.chat.parar()

    def no_ar(self):
        return self.captura.no_ar and time.time() - self.buffer.ultimo_fim() < 30

    def _segmento(self, seg):
        if self.cfg["deteccao"]["usar_audio"]:
            self.detector.novo_audio(volume_medio(self.cfg["geral"]["ffmpeg"], seg.caminho), seg.fim)

    def _momento(self, m):
        if not self.no_ar():
            self.log.info("Pico no chat, mas a live não está sendo capturada. Ignorado.")
            return
        self.fabrica.enviar(m, self)


class Fabrica:
    """Fila de cortes: corta, julga, renderiza e publica (ou manda pra revisão)."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.pasta = os.path.join(cfg["geral"]["pasta_trabalho"], "clipes")
        os.makedirs(self.pasta, exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=cfg["geral"]["workers_corte"])
        self.trava = threading.Lock()
        self.log = logging.getLogger("fabrica")
        self.ffprobe = shutil.which("ffprobe") or "ffprobe"

    # ---------- registro dos clipes (um meta.json por pasta) ----------
    def listar(self):
        metas = []
        for cam in glob.glob(os.path.join(self.pasta, "*", "meta.json")):
            try:
                with open(cam, encoding="utf-8") as f:
                    metas.append(json.load(f))
            except Exception:
                pass
        return sorted(metas, key=lambda m: m.get("criado", 0), reverse=True)

    def ler(self, cid):
        cam = os.path.join(self.pasta, os.path.basename(cid), "meta.json")
        with open(cam, encoding="utf-8") as f:
            return json.load(f)

    def salvar(self, meta):
        with self.trava:
            cam = os.path.join(self.pasta, meta["id"], "meta.json")
            with open(cam + ".tmp", "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            os.replace(cam + ".tmp", cam)

    # ---------- fluxo ----------
    def enviar(self, momento, vigia):
        self.pool.submit(self._processar, momento, vigia)

    def _processar(self, m, vigia):
        try:
            self._processar_seguro(m, vigia)
        except Exception as e:
            self.log.exception("Erro processando momento de %s: %s", m.canal, e)

    def _processar_seguro(self, m, vigia):
        cfg, c = self.cfg, self.cfg["corte"]
        canal = vigia.canal
        t0 = m.instante - c["antes_segundos"] - c["atraso_live_segundos"]
        t1 = m.instante + c["depois_segundos"] - c["atraso_live_segundos"]
        limite = time.time() + c["depois_segundos"] + 40
        while vigia.buffer.ultimo_fim() < t1 and time.time() < limite:
            time.sleep(1)  # espera a live "andar" até o fim da janela
        segs = vigia.buffer.pegar(t0, t1)
        if not segs:
            self.log.warning("Sem vídeo no replay para o momento de %s.", m.canal)
            return
        try:
            cid = f"{canal['nome']}_{time.strftime('%Y%m%d_%H%M%S', time.localtime(m.instante))}"
            pasta = os.path.join(self.pasta, cid)
            os.makedirs(pasta, exist_ok=True)
            lista = corte.escrever_lista(segs, pasta)
            ini = max(0.0, t0 - segs[0].inicio)
            dur = min(t1, segs[-1].fim) - max(t0, segs[0].inicio)
            ff = cfg["geral"]["ffmpeg"]
            self.log.info("Cortando %s (%.0f s de vídeo)...", cid, dur)

            palavras = []
            if c["legenda"] or cfg["ia"]["usar_claude"]:
                wav = corte.extrair_audio(ff, lista, ini, dur, pasta)
                palavras = ia.transcrever(wav, c["modelo_whisper"], canal.get("idioma", c["idioma"]), c.get("whisper_dispositivo", "auto"))
            decisao = ia.julgar(cfg, canal, palavras, m.amostra_chat, dur)

            meta = {"id": cid, "canal": canal["nome"], "criado": m.instante, "score": m.score,
                    "motivo": m.motivo, "manual": m.manual, "titulo": decisao["titulo"],
                    "descricao": decisao["descricao"], "hashtags": decisao.get("hashtags", []),
                    "hashtags_fixas": canal.get("hashtags", []), "nota_ia": decisao.get("nota"),
                    "motivo_ia": decisao.get("motivo"), "destinos": canal["publicar_em"],
                    "video": os.path.join(pasta, "final.mp4"), "status": "renderizando",
                    "resultados": {}}

            if not decisao["publicar"] and cfg["ia"]["respeitar_descarte"] and not m.manual:
                meta["status"] = "descartado_ia"
                self.salvar(meta)
                self.log.info("Claude descartou %s: %s", cid, decisao.get("motivo"))
                return
            self.salvar(meta)

            layout, facecam = vigia.layout_atual, vigia.facecam_atual  # fotografa o layout deste corte
            a, b = decisao["inicio"], decisao["fim"]
            b = min(b, a + c["duracao_maxima"])
            ass = None
            if c["legenda"] and palavras:
                pal = [(p0 - a, p1 - a, w) for p0, p1, w in palavras if p0 >= a and p1 <= b]
                if pal:
                    ass = corte.gerar_ass(pal, os.path.join(pasta, "legenda.ass"),
                                          corte.altura_legenda(layout))
            corte.renderizar(ff, self.ffprobe, lista, ini + a, b - a, pasta, layout,
                             facecam, canal.get("centro_x", 0.5), ass, c["fps"], c["crf"],
                             primeiro_seg=segs[0].caminho)
        finally:
            vigia.buffer.soltar(segs)

        meta["duracao"] = round(b - a, 1)
        modo = cfg["publicacao"]["modo"]
        if modo == "auto" and meta["destinos"]:
            self.publicar(meta)
        else:
            meta["status"] = "pendente" if modo == "revisao" else "pronto"
            self.salvar(meta)
            self.log.info("Clipe pronto (%s): %s | %s", meta["status"], cid, meta["titulo"])

    def publicar(self, meta, titulo=None):
        if titulo:
            meta["titulo"] = titulo
        meta["status"] = "publicando"
        self.salvar(meta)
        meta["resultados"] = publicar(self.cfg, meta, meta["destinos"])
        erros = [v for v in meta["resultados"].values() if str(v).startswith("ERRO")]
        meta["status"] = "erro" if erros and len(erros) == len(meta["resultados"]) else "publicado"
        self.salvar(meta)
        self.log.info("%s -> %s", meta["id"], meta["resultados"])

    def destinos_atuais(self, meta):
        """Destinos do clipe; se o clipe não tinha nenhum, usa o publicar_em atual do canal no config."""
        if meta.get("destinos"):
            return meta["destinos"]
        canal = next((c for c in self.cfg["canais"] if c["nome"] == meta.get("canal")), None)
        return list(canal.get("publicar_em", [])) if canal else []

    def publicar_async(self, cid, titulo=None):
        meta = self.ler(cid)
        meta["destinos"] = self.destinos_atuais(meta)
        if not meta["destinos"]:
            raise ValueError(f"o canal '{meta.get('canal')}' não tem destino: coloque publicar_em no config.yaml")
        if meta["status"] in ("pendente", "pronto", "erro"):
            self.pool.submit(self.publicar, meta, titulo)

    def mudar_titulo(self, cid, titulo):
        meta = self.ler(cid)
        if meta.get("status") not in ("pendente", "pronto", "erro"):
            raise RuntimeError("esse clipe não pode mais ser editado")
        if not titulo:
            raise ValueError("o título não pode ficar vazio")
        meta["titulo"] = titulo[:100]
        self.salvar(meta)

    def excluir(self, cid):
        """Apaga o clipe do painel e a pasta dele do disco (vídeo, legenda, áudio...)."""
        meta = self.ler(cid)
        if meta.get("status") in ("renderizando", "publicando"):
            raise RuntimeError("clipe ainda em andamento; espere terminar")
        shutil.rmtree(os.path.join(self.pasta, os.path.basename(cid)), ignore_errors=True)
        self.log.info("Clipe excluído: %s", cid)

    def limpar_descartados(self):
        n = 0
        for m in self.listar():
            if m.get("status") in ("descartado", "descartado_ia"):
                shutil.rmtree(os.path.join(self.pasta, m["id"]), ignore_errors=True)
                n += 1
        self.log.info("Limpeza: %d clipe(s) descartado(s) apagado(s).", n)
        return n

    def lote(self, acao, ids):
        """Aplica uma ação em vários clipes. Os que não podem receber a ação são pulados (com o motivo)."""
        feitos, pulados = 0, {}
        for cid in ids:
            try:
                if acao == "publicar":
                    meta = self.ler(cid)
                    if not os.path.exists(meta.get("video", "") or ""):
                        raise RuntimeError("sem vídeo")
                    if meta.get("status") not in ("pendente", "pronto", "erro"):
                        raise RuntimeError("já publicado ou em andamento")
                    self.publicar_async(cid)
                elif acao == "descartar":
                    if self.ler(cid).get("status") not in ("pendente", "pronto", "erro"):
                        raise RuntimeError("não pode ser descartado nesse estado")
                    self.descartar(cid)
                elif acao == "excluir":
                    self.excluir(cid)
                else:
                    raise ValueError(f"ação desconhecida: {acao}")
                feitos += 1
            except FileNotFoundError:
                pulados[cid] = "não encontrado"
            except (RuntimeError, ValueError) as e:
                pulados[cid] = str(e)
        self.log.info("Lote '%s': %d feito(s), %d pulado(s).", acao, feitos, len(pulados))
        return {"feitos": feitos, "pulados": pulados}

    def descartar(self, cid):
        meta = self.ler(cid)
        meta["status"] = "descartado"
        self.salvar(meta)
