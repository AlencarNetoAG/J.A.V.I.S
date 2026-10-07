"""Player SDL para MP3 local, com comandos curtos protegidos por lock."""
from pathlib import Path
import logging
import threading
import time

log = logging.getLogger(__name__)


class Musica:
    def __init__(self, caminho, volume=.12, avisar=None):
        self.caminho = Path(caminho)
        self.volume = volume
        self.mixer = None
        self.ativa = False
        self.pausada = False
        self.audio_pendente = False
        self.duck = False
        self.ganho_fade = 1.
        self.avisar = avisar
        self.lock = threading.RLock()

    def _aviso(self, texto):
        if self.avisar: self.avisar(texto)
        else: print(texto, flush=True)

    def _aplicar_volume(self):
        volume = min(self.volume*.35, .08) if self.duck else self.volume
        self.mixer.music.set_volume(volume*self.ganho_fade)

    def iniciar(self):
        with self.lock:
            self.parar()
            if self.audio_pendente: return
            if not self.caminho.is_file():
                self._aviso("Música ausente. Coloque seu MP3 em assets/highway_to_hell.mp3 ou escolha outro arquivo.")
                return
            try:
                import os
                os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
                from pygame import mixer
                self.mixer = mixer
                if not mixer.get_init(): mixer.init()
                mixer.music.load(str(self.caminho))
                self.duck = False; self.ganho_fade = 1.
                self._aplicar_volume()
                mixer.music.play()
                self.ativa = True
                self._aviso("Música de fundo iniciada.")
            except Exception as erro:
                log.warning("Player não iniciou: %s", type(erro).__name__)
                self._aviso("Não foi possível reproduzir a música. A saudação continuará.")
                self.parar()

    def estado_atual(self):
        with self.lock:
            if self.audio_pendente: return "falha"
            if self.ativa and not self.pausada:
                try:
                    if not self.mixer.music.get_busy(): self.ativa = False
                except Exception as erro:
                    log.warning("Estado do player indisponível: %s", type(erro).__name__)
                    self.parar()
            return "pausada" if self.pausada else ("tocando" if self.ativa else "parada")

    def pausar(self):
        with self.lock:
            if self.estado_atual() == "tocando":
                self.mixer.music.pause()
                self.pausada = True

    def retomar(self):
        with self.lock:
            if self.ativa and self.pausada:
                self.mixer.music.unpause()  # Sem load/play/rewind: preserva a posição.
                self.pausada = False

    def definir_volume(self, volume):
        with self.lock:
            self.volume = max(0., min(1., float(volume)))
            if self.ativa: self._aplicar_volume()

    def abaixar_para_fala(self):
        with self.lock:
            if self.ativa:
                self.duck = True
                self._aplicar_volume()

    def finalizar(self, duracao=1.5, cancelar=None):
        # Fade no worker da saudação; o controlador continua recebendo pause/stop/volume.
        with self.lock:
            if not self.ativa or self.pausada: return
            ganho_inicial = self.ganho_fade
        try:
            for passo in range(1, 31):
                if cancelar is not None and cancelar.is_set(): break
                with self.lock:
                    if self.pausada: return  # Continua deste ponto ao retomar, sem reiniciar MP3.
                    if not self.ativa or not self.mixer.music.get_busy(): break
                    self.ganho_fade = ganho_inicial*(1-passo/30)
                    self._aplicar_volume()
                if cancelar is None: time.sleep(duracao/30)
                else: cancelar.wait(duracao/30)
        except Exception as erro:
            log.warning("Fade falhou: %s", type(erro).__name__)
        finally:
            with self.lock:
                if not self.pausada or (cancelar is not None and cancelar.is_set()): self.parar()

    def parar(self):
        with self.lock:
            if self.mixer is not None:
                try: self.mixer.music.stop()
                except Exception as erro:
                    log.warning("Player não confirmou stop: %s", type(erro).__name__)
                    try: self.mixer.quit()
                    except Exception as erro_quit:
                        log.warning("Mixer não confirmou quit: %s", type(erro_quit).__name__)
                        self.audio_pendente = True
                        self.ativa = True; self.pausada = False
                        self._aviso("Não foi confirmado o fim da música. Reinicie o Jarvis antes de escutar.")
                        return
            self.audio_pendente = False
            self.ativa = self.pausada = False
            self.ganho_fade = 1.

    def fechar(self):
        with self.lock:
            self.parar()
            if self.mixer is not None:
                try:
                    self.mixer.quit()
                    self.mixer = None
                    self.audio_pendente = self.ativa = self.pausada = False
                except Exception as erro:
                    log.warning("Mixer não confirmou encerramento: %s", type(erro).__name__)
