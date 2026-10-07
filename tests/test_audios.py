"""Controles de áudio com Qt real, player/SAPI simulados, sem dispositivos físicos."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication
from jarvis.cancelamento import Cancelado, verificar
from jarvis.configuracoes import Configuracoes
from jarvis.interface import Janela
from jarvis.musica import Musica
from jarvis.voz import Voz, ErroVoz


class PlayerTests(unittest.TestCase):
    def test_pausa_retoma_preserva_posicao_stop_nao_reinicia(self):
        mixer=Mock();mixer.get_init.return_value=True;mixer.music.get_busy.return_value=True
        with tempfile.TemporaryDirectory() as pasta:
            caminho=Path(pasta)/"teste.mp3";caminho.touch()
            with patch.dict("sys.modules", {"pygame":SimpleNamespace(mixer=mixer)}):
                m=Musica(str(caminho),avisar=lambda _:None);m.iniciar();m.pausar()
                self.assertEqual(m.estado_atual(),"pausada")
                m.retomar();self.assertEqual(m.estado_atual(),"tocando")
                mixer.music.pause.assert_called_once();mixer.music.unpause.assert_called_once()
                mixer.music.load.assert_called_once();mixer.music.play.assert_called_once_with()
                m.parar();self.assertEqual(m.estado_atual(),"parada")
                m.retomar();self.assertEqual(mixer.music.play.call_count,1)
                m.fechar();self.assertIsNone(m.mixer)

    def test_pausa_durante_fade_preserva_track_e_volume_duck(self):
        mixer=Mock();mixer.get_init.return_value=True;mixer.music.get_busy.return_value=True;mixer.music.get_volume.return_value=.07
        m=Musica("x.mp3",.2);m.mixer=mixer;m.ativa=True
        m.abaixar_para_fala();m.definir_volume(.1)
        self.assertAlmostEqual(mixer.music.set_volume.call_args.args[0],.035)
        with patch("jarvis.musica.time.sleep",side_effect=lambda _:m.pausar()):m.finalizar()
        self.assertTrue(m.pausada);self.assertTrue(m.ativa);mixer.music.stop.assert_not_called()
        m.retomar()
        with patch("jarvis.musica.time.sleep"):m.finalizar()
        self.assertFalse(m.ativa);mixer.music.stop.assert_called_once()

    def test_stop_e_quit_falham_sem_estado_parado_inventado(self):
        m=Musica("x.mp3",avisar=lambda _:None);m.mixer=Mock();m.ativa=True
        m.mixer.music.stop.side_effect=RuntimeError("stop falhou")
        m.mixer.quit.side_effect=RuntimeError("quit falhou")
        m.parar();self.assertEqual(m.estado_atual(),"falha")
        m.mixer.music.stop.side_effect=None;m.parar();self.assertEqual(m.estado_atual(),"parada")


class VozTests(unittest.TestCase):
    def test_interrupcao_limpa_fila_e_confirma_termino(self):
        evento=threading.Event();engine=Mock();fila=[];estado={"ativo":False,"purga":False}
        engine.say.side_effect=lambda texto:fila.append(texto)
        engine.startLoop.side_effect=lambda _:estado.update(ativo=True)
        def iterate():
            if estado["purga"]:estado["ativo"]=False
            else:evento.set()
        engine.iterate.side_effect=iterate
        engine.isBusy.side_effect=lambda:estado["ativo"]
        def stop():fila.clear();estado["purga"]=True
        engine.stop.side_effect=stop
        voz=Voz.__new__(Voz);voz.engine=engine
        with self.assertRaises(Cancelado):voz.falar_cancelavel("Texto de teste",evento)
        self.assertEqual(fila,[]);self.assertFalse(estado["ativo"])
        engine.stop.assert_called_once();engine.endLoop.assert_called_once()

    def test_volume_sapi_aplicado_pelo_driver_na_mesma_thread(self):
        evento=threading.Event();engine=Mock();engine.isBusy.side_effect=[False,False,False]
        voz=Voz.__new__(Voz);voz.engine=engine
        volume=iter([.8,.2])
        with patch("sys.platform","win32"):
            voz.falar_cancelavel("Teste",evento,volume=lambda:next(volume))
        self.assertEqual([c.args for c in engine.proxy._driver.setProperty.call_args_list],[("volume",.8),("volume",.2)])
        engine.setProperty.assert_not_called()

    def test_falha_da_purga_impede_reabrir_microfone(self):
        voz=Voz.__new__(Voz);voz.engine=Mock()
        voz.engine.isBusy.return_value=False
        voz.engine.stop.side_effect=RuntimeError("driver falhou")
        with self.assertRaises(ErroVoz) as contexto:
            voz.falar_cancelavel("Teste",threading.Event())
        self.assertTrue(contexto.exception.audio_pendente)


class AudioInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def esperar(self, predicado, timeout=3):
        fim=time.monotonic()+timeout
        while time.monotonic()<fim:
            self.app.processEvents()
            if predicado():return
            time.sleep(.005)
        self.fail("Condição de áudio não ocorreu no prazo")
    def fechar(self,w):
        w.close();w.runtime.thread.join(2);w.runtime.audio_thread.join(2)
        self.assertFalse(w.runtime.audio_thread.is_alive())

    def test_controles_durante_consulta_fala_independentes_e_historico(self):
        eventos=[];consulta=threading.Event();liberar=threading.Event();falando=threading.Event()
        class Player:
            pausada=False
            estado="parada"
            def __init__(self,*args,**kwargs):pass
            def iniciar(self):self.estado="tocando";eventos.append("musica")
            def estado_atual(self):return self.estado
            def pausar(self):self.estado="pausada";self.pausada=True;eventos.append("pausa")
            def retomar(self):self.estado="tocando";self.pausada=False;eventos.append("retoma")
            def parar(self):self.estado="parada";self.pausada=False;eventos.append("stop")
            def definir_volume(self,v):eventos.append(("volume_mp3",v))
            def abaixar_para_fala(self):pass
            def finalizar(self,**kwargs):self.parar()
            def fechar(self):self.parar()
        def consultar(*args):consulta.set();liberar.wait(2);return "Resposta preservada no histórico"
        def falar(texto,cancel,**kwargs):
            falando.set()
            while not cancel.wait(.01):pass
            verificar(cancel)
        voz=SimpleNamespace(falar_cancelavel=falar,fechar=lambda:None)
        with patch("jarvis.runtime.Musica",Player),patch("jarvis.runtime.consultar_painel",side_effect=consultar),patch("jarvis.runtime.Voz",return_value=voz),patch("jarvis.interface.salvar"):
            w=Janela(Configuracoes());w.show()
            try:
                self.assertTrue(w.runtime.enviar("bom dia Jarvis"));self.esperar(consulta.is_set)
                self.esperar(lambda:w.pausa_musica.isEnabled())
                w.pausa_musica.click();self.esperar(lambda:w.pausa_musica.text()=="Retomar música")
                # A consulta ainda está bloqueada: o Qt e o player continuam respondendo.
                self.assertFalse(liberar.is_set());w.pausa_musica.click()
                self.esperar(lambda:"retoma" in eventos)
                liberar.set();self.esperar(falando.is_set)
                self.esperar(w.interromper_voz.isEnabled)
                w.stop_musica.click();self.esperar(lambda:w.audio_estado=="parada")
                self.assertTrue(w.runtime.falando_agora.is_set())
                w.interromper_voz.click();self.esperar(lambda:not w.runtime.trabalhando)
                self.assertIn("Resposta preservada",w.historico.toPlainText())
                self.assertFalse(w.runtime.falando_agora.is_set())
            finally:liberar.set();self.fechar(w)

    def test_parar_todos_durante_consulta_impede_fala_posterior(self):
        iniciou=threading.Event();liberar=threading.Event()
        def consultar(*args):iniciou.set();liberar.wait(2);return "Texto após parar áudios"
        with patch("jarvis.runtime.consultar_painel",side_effect=consultar),patch("jarvis.runtime.Voz") as voz:
            w=Janela(Configuracoes(sem_musica=True));w.show()
            try:
                w.runtime.enviar("bom dia Jarvis");self.esperar(iniciou.is_set)
                w.stop_audios.click();liberar.set();self.esperar(lambda:not w.runtime.trabalhando and "Texto após parar áudios" in w.historico.toPlainText())
                self.assertIn("Texto após parar áudios",w.historico.toPlainText());voz.assert_not_called()
            finally:liberar.set();self.fechar(w)

    def test_voz_desativada_volume_independente_e_redimensionamento(self):
        with patch("jarvis.runtime.Conversa.perguntar",return_value="Resposta escrita"),patch("jarvis.runtime.Voz") as voz,patch("jarvis.interface.salvar"):
            w=Janela(Configuracoes());w.show()
            try:
                w.habilitar_voz.setChecked(False)
                w.volume_voz.setValue(40);w.volume_musica.setValue(15)
                self.assertTrue(w.runtime.config.sem_voz)
                self.assertEqual(w.runtime.config.volume_voz,.4);self.assertEqual(w.runtime.config.volume,.15)
                w.runtime.enviar("Jarvis, explique Python")
                self.esperar(lambda:"Resposta escrita" in w.historico.toPlainText());voz.assert_not_called()
                from PySide6.QtCore import QPoint
                w.resize(580,420);self.app.processEvents()
                for botao in (w.stop_audios,w.pausa_musica,w.interromper_voz,w.parar):
                    p=botao.mapTo(w,QPoint(0,0))
                    self.assertGreaterEqual(p.y(),0);self.assertLessEqual(p.y()+botao.height(),w.height())
                    self.assertLessEqual(p.x()+botao.width(),w.width())
                from PySide6.QtWidgets import QScrollArea
                self.assertEqual(w.findChild(QScrollArea).horizontalScrollBar().maximum(),0)
            finally:self.fechar(w)

    def test_retomar_fecha_captura_e_microfone_retoma_apos_stop(self):
        captura=threading.Event();fechou=threading.Event();retomou=threading.Event();chamadas=[]
        class Player:
            estado="pausada"
            def estado_atual(self):return self.estado
            def retomar(self):
                self_estado=self
                if not fechou.is_set():raise AssertionError("Retomada antes de fechar o microfone")
                self.estado="tocando";retomou.set()
            def parar(self):self.estado="parada"
            def fechar(self):self.parar()
        def capturar(cancel,**kwargs):
            chamadas.append("captura");captura.set()
            try:
                cancel.wait(2);verificar(cancel)
            finally:
                fechou.set();kwargs["captura_finalizada"]()
        with patch("jarvis.runtime.Ouvinte",return_value=SimpleNamespace(capturar_texto=capturar)):
            w=Janela(Configuracoes(sem_voz=True));w.show()
            try:
                w.runtime.musica=Player();w.mic.click();self.esperar(captura.is_set)
                w.runtime.controlar_musica("retomar");self.esperar(retomou.is_set)
                n=len(chamadas);time.sleep(.1);self.app.processEvents();self.assertEqual(len(chamadas),n)
                w.runtime.parar_audios();self.esperar(lambda:len(chamadas)>n)
                self.assertTrue(w.runtime.ativo)
            finally:self.fechar(w)

    def test_interromper_fala_retoma_microfone_sem_apagar_resposta(self):
        iniciou=threading.Event();capturas=[]
        def capturar(cancel,**kwargs):
            capturas.append(True)
            if len(capturas)==1:return "bom dia Jarvis"
            cancel.wait(2);verificar(cancel)
        def falar(texto,cancel,**kwargs):
            iniciou.set();cancel.wait(2);verificar(cancel)
        with patch("jarvis.runtime.Ouvinte",return_value=SimpleNamespace(capturar_texto=capturar)),patch("jarvis.runtime.Voz",return_value=SimpleNamespace(falar_cancelavel=falar,fechar=lambda:None)),patch("jarvis.runtime.consultar_painel",return_value="Resposta que permanece"):
            w=Janela(Configuracoes(sem_musica=True));w.show()
            try:
                w.mic.click();self.esperar(iniciou.is_set)
                self.assertEqual(len(capturas),1)
                self.esperar(w.interromper_voz.isEnabled);w.interromper_voz.click()
                self.esperar(lambda:len(capturas)>1)
                self.assertTrue(w.runtime.ativo);self.assertIn("Resposta que permanece",w.historico.toPlainText())
            finally:self.fechar(w)

    def test_retomar_durante_inferencia_nao_espera_modelo(self):
        inferindo=threading.Event();retomou=threading.Event();liberar=threading.Event()
        class Player:
            estado="pausada"
            def estado_atual(self):return self.estado
            def retomar(self):self.estado="tocando";retomou.set()
            def parar(self):self.estado="parada"
            def fechar(self):self.parar()
        def capturar(cancel,**kwargs):
            kwargs["captura_finalizada"]();inferindo.set()
            liberar.wait(2);verificar(cancel);return "ruído"
        with patch("jarvis.runtime.Ouvinte",return_value=SimpleNamespace(capturar_texto=capturar)):
            w=Janela(Configuracoes(sem_voz=True));w.show()
            try:
                w.runtime.musica=Player();w.mic.click();self.esperar(inferindo.is_set)
                w.runtime.controlar_musica("retomar");self.esperar(retomou.is_set)
                self.assertFalse(liberar.is_set())
            finally:liberar.set();self.fechar(w)


if __name__=="__main__":unittest.main()
