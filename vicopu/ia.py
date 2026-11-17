"""Transcrição (Whisper local) e o JUIZ (Claude): vale postar? Qual título? Onde começar e terminar?"""
import json
import logging
import os
import re
import threading

log = logging.getLogger("ia")

_modelo_whisper = None
_dispositivo = None
_trava_whisper = threading.Lock()


def _preparar_dlls_nvidia():
    """No Windows, se os pacotes nvidia-cublas-cu12 / nvidia-cudnn-cu12 estiverem instalados via pip,
    deixa as DLLs deles visíveis pro Whisper usar a placa de vídeo."""
    if os.name != "nt":
        return
    import site
    import glob as _glob
    for base in site.getsitepackages() + [site.getusersitepackages()]:
        for pasta in _glob.glob(os.path.join(base, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(pasta)
            except (OSError, AttributeError):
                pass
            os.environ["PATH"] = pasta + os.pathsep + os.environ.get("PATH", "")


def _carregar(modelo, dispositivo):
    from faster_whisper import WhisperModel
    global _modelo_whisper, _dispositivo
    log.info("Carregando Whisper '%s' em %s...", modelo, dispositivo.upper())
    _modelo_whisper = WhisperModel(modelo, device=dispositivo, compute_type="int8")
    _dispositivo = dispositivo


def _rodar_whisper(audio, idioma):
    segs, _ = _modelo_whisper.transcribe(audio, language=idioma or None, word_timestamps=True,
                                         vad_filter=True)
    palavras = []
    for s in segs:
        for w in (s.words or []):
            palavras.append((float(w.start), float(w.end), w.word))
    return palavras


def transcrever(wav, modelo="small", idioma="pt", dispositivo="auto"):
    """Retorna lista de palavras (inicio, fim, texto). Lista vazia se o faster-whisper não estiver instalado."""
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        log.warning("faster-whisper não instalado: clipe sai sem legenda e com título genérico.")
        return []
    try:
        audio = _ler_wav(wav)
        with _trava_whisper:
            if _modelo_whisper is None:
                if dispositivo != "cpu":
                    _preparar_dlls_nvidia()
                _carregar(modelo, dispositivo)
            try:
                return _rodar_whisper(audio, idioma)
            except Exception as e:
                # placa NVIDIA detectada, mas faltam as bibliotecas CUDA (cublas/cudnn): cai pro processador
                if _dispositivo != "cpu" and any(k in str(e).lower() for k in ("cublas", "cudnn", "cuda")):
                    log.warning("Placa de vídeo sem as bibliotecas CUDA (%s). Usando o processador.", e)
                    _carregar(modelo, "cpu")
                    return _rodar_whisper(audio, idioma)
                raise
    except Exception as e:  # legenda nunca pode derrubar o corte
        log.warning("Transcrição falhou (%s). O clipe sai sem legenda.", e)
        return []


def _ler_wav(caminho):
    """Lê o WAV 16 kHz mono (gerado pelo ffmpeg) direto pra numpy, no formato que o Whisper espera."""
    import wave

    import numpy as np

    with wave.open(caminho, "rb") as w:
        dados = w.readframes(w.getnframes())
    return np.frombuffer(dados, dtype=np.int16).astype(np.float32) / 32768.0


PROMPT = """Você é o editor de cortes de um canal de clipes de lives.{foco}
Recebe a transcrição de um trecho de {dur:.0f}s da live de "{canal}" (tempos em segundos desde o início do trecho)
e uma amostra do chat no momento do pico. Decida se vira um Short/TikTok e prepare a publicação.

Regras:
- publicar=false se o trecho for parado, sem contexto, ou o pico do chat claramente não tem a ver com a live.
- "inicio" e "fim": recorte o melhor pedaço DENTRO do trecho (15 a {maxd}s), começando no gancho, sem enrolação no começo e terminando logo depois da reação/punchline.
- titulo: SEMPRE um título de corte pronto pra postar, MESMO quando publicar=false (o humano pode decidir postar). Nunca escreva o motivo ou a avaliação no título. Até 80 caracteres, em português do Brasil, estilo corte viral (gancho forte, pode usar CAIXA ALTA em 1-2 palavras e 1 emoji). Não invente coisas que não estão na transcrição.
- motivo: aqui sim, explique a avaliação.
- descricao: 1-2 frases curtas PARA O PÚBLICO, que vão na descrição do vídeo (chamam pra assistir e dão contexto do que acontece). NUNCA escreva aqui a sua avaliação, a nota, críticas ao trecho ou o motivo de publicar/não publicar: isso vai só em "motivo".
- hashtags: 3 a 5, sem repetir as fixas: {fixas}.
{extras}
Responda usando a ferramenta avaliar_clipe.

TRANSCRIÇÃO:
{transcricao}

CHAT NO PICO:
{chat}"""


FERRAMENTA_JUIZ = {
    "name": "avaliar_clipe",
    "description": "Decide se o trecho vira clipe e prepara a publicação.",
    "input_schema": {
        "type": "object",
        "properties": {
            "publicar": {"type": "boolean"},
            "nota": {"type": "number", "description": "0 a 10"},
            "inicio": {"type": "number", "description": "segundos desde o início do trecho"},
            "fim": {"type": "number", "description": "segundos desde o início do trecho"},
            "titulo": {"type": "string", "description": "título do clipe pronto pra postar (nunca o motivo da nota)"},
            "descricao": {"type": "string", "description": "texto público da descrição do vídeo (nunca a avaliação)"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "motivo": {"type": "string", "description": "sua avaliação interna: por que publicar ou não (não é publicado)"},
        },
        "required": ["publicar", "nota", "inicio", "fim", "titulo", "descricao", "hashtags", "motivo"],
    },
}


def _texto_transcricao(palavras):
    if not palavras:
        return "(sem fala detectada)"
    linhas, atual, t0 = [], [], None
    for ini, fim, w in palavras:
        if t0 is None:
            t0 = ini
        atual.append(w.strip())
        if len(atual) >= 12:
            linhas.append(f"[{t0:5.1f}-{fim:5.1f}] {' '.join(atual)}")
            atual, t0 = [], None
    if atual:
        linhas.append(f"[{t0:5.1f}-{palavras[-1][1]:5.1f}] {' '.join(atual)}")
    return "\n".join(linhas)


def julgar(cfg, canal, palavras, amostra_chat, duracao):
    nome = canal.get("apelido", canal["nome"])
    fixas = " ".join(canal.get("hashtags", []))
    padrao = {"publicar": True, "nota": 5, "inicio": 0.0, "fim": duracao,
              "titulo": f"MOMENTO INSANO na live do {nome} 😱"[:80],
              "descricao": f"Corte da live do {nome}.", "hashtags": [], "motivo": "sem IA"}
    ia = cfg["ia"]
    if not ia["usar_claude"] or not os.environ.get("ANTHROPIC_API_KEY"):
        return padrao
    try:
        import anthropic
        prompt = PROMPT.format(
            foco=(f" Foco do canal: {ia['foco']}." if ia.get("foco") else ""),
            dur=duracao, canal=nome, maxd=cfg["corte"]["duracao_maxima"], fixas=fixas or "(nenhuma)",
            extras=("- " + ia["instrucoes_extras"]) if ia["instrucoes_extras"] else "",
            transcricao=_texto_transcricao(palavras),
            chat="\n".join(amostra_chat[-30:]) or "(sem chat)")
        r = anthropic.Anthropic().messages.create(
            model=ia["modelo"], max_tokens=700, tools=[FERRAMENTA_JUIZ],
            tool_choice={"type": "tool", "name": "avaliar_clipe"},  # resposta sempre estruturada
            messages=[{"role": "user", "content": prompt}])
        dados = next((b.input for b in r.content if getattr(b, "type", "") == "tool_use"), None)
        if dados is None:
            texto = "".join(getattr(b, "text", "") for b in r.content)
            m = re.search(r"\{.*\}", texto, re.S)
            if not m:
                raise ValueError(f"resposta sem dados: {texto[:200]!r}")
            dados = json.loads(m.group(0))
        saida = {**padrao, **dados}
        saida["inicio"] = max(0.0, float(saida["inicio"]))
        saida["fim"] = min(duracao, float(saida["fim"]))
        if saida["fim"] - saida["inicio"] < 8:  # resposta estranha: usa o trecho todo
            saida["inicio"], saida["fim"] = 0.0, duracao
        return saida
    except Exception as e:
        log.warning("Juiz Claude falhou (%s). Usando título padrão.", e)
        return padrao
