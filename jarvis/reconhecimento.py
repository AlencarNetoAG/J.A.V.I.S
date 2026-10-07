"""Captura exclusiva pelo worker, PCM em memória e Whisper local em português."""
from collections import deque
from pathlib import Path
import logging
import queue
import unicodedata
import time
from .cancelamento import verificar, Cancelado

log = logging.getLogger(__name__)


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto.casefold())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in texto).split())


def eh_ativacao(texto):
    return " bom dia jarvis " in f" {normalizar(texto)} "


class ErroMicrofone(Exception):
    pass


class ErroReconhecedor(Exception):
    pass


def listar_microfones(sd):
    hosts = sd.query_hostapis()
    return [(i, d["name"], hosts[d["hostapi"]]["name"])
            for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]


def resolver_dispositivo(sd, indice=None, identidade=None):
    dispositivos = listar_microfones(sd)
    if identidade:
        candidatos = [i for i, nome, host in dispositivos if [nome, host] == list(identidade)]
        if len(candidatos) != 1:
            raise ErroMicrofone("Microfone selecionado indisponível ou ambíguo. Reconecte-o e atualize a lista; selecione novamente. Nenhum outro microfone foi usado.")
        indice = candidatos[0]
    elif indice is None:
        indice = int(sd.default.device[0])
    if indice not in [i for i, _, _ in dispositivos]:
        raise ErroMicrofone("Dispositivo de entrada indisponível. Atualize a lista e selecione um microfone.")
    return indice, sd.query_devices(indice, "input")


def mensagem_audio(erro):
    detalhe = str(erro).casefold()
    if any(t in detalhe for t in ("permission", "access denied", "denied", "acesso negado")):
        return "Permissão do microfone negada. No Windows, permita o acesso ao microfone para aplicativos da área de trabalho nas configurações de privacidade."
    return "Não foi possível abrir ou manter a captura. O dispositivo pode estar desconectado, ocupado ou bloqueado pelo Windows. Atualize a lista e confira as permissões do microfone."


class Ouvinte:
    TAXA = 16000

    def __init__(self, modelo, dispositivo=None, limiar=0.01, identidade=None):
        try:
            import numpy as np
            import sounddevice as sd
        except Exception as erro:
            log.warning("Inicialização do áudio falhou: %s", type(erro).__name__)
            raise ErroMicrofone("Entrada de áudio indisponível. Confira instalação de sounddevice/PortAudio e as dependências do projeto.") from erro
        self.sd, self.np = sd, np
        self.nome_modelo = modelo
        self.modelo = None  # Diagnosticar captura não exige baixar/carregar o modelo.
        self.dispositivo, self.identidade, self.limiar = dispositivo, identidade, limiar
        self.ruido = None
        self.chave_audio = None
        self.ultimo = {}

    def _formato(self):
        indice, dados = resolver_dispositivo(self.sd, self.dispositivo, self.identidade)
        # O índice resolvido é explícito: não delegar a escolha ao PortAudio.
        for taxa in dict.fromkeys((int(dados["default_samplerate"]), self.TAXA, 48000, 44100)):
            for canais in dict.fromkeys((1, min(2, int(dados["max_input_channels"])))):
                try:
                    self.sd.check_input_settings(device=indice, samplerate=taxa, channels=canais, dtype="float32")
                    return indice, taxa, canais, dados["name"]
                except self.sd.PortAudioError:
                    continue
        raise ErroMicrofone("Microfone sem formato PCM compatível. Confira o formato de entrada nas propriedades de Som do Windows.")

    def _capturar_frase(self, cancelar=None, timeout=None, maximo=12., nivel=None, estado=None):
        np = self.np
        self.ultimo = {"captura": False, "blocos": 0, "pico_rms": 0., "voz": False}
        try:
            indice, taxa, canais, nome = self._formato()
            chave = (indice, taxa, canais, nome)
            if chave != self.chave_audio:
                self.ruido = None
                self.chave_audio = chave
            bloco_tamanho = int(taxa * .1)
            audios = queue.Queue(maxsize=40)
            falhas = queue.Queue(maxsize=1)

            def receber(indata, frames, time_info, status):
                if status:
                    try: falhas.put_nowait(str(status))
                    except queue.Full: pass
                try: audios.put_nowait(indata.copy())
                except queue.Full:
                    try: falhas.put_nowait("Fila de captura excedida")
                    except queue.Full: pass

            inicio, frase = deque(maxlen=5), []
            silencios = ativos = 0
            calibracao = []
            with self.sd.InputStream(device=indice, samplerate=taxa, channels=canais,
                                     dtype="float32", blocksize=bloco_tamanho, callback=receber) as stream:
                verificar(cancelar)
                if not stream.active:
                    raise ErroMicrofone("A captura do microfone não foi iniciada.")
                log.info("Captura ativa: dispositivo=%s nome=%s taxa=%s canais=%s PCM=float32", indice, nome, taxa, canais)
                if estado: estado("Calibrando ruído · fique em silêncio por 1 segundo" if self.ruido is None else 'Ouvindo · aguardando “Jarvis”')
                inicio_espera = ultimo_bloco = time.monotonic()
                while True:
                    verificar(cancelar)
                    try:
                        aviso = falhas.get_nowait()
                    except queue.Empty: aviso = None
                    if aviso:
                        log.warning("Falha de captura: %s", aviso)
                        raise ErroMicrofone("Captura de áudio interrompida ou com perda de blocos. Atualize o dispositivo e tente novamente.")
                    if not frase and timeout is not None and time.monotonic() - inicio_espera >= timeout:
                        return None
                    try: bloco = audios.get(timeout=.2)
                    except queue.Empty:
                        if not stream.active or time.monotonic() - ultimo_bloco > 2:
                            raise ErroMicrofone("Microfone desconectado ou sem entrega de áudio. Atualize a lista e confira permissões.")
                        continue
                    ultimo_bloco = time.monotonic()
                    # Downmix PCM nativo e conversão para mono 16 kHz após a captura.
                    amostras = np.mean(bloco, axis=1, dtype=np.float32)
                    energia = float(np.sqrt(np.mean(amostras ** 2)))
                    self.ultimo["captura"] = True
                    self.ultimo["blocos"] += 1
                    self.ultimo["pico_rms"] = max(energia, self.ultimo["pico_rms"])
                    if nivel: nivel(min(1., energia * 10))
                    if self.ruido is None:
                        calibracao.append(energia)
                        if len(calibracao) >= 10:
                            self.ruido = float(np.median(calibracao))
                            inicio_espera = time.monotonic()
                            log.info("Calibração: ruído RMS=%.5f limiar=%.5f", self.ruido, max(self.limiar, self.ruido * 2.5))
                            if estado: estado('Ouvindo · fale agora')
                        continue
                    falando = energia >= max(self.limiar, self.ruido * 2.5)
                    if not frase:
                        inicio.append(amostras)
                        if not falando: continue
                        frase.extend(inicio)
                    else: frase.append(amostras)
                    if falando:
                        ativos += 1
                        silencios = 0
                    else: silencios += 1
                    if silencios >= 10 or len(frase) >= int(maximo * 10):
                        if ativos >= 2:
                            self.ultimo["voz"] = True
                            audio = np.concatenate(frase)
                            if taxa != self.TAXA:
                                # PyAV já é dependência do Whisper; resampling com filtro antialias.
                                import av
                                frame = av.AudioFrame.from_ndarray(audio.reshape(1, -1), format="flt", layout="mono")
                                frame.sample_rate = taxa
                                resampler = av.AudioResampler(format="flt", layout="mono", rate=self.TAXA)
                                frames = resampler.resample(frame) + resampler.resample(None)
                                audio = np.concatenate([f.to_ndarray().reshape(-1) for f in frames]).astype(np.float32)
                            return audio
                        frase.clear(); inicio.clear(); ativos = silencios = 0
        except ErroMicrofone:
            self.ruido = None
            raise
        except Cancelado:
            raise
        except Exception as erro:
            log.warning("Falha de entrada %s: %s", type(erro).__name__, erro)
            raise ErroMicrofone(mensagem_audio(erro)) from erro
        finally:
            if nivel: nivel(0.)
            if estado: estado("Captura pausada")

    def capturar_texto(self, cancelar=None, timeout=None, maximo=12., nivel=None, estado=None, captura_finalizada=None):
        try:
            audio = self._capturar_frase(cancelar, timeout, maximo, nivel, estado)
        finally:
            if captura_finalizada: captura_finalizada()
        verificar(cancelar)
        if audio is None: return ""
        if estado: estado("Reconhecendo localmente · microfone pausado")
        try:
            if self.modelo is None:
                from faster_whisper import WhisperModel
                cache = Path(__file__).resolve().parent.parent / "modelos"
                if estado: estado("Carregando reconhecedor local · primeiro uso requer internet")
                self.modelo = WhisperModel(self.nome_modelo, device="cpu", compute_type="int8", cpu_threads=2, download_root=str(cache))
            verificar(cancelar)
            segmentos, _ = self.modelo.transcribe(audio, language="pt", beam_size=5,
                vad_filter=True, condition_on_previous_text=False, initial_prompt="Português brasileiro. Jarvis. Bom dia Jarvis.")
            texto = " ".join(s.text for s in segmentos).strip()
            verificar(cancelar)
            log.info("Reconhecimento local concluído: %s caracteres", len(texto))
            return texto
        except Cancelado: raise
        except Exception as erro:
            log.warning("Falha do reconhecedor: %s", type(erro).__name__)
            raise ErroReconhecedor("Áudio capturado, mas o reconhecedor local falhou. Confira o modelo Whisper, a instalação e a internet no primeiro download.") from erro

    def aguardar_ativacao(self):
        while not eh_ativacao(self.capturar_texto()):
            pass
