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
        self.ativo = lambda: True  # o Vigia troca por "a live está no ar?"
        self._ultimo_erro, self._repeticoes = None, 0

    def parar(self):
        self.parar_evt.set()

    def no_ar(self):
        return self.ativo() and not self.parar_evt.is_set()

    def run(self):
        while not self.parar_evt.is_set():
            if not self.ativo():  # live offline: nem tenta conectar o chat
                self.parar_evt.wait(5)
                continue
            try:
                self.ler()
                self._ultimo_erro, self._repeticoes = None, 0
            except Exception as e:
                if self.ativo():
                    self._avisar(str(e))
            self.parar_evt.wait(15)

    def _avisar(self, erro):
        """Mostra o erro na primeira vez e depois só a cada ~5 min, pra não encher o console."""
        if erro == self._ultimo_erro:
            self._repeticoes += 1
            if self._repeticoes % 20:
                return
            self.log.warning("Chat ainda sem conexão (%s). Continuo tentando.", erro)
            return
        self._ultimo_erro, self._repeticoes = erro, 0
        self.log.warning("Chat caiu (%s). Tentando de novo a cada 15 s.", erro)

    def ler(self):
        raise NotImplementedError


class ChatTwitch(LeitorChat):
    """Chat da Twitch como espectador anônimo (justinfan, só leitura).
    Tenta o IRC normal (porta 6667) e, se a rede bloquear, o IRC por WebSocket (porta 443)."""

    def _linha(self, linha):
        if " PRIVMSG " in linha:
            self.ao_msg(linha.split(" :", 1)[1] if " :" in linha else "", time.time())

    def ler(self):
        canal = str(self.canal["canal"]).lower().rstrip("/").split("/")[-1]
        try:
            self._ler_irc(canal)
        except (socket.gaierror, ConnectionRefusedError, socket.timeout) as e:
            self.log.debug("IRC normal falhou (%s); tentando por WebSocket.", e)
            self._ler_websocket(canal)

    def _ler_irc(self, canal):
        s = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=20)
        s.settimeout(400)
        s.sendall(f"NICK justinfan{random.randint(10000, 99999)}\r\n".encode())
        s.sendall(f"JOIN #{canal}\r\n".encode())
        self.log.info("Chat da Twitch conectado (#%s)", canal)
        resto = b""
        try:
            while self.no_ar():
                dados = s.recv(8192)
                if not dados:
                    raise ConnectionError("conexão fechada")
                resto += dados
                *linhas, resto = resto.split(b"\r\n")
                for bruta in linhas:
                    linha = bruta.decode("utf-8", errors="ignore")
                    if linha.startswith("PING"):
                        s.sendall(b"PONG :tmi.twitch.tv\r\n")
                    else:
                        self._linha(linha)
        finally:
            s.close()

    def _ler_websocket(self, canal):
        import websocket  # websocket-client
        ws = websocket.create_connection("wss://irc-ws.chat.twitch.tv:443", timeout=400)
        ws.send(f"NICK justinfan{random.randint(10000, 99999)}")
        ws.send(f"JOIN #{canal}")
        self.log.info("Chat da Twitch conectado por WebSocket (#%s)", canal)
        try:
            while self.no_ar():
                for linha in ws.recv().split("\r\n"):
                    if linha.startswith("PING"):
                        ws.send("PONG :tmi.twitch.tv")
                    elif linha:
                        self._linha(linha)
        finally:
            ws.close()


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
            while self.no_ar():
                bruto = ws.recv()
                if not bruto or not isinstance(bruto, str):
                    continue  # quadro vazio/controle: a Kick manda às vezes, não é queda
                try:
                    msg = json.loads(bruto)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                ev = msg.get("event", "")
                if ev == "pusher:ping":
                    ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
                elif ev.endswith("ChatMessageEvent"):
                    dados = msg.get("data")
                    try:
                        dados = json.loads(dados) if isinstance(dados, str) else dados
                    except ValueError:
                        continue
                    if not isinstance(dados, dict):
                        continue
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
            while self.no_ar():
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
