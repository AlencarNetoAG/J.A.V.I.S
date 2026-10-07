"""Áudio sintético em memória; nenhum dispositivo físico ou modelo baixado."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from jarvis.reconhecimento import (Ouvinte, ErroMicrofone, ErroReconhecedor,
                                   resolver_dispositivo, mensagem_audio)
from jarvis.cancelamento import Cancelado


class PortAudioError(Exception):
    pass


def backend(taxa=48000, canais=2):
    dispositivo = {"name": "USB", "hostapi": 0, "max_input_channels": canais, "default_samplerate": taxa}
    estado = {"aberto": False, "aberturas": 0, "max_concorrencia": 0}
    sd = SimpleNamespace(query_devices=lambda *args: dispositivo if args else [dispositivo],
        query_hostapis=lambda: [{"name": "WASAPI"}], default=SimpleNamespace(device=(0, 1)), PortAudioError=PortAudioError)
    def verificar_formato(**kwargs):
        if kwargs["samplerate"] != taxa or kwargs["channels"] != canais:
            raise PortAudioError("Formato incompatível")
    sd.check_input_settings = verificar_formato
    class Stream:
        active = True
        def __init__(self, **kwargs): self.kwargs = kwargs
        def __enter__(self):
            assert not estado["aberto"], "Captura concorrente"
            estado["aberto"] = True; estado["aberturas"] += 1
            estado["max_concorrencia"] = 1
            n = int(taxa * .1)
            silencio = np.full((n, canais), .001, dtype=np.float32)
            voz = np.tile((.1*np.sin(2*np.pi*440*np.arange(n)/taxa)).astype(np.float32)[:,None], (1,canais))
            for bloco in [*([silencio]*10), *([voz]*4), *([silencio]*10)]:
                self.kwargs["callback"](bloco, n, None, None)
            return self
        def __exit__(self, *args): estado["aberto"] = False
    sd.InputStream = Stream
    return sd, estado


class MicrofoneTests(unittest.TestCase):
    def criar(self, sd):
        with patch.dict("sys.modules", {"sounddevice": sd}):
            return Ouvinte("tiny", identidade=["USB", "WASAPI"])

    def test_resolve_identidade_independente_de_indice_e_sem_fallback(self):
        sd, _ = backend()
        self.assertEqual(resolver_dispositivo(sd, 99, ["USB", "WASAPI"])[0], 0)
        with self.assertRaisesRegex(ErroMicrofone, "Nenhum outro"):
            resolver_dispositivo(sd, 0, ["Desconectado", "WASAPI"])
        sd.default.device = (-1, 1)
        with self.assertRaises(ErroMicrofone): resolver_dispositivo(sd)
        sd.query_devices = lambda *args: [{"name":"USB","hostapi":0,"max_input_channels":1}]*2
        with self.assertRaisesRegex(ErroMicrofone, "ambíguo"):
            resolver_dispositivo(sd, identidade=["USB", "WASAPI"])

    def test_formato_nativo_stereo_resample_calibracao_nivel_e_fechamento(self):
        sd, estado = backend()
        ouvinte = self.criar(sd)
        niveis, estados = [], []
        def transcribe(audio, **kwargs):
            self.assertFalse(estado["aberto"])
            self.assertEqual(audio.dtype, np.float32)
            self.assertEqual(audio.ndim, 1)
            self.assertEqual(kwargs["language"], "pt")
            self.assertAlmostEqual(len(audio)/16000, 1.4, places=2)
            self.assertGreater(float(np.max(audio)), .08)
            return iter([SimpleNamespace(text="Bom dia, Jarvis!")]), None
        ouvinte.modelo = SimpleNamespace(transcribe=transcribe)
        texto = ouvinte.capturar_texto(nivel=niveis.append, estado=estados.append)
        self.assertEqual(texto, "Bom dia, Jarvis!")
        self.assertTrue(ouvinte.ultimo["captura"]); self.assertTrue(ouvinte.ultimo["voz"])
        self.assertAlmostEqual(ouvinte.ruido, .001, places=4)
        self.assertGreater(max(niveis), .5); self.assertEqual(niveis[-1], 0)
        self.assertTrue(estados[0].startswith("Calibrando"))
        self.assertFalse(estado["aberto"])

    def test_microfone_permissao_negada_e_captura_nao_confirmada(self):
        sd, _ = backend(); ouvinte = self.criar(sd)
        def negar(**kwargs): raise PortAudioError("Access denied")
        sd.InputStream = negar
        estados = []
        with self.assertRaisesRegex(ErroMicrofone, "Permissão"):
            ouvinte.capturar_texto(estado=estados.append)
        self.assertFalse(ouvinte.ultimo["captura"])
        self.assertFalse(any("Ouvindo" in s for s in estados))

    def test_reconhecedor_falha_independente_de_captura(self):
        sd, estado = backend(); ouvinte = self.criar(sd)
        def falhar(*args, **kwargs): raise RuntimeError("modelo falhou")
        ouvinte.modelo = SimpleNamespace(transcribe=falhar)
        with self.assertRaises(ErroReconhecedor): ouvinte.capturar_texto()
        self.assertTrue(ouvinte.ultimo["captura"]); self.assertFalse(estado["aberto"])

    def test_cancelamento_fecha_stream_sem_transcricao(self):
        sd, estado = backend(); ouvinte = self.criar(sd)
        cancelar = threading.Event()
        def nivel(valor): cancelar.set()
        with self.assertRaises(Cancelado): ouvinte.capturar_texto(cancelar, nivel=nivel)
        self.assertFalse(estado["aberto"])

    def test_silencio_nao_dispara_reconhecedor(self):
        sd, estado = backend(); ouvinte = self.criar(sd)
        original = sd.InputStream
        class Silencio(original):
            def __enter__(self):
                estado["aberto"] = True
                for _ in range(30):
                    self.kwargs["callback"](np.zeros((4800, 2), np.float32),4800,None,None)
                return self
        sd.InputStream = Silencio
        ouvinte.ruido = 0.; ouvinte.chave_audio = (0,48000,2,"USB")
        ouvinte.modelo = SimpleNamespace(transcribe=lambda *args,**kwargs:self.fail("Silêncio transcrito"))
        self.assertEqual(ouvinte.capturar_texto(timeout=.01), "")
        self.assertTrue(ouvinte.ultimo["captura"])
        self.assertFalse(estado["aberto"])

    def test_overflow_visivel(self):
        sd, _ = backend(); ouvinte = self.criar(sd)
        original = sd.InputStream
        class Overflow(original):
            def __enter__(self):
                self.kwargs["callback"](np.zeros((4800,2),np.float32),4800,None,"input overflow")
                return self
        sd.InputStream = Overflow
        with self.assertRaisesRegex(ErroMicrofone, "perda de blocos"):
            ouvinte.capturar_texto()


if __name__ == "__main__": unittest.main()
