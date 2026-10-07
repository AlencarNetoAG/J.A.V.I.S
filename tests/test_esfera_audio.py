"""Qt real e PCM sintético; PortAudio/SAPI simulados, sem áudio físico."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import math
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, Qt
from jarvis.audio_voz import reproduzir
from jarvis.voz import Voz, ErroVoz
from jarvis.cancelamento import Cancelado
from jarvis.configuracoes import Configuracoes
from jarvis.interface import Janela, ESTILO, Preferencias
from jarvis.esfera import Nucleo


class Backend:
    """Relógio de saída e fila com latência, para conferir o agendamento DAC."""

    class CallbackStop(Exception):
        pass

    class CallbackAbort(Exception):
        pass

    def __init__(self, taxa=22050, estereo=False, erro=False, fechar_falha=False):
        self.taxa = taxa
        self.estereo = estereo
        self.erro = erro
        self.fechar_falha = fechar_falha
        self.entregues = []
        self.abortou = False
        self.fechou = False

    def query_devices(self, **kwargs):
        return {"default_samplerate": self.taxa, "max_output_channels": 2}

    def check_output_settings(self, **kwargs):
        if self.estereo and kwargs["channels"] == 1:
            raise ValueError("Exige estéreo")

    def OutputStream(self, **kwargs):
        backend = self

        class Stream:
            def __init__(self):
                self.encerrar = threading.Event()

            @property
            def time(self):
                return time.monotonic()

            def start(self):
                def executar():
                    duracao = kwargs["blocksize"] / kwargs["samplerate"]
                    try:
                        while not self.encerrar.is_set():
                            out = np.zeros(
                                (kwargs["blocksize"], kwargs["channels"]), np.float32
                            )
                            dac = time.monotonic() + 0.035
                            terminou = False
                            try:
                                kwargs["callback"](
                                    out,
                                    len(out),
                                    SimpleNamespace(outputBufferDacTime=dac),
                                    backend.erro,
                                )
                            except backend.CallbackStop:
                                terminou = True
                            except backend.CallbackAbort:
                                break
                            backend.entregues.append((dac, out.copy()))
                            if terminou:
                                self.encerrar.wait(
                                    max(0, dac + duracao - time.monotonic())
                                )
                                break
                            self.encerrar.wait(duracao)
                    finally:
                        kwargs["finished_callback"]()

                self.thread = threading.Thread(target=executar)
                self.thread.start()

            def stop(self):
                self.encerrar.set()
                self.thread.join(1)

            def abort(self):
                backend.abortou = True
                self.stop()

            def close(self):
                backend.fechou = True
                if backend.fechar_falha:
                    raise RuntimeError("Dispositivo preso")

        self.stream = Stream()
        return self.stream


def sinal(taxa=22050):
    seno = (np.sin(np.arange(int(taxa * 0.16)) * math.tau * 440 / taxa) * 11000).astype(
        "<i2"
    )
    return np.concatenate(
        (np.zeros(int(taxa * 0.08), "<i2"), seno, np.zeros(int(taxa * 0.08), "<i2"))
    ).tobytes()


class PCMTests(unittest.TestCase):
    def test_amplitude_silencio_volume_e_relogio_dac(self):
        backend = Backend()
        medidas = []
        reproduzir(
            sinal(),
            22050,
            threading.Event(),
            lambda: 0.5,
            lambda v: medidas.append((time.monotonic(), v)),
            backend=backend,
        )
        positivos = [(t, v) for t, v in medidas if v > 0.1]
        self.assertTrue(positivos)
        primeiro_dac = next(
            t for t, out in backend.entregues if np.max(np.abs(out)) > 0.01
        )
        self.assertGreaterEqual(positivos[0][0], primeiro_dac)
        self.assertEqual(medidas[0][1], 0.0)
        self.assertEqual(medidas[-1][1], 0.0)
        self.assertTrue(any(t > positivos[-1][0] and v == 0 for t, v in medidas))
        self.assertTrue(backend.fechou)
        self.assertLessEqual(max(abs(out).max() for _, out in backend.entregues), 0.17)

    def test_mudo_resampling_e_fallback_estereo(self):
        backend = Backend(taxa=48000, estereo=True)
        medidas = []
        reproduzir(
            sinal(),
            22050,
            threading.Event(),
            lambda: 0.0,
            medidas.append,
            backend=backend,
        )
        self.assertTrue(backend.entregues)
        self.assertEqual(backend.entregues[0][1].shape, (960, 2))
        self.assertTrue(all(v == 0 for v in medidas))
        self.assertTrue(all(np.count_nonzero(out) == 0 for _, out in backend.entregues))

    def test_cancelamento_aborta_fila_e_encerra_saida(self):
        backend = Backend()
        cancelar = threading.Event()
        medidas = []

        def nivel(v):
            medidas.append(v)
            if v > 0.1:
                cancelar.set()

        with self.assertRaises(Cancelado):
            reproduzir(sinal(), 22050, cancelar, lambda: 1.0, nivel, backend=backend)
        self.assertTrue(backend.abortou)
        self.assertTrue(backend.fechou)
        self.assertEqual(medidas[-1], 0.0)

    def test_falha_de_callback_e_encerramento_inseguro(self):
        with self.assertRaisesRegex(ErroVoz, "perdeu blocos"):
            reproduzir(
                sinal(),
                22050,
                threading.Event(),
                None,
                lambda v: None,
                backend=Backend(erro=True),
            )
        medidas = []
        with self.assertRaises(ErroVoz) as erro:
            reproduzir(
                sinal(),
                22050,
                threading.Event(),
                None,
                medidas.append,
                backend=Backend(fechar_falha=True),
            )
        self.assertTrue(erro.exception.audio_pendente)
        self.assertEqual(medidas[-1], 0.0)


class SAPIEmMemoriaTests(unittest.TestCase):
    def preparar(self, cancelar=None):
        self.sapi = SimpleNamespace(WaitUntilDone=Mock(return_value=True), Speak=Mock())
        if cancelar:

            def falar(texto, flags):
                if texto:
                    cancelar.set()

            self.sapi.Speak.side_effect = falar
        self.memoria = SimpleNamespace(
            Format=SimpleNamespace(Type=None), GetData=lambda: sinal()
        )
        voz = Voz.__new__(Voz)
        voz.engine = SimpleNamespace(
            proxy=SimpleNamespace(
                _driver=SimpleNamespace(
                    _tts=SimpleNamespace(Voice="voz instalada", Rate=2)
                )
            )
        )
        criar = Mock(
            side_effect=lambda nome: (
                self.sapi if nome == "SAPI.SpVoice" else self.memoria
            )
        )
        return voz, criar

    def test_pcm_em_memoria_configuracao_e_fala_literal(self):
        voz, criar = self.preparar()
        pcm, taxa = voz._sintetizar_pcm(
            "Olá <senhor>", threading.Event(), criar=criar, bombear=lambda: None
        )
        self.assertEqual(taxa, 22050)
        self.assertEqual(pcm, sinal())
        self.assertEqual(self.memoria.Format.Type, 22)
        self.assertIs(self.sapi.AudioOutputStream, self.memoria)
        self.assertEqual(self.sapi.Volume, 100)
        self.assertEqual(self.sapi.Voice, "voz instalada")
        self.sapi.Speak.assert_any_call("Olá <senhor>", 17)
        self.sapi.Speak.assert_any_call("", 3)
        self.assertEqual(
            [c.args[0] for c in criar.call_args_list],
            ["SAPI.SpVoice", "SAPI.SpMemoryStream"],
        )

    def test_cancelar_sintese_purga_sem_reproduzir(self):
        evento = threading.Event()
        voz, criar = self.preparar(evento)
        with self.assertRaises(Cancelado):
            voz._sintetizar_pcm("Cancelar", evento, criar=criar, bombear=lambda: None)
        self.sapi.Speak.assert_any_call("", 3)

    def test_fluxo_windows_usa_pcm_e_restaura_nivel_apos_interrupcao(self):
        voz = Voz.__new__(Voz)
        voz._sintetizar_pcm = Mock(return_value=(sinal(), 22050))
        nivel = Mock()
        with patch("sys.platform", "win32"), patch(
            "jarvis.audio_voz.reproduzir", side_effect=Cancelado
        ):
            with self.assertRaises(Cancelado):
                voz.falar_cancelavel("Teste", threading.Event(), nivel=nivel)
        nivel.assert_called_with(0.0)


class EsferaInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(ESTILO)

    def test_audio_capturado_fala_silencio_movimento_e_minimizar(self):
        with patch("jarvis.runtime.Runtime._dispositivos"):
            w = Janela(Configuracoes(sem_voz=True, sem_musica=True))
            w.show()
            self.app.processEvents()
            try:
                w.estado_runtime("Ouvindo · stream ativo")
                w.amplitude(0.6)
                w.nucleo.avancar()
                self.assertGreater(w.nucleo.nivel, 0)
                w.estado_runtime("Falando · microfone pausado")
                w.amplitude_voz(0.7)
                w.nucleo.avancar()
                voz = w.nucleo.nivel
                w.amplitude(0.0)
                self.assertEqual(w.nucleo.nivel, voz)
                w.amplitude_voz(0.0)
                self.assertEqual(w.nucleo.nivel, 0.0)
                w.nucleo.movimento(True)
                self.assertFalse(w.nucleo.timer.isActive())
                fase = w.nucleo.fase
                w.nucleo.amplitude(0.9)
                self.assertEqual(w.nucleo.fase, fase)
                w.nucleo.movimento(False)
                w.showMinimized()
                self.app.processEvents()
                self.assertFalse(w.nucleo.timer.isActive())
                w.showNormal()
                self.app.processEvents()
                self.assertTrue(w.nucleo.timer.isActive())
            finally:
                self.encerrar(w)

    def test_resultados_parciais_selecionaveis_markdown_e_layout(self):
        with patch("jarvis.runtime.Runtime._dispositivos"):
            w = Janela(Configuracoes(sem_voz=True, sem_musica=True))
            w.show()
            self.app.processEvents()
            try:
                w.atualizar_cartoes({"clima": "Fonte de teste"})
                self.assertTrue(w.clima.isVisible())
                self.assertFalse(w.dolar.isVisible())
                w.atualizar_cartoes({"dolar": "Cotação de teste"})
                self.assertIn("teste", w.clima.text())
                w.adicionar(
                    "Jarvis",
                    "**Resposta**\n\nTexto legível <script>não executável</script>",
                )
                self.assertIn("Resposta", w.resposta.toPlainText())
                self.assertIn("Resposta", w.historico.toPlainText())
                w.estado_acao_pc(
                    {
                        "ferramenta": "arquivo_buscar",
                        "status": "verificado",
                        "arquivos": [
                            {"nome": "notas.txt", "caminho": "C:/Documentos/notas.txt"}
                        ],
                    }
                )
                with patch.object(
                    w.runtime, "ferramenta_pc", return_value=True
                ) as abrir:
                    w.abrir_resultado(w.resultados_arquivos.item(0))
                    abrir.assert_called_once_with(
                        "arquivo_abrir", {"alvo": "C:/Documentos/notas.txt"}
                    )
                for largura, altura in ((1220, 850), (800, 600), (580, 420)):
                    w.resize(largura, altura)
                    self.app.processEvents()
                    p = w.nucleo.mapTo(w, QPoint(0, 0))
                    self.assertGreaterEqual(p.x(), 0)
                    self.assertLessEqual(p.x() + w.nucleo.width(), w.width())
                    self.assertLessEqual(
                        p.y() + w.nucleo.height(), w.entrada.mapTo(w, QPoint(0, 0)).y()
                    )
                    self.assertEqual(w.scroll.horizontalScrollBar().maximum(), 0)
                    self.assertGreater(w.clima.width(), 150)
                    self.assertGreater(w.dolar.width(), 150)
                w.estado_microfone(True)
                self.app.processEvents()
                self.assertEqual(w.width(), 580)
                d = Preferencias(w.config, w)
                d.provedor.setCurrentIndex(1)
                self.assertEqual(d.resultado().provedor_ia, "openai")
                d.close()
            finally:
                self.encerrar(w)

    def test_dispensar_resultados_preserva_historico_e_nova_consulta_reaparece(self):
        with patch("jarvis.runtime.Runtime._dispositivos"):
            w = Janela(Configuracoes(sem_voz=True, sem_musica=True))
            w.show()
            self.app.processEvents()
            try:
                w.adicionar("Jarvis", "Resposta preservada")
                w.atualizar_cartoes({"clima": "Fonte de teste"})
                w.dispensar.click()
                w.atualizar_cartoes({"clima": "Resultado seguinte"})
                fim = time.monotonic() + 0.35
                while time.monotonic() < fim:
                    self.app.processEvents()
                    time.sleep(0.005)
                self.assertTrue(w.clima.isVisible())
                self.assertFalse(w.resposta.isVisible())
                self.assertIn("preservada", w.historico.toPlainText())
                self.assertIn("seguinte", w.clima.text())
                self.assertIsNone(w.clima.graphicsEffect())
            finally:
                self.encerrar(w)

    def test_desenho_procedural_muda_apenas_com_audio_e_estado(self):
        orb = Nucleo()
        orb.resize(440, 440)
        orb.show()
        orb.timer.stop()
        try:
            orb.estado_operacao("aguardando")
            a = orb.grab().toImage()
            orb.estado_operacao("falando")
            orb.amplitude(0.8)
            orb.avancar()
            b = orb.grab().toImage()
            self.assertNotEqual(a, b)
            orb.amplitude(0.0)
            self.assertEqual(orb.nivel, 0.0)
            orb.estado_operacao("desativado")
            c = orb.grab().toImage()
            self.assertNotEqual(a, c)
        finally:
            orb.close()

    def encerrar(self, w):
        w.close()
        w.runtime.thread.join(2)
        w.runtime.audio_thread.join(2)
        w.runtime.monitor_thread.join(3)


class ConversaOpcionalTests(unittest.TestCase):
    def test_openai_explicita_sem_mudar_comandos_locais_e_sem_fallback_pago(self):
        from jarvis.cliente_local import ConversaLocal
        from jarvis.ferramentas.base import ErroFerramenta, resultado

        c = Configuracoes(provedor_ia="openai")
        controle = SimpleNamespace(
            config=lambda: c,
            cancelar_acao=threading.Event(),
            executar=Mock(return_value=resultado("Navegador solicitado")),
        )
        with patch("jarvis.cliente_local.load_dotenv"), patch(
            "jarvis.cliente_openai.Conversa"
        ) as remota, patch.dict(os.environ, {"OLLAMA_MODEL": ""}):
            remota.return_value.perguntar.return_value = "Resposta da API simulada"
            conversa = ConversaLocal(controle)
            try:
                self.assertEqual(
                    conversa.perguntar("Explique Python", threading.Event()),
                    "Resposta da API simulada",
                )
                self.assertEqual(
                    conversa.perguntar("abra o Google", threading.Event()),
                    "Navegador solicitado",
                )
                self.assertEqual(remota.return_value.perguntar.call_count, 1)
                c.provedor_ia = "local"
                with self.assertRaises(ErroFerramenta):
                    conversa.perguntar("Explique Python", threading.Event())
                self.assertEqual(remota.return_value.perguntar.call_count, 1)
                conversa.limpar()
                remota.return_value.limpar.assert_called_once()
            finally:
                conversa.fechar()
            remota.return_value.fechar.assert_called_once()


class CartoesParalelosTests(unittest.TestCase):
    def test_clima_publicado_antes_de_finalizar_dolar(self):
        from decimal import Decimal
        from jarvis.runtime import consultar_painel
        from jarvis.clima import Clima, Localizacao
        from jarvis.cotacao import Cotacao
        from jarvis.horario import agora_recife

        liberar = threading.Event()
        parcial = threading.Event()
        publicacoes = []
        resposta = []
        clima = Clima(
            Decimal("25"), "céu limpo", agora_recife(), Localizacao(-8.07, -39.12)
        )

        def dolar():
            liberar.wait(2)
            return Cotacao(Decimal("5"), agora_recife())

        def publicar(dados):
            publicacoes.append(dados)
            if "clima" in dados and "céu limpo" in dados["clima"]:
                parcial.set()

        with patch("jarvis.runtime.consultar_clima", return_value=clima), patch(
            "jarvis.runtime.consultar_cotacao", side_effect=dolar
        ):
            t = threading.Thread(
                target=lambda: resposta.append(
                    consultar_painel(threading.Event(), publicar)
                )
            )
            t.start()
            try:
                self.assertTrue(parcial.wait(1), "Clima esperou a outra consulta")
                self.assertFalse(any("R$" in d.get("dolar", "") for d in publicacoes))
            finally:
                liberar.set()
                t.join(2)
        self.assertTrue(any("R$" in d.get("dolar", "") for d in publicacoes))
        self.assertIn("Bom dia", resposta[0])


class CancelamentoCartoesTests(unittest.TestCase):
    def test_cancelar_consulta_remove_estado_consultando(self):
        from jarvis.runtime import consultar_painel

        publicacoes = []
        cancelar = threading.Event()
        executor = Mock()
        executor.submit.return_value.done.return_value = False

        def publicar(dados):
            publicacoes.append(dados)
            if any("Consultando" in v for v in dados.values()):
                cancelar.set()

        with patch("jarvis.runtime.ThreadPoolExecutor", return_value=executor):
            with self.assertRaises(Cancelado):
                consultar_painel(cancelar, publicar)
        self.assertTrue(all("cancelada" in v for v in publicacoes[-1].values()))
        self.assertFalse(any("Consultando" in v for v in publicacoes[-1].values()))
        executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()
