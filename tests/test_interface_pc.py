"""Qt real offscreen, worker real; nenhuma entrada/saída física de áudio."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from dataclasses import replace
import tempfile
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from jarvis.configuracoes import Configuracoes
from jarvis.interface import Janela
from jarvis.interface_pc import PermissoesDialog, ConfirmacaoDialog
from jarvis.ferramentas.base import Decisoes


class InterfacePCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def esperar(self, fn):
        fim = time.monotonic() + 3
        while time.monotonic() < fim:
            self.app.processEvents()
            if fn():
                return
            time.sleep(0.005)
        self.fail("Evento não ocorreu")

    def test_confirmacao_modeless_cancelar_worker_e_suspender_preserva_saudacao(self):
        with tempfile.TemporaryDirectory() as pasta, patch("jarvis.interface.salvar"):
            p = Path(pasta) / "alvo.txt"
            p.write_text("original")
            w = Janela(
                Configuracoes(sem_voz=True, sem_musica=True, pastas_autorizadas=[pasta])
            )
            w.show()
            try:
                self.assertTrue(
                    w.runtime.ferramenta_pc(
                        "arquivo_criar", {"destino": str(p), "conteudo": "novo"}
                    )
                )
                self.esperar(lambda: w.runtime.decisoes.pendente is not None)
                self.assertTrue(w.runtime.trabalhando)
                self.app.processEvents()
                dialogs = w.findChildren(ConfirmacaoDialog)
                self.assertTrue(dialogs)
                self.assertFalse(dialogs[-1].isModal())
                self.assertIn(str(p), dialogs[-1].alvo.toPlainText())
                w.runtime.cancelar_acao()
                self.esperar(lambda: not w.runtime.trabalhando)
                self.assertEqual(p.read_text(), "original")
                w.runtime.suspender_pc()
                self.assertTrue(w.runtime.config.pc_suspenso)
                with patch(
                    "jarvis.runtime.consultar_painel",
                    return_value="Saudação preservada",
                ):
                    w.runtime.enviar("bom dia Jarvis")
                    self.esperar(
                        lambda: "Saudação preservada" in w.historico.toPlainText()
                    )
            finally:
                w.close()
                w.runtime.thread.join(2)
                w.runtime.audio_thread.join(2)
            self.assertFalse(w.runtime.thread.is_alive())
            self.assertFalse(w.runtime.audio_thread.is_alive())

    def test_confirmacao_por_voz_local_rejeita_texto_generico(self):
        w = Janela(Configuracoes(sem_voz=True, sem_musica=True))
        try:
            d = w.runtime.decisoes
            p = {
                "id": "local",
                "acao": "Excluir",
                "alvo": "arquivo",
                "opcoes": [],
                "expira": time.monotonic() + 10,
            }
            d.pendente = p
            self.assertFalse(w.runtime._responder_decisao("sim", p))
            self.assertTrue(w.runtime._responder_decisao("Jarvis, confirmar", p))
            self.assertTrue(d.resposta)
            p["expira"] = time.monotonic() - 1
            self.assertFalse(w.runtime._responder_decisao("confirmar", p))
        finally:
            w.close()
            w.runtime.thread.join(2)

    def test_erro_de_controle_nao_libera_microfone_com_musica_ativa(self):
        w = Janela(Configuracoes(sem_voz=True, sem_musica=True))
        try:
            w.runtime._midia_externa("spotify", True)
            w.runtime._estado_acao(
                {"ferramenta": "spotify_controlar", "status": "em andamento"}
            )
            w.runtime._estado_acao(
                {
                    "ferramenta": "spotify_controlar",
                    "status": "negado",
                    "audio_nao_executado": True,
                }
            )
            self.assertTrue(w.runtime.midia_externa.is_set())
        finally:
            w.close()
            w.runtime.thread.join(2)

    def test_permissoes_persistentes_sem_mexer_microfone_e_guard_audio_externo(self):
        with patch("jarvis.interface.salvar"):
            w = Janela(Configuracoes(sem_voz=True, sem_musica=True))
            try:
                d = PermissoesDialog(w.config, w)
                d.categorias["arquivos"].setChecked(False)
                d.fones.setChecked(True)
                cfg = d.resultado()
                w.runtime.configurar_pc(cfg)
                self.assertFalse(w.runtime.config.permissoes_pc["arquivos"])
                self.assertTrue(w.runtime.config.fones_midia_externa)
                w.runtime._estado_acao(
                    {
                        "ferramenta": "spotify_controlar",
                        "status": "verificado",
                        "fonte": "spotify",
                        "tocando": True,
                    }
                )
                self.assertTrue(w.runtime.midia_externa.is_set())
                w.runtime._estado_acao(
                    {
                        "ferramenta": "spotify_controlar",
                        "status": "verificado",
                        "fonte": "spotify",
                        "tocando": False,
                    }
                )
                self.assertFalse(w.runtime.midia_externa.is_set())
                d.close()
            finally:
                w.close()
                w.runtime.thread.join(2)


class InterfaceLocalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def esperar(self, predicado):
        fim = time.monotonic() + 3
        while time.monotonic() < fim:
            self.app.processEvents()
            if predicado():
                return
            time.sleep(0.005)
        self.fail("Evento não ocorreu")

    def test_pesquisa_digitada_sem_chave_sem_openai_e_resultado_no_painel(self):
        from jarvis.ferramentas.base import HistoricoAcoes, resultado

        with tempfile.TemporaryDirectory() as pasta, patch.dict(
            os.environ, {"OPENAI_API_KEY": "", "OLLAMA_MODEL": ""}
        ), patch("jarvis.cliente_local.load_dotenv"), patch(
            "openai.OpenAI", side_effect=AssertionError("OpenAI proibida")
        ), patch(
            "requests.Session.post", side_effect=AssertionError("IA proibida")
        ):
            w = Janela(Configuracoes(sem_voz=True, sem_musica=True))
            w.runtime.controle.historico = HistoricoAcoes(Path(pasta) / "log.jsonl")
            w.show()
            try:
                with patch.object(
                    w.runtime.controle.windows,
                    "google",
                    return_value=resultado(
                        "Pesquisa encaminhada ao navegador", "solicitado"
                    ),
                ) as google:
                    w.entrada.setText("Jarvis, pesquise notícias de Salgueiro")
                    w.enviar.click()
                    self.esperar(
                        lambda: "Pesquisa encaminhada" in w.historico.toPlainText()
                    )
                    self.assertEqual(google.call_args.args[0], "notícias de Salgueiro")
                    self.assertIn("solicitado", w.acao_pc.text())
            finally:
                w.close()
                w.runtime.thread.join(2)
                w.runtime.audio_thread.join(2)
                w.runtime.monitor_thread.join(3)

    def test_ativacao_e_pergunta_capturadas_sem_openai_retoma(self):
        from types import SimpleNamespace
        from jarvis.ferramentas.base import HistoricoAcoes, resultado
        from jarvis.cancelamento import verificar

        frases = iter(["Jarvis", "pesquise como fazer currículo"])
        retomou = threading.Event()

        def capturar(cancel, **kwargs):
            try:
                return next(frases)
            except StopIteration:
                retomou.set()
                cancel.wait(0.05)
                verificar(cancel)
                return ""

        with tempfile.TemporaryDirectory() as pasta, patch(
            "jarvis.runtime.Ouvinte",
            return_value=SimpleNamespace(capturar_texto=capturar),
        ), patch("jarvis.cliente_local.load_dotenv"), patch.dict(
            os.environ, {"OPENAI_API_KEY": "", "OLLAMA_MODEL": ""}
        ), patch(
            "requests.Session.post", side_effect=AssertionError("IA proibida")
        ):
            w = Janela(Configuracoes(sem_voz=True, sem_musica=True))
            w.runtime.controle.historico = HistoricoAcoes(Path(pasta) / "log.jsonl")
            w.show()
            try:
                with patch.object(
                    w.runtime.controle.windows,
                    "google",
                    return_value=resultado(
                        "Pesquisa de currículo enviada", "solicitado"
                    ),
                ) as google:
                    w.mic.click()
                    self.esperar(
                        lambda: "Pesquisa de currículo" in w.historico.toPlainText()
                    )
                    self.esperar(retomou.is_set)
                    self.assertEqual(google.call_args.args[0], "como fazer currículo")
                    self.assertTrue(w.runtime.ativo)
            finally:
                w.close()
                w.runtime.thread.join(2)
                w.runtime.audio_thread.join(2)
                w.runtime.monitor_thread.join(3)
