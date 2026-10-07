"""Um único worker serializa reconhecimento, consultas e áudio; Qt só recebe sinais."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import logging
import queue
import sys
import threading
import time

from PySide6.QtCore import QObject, Signal

from .cancelamento import Cancelado, Eventos, verificar
from .cliente_openai import Conversa, ErroOpenAI
from .clima import consultar_clima
from .comandos import interpretar
from .cotacao import consultar_cotacao
from .horario import agora_recife
from .musica import Musica
from .reconhecimento import Ouvinte, ErroMicrofone, ErroReconhecedor, listar_microfones
from .saudacao import montar_saudacao
from .voz import Voz, ErroVoz


def consultar_painel(cancelar, publicar):
    executor = ThreadPoolExecutor(max_workers=2)
    resultados = {"clima": None, "dolar": None}
    try:
        futuros = {"clima": executor.submit(consultar_clima), "dolar": executor.submit(consultar_cotacao)}
        pendentes = dict(futuros)
        publicar({"clima": "Consultando…", "dolar": "Consultando…"})
        while pendentes:
            verificar(cancelar)
            for nome, futuro in list(pendentes.items()):
                if futuro.done():
                    try:
                        resultados[nome] = futuro.result()
                    except Exception:
                        pass
                    del pendentes[nome]
            cancelar.wait(0.05)
        verificar(cancelar)
        clima, dolar = resultados["clima"], resultados["dolar"]
        publicar({
            "clima": (f"{clima.temperatura} °C · {clima.condicao}\nSalgueiro · Pernambuco\n{clima.fonte}\n{clima.atualizacao:%d/%m %H:%M} · America/Recife" if clima else "Condições atuais indisponíveis\nOpen-Meteo"),
            "dolar": (f"R$ {dolar.valor}\nCompra · referência de mercado\n{dolar.fonte}\n{dolar.atualizacao:%d/%m/%Y %H:%M} · UTC−03" if dolar else "Cotação indisponível\nAwesomeAPI"),
        })
        return montar_saudacao(agora_recife(), clima, dolar)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


class Runtime(QObject):
    estado = Signal(str)
    mensagem = Signal(str, str)
    ocupado = Signal(bool)
    nivel = Signal(float)
    cartoes = Signal(dict)
    dispositivos = Signal(dict)
    microfone = Signal(bool)
    reconhecido = Signal(str)
    diagnostico = Signal(dict)
    audio = Signal(dict)
    falando = Signal(bool)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.cancelar = threading.Event()
        self.shutdown = threading.Event()
        self.limpar_pendente = threading.Event()
        self.fila = queue.Queue(maxsize=1)
        self.lock = threading.Lock()
        self.ativo = False
        self.trabalhando = False
        self.ultima_voz = float("-inf")
        self.fala_cancelar = threading.Event()
        self.todos_audio_cancelar = threading.Event()
        self.captura_interromper = threading.Event()
        self.retomada_pendente = threading.Event()
        self.captura_gate = threading.Lock()
        self.falando_agora = threading.Event()
        self.audio_inseguro = threading.Event()
        self.comandos_audio = queue.Queue()
        self.musica = None
        self.finalizacao_musica = False
        self.audio_thread = threading.Thread(target=self._loop_player, name="jarvis-player", daemon=True)
        self.audio_thread.start()
        self.thread = threading.Thread(target=self._loop, name="jarvis-runtime", daemon=True)
        self.thread.start()

    def emitir(self, sinal, *args):
        if not self.shutdown.is_set():
            sinal.emit(*args)

    def enviar(self, texto):
        texto = texto.strip()[:4000]
        if not texto:
            return False
        with self.lock:
            if self.trabalhando or not self.fila.empty():
                return False
            self.fila.put_nowait(("texto", texto))
            self.cancelar.set()  # Fecha captura atual antes de tocar qualquer áudio.
            return True

    def alternar_microfone(self):
        with self.lock:
            self.ativo = not self.ativo
            self.cancelar.set()
        self.microfone.emit(self.ativo)

    def controlar_musica(self, acao):
        if acao not in ("pausar", "retomar", "parar"): return
        if acao == "retomar":
            self.retomada_pendente.set()
            self.captura_interromper.set()
        self.comandos_audio.put((acao, self.musica, None))

    def interromper_fala(self):
        if self.falando_agora.is_set(): self.fala_cancelar.set()

    def parar_audios(self):
        # Preserva as consultas/histórico e a opção de microfone habilitado.
        self.todos_audio_cancelar.set()
        self.fala_cancelar.set()
        self.controlar_musica("parar")

    def preferencia_audio(self, nome, valor):
        if nome not in ("volume", "volume_voz", "sem_voz"): return
        self.config = replace(self.config, **{nome: valor}).validar()
        if nome == "volume": self.comandos_audio.put(("volume", self.musica, valor))
        if nome == "sem_voz" and valor: self.interromper_fala()

    def _loop_player(self):
        anterior = None
        try:
            while not self.shutdown.is_set():
                try:
                    acao, musica, valor = self.comandos_audio.get(timeout=.05)
                    if acao == "retomar":
                        try:
                            # A thread de captura deve fechar o stream antes de unpause.
                            with self.captura_gate:
                                if musica and musica is self.musica and not self.todos_audio_cancelar.is_set(): musica.retomar()
                        finally:
                            self.retomada_pendente.clear()
                    elif musica and musica is self.musica:
                        if acao == "pausar": musica.pausar()
                        elif acao == "parar": musica.parar()
                        elif acao == "volume": musica.definir_volume(valor)
                except queue.Empty: pass
                except Exception as erro:
                    logging.getLogger(__name__).warning("Controle do MP3 falhou: %s", type(erro).__name__)
                    self.emitir(self.mensagem, "Aviso", "Não foi possível alterar a música; reprodução interrompida.")
                    if self.musica: self.musica.parar()
                musica = self.musica
                atual = {"musica": musica.estado_atual() if musica else "parada"}
                if atual != anterior:
                    self.emitir(self.audio, atual)
                    anterior = atual
        finally:
            if self.musica: self.musica.fechar()

    def _capturar(self, ouvinte, **opcoes):
        while True:
            verificar(self.cancelar)
            if self.audio_inseguro.is_set():
                raise ErroMicrofone("Não foi confirmado o fim da fala. Feche e reabra o Jarvis antes de escutar.")
            if self.musica and self.musica.estado_atual() == "falha":
                raise ErroMicrofone("Não foi confirmado o fim da música. Feche e reabra o Jarvis antes de escutar.")
            self.captura_gate.acquire()
            aberta = True
            def liberar_captura():
                nonlocal aberta
                if aberta:
                    aberta = False
                    self.captura_gate.release()
            try:
                if not self.retomada_pendente.is_set() and (not self.musica or self.musica.estado_atual() != "tocando"):
                    self.captura_interromper.clear()
                    # O stream fecha antes da inferência: retomar não espera o download/modelo.
                    if self.musica and self.musica.estado_atual() == "falha":
                        raise ErroMicrofone("Não foi confirmado o fim da música. Reinicie o Jarvis antes de escutar.")
                    return ouvinte.capturar_texto(Eventos(self.cancelar, self.captura_interromper),
                        captura_finalizada=liberar_captura, **opcoes)
            finally:
                liberar_captura()
            self.emitir(self.estado, "Microfone pausado · aguardando fim da música")
            self.cancelar.wait(.05)

    def parar(self):
        self.parar_audios()
        with self.lock:
            self.ativo = False
            self.cancelar.set()
            while not self.fila.empty():
                try:
                    self.fila.get_nowait()
                except queue.Empty:
                    break
        self.emitir(self.microfone, False)
        self.emitir(self.estado, "Cancelando…" if self.trabalhando else "Desativado")

    def limpar(self):
        self.parar()
        self.limpar_pendente.set()

    def configurar(self, config):
        self.parar()
        self.config = config

    def testar_microfone(self):
        with self.lock:
            if self.trabalhando or not self.fila.empty():
                return False
            self.fila.put_nowait(("teste_microfone", ""))
            self.cancelar.set()
            return True

    def listar_dispositivos(self):
        with self.lock:
            if self.trabalhando or not self.fila.empty():
                return
            self.fila.put_nowait(("dispositivos", ""))
            self.cancelar.set()

    def fechar(self):
        self.parar()
        self.shutdown.set()

    def _loop(self):
        com = None
        if sys.platform == "win32":
            try:
                import pythoncom
                pythoncom.CoInitialize()
                com = pythoncom
            except ImportError:
                pass
        conversa = Conversa()
        ouvinte = None
        assinatura = None
        self.voz = None
        self.voz_config = None
        try:
            while not self.shutdown.is_set():
                if self.limpar_pendente.is_set():
                    conversa.limpar()
                    self.limpar_pendente.clear()
                if self.finalizacao_musica and self.musica:
                    if self.musica.estado_atual() == "tocando":
                        self.emitir(self.estado, "Finalizando música · microfone pausado")
                        self.musica.finalizar(cancelar=self.shutdown)
                    if self.musica.estado_atual() == "parada":
                        self.musica.fechar()
                        self.finalizacao_musica = False
                origem, texto = "", ""
                with self.lock:
                    if not self.fila.empty():
                        origem, texto = self.fila.get_nowait()
                    elif not self.ativo:
                        pass
                    else:
                        origem = "microfone"
                    self.cancelar.clear()
                if not origem:
                    self.shutdown.wait(0.1)
                    continue
                config = replace(self.config)
                try:
                    if origem == "dispositivos":
                        self._dispositivos()
                        continue
                    if origem in ("microfone", "teste_microfone"):
                        nova = (config.modelo, config.microfone, config.limiar, config.microfone_identidade)
                        if assinatura != nova:
                            self.emitir(self.estado, "Preparando entrada de áudio…")
                            ouvinte = None
                            ouvinte = Ouvinte(*nova)
                            assinatura = nova
                        verificar(self.cancelar)
                        if origem == "teste_microfone":
                            ouvinte.ruido = None
                            with self.lock:
                                self.trabalhando = True
                            self.emitir(self.ocupado, True)
                            self.emitir(self.diagnostico, {"captura": "Aguardando áudio", "reconhecimento": "Ainda não executado"})
                        def publicar_estado(valor):
                            self.emitir(self.estado, valor)
                            if origem == "teste_microfone" and ouvinte.ultimo.get("captura"):
                                self.emitir(self.diagnostico, {"captura": "Sim · áudio recebido", "reconhecimento": "Em processamento local"})
                        try:
                            texto = self._capturar(ouvinte, maximo=config.captura_maxima,
                                **({"timeout": 8.0} if origem == "teste_microfone" else {}),
                                nivel=lambda valor: self.emitir(self.nivel, valor),
                                estado=publicar_estado)
                            self.emitir(self.reconhecido, texto)
                            if origem == "teste_microfone":
                                self.emitir(self.diagnostico, {
                                    "captura": "Sim · áudio recebido" if ouvinte.ultimo.get("captura") else "Não · nenhum áudio recebido",
                                    "reconhecimento": f"Sim · {texto}" if texto else "Não · nenhuma fala reconhecida; confira silêncio, ganho e limiar",
                                    "rms": ouvinte.ultimo.get("pico_rms", 0.),
                                })
                                continue
                        except (ErroMicrofone, ErroReconhecedor, Cancelado) as erro:
                            if origem == "teste_microfone":
                                self.emitir(self.diagnostico, {
                                    "captura": "Sim · áudio recebido" if ouvinte.ultimo.get("captura") else "Não · captura não confirmada",
                                    "reconhecimento": "Cancelado" if isinstance(erro, Cancelado) else str(erro),
                                })
                            raise
                        finally:
                            if origem == "teste_microfone":
                                with self.lock:
                                    self.trabalhando = False
                                self.emitir(self.ocupado, False)
                                self.emitir(self.estado, "Preparando escuta" if self.ativo else "Desativado")
                        tipo, pergunta = interpretar(texto)
                        if tipo == "ignorar":
                            continue
                        if time.monotonic() - self.ultima_voz < 3:
                            continue
                    else:
                        tipo, pergunta = interpretar(texto)
                        if tipo == "ignorar":
                            tipo, pergunta = "pergunta", texto
                    # Só este worker usa música/SAPI/SDK/histórico. Nada se sobrepõe.
                    with self.lock:
                        if self.cancelar.is_set() or not self.fila.empty():
                            continue
                        self.trabalhando = True
                        self.fala_cancelar.clear()
                        self.todos_audio_cancelar.clear()
                    self.emitir(self.ocupado, True)
                    try:
                        if tipo == "aguardar":
                            self._falar("Sim, senhor?", config)
                            verificar(self.cancelar)
                            self.emitir(self.estado, "Preparando captura da pergunta")
                            if origem != "microfone":
                                # Ativação apenas por texto: a próxima pergunta vem pelo campo.
                                self.emitir(self.mensagem, "Jarvis", "Sim, senhor? Digite sua pergunta.")
                                continue
                            pergunta = self._capturar(ouvinte, timeout=config.timeout_pergunta,
                                                             maximo=config.captura_maxima,
                                                             nivel=lambda valor: self.emitir(self.nivel, valor),
                                                             estado=lambda valor: self.emitir(self.estado, valor))
                            self.emitir(self.reconhecido, pergunta)
                            if not pergunta:
                                self.emitir(self.mensagem, "Aviso", "Nenhuma pergunta capturada no prazo.")
                                continue
                            if interpretar(pergunta)[0] == "bom_dia":
                                tipo = "bom_dia"
                            elif interpretar(pergunta)[0] == "aguardar":
                                continue
                            elif interpretar(pergunta)[0] == "pergunta":
                                pergunta = interpretar(pergunta)[1]
                        self.emitir(self.mensagem, "Senhor", texto if tipo == "bom_dia" else pergunta)
                        if tipo == "bom_dia":
                            if self.musica: self.musica.fechar()
                            self.finalizacao_musica = False
                            musica = None if config.sem_musica else Musica(config.musica, self.config.volume,
                                avisar=lambda aviso: self.emitir(self.mensagem, "Aviso", aviso))
                            self.musica = musica
                            try:
                                if musica and not self.todos_audio_cancelar.is_set():
                                    musica.iniciar()
                                self.emitir(self.estado, "Consultando")
                                resposta = consultar_painel(self.cancelar, lambda dados: self.emitir(self.cartoes, dados))
                                verificar(self.cancelar)
                                self.emitir(self.mensagem, "Jarvis", resposta)
                                if musica:
                                    musica.abaixar_para_fala()
                                self._falar(resposta, config)
                                if musica:
                                    musica.finalizar(cancelar=self.cancelar)
                            finally:
                                if musica:
                                    if getattr(musica, "pausada", False) and not self.cancelar.is_set() and not self.todos_audio_cancelar.is_set():
                                        self.finalizacao_musica = True
                                    else:
                                        musica.fechar()
                        else:
                            self.emitir(self.estado, "Consultando")
                            resposta = conversa.perguntar(pergunta, self.cancelar)
                            verificar(self.cancelar)
                            self.emitir(self.mensagem, "Jarvis", resposta)
                            self._falar(resposta, config)
                    finally:
                        with self.lock:
                            self.trabalhando = False
                        self.ultima_voz = time.monotonic()
                        self.emitir(self.ocupado, False)
                        self.emitir(self.nivel, 0.0)
                        self.emitir(self.estado, "Preparando escuta" if self.ativo else "Desativado")
                except Cancelado:
                    self.emitir(self.estado, "Desativado" if not self.ativo else "Preparando escuta")
                except (ErroOpenAI, ErroMicrofone, ErroReconhecedor, ErroVoz) as erro:
                    self.emitir(self.mensagem, "Aviso", str(erro))
                    if origem == "teste_microfone" and ouvinte is None:
                        self.emitir(self.diagnostico, {"captura": "Não · captura não iniciada", "reconhecimento": str(erro)})
                    self.emitir(self.estado, "Erro")
                    if isinstance(erro, ErroMicrofone):
                        self.ativo = False
                        self.emitir(self.microfone, False)
                    elif isinstance(erro, ErroReconhecedor):
                        self.shutdown.wait(.5)
                except Exception as erro:
                    logging.getLogger(__name__).error("Falha inesperada no worker: %s", type(erro).__name__)
                    self.emitir(self.mensagem, "Aviso", "Operação não concluída. Confira instalação, internet e dispositivos.")
                    self.emitir(self.estado, "Erro")
                    if origem in ("microfone", "teste_microfone"):
                        self.ativo = False
                        self.emitir(self.microfone, False)
        finally:
            if self.musica: self.musica.fechar()
            if self.voz:
                self.voz.fechar()
            conversa.fechar()
            if com:
                com.CoUninitialize()

    def _falar(self, texto, config):
        verificar(self.cancelar)
        self.emitir(self.nivel, 0.0)
        if self.config.sem_voz or self.todos_audio_cancelar.is_set() or self.fala_cancelar.is_set(): return
        try:
            chave = (config.velocidade, config.voz)
            if self.voz_config != chave:
                if self.voz: self.voz.fechar()
                self.voz = Voz(*chave)
                self.voz_config = chave
            self.falando_agora.set()
            self.emitir(self.falando, True)
            self.emitir(self.estado, "Falando · microfone pausado")
            self.voz.falar_cancelavel(texto, Eventos(self.cancelar, self.fala_cancelar),
                volume=lambda: self.config.volume_voz)
        except Cancelado:
            if self.cancelar.is_set(): raise
            self.emitir(self.estado, "Fala interrompida · resposta preservada no histórico")
        except ErroVoz as erro:
            self.voz_config = None
            if erro.audio_pendente:
                self.audio_inseguro.set()
                self.ativo = False
                self.emitir(self.microfone, False)
            self.emitir(self.mensagem, "Aviso", str(erro))
        finally:
            self.falando_agora.clear()
            self.emitir(self.falando, False)

    def _dispositivos(self):
        dados = {"microfones": [], "vozes": [], "identidades": {}}
        try:
            import sounddevice as sd
            entradas = listar_microfones(sd)
            dados["microfones"] = [(i, f"{nome} · {host}") for i, nome, host in entradas]
            dados["identidades"] = {i: [nome, host] for i, nome, host in entradas}
        except Exception as erro:
            logging.getLogger(__name__).warning("Enumeração de microfones falhou: %s", type(erro).__name__)
            self.emitir(self.mensagem, "Aviso", "Não foi possível listar microfones. Confira instalação de áudio e dispositivos conectados.")
        try:
            import pyttsx3
            engine = self.voz.engine if self.voz else pyttsx3.init("sapi5" if sys.platform == "win32" else None)
            dados["vozes"] = [(v.id, v.name) for v in engine.getProperty("voices")]
        except Exception:
            self.emitir(self.mensagem, "Aviso", "Não foi possível listar vozes; instale uma voz SAPI5 em português.")
        self.emitir(self.dispositivos, dados)
