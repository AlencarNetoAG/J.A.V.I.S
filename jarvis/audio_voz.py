"""PCM em memória, amplitude sincronizada com o relógio DAC do PortAudio."""

from collections import deque
import threading
import math
import numpy as np
from .cancelamento import verificar
from .voz import ErroVoz


def reproduzir(pcm, taxa, cancelar, volume, nivel, estado=None, backend=None):
    if backend is None:
        import sounddevice as backend
    dispositivo = backend.query_devices(kind="output")
    saida = int(round(dispositivo["default_samplerate"]))
    canais = 1 if dispositivo["max_output_channels"] >= 1 else 0
    if not canais:
        raise ErroVoz("Nenhum dispositivo de saída disponível para a voz.")
    try:
        backend.check_output_settings(
            samplerate=saida, channels=canais, dtype="float32"
        )
    except Exception:
        canais = min(2, int(dispositivo["max_output_channels"]))
        backend.check_output_settings(
            samplerate=saida, channels=canais, dtype="float32"
        )
    amostras = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    if not amostras.size:
        raise ErroVoz("A voz selecionada não produziu áudio PCM.")
    if taxa != saida:
        import av

        f = av.AudioFrame.from_ndarray(
            amostras.reshape(1, -1), format="flt", layout="mono"
        )
        f.sample_rate = taxa
        resampler = av.AudioResampler(format="flt", layout="mono", rate=saida)
        amostras = np.concatenate(
            [
                f.to_ndarray().reshape(-1)
                for f in resampler.resample(f) + resampler.resample(None)
            ]
        ).astype(np.float32)
    pos = 0
    medidas = deque(maxlen=400)
    fim = threading.Event()
    falha = []

    def fornecer(out, frames, relogio, status):
        nonlocal pos
        out.fill(0)
        if cancelar.is_set():
            raise backend.CallbackAbort
        if status:
            falha.append("O dispositivo perdeu blocos de áudio.")
            raise backend.CallbackAbort
        n = min(frames, len(amostras) - pos)
        try:
            ganho = max(0.0, min(1.0, float(volume() if volume else 1.0)))
            if n > 0:
                out[:n, :] = amostras[pos : pos + n, None] * ganho
            # Nível do PCM entregue, após volume; não do texto. O timestamp inclui latência da saída.
            rms = float(np.sqrt(np.mean(out * out, dtype=np.float64)))
            medidas.append(
                (float(relogio.outputBufferDacTime), min(1.0, math.sqrt(rms) * 2.6))
            )
        except Exception:
            out.fill(0)
            falha.append("Não foi possível fornecer áudio ao dispositivo de saída.")
            raise backend.CallbackAbort
        pos += n
        if pos >= len(amostras):
            raise backend.CallbackStop  # Drena a saída antes de concluir.

    stream = None
    try:
        verificar(cancelar)
        stream = backend.OutputStream(
            samplerate=saida,
            channels=canais,
            dtype="float32",
            blocksize=max(64, int(saida * 0.02)),
            latency="low",
            callback=fornecer,
            finished_callback=fim.set,
        )
        stream.start()
        if estado:
            estado("Falando · microfone pausado")
        while not fim.is_set():
            verificar(cancelar)
            agora = stream.time
            valor = None
            while medidas and medidas[0][0] <= agora:
                _, valor = medidas.popleft()
            if valor is not None:
                nivel(valor)
            cancelar.wait(0.008)
        verificar(cancelar)
        if falha:
            raise ErroVoz(falha[0])
    finally:
        nivel(0.0)
        if stream is not None:
            try:
                if cancelar.is_set():
                    stream.abort()  # Descarta áudio ainda na fila.
                else:
                    stream.stop()
                stream.close()
            except Exception as erro:
                raise ErroVoz(
                    "Não foi possível confirmar o fim da saída de voz. Reinicie o Jarvis antes de escutar.",
                    audio_pendente=True,
                ) from erro
