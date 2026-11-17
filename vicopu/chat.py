"""VIGIA, parte 2: lê o chat ao vivo da Twitch, Kick e YouTube (sem precisar de login)."""
import json
import logging
import random
import re
import socket
import threading
import time


class LeitorChat(threading.Thread):
    def __init__(self, canal, cfg, ao_msg):
        super().__init__(daemon=True, name=f"chat-{canal['nome']}")
        self.canal = canal
        self.cfg = cfg
        self.ao_msg = ao_msg
        self.parar_evt = threading.Event()
        self.log = logging.getLogger(f"chat.{canal['nome']}")

    def parar(self):
        self.parar_evt.set()

    def run(self):
        while not self.parar_evt.is_set():
            try:
                self.ler()
            except Exception as e:
                self.log.warning("Chat caiu (%s). Reconectando em 15 s.", e)
            self.parar_evt.wait(15)

    def ler(self):
        raise NotImplementedError


class ChatTwitch(LeitorChat):
    """IRC anônimo da Twitch (usuário justinfan, só leitura)."""

    def ler(self):
        canal = str(self.canal["canal"]).lower().split("/")[-1]
        s = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=400)
        s.sendall(f"NICK justinfan{random.randint(10000, 99999)}\r\n".encode())
        s.sendall(f"JOIN #{canal}\r\n".encode())
        self.log.info("Chat da Twitch conectado (#%s)", canal)
        resto = b""
        try:
            while not self.parar_evt.is_set():
                dados = s.recv(8192)
                if not dados:
                    raise ConnectionError("conexão fechada")
                resto += dados
                *linhas, resto = resto.split(b"\r\n")
                for bruta in linhas:
                    linha = bruta.decode("utf-8", errors="ignore")
                    if linha.startswith("PING"):
                        s.sendall(b"PONG :tmi.twitch.tv\r\n")
                    elif " PRIVMSG " in linha:
                        self.ao_msg(linha.split(" :", 1)[1] if " :" in linha else "", time.time())
        finally:
            s.close()


_EMOTE_KICK = re.compile(r"\[emote:\d+:([^\]]+)\]")


class ChatKick(LeitorChat):
    """WebSocket (Pusher) público do chat da Kick."""

    def _id_sala(self):
        if self.canal.get("kick_chatroom_id"):
            return int(self.canal["kick_chatroom_id"])
        slug = str(self.canal["canal"]).split("/")[-1]
        url = f"https://kick.com/api/v2/channels/{slug}"
        try:  # a Kick fica atrás de Cloudflare; curl_cffi imita um navegador e costuma passar
            from curl_cffi import requests as creq
            r = creq.get(url, impersonate="chrome", timeout=20)
        except ImportError:
            import requests
            r = requests.get(url, timeout=20, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
                "Accept": "application/json"})
        if r.status_code != 200:
            raise RuntimeError(
                f"Kick respondeu {r.status_code} ao buscar o chat. Instale curl_cffi ou coloque "
                f"kick_chatroom_id no config deste canal.")
        return int(r.json()["chatroom"]["id"])

    def ler(self):
        import websocket  # websocket-client

        sala = self._id_sala()
        k = self.cfg["kick"]
        url = (f"wss://ws-{k['pusher_cluster']}.pusher.com/app/{k['pusher_key']}"
               f"?protocol=7&client=js&version=8.4.0&flash=false")
        ws = websocket.create_connection(url, timeout=120)
        ws.send(json.dumps({"event": "pusher:subscribe",
                            "data": {"auth": "", "channel": f"chatrooms.{sala}.v2"}}))
        self.log.info("Chat da Kick conectado (sala %s)", sala)
        try:
            while not self.parar_evt.is_set():
                msg = json.loads(ws.recv())
                ev = msg.get("event", "")
                if ev == "pusher:ping":
                    ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
                elif ev.endswith("ChatMessageEvent"):
                    dados = msg.get("data")
                    dados = json.loads(dados) if isinstance(dados, str) else dados
                    texto = _EMOTE_KICK.sub(r" \1 ", dados.get("content", ""))
                    self.ao_msg(texto, time.time())
        finally:
            ws.close()


def _textos_youtube(obj, saida):
    """Acha as mensagens de chat dentro do JSON do YouTube (texto + nome dos emojis)."""
    if isinstance(obj, dict):
        for chave in ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer"):
            r = obj.get(chave)
            if isinstance(r, dict):
                partes = []
                for run in r.get("message", {}).get("runs", []):
                    if "text" in run:
                        partes.append(run["text"])
                    elif "emoji" in run:
                        e = run["emoji"]
                        partes.append((e.get("shortcuts") or [e.get("emojiId", "")])[0])
                saida.append(" ".join(partes))
                return
        for v in obj.values():
            _textos_youtube(v, saida)
    elif isinstance(obj, list):
        for v in obj:
            _textos_youtube(v, saida)


class ChatYouTube(LeitorChat):
    """Chat ao vivo do YouTube via yt-dlp (atualizado toda semana, não gasta cota da API).

    O yt-dlp grava o chat num arquivo, uma linha JSON por mensagem, conforme chegam; a gente lê o arquivo.
    """

    proc = None

    def parar(self):
        super().parar()
        if self.proc:
            self.proc.kill()

    def ler(self):
        import glob
        import os
        import shutil
        import subprocess
        import sys
        from .config import url_da_live

        pasta = os.path.join(self.cfg["geral"]["pasta_trabalho"], "chat_youtube", self.canal["nome"])
        shutil.rmtree(pasta, ignore_errors=True)
        os.makedirs(pasta, exist_ok=True)
        cmd = [sys.executable, "-m", "yt_dlp", "--skip-download", "--write-subs", "--sub-langs", "live_chat",
               "--no-warnings", "--quiet", "--no-progress", "-o", os.path.join(pasta, "chat.%(ext)s"),
               url_da_live(self.canal)]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        arquivo, f, resto, avisou = None, None, "", False
        try:
            while not self.parar_evt.is_set():
                if f is None:
                    achados = glob.glob(os.path.join(pasta, "*live_chat*"))
                    if achados:
                        arquivo = achados[0]
                        f = open(arquivo, encoding="utf-8", errors="ignore")
                if f is not None:
                    resto += f.read()
                    *linhas, resto = resto.split("\n")
                    for linha in linhas:
                        if not linha.strip():
                            continue
                        if not avisou:
                            self.log.info("Chat do YouTube conectado")
                            avisou = True
                        try:
                            textos = []
                            _textos_youtube(json.loads(linha), textos)
                        except ValueError:
                            continue
                        agora = time.time()
                        for t in textos:
                            self.ao_msg(t, agora)
                if self.proc.poll() is not None:
                    erro = (self.proc.stderr.read() or b"").decode(errors="ignore").strip()
                    raise ConnectionError(erro.splitlines()[-1] if erro else "chat terminou (live acabou?)")
                time.sleep(0.5)
        finally:
            if f:
                f.close()
            if self.proc.poll() is None:
                self.proc.kill()


def criar_leitor(canal, cfg, ao_msg):
    plat = canal["plataforma"].lower()
    if plat == "twitch":
        return ChatTwitch(canal, cfg, ao_msg)
    if plat == "kick":
        return ChatKick(canal, cfg, ao_msg)
    if plat == "youtube":
        return ChatYouTube(canal, cfg, ao_msg)
    return None  # "arquivo" (simulação) não tem chat
