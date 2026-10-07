"""Whisper processa o áudio localmente; nenhum áudio é salvo ou enviado."""

from collections import deque
from pathlib import Path
import queue
import unicodedata


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.casefold())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in texto).split())


def eh_ativacao(texto: str) -> bool:
    return " bom dia jarvis " in f" {normalizar(texto)} "


class ErroMicrofone(Exception):
    pass


class Ouvinte:
    TAXA = 16000
    BLOCO = 3200  # 200 ms de PCM mono

    def __init__(self, modelo: str, dispositivo: int | None = None, limiar: float = 0.01):
        try:
            import numpy as np
            import sounddevice as sd
            from faster_whisper import WhisperModel
            self.sd = sd
            self.np = np
            cache = Path(__file__).resolve().parent.parent / "modelos"
            # O primeiro uso baixa pesos públicos. Depois a transcrição é local.
            self.modelo = WhisperModel(modelo, device="cpu", compute_type="int8", cpu_threads=2, download_root=str(cache))
            self.dispositivo = dispositivo
            self.limiar = limiar
        except Exception as erro:
            raise ErroMicrofone(
                "Não foi possível carregar o modelo ou o áudio. Confira a instalação, "
                "a internet no primeiro uso e --modelo. Use --texto para testar sem microfone."
            ) from erro

    def _capturar_frase(self):
        audios = queue.Queue(maxsize=32)
        avisos = queue.Queue(maxsize=1)

        def receber(indata, frames, time_info, status):
            if status:
                try:
                    avisos.put_nowait(str(status))
                except queue.Full:
                    pass
            try:
                audios.put_nowait(bytes(indata))
            except queue.Full:
                pass

        inicio = deque(maxlen=3)  # Até 600 ms antes de detectar a voz.
        frase = []
        silencios = 0
        ativos = 0
        with self.sd.RawInputStream(
            samplerate=self.TAXA, blocksize=self.BLOCO, device=self.dispositivo,
            dtype="int16", channels=1, callback=receber,
        ) as stream:
            while True:
                try:
                    aviso = avisos.get_nowait()
                    print(f"Aviso de áudio: {aviso}. Se persistir, confira o microfone.", flush=True)
                except queue.Empty:
                    pass
                try:
                    bloco = audios.get(timeout=0.5)
                except queue.Empty:
                    if not stream.active:
                        raise ErroMicrofone("O microfone foi desconectado ou interrompido.")
                    continue
                amostras = self.np.frombuffer(bloco, dtype=self.np.int16).astype(self.np.float32) / 32768.0
                energia = float(self.np.sqrt(self.np.mean(amostras ** 2)))
                falando = energia >= self.limiar
                if not frase:
                    inicio.append(amostras)
                    if not falando:
                        continue
                    frase.extend(inicio)
                else:
                    frase.append(amostras)
                if falando:
                    ativos += 1
                    silencios = 0
                else:
                    silencios += 1
                # Um segundo de silêncio encerra a frase; oito segundos limitam
                # a memória e o custo de transcrição em ambientes ruidosos.
                if silencios >= 5 or len(frase) >= 40:
                    if ativos >= 2:
                        return self.np.concatenate(frase)
                    frase.clear()
                    inicio.clear()
                    ativos = silencios = 0

    def aguardar_ativacao(self) -> None:
        try:
            while True:
                audio = self._capturar_frase()
                # O stream já foi fechado. Não acumula áudio durante inferência.
                segmentos, _ = self.modelo.transcribe(
                    audio, language="pt", beam_size=5, vad_filter=True,
                    condition_on_previous_text=False,
                )
                texto = " ".join(segmento.text for segmento in segmentos)
                del audio
                if eh_ativacao(texto):
                    return
        except ErroMicrofone:
            raise
        except Exception as erro:
            raise ErroMicrofone(
                "Não foi possível escutar ou reconhecer. Confira conexão, permissão "
                "e entrada mono a 16 kHz do microfone."
            ) from erro
