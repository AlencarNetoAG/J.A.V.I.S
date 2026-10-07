"""Um único worker serializa reconhecimento, consultas e áudio; Qt só recebe sinais."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import queue
import sys
import threading
import time

from PySide6.QtCore import QObject, Signal

from .cancelamento import Cancelado, verificar
from .cliente_openai import Conversa, ErroOpenAI
from .clima import consultar_clima
from .comandos import interpretar
from .cotacao import consultar_cotacao
from .horario import agora_recife
from .musica import Musica
from .reconhecimento import Ouvinte, ErroMicrofone
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

    def parar(self):
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
                    if origem == "microfone":
                        nova = (config.modelo, config.microfone, config.limiar)
                        if assinatura != nova:
                            self.emitir(self.estado, "Carregando reconhecimento local…")
                            ouvinte = Ouvinte(*nova)
                            assinatura = nova
                        verificar(self.cancelar)
                        self.emitir(self.estado, 'Aguardando “Jarvis”')
                        texto = ouvinte.capturar_texto(self.cancelar, maximo=config.captura_maxima,
                                                      nivel=lambda valor: self.emitir(self.nivel, valor))
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
                    self.emitir(self.ocupado, True)
                    try:
                        if tipo == "aguardar":
                            self._falar("Sim, senhor?", config)
                            verificar(self.cancelar)
                            self.emitir(self.estado, "Ouvindo pergunta")
                            if ouvinte is None:
                                # Ativação apenas por texto: a próxima pergunta vem pelo campo.
                                self.emitir(self.mensagem, "Jarvis", "Sim, senhor? Digite sua pergunta.")
                                continue
                            pergunta = ouvinte.capturar_texto(self.cancelar, timeout=config.timeout_pergunta,
                                                             maximo=config.captura_maxima,
                                                             nivel=lambda valor: self.emitir(self.nivel, valor))
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
                            musica = None if config.sem_musica else Musica(config.musica, config.volume,
                                avisar=lambda aviso: self.emitir(self.mensagem, "Aviso", aviso))
                            try:
                                if musica:
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
                        self.emitir(self.estado, 'Aguardando “Jarvis”' if self.ativo else "Desativado")
                except Cancelado:
                    self.emitir(self.estado, "Desativado" if not self.ativo else 'Aguardando “Jarvis”')
                except (ErroOpenAI, ErroMicrofone, ErroVoz) as erro:
                    self.emitir(self.mensagem, "Aviso", str(erro))
                    self.emitir(self.estado, "Erro")
                    if origem == "microfone":
                        self.ativo = False
                        self.emitir(self.microfone, False)
                except Exception:
                    self.emitir(self.mensagem, "Aviso", "Operação não concluída. Confira instalação, internet e dispositivos.")
                    self.emitir(self.estado, "Erro")
                    self.ativo = False
                    self.emitir(self.microfone, False)
        finally:
            if self.voz:
                self.voz.fechar()
            conversa.fechar()
            if com:
                com.CoUninitialize()

    def _falar(self, texto, config):
        verificar(self.cancelar)
        self.emitir(self.nivel, 0.0)
        self.emitir(self.estado, "Respondendo")
        if config.sem_voz:
            return
        try:
            chave = (config.velocidade, config.voz)
            if self.voz_config != chave:
                if self.voz:
                    self.voz.fechar()
                self.voz = Voz(*chave)
                self.voz_config = chave
            self.voz.falar_cancelavel(texto, self.cancelar)
        except ErroVoz:
            self.voz_config = None
            self.emitir(self.mensagem, "Aviso", "Voz local indisponível. A resposta está no histórico; confira configurações de fala.")

    def _dispositivos(self):
        dados = {"microfones": [], "vozes": []}
        try:
            import sounddevice as sd
            dados["microfones"] = [(i, d["name"]) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
        except Exception:
            self.emitir(self.mensagem, "Aviso", "Não foi possível listar microfones.")
        try:
            import pyttsx3
            engine = self.voz.engine if self.voz else pyttsx3.init("sapi5" if sys.platform == "win32" else None)
            dados["vozes"] = [(v.id, v.name) for v in engine.getProperty("voices")]
        except Exception:
            self.emitir(self.mensagem, "Aviso", "Não foi possível listar vozes; instale uma voz SAPI5 em português.")
        self.emitir(self.dispositivos, dados)
