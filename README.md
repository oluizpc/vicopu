# VICOPU: VIgia, COrta e PUblica

Assiste várias lives ao mesmo tempo (Twitch, Kick e YouTube), detecta os melhores momentos **enquanto a live está rolando**, corta em vertical 1080x1920 com legenda e publica no YouTube Shorts e no TikTok. O clipe fica pronto uns 30 a 60 segundos depois do lance.

```
 live ──► streamlink ──► replay dos últimos 5 min (pedaços de 4 s, sem recodificar)
 chat ──► detector (pico de msgs + "KKKK/CLIPA/KEKW" + pico de volume) ──► MOMENTO!
                                                                  │
            ┌─────────────────────────────────────────────────────┘
            ▼
  recorta 35 s antes + 12 s depois ─► Whisper (legenda) ─► Claude (vale postar? título? onde cortar?)
            ─► ffmpeg 1080x1920 (split / blur / centro) ─► YouTube Shorts + TikTok  (ou painel de revisão)
```

## 1. Instalar

Precisa de **Python 3.10+**, **ffmpeg** e **git** no PATH.

**Windows (Prompt de Comando):**
```bat
cd C:\
git clone https://github.com/oluizpc/vicopu.git
cd vicopu
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy config.exemplo.yaml config.yaml
set ANTHROPIC_API_KEY=sk-ant-...
```

**Linux / Mac:**
```bash
git clone https://github.com/oluizpc/vicopu.git && cd vicopu
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.exemplo.yaml config.yaml
export ANTHROPIC_API_KEY=sk-ant-...
```

**Atualizar** (quando sair correção nova):
```bat
git pull
pip install -r requirements.txt
```
O `config.yaml`, a pasta `dados` e o `.venv` não vão pro git, então o `git pull` não mexe neles.

## 2. Configurar as lives

Edite `canais:` no `config.yaml`. Cada canal tem a plataforma, o nome do canal, o layout e onde publicar.

**Layout automático (`layout: auto`, o padrão):** quando a live entra no ar, o VICOPU procura a webcam do streamer em duas etapas:
1. **Grátis, no seu PC:** detecta o rosto que fica parado no mesmo lugar em vários quadros (a cam; personagens do jogo se mexem) e sai do rosto pra fora até achar a moldura.
2. **Claude, só se precisar:** se não achar rosto (streamer de perfil, cam muito pequena), manda um quadro pro Claude apontar a cam, e um ajuste fino encaixa na moldura. Custa frações de centavo por detecção e precisa da `ANTHROPIC_API_KEY`. Pra nunca usar o Claude nisso, coloque `ia.camauto_claude: false`.

Se achar a cam, o canal usa o split; se não, usa o blur. A detecção se repete a cada 15 minutos, porque o streamer pode mudar a cena. No painel, clique no nome do layout ao lado da live pra ver **onde ele achou a cam** (retângulo verde).

**Calibrar a facecam na mão (layout `split` + `facecam`):** grave uns 30 s da live do streamer (ou baixe um VOD) e rode:

```bash
python -m vicopu testar-layout streamer_twitch amostra.mp4
```

Abra o vídeo gerado e ajuste `facecam: {x, y, w, h}` até a cam ficar certinha. Os valores são frações da tela: `x: 0.75, y: 0.0, w: 0.25, h: 0.3` = canto superior direito.

Layouts disponíveis:
- `auto`: acha a cam sozinho e escolhe entre `split` e `blur`.
- `split`: facecam em cima, jogo embaixo. É o melhor pra streamer com cam.
- `blur`: jogo inteiro no meio, com fundo desfocado. Serve pra quem joga sem cam.
- `centro`: recorte vertical da ação, controlado por `centro_x`.

## 3. Ligar as contas (uma vez)

**YouTube**
1. No Google Cloud Console: crie um projeto, ative a **YouTube Data API v3**, crie um ID do cliente OAuth do tipo *App para computador* e baixe o JSON para `credenciais/youtube_client_secret.json`.
2. Rode `python -m vicopu auth-youtube cortes_principal` e entre com a conta do canal.
3. ⚠️ **Cota:** o padrão do Google dá poucos uploads por dia por projeto, algo como meia dúzia. Pra volume de GTA, peça aumento de cota no Console **já**.

**TikTok**
1. Em developers.tiktok.com: crie um app com *Login Kit* + *Content Posting API*. Os escopos são `video.upload` e `video.publish`, e o redirect URI é qualquer URL https sua.
2. Coloque `TIKTOK_CLIENT_KEY` e `TIKTOK_CLIENT_SECRET` no ambiente e o `redirect_uri` no config.
3. Rode `python -m vicopu auth-tiktok cortes_tiktok`, autorize e cole o endereço de volta.
4. Os modos de publicação:
   - `rascunho` (padrão): o clipe cai no app do TikTok e você só toca em publicar. Funciona sem a auditoria do app.
   - `direto`: publica sozinho, mas **só sai privado até o TikTok aprovar a auditoria do app**. Peça a auditoria cedo.

## 4. Rodar

```bash
python -m vicopu rodar
```

Abra o painel em **http://127.0.0.1:8787**. Lá você vê:
- quais lives estão no ar, com um botão **✂ cortar agora** pra disparar um corte na mão;
- os clipes gerados, com player, título editável e os botões **Publicar** e **Descartar**.

Modos (`publicacao.modo`):
- `revisao`: os clipes esperam sua aprovação no painel. **Recomendado nos primeiros dias**, pra calibrar.
- `auto`: publica sozinho assim que o clipe fica pronto.
- `nenhum`: só gera os arquivos (em `dados/clipes/`).

## 5. Calibrar a detecção

Os ajustes ficam em `deteccao:` no config:

| Problema | O que mexer |
|---|---|
| Corta demais / momentos fracos | aumente `limiar_score` (1.3) ou `multiplicador_pico` (4) |
| Não corta nunca (chat pequeno) | diminua `minimo_mensagens_janela` (4) e `multiplicador_pico` (2) |
| Clipes muito seguidos | aumente `cooldown_segundos` |
| Começa tarde demais / perde o lance | aumente `corte.antes_segundos` |

O log mostra cada disparo com o motivo, por exemplo `chat 48 msgs/10s (normal 9.2, x5.2), palavras 31, áudio sim`. Use isso pra ajustar.

## 6. Quanto de máquina precisa

- **Capturar** é leve: não recodifica, só copia os pedaços. Dá pra vigiar dezenas de lives.
- **Cortar** é o que pesa: cada clipe de 45 s leva uns 10 a 30 s de CPU com o preset `veryfast`. `workers_corte` controla quantos cortes rodam ao mesmo tempo.
- **Whisper `small`** na CPU leva uns 5 a 15 s por clipe. Com GPU NVIDIA, cai pra 1 a 2 s.
- Uma referência, que é estimativa e precisa ser confirmada no teste: uma VPS de 8 vCPU e 16 GB aguenta umas 10 lives com cortes frequentes. Com mais lives, adicione GPU ou mais máquinas, separando os canais em configs diferentes.

## 7. Estrutura

```
vicopu/
  captura.py   VIGIA: streamlink → ffmpeg → replay em pedaços (reconecta sozinho)
  chat.py      VIGIA: chat Twitch (IRC), Kick (Pusher), YouTube (chat-downloader)
  detector.py  VIGIA: pico de chat + palavras-chave + volume → Momento
  corte.py     CORTA: layouts 9:16, legenda ASS estilo viral, render H.264/AAC
  ia.py        Whisper (transcrição) + Claude (juiz: publica? título? início/fim?)
  camauto.py   acha a webcam sozinho (rosto grátis via OpenCV; Claude como reserva)
  nucleo.py    junta tudo: Vigia por canal + Fábrica (fila de cortes)
  publicar/    PUBLICA: youtube.py, tiktok.py
  painel.py    painel web de revisão
```

## 8. Status do teste

- **Testado no Windows com lives reais do YouTube:** captura, chat ao vivo, corte automático por pico de chat e de áudio, layouts split e blur, e painel.
- **Testado aqui, ponta a ponta, com uma live simulada:** captura com replay, pico de chat, disparo no segundo certo, corte, render 1080x1920 30 fps AAC 48 kHz, legenda, layouts split e blur, e painel (listar, player, cortar agora, descartar).
- **Não testado aqui (precisa de internet aberta e das suas contas):** a conexão real com Twitch, Kick e YouTube, os chats ao vivo e o upload pro YouTube e pro TikTok. Rode primeiro com 1 canal em modo `revisao` pra validar.
- **Pontos frágeis:** a Kick às vezes bloqueia a busca do chat. Nesse caso, instale `curl_cffi` ou coloque `kick_chatroom_id` no canal. O chat do YouTube é lido pelo `yt-dlp`. Se ele parar de funcionar, rode `pip install -U yt-dlp`. Mesmo assim, o pico de volume continua funcionando como sinal.

## ⚠️ Direitos

Corte e publique só lives de quem autorizou. YouTube e TikTok punem conteúdo reaproveitado sem permissão, e o streamer pode pedir a derrubada do vídeo.
