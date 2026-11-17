"""VIGIA, parte 3: decide quando algo aconteceu (pico de chat + palavras-chave + pico de volume)."""
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class Momento:
    canal: str
    instante: float
    score: float
    motivo: str
    amostra_chat: list = field(default_factory=list)
    manual: bool = False


class Detector:
    def __init__(self, nome, cfg_det, ao_momento):
        self.nome = nome
        self.c = cfg_det
        self.ao_momento = ao_momento
        self.msgs = deque()  # (instante, texto, tem_palavra)
        self.base_chat = None
        self.base_audio = None
        self.audio_pico_ate = 0.0
        self.inicio = time.time()
        self.ultimo_disparo = 0.0
        self.trava = threading.Lock()
        self.palavras = [p.lower() for p in self.c["palavras_chave"]]
        self.log = logging.getLogger(f"detector.{nome}")

    def reiniciar(self):
        """A live (re)começou: esquece o ritmo antigo do chat e aprende de novo."""
        with self.trava:
            self.msgs.clear()
        self.base_chat = None
        self.base_audio = None
        self.audio_pico_ate = 0.0
        self.inicio = time.time()

    def _tem_palavra(self, texto):
        t = texto.lower()
        return any(p in t for p in self.palavras)

    def _ignorar(self, texto):
        t = (texto or "").strip().lower()
        if not t:
            return True
        if self.c.get("ignorar_comandos", True) and t.startswith("!"):
            return True  # !sorteio, !pix, !discord... é comando de bot, não reação
        return any(p and p.lower() in t for p in self.c.get("ignorar_palavras", []))

    def nova_msg(self, texto, instante):
        if self._ignorar(texto):
            return
        with self.trava:
            self.msgs.append((instante, texto, self._tem_palavra(texto)))

    def novo_audio(self, db, instante):
        if not self.c["usar_audio"] or db is None or db < -60:
            return
        if self.base_audio is None:
            self.base_audio = db
            return
        if db > self.base_audio + self.c["audio_salto_db"]:
            self.audio_pico_ate = instante + self.c["janela_segundos"]
        else:
            self.base_audio = 0.95 * self.base_audio + 0.05 * db

    def estado(self, agora=None):
        agora = agora or time.time()
        with self.trava:
            while self.msgs and self.msgs[0][0] < agora - self.c["janela_segundos"]:
                self.msgs.popleft()
            n = len(self.msgs)
            kw = sum(1 for m in self.msgs if m[2])
            amostra = [m[1] for m in list(self.msgs)[-40:]]
        base = self.base_chat if self.base_chat is not None else n
        razao = n / max(base, 1.0)
        s_chat = razao / self.c["multiplicador_pico"] if n >= self.c["minimo_mensagens_janela"] else 0.0
        s_kw = self.c["peso_palavras"] * (kw / n) if n >= self.c["minimo_mensagens_janela"] / 2 else 0.0
        s_audio = self.c["peso_audio"] if self.audio_pico_ate > agora else 0.0
        return {"n": n, "kw": kw, "base": base, "razao": razao,
                "score": s_chat + s_kw + s_audio, "s_chat": s_chat, "s_kw": s_kw,
                "s_audio": s_audio, "amostra": amostra}

    def tick(self, agora=None):
        """Chamar 1x por segundo."""
        agora = agora or time.time()
        e = self.estado(agora)
        pico = e["score"] >= self.c["limiar_score"]
        # a média só aprende em momentos normais, pra o pico não "virar o novo normal"
        aquecendo = agora - self.inicio < self.c["aquecimento_segundos"]
        if aquecendo or not pico:
            alfa = 0.1 if aquecendo else 0.015  # aprende rápido no começo, devagar depois
            self.base_chat = e["n"] if self.base_chat is None else (1 - alfa) * self.base_chat + alfa * e["n"]
        if aquecendo:
            return None
        if pico and agora - self.ultimo_disparo >= self.c["cooldown_segundos"]:
            self.ultimo_disparo = agora
            motivo = (f"chat {e['n']} msgs/{self.c['janela_segundos']}s (normal {e['base']:.1f}, "
                      f"x{e['razao']:.1f}), palavras {e['kw']}, áudio {'sim' if e['s_audio'] else 'não'}")
            m = Momento(self.nome, agora, round(e["score"], 2), motivo, e["amostra"])
            self.log.info("MOMENTO! score %.2f | %s", e["score"], motivo)
            self.ao_momento(m)
            return m
        return None

    def manual(self, motivo="disparo manual"):
        m = Momento(self.nome, time.time(), 99.0, motivo, self.estado()["amostra"], manual=True)
        self.ultimo_disparo = m.instante
        self.log.info("Corte manual pedido (%s). Esperando a live andar pra fechar o trecho...", motivo)
        self.ao_momento(m)
        return m
