"""Teste Qt offscreen: widgets reais, rede/áudio substituídos, sem hardware."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from jarvis.configuracoes import Configuracoes
from jarvis.interface import Janela, Preferencias, ESTILO


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(ESTILO)

    def esperar(self, predicado, timeout=3):
        fim=time.monotonic()+timeout
        while time.monotonic()<fim:
            self.app.processEvents()
            if predicado():return
            time.sleep(.01)
        self.fail("Evento da interface não ocorreu no prazo.")

    def test_bom_dia_sem_chave_e_sem_audio_cards_limpar_resize(self):
        def consultar(cancel,publicar):
            publicar({"clima":"Fonte meteorológica de teste","dolar":"Fonte cambial de teste"})
            return "Bom dia de teste, senhor."
        with patch("jarvis.runtime.consultar_painel",side_effect=consultar):
            w=Janela(Configuracoes(sem_voz=True,sem_musica=True));w.show()
            try:
                w.entrada.setText("bom dia Jarvis");w.enviar.click()
                self.esperar(lambda:"Bom dia de teste" in w.historico.toPlainText())
                self.assertIn("meteorológica",w.clima.text())
                w.resize(580,420);self.app.processEvents()
                self.assertGreater(w.parar.width(),0)
                from PySide6.QtCore import QPoint
                posicao=w.parar.mapTo(w,QPoint(0,0))
                self.assertLessEqual(posicao.y()+w.parar.height(),w.height())
                w.limpar.click();self.assertEqual(w.historico.toPlainText(),"")
                w.nucleo.movimento(True);self.assertFalse(w.nucleo.timer.isActive())
                w.amplitude(.5);self.assertEqual(w.nivel.value(),50)
                d=Preferencias(w.config,w)
                d.atualizar_dispositivos({"microfones":[(1,"Entrada teste")],"vozes":[("voz-teste","Voz teste")]})
                self.assertEqual(d.mic.count(),2)
                d.volume.setValue(.2);self.assertEqual(d.resultado().volume,.2)
                d.close()
            finally:
                w.close();w.runtime.thread.join(timeout=2)

    def test_parar_e_duplicatas_durante_consulta(self):
        iniciou=threading.Event()
        def consulta(pergunta,cancel):
            iniciou.set();cancel.wait(2)
            from jarvis.cancelamento import verificar
            verificar(cancel)
            return "Resposta que não deve aparecer"
        with patch("jarvis.runtime.Conversa.perguntar",side_effect=consulta) as api:
            w=Janela(Configuracoes(sem_voz=True,sem_musica=True));w.show()
            try:
                self.assertTrue(w.runtime.enviar("Jarvis, explique uma função"))
                self.esperar(iniciou.is_set)
                self.assertFalse(w.runtime.enviar("Pergunta duplicada"))
                self.app.processEvents()
                self.assertTrue(w.parar.isEnabled())
                w.parar.click()
                self.esperar(lambda:not w.runtime.trabalhando)
                self.assertNotIn("não deve aparecer",w.historico.toPlainText())
                self.assertEqual(api.call_count,1)
            finally:w.close();w.runtime.thread.join(timeout=2)

    def test_jarvis_sozinho_pede_e_captura_pergunta_sem_audio_sobreposto(self):
        eventos=[]
        frases=iter(["Jarvis", "Explique uma função"])
        def capturar(cancel, **kwargs):
            eventos.append("captura")
            try:return next(frases)
            except StopIteration:
                cancel.wait(.2)
                from jarvis.cancelamento import verificar
                verificar(cancel)
                return "ruído"
        from types import SimpleNamespace
        ouvinte=SimpleNamespace(capturar_texto=capturar)
        voz=SimpleNamespace(falar_cancelavel=lambda texto,cancel:eventos.append(texto),fechar=lambda:None)
        with patch("jarvis.runtime.Ouvinte",return_value=ouvinte),patch("jarvis.runtime.Voz",return_value=voz),patch("jarvis.runtime.Conversa.perguntar",return_value="Resposta de teste") as api:
            w=Janela(Configuracoes(sem_musica=True));w.show()
            try:
                w.mic.click()
                self.esperar(lambda:"Resposta de teste" in w.historico.toPlainText())
                self.assertEqual(eventos[:4],["captura","Sim, senhor?","captura","Resposta de teste"])
                self.assertEqual(api.call_args.args[0],"Explique uma função")
            finally:w.close();w.runtime.thread.join(timeout=2)

    def test_ativacao_sem_pergunta_expira_sem_openai(self):
        from types import SimpleNamespace
        frases=iter(["Jarvis", ""])
        timeout=[]
        def capturar(cancel,**kwargs):
            if "timeout" in kwargs:timeout.append(kwargs["timeout"])
            try:return next(frases)
            except StopIteration:
                cancel.wait(.2)
                from jarvis.cancelamento import verificar
                verificar(cancel)
                return "ruído"
        with patch("jarvis.runtime.Ouvinte",return_value=SimpleNamespace(capturar_texto=capturar)),patch("jarvis.runtime.Conversa.perguntar") as api:
            w=Janela(Configuracoes(sem_voz=True,sem_musica=True,timeout_pergunta=7));w.show()
            try:
                w.mic.click()
                self.esperar(lambda:"Nenhuma pergunta" in w.aviso.text())
                api.assert_not_called();self.assertEqual(timeout,[7])
            finally:w.close();w.runtime.thread.join(timeout=2)


if __name__=="__main__":unittest.main()
