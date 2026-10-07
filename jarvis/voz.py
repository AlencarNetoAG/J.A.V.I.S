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
            self.engine = pyttsx3.init(driverName="sapi5" if sys.platform == "win32" else None)
            vozes = self.engine.getProperty("voices")
            if identificador:
                selecionada = next((v for v in vozes if v.id == identificador), None)
            else:
                portugues = [v for v in vozes if self._portugues(v)]
                selecionada = next((v for v in portugues if self._brasileira(v)), None)
                selecionada = selecionada or (portugues[0] if portugues else None)
            if selecionada is None:
                raise ErroVoz("Voz não encontrada. Instale uma voz em português no Windows ou confira --voz.")
            self.engine.setProperty("voice", selecionada.id)
            self.engine.setProperty("rate", velocidade)
            print(f"Voz selecionada: {selecionada.name}", flush=True)
        except ErroVoz:
            self.fechar()
            raise
        except Exception as erro:
            self.fechar()
            raise ErroVoz("Não foi possível iniciar a voz. Confira as dependências e as vozes do Windows.") from erro

    @staticmethod
    def _descricao(voz) -> str:
        idiomas = [s.decode("utf-8", errors="ignore") if isinstance(s, bytes) else str(s) for s in voz.languages]
        return " ".join([voz.id, voz.name, *idiomas]).casefold().replace("_", "-")

    @classmethod
    def _portugues(cls, voz) -> bool:
        texto = cls._descricao(voz)
        return any(x in texto for x in ("pt-br", "pt-pt", "portugu", "brazil", "\x05pt", "\x02pt"))

    @classmethod
    def _brasileira(cls, voz) -> bool:
        texto = cls._descricao(voz)
        return "pt-br" in texto or "brazil" in texto

    def falar(self, texto: str) -> None:
        try:
            self.engine.say(texto)
            self.engine.runAndWait()
        except Exception as erro:
            raise ErroVoz("Falha na síntese de voz. Confira a saída de áudio do Windows.") from erro

    def fechar(self) -> None:
        engine, self.engine = self.engine, None
        if engine is not None:
            try: engine.stop()
            except Exception as erro:
                logging.getLogger(__name__).warning("Voz não confirmou encerramento: %s", type(erro).__name__)

    def definir_volume(self, volume):
        import sys
        volume = max(0., min(1., float(volume)))
        if sys.platform == "win32":
            # Driver SAPI5 do pyttsx3 2.99: evita enfileirar a mudança atrás da fala.
            # Executado exclusivamente na thread que criou o COM/SAPI.
            self.engine.proxy._driver.setProperty("volume", volume)
        else:
            self.engine.setProperty("volume", volume)

    def falar_cancelavel(self, texto, cancelar, volume=None):
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
            raise ErroVoz("Falha na síntese local. Confira voz e saída de áudio.") from erro
        finally:
            # stop purga a fila pyttsx3 e usa SAPI Speak("", 3) para purgar o áudio.
            # Bombeia os eventos de término antes de permitir reabrir o microfone.
            try:
                self.engine.stop()
            except Exception as erro:
                raise ErroVoz("Não foi possível interromper a saída de voz. Reinicie o Jarvis antes de escutar.", audio_pendente=True) from erro
            if iniciou:
                limite = time.monotonic()+1.
                try:
                    while self.engine.isBusy() and time.monotonic() < limite:
                        self.engine.iterate()
                        time.sleep(.005)
                    if self.engine.isBusy():
                        raise ErroVoz("Não foi possível confirmar o fim da fala. Reinicie o Jarvis antes de ativar o microfone.", audio_pendente=True)
                finally:
                    try: self.engine.endLoop()
                    except Exception as erro:
                        raise ErroVoz("Não foi possível encerrar o ciclo da voz. Reinicie o Jarvis antes de escutar.", audio_pendente=True) from erro
