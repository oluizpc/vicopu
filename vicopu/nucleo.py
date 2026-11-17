"""Junta tudo: VIgia (captura + chat + detector) -> COrta -> PUblica."""
import glob
import json
import logging
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import corte, ia
from .captura import Buffer, Captura, volume_medio
from .chat import criar_leitor
from .detector import Detector
from .publicar import publicar


# estados em que o clipe ainda pode ter título editado e ser publicado (descartado = resgate manual)
EDITAVEIS = ("pendente", "pronto", "erro", "descartado", "descartado_ia")

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
        self.captura = Captura(canal, cfg, self.buffer, self._segmento, self.detector.reiniciar)
        self.chat = criar_leitor(canal, cfg, self.detector.nova_msg)
        if self.chat:
            self.chat.ativo = lambda: self.captura.no_ar  # chat só conecta com a live no ar
        self.log = logging.getLogger(f"vigia.{canal['nome']}")
        # layout "auto": começa no blur e troca pro split quando achar a webcam
        self.automatico = canal["layout"] == "auto" or canal.get("facecam") == "auto"
        self.layout_atual = "blur" if self.automatico else canal["layout"]
        self.facecam_atual = None if self.automatico else canal.get("facecam")
        if self.automatico:
            salva = self._cam_salva()
            if salva:  # usa a cam achada na última vez já no primeiro corte (e confere de novo depois)
                self.layout_atual, self.facecam_atual = "split", salva
                self.log.info("Usando a cam achada da última vez: %s", salva)

    def _arquivo_cam(self):
        return os.path.join(self.cfg["geral"]["pasta_trabalho"], "camauto", f"{self.canal['nome']}.json")

    def _cam_salva(self):
        try:
            with open(self._arquivo_cam(), encoding="utf-8") as f:
                caixa = json.load(f)
            return caixa if all(k in caixa for k in ("x", "y", "w", "h")) else None
        except (OSError, ValueError, TypeError):
            return None

    def _salvar_cam(self, caixa):
        try:
            os.makedirs(os.path.dirname(self._arquivo_cam()), exist_ok=True)
            with open(self._arquivo_cam(), "w", encoding="utf-8") as f:
                json.dump(caixa, f)
        except OSError:
            pass

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
                self._salvar_cam(caixa)
                self.log.info("Layout automático: split")
                self.captura.parar_evt.wait(15 * 60)
            elif self.facecam_atual:
                # não achou agora (streamer saiu da frente da cam, cena de transição...):
                # mantém a cam que já funcionava e tenta de novo em 2 min
                self.log.info("Não achei a cam agora; mantendo a anterior e tentando de novo em 2 min.")
                self.captura.parar_evt.wait(120)
            else:
                self.layout_atual = "blur"
                self.log.info("Layout automático: blur (sem cam achada; tento de novo em 2 min)")
                self.captura.parar_evt.wait(120)

    def mudar_sensibilidade(self, nivel):
        nivel = str(nivel).lower()
        if nivel not in SENSIBILIDADES:
            raise ValueError("sensibilidade inválida (alta, normal ou baixa)")
        self.canal["sensibilidade"] = nivel
        self.detector.c.update(deteccao_do_canal(self.cfg, self.canal))
        self.log.info("Sensibilidade agora: %s", nivel)

    def termometro(self):
        try:
            e = self.detector.estado()
        except Exception:  # noqa: BLE001
            return None
        aquecendo = time.time() - self.detector.inicio < self.detector.c["aquecimento_segundos"]
        return {"msgs": e["n"], "normal": round(e["base"] or 0, 1), "score": round(e["score"], 2),
                "limiar": self.detector.c["limiar_score"], "aquecendo": aquecendo,
                "janela": self.detector.c["janela_segundos"]}

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
            try:  # trecho bruto guardado pra poder ajustar o corte depois no painel
                corte.guardar_fonte(ff, lista, pasta)
            except Exception as e:  # noqa: BLE001
                self.log.warning("Não guardei o trecho bruto de %s (ajuste do corte indisponível): %s", cid, e)

            palavras = []
            if c["legenda"] or cfg["ia"]["usar_claude"]:
                wav = corte.extrair_audio(ff, lista, ini, dur, pasta)
                palavras = ia.transcrever(wav, c["modelo_whisper"], canal.get("idioma", c["idioma"]), c.get("whisper_dispositivo", "auto"))
            decisao = ia.julgar(cfg, canal, palavras, m.amostra_chat, dur)

            try:
                with open(os.path.join(pasta, "palavras.json"), "w", encoding="utf-8") as f:
                    json.dump(palavras, f)
            except (OSError, TypeError):
                pass
            meta = {"id": cid, "canal": canal["nome"], "criado": m.instante, "score": m.score,
                    "fonte_ini": ini, "janela": round(dur, 2),
                    "motivo": m.motivo, "manual": m.manual, "titulo": decisao["titulo"],
                    "descricao": decisao["descricao"], "hashtags": decisao.get("hashtags", []),
                    "hashtags_fixas": canal.get("hashtags", []), "nota_ia": decisao.get("nota"),
                    "motivo_ia": decisao.get("motivo"), "destinos": canal["publicar_em"],
                    "video": os.path.join(pasta, "final.mp4"), "status": "renderizando",
                    "resultados": {}}

            descartou = (not decisao["publicar"] and cfg["ia"]["respeitar_descarte"] and not m.manual)
            if descartou and not cfg["ia"].get("montar_descartados", True):
                meta["status"] = "descartado_ia"
                self.salvar(meta)
                self.log.info("Claude descartou %s: %s", cid, decisao.get("motivo"))
                return
            meta["descartado_pela_ia"] = descartou
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
                             primeiro_seg=segs[0].caminho, encoder=c.get("encoder", "auto"))
            meta.update({"corte": [round(a, 2), round(b, 2)], "layout": layout, "facecam": facecam,
                         "legenda": bool(ass), "centro_x": canal.get("centro_x", 0.5), "versao": 1})
        finally:
            vigia.buffer.soltar(segs)

        meta["duracao"] = round(b - a, 1)
        modo = cfg["publicacao"]["modo"]
        if meta.get("descartado_pela_ia"):
            # monta mesmo assim pra você poder assistir e, se a IA errou, publicar na mão
            meta["status"] = "descartado_ia"
            self.salvar(meta)
            self.log.info("Claude descartou %s (vídeo montado; dá pra ver e publicar no painel, aba Descartados): %s",
                          cid, decisao.get("motivo"))
        elif modo == "auto" and meta["destinos"]:
            self.publicar(meta)
        else:
            meta["status"] = "pendente" if modo == "revisao" else "pronto"
            self.salvar(meta)
            self.log.info("Clipe pronto (%s): %s | %s", meta["status"], cid, meta["titulo"])

    def remontar(self, cid, inicio, fim, layout, legenda, cam_do_canal=None):
        """Ajusta o corte (início/fim dentro da janela gravada), o layout e a legenda, e monta de novo."""
        meta = self.ler(cid)
        if meta.get("status") in ("renderizando", "publicando"):
            raise RuntimeError("esse clipe ainda está sendo montado ou publicado; espere terminar")
        if meta.get("status") not in EDITAVEIS:
            raise RuntimeError("esse clipe não pode mais ser editado")
        pasta = os.path.join(self.pasta, os.path.basename(cid))
        if not os.path.exists(os.path.join(pasta, "fonte.ts")):
            raise RuntimeError("esse clipe não tem o trecho bruto guardado (é de antes dessa função)")
        janela = float(meta.get("janela") or 0)
        inicio, fim = max(0.0, float(inicio)), min(janela, float(fim))
        if fim - inicio < 3:
            raise ValueError("o corte precisa ter pelo menos 3 segundos")
        if fim - inicio > self.cfg["corte"]["duracao_maxima"] + 0.5:
            raise ValueError(f"o corte passa de {self.cfg['corte']['duracao_maxima']} s")
        if layout not in ("split", "blur", "centro"):
            raise ValueError("layout inválido")
        facecam = meta.get("facecam")
        if layout == "split" and not facecam:
            facecam = cam_do_canal
            if not facecam:
                raise ValueError("não tenho a posição da cam desse canal pra montar em split")
        anterior = meta["status"]
        meta["status"] = "renderizando"
        self.salvar(meta)
        self.pool.submit(self._remontar, meta, anterior, inicio, fim, layout, facecam, bool(legenda))

    def _remontar(self, meta, anterior, a, b, layout, facecam, legenda):
        c = self.cfg["corte"]
        pasta = os.path.join(self.pasta, meta["id"])
        try:
            ass = None
            if legenda:
                try:
                    with open(os.path.join(pasta, "palavras.json"), encoding="utf-8") as f:
                        palavras = json.load(f)
                except (OSError, ValueError):
                    palavras = []
                pal = [(p0 - a, p1 - a, w) for p0, p1, w in palavras if p0 >= a and p1 <= b]
                if pal:
                    ass = corte.gerar_ass(pal, os.path.join(pasta, "legenda.ass"), corte.altura_legenda(layout))
            corte.renderizar(self.cfg["geral"]["ffmpeg"], self.ffprobe, os.path.join(pasta, "lista_fonte.txt"),
                             float(meta.get("fonte_ini", 0)) + a, b - a, pasta, layout, facecam,
                             meta.get("centro_x", 0.5), ass, c["fps"], c["crf"],
                             primeiro_seg=os.path.join(pasta, "fonte.ts"), encoder=c.get("encoder", "auto"),
                             saida="novo.mp4")
            for tentativa in range(10):  # no Windows o vídeo pode estar aberto no navegador por um instante
                try:
                    os.replace(os.path.join(pasta, "novo.mp4"), os.path.join(pasta, "final.mp4"))
                    break
                except PermissionError:
                    time.sleep(0.5)
            else:
                raise RuntimeError("não consegui trocar o vídeo (arquivo em uso)")
            meta.update({"corte": [round(a, 2), round(b, 2)], "layout": layout, "facecam": facecam,
                         "legenda": bool(ass), "duracao": round(b - a, 1),
                         "versao": int(meta.get("versao") or 1) + 1})
            self.log.info("Clipe remontado: %s (%.1f–%.1f s, %s%s)", meta["id"], a, b, layout,
                          ", com legenda" if ass else "")
        except Exception as e:  # noqa: BLE001
            self.log.exception("Falha ao remontar %s: %s", meta["id"], e)
        finally:
            meta["status"] = anterior
            self.salvar(meta)

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
        if meta["status"] in EDITAVEIS:
            self.pool.submit(self.publicar, meta, titulo)
        else:
            raise RuntimeError("esse clipe já foi publicado ou está em andamento")

    def mudar_titulo(self, cid, titulo):
        meta = self.ler(cid)
        if meta.get("status") not in EDITAVEIS:
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
                    if meta.get("status") not in EDITAVEIS:
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


class Central:
    """Lista de lives vigiadas, que pode mudar com o VICOPU rodando (adicionar/parar/retomar pelo painel).

    Parar é lembrado: a live continua parada quando você reinicia, até clicar em 'Vigiar de novo'.
    - live do painel: fica em dados/canais_painel.yaml com parado: true
    - live do config.yaml: o nome vai pra dados/lives_paradas.yaml (o config.yaml não é mexido)
    """

    def __init__(self, cfg, fabrica):
        self.cfg, self.fabrica = cfg, fabrica
        self.trava = threading.Lock()
        self.log = logging.getLogger("vicopu")
        self.vigias = [Vigia(c, cfg, fabrica) for c in cfg["canais"]
                       if not c.get("parado") and not c.get("removido")]

    def lista(self):
        with self.trava:
            return list(self.vigias)

    def paradas(self):
        with self.trava:
            return [c for c in self.cfg["canais"] if c.get("parado") and not c.get("removido")]

    def por_nome(self, nome):
        return next((v for v in self.lista() if v.canal["nome"] == nome), None)

    def iniciar(self):
        for v in self.lista():
            v.iniciar()

    def _persistir(self):
        from .config import salvar_canais_painel, salvar_paradas
        guardar = [{k: v for k, v in c.items() if k not in ("do_painel", "removido")}
                   for c in self.cfg["canais"] if c.get("do_painel") and not c.get("removido")]
        salvar_canais_painel(self.cfg, guardar)
        salvar_paradas(self.cfg, {c["nome"] for c in self.cfg["canais"]
                                  if c.get("parado") and not c.get("do_painel")})

    def adicionar(self, dados):
        from .config import canal_do_link, preparar_canal
        canal = canal_do_link(dados.get("link"))
        apelido = (dados.get("apelido") or "").strip()
        if apelido:
            canal["apelido"] = apelido[:60]
        nome = re.sub(r"[^\w\-]", "", (dados.get("nome") or canal["nome"]).strip())[:40] or "live"
        canal["nome"] = nome
        canal["layout"] = "auto"
        sens = str(dados.get("sensibilidade") or "normal").lower()
        if sens not in SENSIBILIDADES:
            raise ValueError("sensibilidade inválida")
        canal["sensibilidade"] = sens
        idioma = (dados.get("idioma") or "").strip().lower()
        if idioma and idioma != "padrao":
            canal["idioma"] = "" if idioma == "auto" else idioma[:5]
        # destino: o mesmo do primeiro canal do config (pra não publicar em lugar inesperado)
        base = next((c for c in self.cfg["canais"] if c.get("publicar_em") and not c.get("do_painel")), None) \
            or next((c for c in self.cfg["canais"] if c.get("publicar_em")), None)
        canal["publicar_em"] = list(base["publicar_em"]) if base else []
        if base and base.get("hashtags"):
            canal["hashtags"] = list(base["hashtags"])
        preparar_canal(self.cfg, canal)
        with self.trava:
            if any(v.canal["nome"] == nome for v in self.vigias):
                raise ValueError(f"já existe uma live chamada '{nome}'")
            parada = next((c for c in self.cfg["canais"] if c["nome"] == nome and c.get("parado")
                           and not c.get("removido")), None)
        if parada:  # já existia e estava parada: só volta a vigiar
            self.retomar(nome)
            return nome
        with self.trava:
            self.cfg["canais"] = [c for c in self.cfg["canais"]
                                  if not (c.get("removido") and c["nome"] == nome)]
            canal["do_painel"] = True
            self.cfg["canais"].append(canal)
            v = Vigia(canal, self.cfg, self.fabrica)
            self.vigias.append(v)
        v.iniciar()
        self._persistir()
        self.log.info("Live adicionada pelo painel: %s (%s %s)", nome, canal["plataforma"], canal["canal"])
        return nome

    def mudar_sensibilidade(self, nome, nivel):
        v = self.por_nome(nome)
        if not v:
            raise ValueError("live não encontrada")
        v.mudar_sensibilidade(nivel)
        if v.canal.get("do_painel"):
            self._persistir()

    def remover(self, nome):
        """Para de vigiar e lembra disso (continua parada ao reiniciar)."""
        with self.trava:
            v = next((x for x in self.vigias if x.canal["nome"] == nome), None)
            if not v:
                raise ValueError("live não encontrada")
            self.vigias.remove(v)
            v.canal["parado"] = True
        v.parar()
        self._persistir()
        self.log.info("Parei de vigiar %s (fica parada até você clicar em 'Vigiar de novo')", nome)

    def retomar(self, nome):
        with self.trava:
            if any(v.canal["nome"] == nome for v in self.vigias):
                raise ValueError(f"{nome} já está sendo vigiada")
            canal = next((c for c in self.cfg["canais"] if c["nome"] == nome and c.get("parado")
                          and not c.get("removido")), None)
            if not canal:
                raise ValueError("live parada não encontrada")
            canal.pop("parado", None)
            v = Vigia(canal, self.cfg, self.fabrica)
            self.vigias.append(v)
        v.iniciar()
        self._persistir()
        self.log.info("Voltei a vigiar %s", nome)

    def esquecer(self, nome):
        """Tira de vez uma live parada que foi adicionada pelo painel."""
        with self.trava:
            canal = next((c for c in self.cfg["canais"] if c["nome"] == nome and c.get("parado")
                          and not c.get("removido")), None)
            if not canal:
                raise ValueError("live parada não encontrada")
            if not canal.get("do_painel"):
                raise ValueError(f"{nome} está no config.yaml: pra tirar de vez, apague de lá")
            canal["removido"] = True  # some do arquivo; o crédito dos clipes antigos continua
        self._persistir()
        self.log.info("Live %s tirada da lista", nome)
