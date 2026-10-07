"""Síntese local com uma voz portuguesa instalada no computador."""

import logging


class ErroVoz(Exception):
    def __init__(self, mensagem, audio_pendente=False):
        super().__init__(mensagem)
        self.audio_pendente = audio_pendente


class Voz:
    def __init__(self, velocidade: int = 175, identificador: str | None = None):
        self.engine = None
        try:
            import pyttsx3
            import sys

            self.engine = pyttsx3.init(
                driverName="sapi5" if sys.platform == "win32" else None
            )
            vozes = self.engine.getProperty("voices")
            if identificador:
                selecionada = next((v for v in vozes if v.id == identificador), None)
            else:
                portugues = [v for v in vozes if self._portugues(v)]
                selecionada = next((v for v in portugues if self._brasileira(v)), None)
                selecionada = selecionada or (portugues[0] if portugues else None)
            if selecionada is None:
                raise ErroVoz(
                    "Voz não encontrada. Instale uma voz em português no Windows ou confira --voz."
                )
            self.engine.setProperty("voice", selecionada.id)
            self.engine.setProperty("rate", velocidade)
            if sys.platform == "win32":
                # A síntese em memória não inicia o loop pyttsx3 que consumiria estas propriedades.
                self.engine.proxy._driver.setProperty("voice", selecionada.id)
                self.engine.proxy._driver.setProperty("rate", velocidade)
            print(f"Voz selecionada: {selecionada.name}", flush=True)
        except ErroVoz:
            self.fechar()
            raise
        except Exception as erro:
            self.fechar()
            raise ErroVoz(
                "Não foi possível iniciar a voz. Confira as dependências e as vozes do Windows."
            ) from erro

    @staticmethod
    def _descricao(voz) -> str:
        idiomas = [
            s.decode("utf-8", errors="ignore") if isinstance(s, bytes) else str(s)
            for s in voz.languages
        ]
        return " ".join([voz.id, voz.name, *idiomas]).casefold().replace("_", "-")

    @classmethod
    def _portugues(cls, voz) -> bool:
        texto = cls._descricao(voz)
        return any(
            x in texto
            for x in ("pt-br", "pt-pt", "portugu", "brazil", "\x05pt", "\x02pt")
        )

    @classmethod
    def _brasileira(cls, voz) -> bool:
        texto = cls._descricao(voz)
        return "pt-br" in texto or "brazil" in texto

    def falar(self, texto: str) -> None:
        try:
            self.engine.say(texto)
            self.engine.runAndWait()
        except Exception as erro:
            raise ErroVoz(
                "Falha na síntese de voz. Confira a saída de áudio do Windows."
            ) from erro

    def fechar(self) -> None:
        engine, self.engine = self.engine, None
        if engine is not None:
            try:
                engine.stop()
            except Exception as erro:
                logging.getLogger(__name__).warning(
                    "Voz não confirmou encerramento: %s", type(erro).__name__
                )

    def definir_volume(self, volume):
        import sys

        volume = max(0.0, min(1.0, float(volume)))
        if sys.platform == "win32":
            # Driver SAPI5 do pyttsx3 2.99: evita enfileirar a mudança atrás da fala.
            # Executado exclusivamente na thread que criou o COM/SAPI.
            self.engine.proxy._driver.setProperty("volume", volume)
        else:
            self.engine.setProperty("volume", volume)

    def _sintetizar_pcm(self, texto, cancelar, criar=None, bombear=None):
        """SAPI para SpMemoryStream (22.050 Hz, 16 bits, mono), sem gravação em disco."""
        from .cancelamento import verificar, Cancelado
        import time

        if criar is None:
            from comtypes.client import CreateObject

            criar = CreateObject
        if bombear is None:
            import pythoncom

            bombear = pythoncom.PumpWaitingMessages
        verificar(cancelar)
        sapi = criar("SAPI.SpVoice")
        memoria = criar("SAPI.SpMemoryStream")
        memoria.Format.Type = 22  # SpeechAudioFormatType.SAFT22kHz16BitMono
        instalado = self.engine.proxy._driver._tts
        sapi.Voice, sapi.Rate = instalado.Voice, instalado.Rate
        sapi.Volume = 100  # Ganho aplicado no player; o medidor inclui o volume da voz.
        sapi.AllowAudioOutputFormatChangesOnNextSet = False
        sapi.AudioOutputStream = memoria
        try:
            sapi.Speak(texto, 1 | 16)  # Assíncrono; SVSFIsNotXML: fala literal.
            limite = time.monotonic() + 30.0
            while not sapi.WaitUntilDone(10):
                verificar(cancelar)
                bombear()
                if time.monotonic() > limite:
                    raise ErroVoz(
                        "A síntese demorou demais. Tente uma resposta mais curta ou outra voz."
                    )
            verificar(cancelar)
            pcm = bytes(memoria.GetData())
            if not pcm or len(pcm) % 2:
                raise ErroVoz(
                    "A voz instalada não produziu PCM válido. Selecione outra voz SAPI5."
                )
            return pcm, 22050
        except (Cancelado, ErroVoz):
            raise
        except Exception as erro:
            raise ErroVoz(
                "Não foi possível sintetizar a voz em memória. Confira a voz SAPI5 instalada."
            ) from erro
        finally:
            # Só há síntese em memória neste objeto COM; não há áudio no dispositivo ainda.
            try:
                sapi.Speak("", 3)
                if not sapi.WaitUntilDone(1000):
                    raise ErroVoz("A voz não confirmou o fim da síntese em memória.")
            except ErroVoz:
                raise
            except Exception as erro:
                raise ErroVoz(
                    "Não foi possível encerrar a síntese em memória."
                ) from erro

    def falar_cancelavel(self, texto, cancelar, volume=None, nivel=None, estado=None):
        import sys

        if sys.platform == "win32" and nivel is not None:
            from .audio_voz import reproduzir
            from .cancelamento import Cancelado

            try:
                pcm, taxa = self._sintetizar_pcm(texto, cancelar)
                reproduzir(pcm, taxa, cancelar, volume, nivel, estado)
            except (Cancelado, ErroVoz):
                raise
            except Exception as erro:
                raise ErroVoz(
                    "Falha na reprodução da voz. Confira o dispositivo de saída do Windows."
                ) from erro
            finally:
                nivel(0.0)
            return
        if estado:
            estado("Falando · microfone pausado")
        from .cancelamento import verificar
        import time

        iniciou = False
        ultimo_volume = None
        try:
            verificar(cancelar)
            if volume is not None:
                ultimo_volume = volume()
                self.definir_volume(ultimo_volume)
            self.engine.say(texto)
            self.engine.startLoop(False)
            iniciou = True
            while True:
                verificar(cancelar)
                if volume is not None and (novo_volume := volume()) != ultimo_volume:
                    self.definir_volume(novo_volume)
                    ultimo_volume = novo_volume
                self.engine.iterate()
                if not self.engine.isBusy():
                    break
                cancelar.wait(0.01)
        except Exception as erro:
            from .cancelamento import Cancelado

            if isinstance(erro, Cancelado):
                raise
            raise ErroVoz(
                "Falha na síntese local. Confira voz e saída de áudio."
            ) from erro
        finally:
            # stop purga a fila pyttsx3 e usa SAPI Speak("", 3) para purgar o áudio.
            # Bombeia os eventos de término antes de permitir reabrir o microfone.
            try:
                self.engine.stop()
            except Exception as erro:
                raise ErroVoz(
                    "Não foi possível interromper a saída de voz. Reinicie o Jarvis antes de escutar.",
                    audio_pendente=True,
                ) from erro
            if iniciou:
                limite = time.monotonic() + 1.0
                try:
                    while self.engine.isBusy() and time.monotonic() < limite:
                        self.engine.iterate()
                        time.sleep(0.005)
                    if self.engine.isBusy():
                        raise ErroVoz(
                            "Não foi possível confirmar o fim da fala. Reinicie o Jarvis antes de ativar o microfone.",
                            audio_pendente=True,
                        )
                finally:
                    try:
                        self.engine.endLoop()
                    except Exception as erro:
                        raise ErroVoz(
                            "Não foi possível encerrar o ciclo da voz. Reinicie o Jarvis antes de escutar.",
                            audio_pendente=True,
                        ) from erro
