"""VIGIA, parte 1: puxa a live sem parar e guarda os últimos minutos em pedaços (replay)."""
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass

from .config import url_da_live


@dataclass
class Segmento:
    caminho: str
    inicio: float  # horário real (time.time) em que o trecho começou
    fim: float


class Buffer:
    """Replay em memória: lista de segmentos recentes, com proteção para os que estão sendo cortados."""

    def __init__(self, segundos_max):
        self.segundos_max = segundos_max
        self.segmentos = []
        self.presos = Counter()
        self.trava = threading.Lock()

    def adicionar(self, seg):
        with self.trava:
            self.segmentos.append(seg)
            limite = time.time() - self.segundos_max
            manter = []
            for s in self.segmentos:
                if s.fim < limite and self.presos[s.caminho] == 0:
                    try:
                        os.remove(s.caminho)
                    except OSError:
                        pass
                else:
                    manter.append(s)
            self.segmentos = manter

    def ultimo_fim(self):
        with self.trava:
            return self.segmentos[-1].fim if self.segmentos else 0.0

    def pegar(self, t0, t1):
        """Segmentos que cobrem [t0, t1], já presos (não serão apagados até soltar)."""
        with self.trava:
            segs = [s for s in self.segmentos if s.fim > t0 and s.inicio < t1]
            for s in segs:
                self.presos[s.caminho] += 1
            return segs

    def soltar(self, segs):
        with self.trava:
            for s in segs:
                self.presos[s.caminho] -= 1
                if self.presos[s.caminho] <= 0:
                    del self.presos[s.caminho]


class Captura(threading.Thread):
    """streamlink -> ffmpeg (segmentador). Reconecta sozinho quando a live cai ou ainda não começou."""

    def __init__(self, canal, cfg, buffer, ao_segmento=None):
        super().__init__(daemon=True, name=f"captura-{canal['nome']}")
        self.canal = canal
        self.cfg = cfg
        self.buffer = buffer
        self.ao_segmento = ao_segmento
        self.parar_evt = threading.Event()
        self.log = logging.getLogger(f"vigia.{canal['nome']}")
        self.no_ar = False
        self.procs = []

    def parar(self):
        self.parar_evt.set()
        for p in self.procs:
            try:
                p.kill()
            except Exception:
                pass

    def _comandos(self, pasta):
        g = self.cfg["geral"]
        url = url_da_live(self.canal)
        saida = [
            g["ffmpeg"], "-hide_banner", "-loglevel", "error",
        ]
        fonte = None
        if self.canal["plataforma"].lower() == "arquivo":
            # Live simulada: lê um arquivo em velocidade real, em loop. Ótimo para testar.
            saida += ["-re", "-stream_loop", "-1", "-i", url]
        else:
            fonte = [
                sys.executable, "-m", "streamlink", "--stdout", "--loglevel", "warning",
                "--hls-live-edge", "2", "--stream-segment-threads", "2",
            ]
            if self.canal["plataforma"].lower() == "twitch":
                fonte += ["--twitch-low-latency"]  # streamlink 7+ já pula os anúncios sozinho
            fonte += [url, self.canal.get("qualidade", g["qualidade_stream"])]
            saida += ["-i", "pipe:0"]
        saida += [
            "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
            "-f", "segment", "-segment_time", str(g["segundos_por_segmento"]),
            "-segment_format", "mpegts", "-reset_timestamps", "1",
            "-segment_list", os.path.join(pasta, "lista.csv"),
            "-segment_list_type", "csv", "-segment_list_flags", "+live",
            os.path.join(pasta, "seg_%08d.ts"),
        ]
        return fonte, saida

    def run(self):
        base = os.path.join(self.cfg["geral"]["pasta_trabalho"], "buffer", self.canal["nome"])
        while not self.parar_evt.is_set():
            pasta = os.path.join(base, time.strftime("%Y%m%d_%H%M%S"))
            os.makedirs(pasta, exist_ok=True)
            fonte, cmd_ffmpeg = self._comandos(pasta)
            self.procs = []
            try:
                if fonte:
                    p1 = subprocess.Popen(fonte, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    p2 = subprocess.Popen(cmd_ffmpeg, stdin=p1.stdout, stderr=subprocess.PIPE)
                    p1.stdout.close()
                    self.procs = [p1, p2]
                else:
                    p2 = subprocess.Popen(cmd_ffmpeg, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    self.procs = [p2]
                self.log.info("Conectando em %s", url_da_live(self.canal))
                self._acompanhar_lista(pasta, p2)
            except FileNotFoundError as e:
                self.log.error("Programa não encontrado (%s). Instale ffmpeg/streamlink.", e)
            finally:
                self.no_ar = False
                for p in self.procs:
                    try:
                        p.kill()
                    except Exception:
                        pass
                erro = ""
                for p in self.procs:
                    try:
                        erro += (p.stderr.read() or b"").decode(errors="ignore")[-400:]
                    except Exception:
                        pass
                if erro.strip() and not self.parar_evt.is_set():
                    self.log.info("Captura encerrou: %s", erro.strip().splitlines()[-1])
            if not self.parar_evt.is_set():
                self.log.info("Live offline ou caiu. Tentando de novo em 30 s.")
                self.parar_evt.wait(30)
                shutil.rmtree(pasta, ignore_errors=True)

    def _acompanhar_lista(self, pasta, proc):
        lista = os.path.join(pasta, "lista.csv")
        lidas = 0
        while not self.parar_evt.is_set():
            if proc.poll() is not None:
                return
            if os.path.exists(lista):
                with open(lista, encoding="utf-8", errors="ignore") as f:
                    linhas = f.read().splitlines()
                for linha in linhas[lidas:]:
                    m = re.match(r"^(.+?),([\d.]+),([\d.]+)$", linha.strip())
                    if not m:
                        continue
                    dur = max(0.1, float(m.group(3)) - float(m.group(2)))
                    agora = time.time()
                    seg = Segmento(os.path.join(pasta, m.group(1)), agora - dur, agora)
                    self.buffer.adicionar(seg)
                    if not self.no_ar:
                        self.no_ar = True
                        self.log.info("NO AR. Vigiando.")
                    if self.ao_segmento:
                        try:
                            self.ao_segmento(seg)
                        except Exception as e:  # nunca derruba a captura
                            self.log.debug("ao_segmento falhou: %s", e)
                lidas = len(linhas)
            time.sleep(0.5)


def volume_medio(ffmpeg, caminho):
    """Volume médio do trecho em dB (ou None se não tiver áudio)."""
    r = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", caminho, "-vn", "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, timeout=30,
    )
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else None
