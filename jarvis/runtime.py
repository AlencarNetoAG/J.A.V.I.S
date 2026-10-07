"""Um único worker serializa reconhecimento, consultas e áudio; Qt só recebe sinais."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import logging
import queue
import sys
import threading
import time

from PySide6.QtCore import QObject, Signal

from .cancelamento import Cancelado, Eventos, verificar
from .cliente_local import ConversaLocal as Conversa
from .clima import consultar_clima
from .comandos import interpretar
from .cotacao import consultar_cotacao, numero_por_extenso
from .horario import agora_recife
from .musica import Musica
from .reconhecimento import Ouvinte, ErroMicrofone, ErroReconhecedor, listar_microfones, normalizar
from .saudacao import montar_saudacao
from .voz import Voz, ErroVoz
from .ferramentas.base import Decisoes, ErroFerramenta, resultado
from .ferramentas.controle import ControlePC
from .ferramentas.spotify import Spotify
from .ferramentas.windows import Windows
from .ferramentas.esquemas import REGISTRO


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
    confirmacao = Signal(dict)
    acao = Signal(dict)
    config_pc = Signal(dict)

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
        self.cancelar_acao_evento = threading.Event()
        self.ouvinte = None
        self.midia_externa = threading.Event()
        self.midia_antes_acao = False
        self.fonte_externa = "spotify"
        self.midia_versao = 0
        self.monitor_externo_erro = None
        self.decisoes = Decisoes(lambda p:self.emitir(self.confirmacao,p),self._ouvir_decisao)
        windows = Windows(antes_audio=self._midia_externa)
        spotify = Spotify(self.decisoes,antes_audio=self._midia_externa)
        self.controle = ControlePC(lambda:self.config,self.decisoes,self.cancelar_acao_evento,
            local=self._controle_mp3,windows=windows,spotify=spotify,publicar=self._estado_acao)
        self.audio_thread = threading.Thread(target=self._loop_player, name="jarvis-player", daemon=True)
        self.audio_thread.start()
        self.monitor_thread = threading.Thread(target=self._loop_midia_externa, name="jarvis-midia", daemon=True)
        self.monitor_thread.start()
        self.thread = threading.Thread(target=self._loop, name="jarvis-runtime", daemon=True)
        self.thread.start()

    def emitir(self, sinal, *args):
        if not self.shutdown.is_set():
            sinal.emit(*args)

    def enviar(self, texto):
        texto = texto.strip()[:4000]
        if not texto:
            return False
        if self.decisoes.pendente:
            return self._responder_decisao(texto,self.decisoes.pendente)
        with self.lock:
            if self.trabalhando or not self.fila.empty():
                return False
            self.fila.put_nowait(("texto", texto))
            self.cancelar.set()  # Fecha captura atual antes de tocar qualquer áudio.
            return True

    def _responder_decisao(self,texto,pendente):
        t=normalizar(texto)
        if t.startswith("jarvis "):t=t[7:]
        if t in ("cancelar","cancelo","nao","nao confirmar"):
            self.decisoes.cancelar();return True
        if not pendente["opcoes"]:
            return self.decisoes.responder(pendente["id"],True) if t in ("confirmar","confirmo") else False
        if t.startswith("opcao "):t=t[6:]
        for i in range(len(pendente["opcoes"])):
            if t in (str(i+1),normalizar(numero_por_extenso(i+1))):return self.decisoes.responder(pendente["id"],i)
        return False

    def _ouvir_decisao(self,pendente,cancelar):
        if not self.ativo or self.ouvinte is None:return
        if self.musica and self.musica.estado_atual()=="tocando":return
        if self.midia_externa.is_set() and not self.config.fones_midia_externa:return
        try:
            texto=self._capturar(self.ouvinte,timeout=.6,maximo=3,
                nivel=lambda v:self.emitir(self.nivel,v),estado=lambda s:self.emitir(self.estado,s))
            verificar(cancelar)
            if texto:
                self.emitir(self.reconhecido,texto)
                self._responder_decisao(texto,pendente)
        except Cancelado:
            verificar(cancelar)
        except (ErroMicrofone,ErroReconhecedor) as erro:
            self.emitir(self.mensagem,"Aviso",str(erro)+" Confirme pelo botão.")
            self.ativo=False;self.emitir(self.microfone,False)

    def cancelar_acao(self):
        self.cancelar_acao_evento.set();self.decisoes.cancelar();self.captura_interromper.set()
        self.emitir(self.mensagem,"Aviso","Ação cancelada. Etapas futuras serão interrompidas; ações já concluídas não são desfeitas.")

    def suspender_pc(self):
        self.config=replace(self.config,pc_suspenso=not self.config.pc_suspenso)
        if self.config.pc_suspenso:self.cancelar_acao()
        self.emitir(self.config_pc,{"pc_suspenso":self.config.pc_suspenso})

    def configurar_pc(self,config):
        self.cancelar_acao()
        self.config=replace(self.config,permissoes_pc=dict(config.permissoes_pc),pastas_autorizadas=list(config.pastas_autorizadas),
                            fones_midia_externa=config.fones_midia_externa)
        self.emitir(self.config_pc,{"pc_suspenso":self.config.pc_suspenso})

    def ferramenta_pc(self,nome,args=None):
        if nome not in REGISTRO and nome not in ("spotify_conectar","spotify_desconectar"):return False
        with self.lock:
            if self.trabalhando or not self.fila.empty():return False
            self.fila.put_nowait(("ferramenta_pc",json.dumps({"nome":nome,"args":args or {}})))
            self.cancelar.set();return True

    def _estado_acao(self,dados):
        self.emitir(self.acao,dados)
        if dados["status"]=="em andamento":
            self.midia_antes_acao=self.midia_externa.is_set()
            self.emitir(self.estado,"Executando: "+dados["ferramenta"].replace("_"," "))
        if dados.get("fonte") in ("spotify","sistema") and type(dados.get("tocando")) is bool:
            self._midia_externa(dados["fonte"],dados["tocando"])
        if dados.get("audio_nao_executado"):
            self._midia_externa(self.fonte_externa,self.midia_antes_acao)

    def _midia_externa(self,fonte,tocando):
        self.fonte_externa=fonte
        self.midia_versao+=1
        self.midia_externa.set() if tocando else self.midia_externa.clear()

    def _controle_mp3(self,acao,valor,cancelar):
        musica=self.musica
        estado=musica.estado_atual() if musica else "parada"
        if acao in ("estado","atual"):return resultado("MP3 da saudação: "+estado,estado=estado)
        if acao=="volume":
            self.preferencia_audio("volume",valor/100)
            self.emitir(self.config_pc,{"pc_suspenso":self.config.pc_suspenso})
            if musica:
                fim=time.monotonic()+2
                while time.monotonic()<fim:
                    verificar(cancelar)
                    if abs(musica.volume-valor/100)<.01:break
                    time.sleep(.02)
                else:raise ErroFerramenta("Não consegui verificar o volume do MP3.")
            return resultado(f"Volume do MP3 configurado em {valor} por cento.")
        if estado=="parada":raise ErroFerramenta("O MP3 da saudação não está carregado/em reprodução.")
        self.controlar_musica(acao)
        esperado="pausada" if acao=="pausar" else "tocando"
        fim=time.monotonic()+2
        while time.monotonic()<fim:
            verificar(cancelar)
            if musica.estado_atual()==esperado:return resultado("MP3 da saudação: "+esperado+"; estado verificado.")
            time.sleep(.02)
        raise ErroFerramenta("Não consegui verificar a alteração do MP3.")

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

    def _loop_midia_externa(self):
        # Consultas WinRT não atrasam os controles independentes do MP3.
        while not self.shutdown.wait(2):
            if not self.midia_externa.is_set() or self.trabalhando:continue
            versao,fonte=self.midia_versao,self.fonte_externa
            try:
                sessoes=self.controle.windows.fontes_midia()
                selecionadas=[s for s in sessoes if ("spotify" in s["id"].casefold())==(fonte=="spotify")]
                if selecionadas and versao==self.midia_versao and not self.trabalhando:
                    self.midia_externa.set() if any(s["tocando"] for s in selecionadas) else self.midia_externa.clear()
            except Exception as erro:
                if self.monitor_externo_erro!=type(erro).__name__:
                    self.monitor_externo_erro=type(erro).__name__
                    logging.getLogger(__name__).warning("Monitor de mídia externa indisponível: %s",type(erro).__name__)
                # Estado desconhecido mantém a pausa; não inventar ausência de reprodução.

    def _capturar(self, ouvinte, **opcoes):
        while True:
            verificar(self.cancelar)
            if self.audio_inseguro.is_set():
                raise ErroMicrofone("Não foi confirmado o fim da fala. Feche e reabra o Jarvis antes de escutar.")
            if self.midia_externa.is_set() and not self.config.fones_midia_externa:
                self.emitir(self.estado,"Microfone pausado · mídia externa. Pause no painel ou habilite uso com fones.")
                self.cancelar.wait(.1);continue
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
        self.cancelar_acao_evento.set();self.decisoes.cancelar()
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
        conversa = Conversa(self.controle)
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
                            self.ouvinte = ouvinte
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
                    elif origem=="ferramenta_pc":
                        tipo,pergunta="pc_painel",texto
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
                        self.cancelar_acao_evento.clear()
                    self.emitir(self.ocupado, True)
                    try:
                        if tipo=="pc_painel":
                            pedido=json.loads(pergunta);nome=pedido["nome"]
                            evento=Eventos(self.cancelar,self.cancelar_acao_evento)
                            if nome in ("spotify_conectar","spotify_desconectar"):
                                self.emitir(self.estado,"Autorizando Spotify no navegador…" if nome=="spotify_conectar" else "Desconectando Spotify…")
                                r=self.controle.conta_spotify(nome,evento)
                            else:r=self.controle.executar(nome,json.dumps(pedido["args"]),evento)
                            self.emitir(self.mensagem,"Jarvis",r["mensagem"])
                            self._falar(r["mensagem"],config)
                            continue
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
                except (ErroMicrofone, ErroReconhecedor, ErroVoz, ErroFerramenta) as erro:
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
            self.controle.fechar()
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
