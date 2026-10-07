"""MP3 fornecido pelo usuário; SDL toca em paralelo, sem baixar músicas."""

from pathlib import Path
import time


class Musica:
    def __init__(self, caminho: str, volume: float = 0.12):
        self.caminho = Path(caminho)
        self.volume = volume
        self.mixer = None
        self.ativa = False

    def iniciar(self) -> None:
        self.parar()
        if not self.caminho.is_file():
            print(f"Música ausente: {self.caminho}. A saudação continuará normalmente.", flush=True)
            return
        try:
            # Evita o banner do pygame e não inicializa vídeo ou outros módulos.
            import os
            os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
            from pygame import mixer
            self.mixer = mixer
            if not mixer.get_init():
                mixer.init()
            mixer.music.load(str(self.caminho))
            mixer.music.set_volume(self.volume)
            mixer.music.play()  # Retorna imediatamente; só um canal de música.
            self.ativa = True
            print("Música de fundo iniciada.", flush=True)
        except Exception as erro:
            print(f"Não foi possível reproduzir a música ({erro}). A saudação continuará.", flush=True)
            self.parar()

    def abaixar_para_fala(self) -> None:
        if self.ativa:
            try:
                self.mixer.music.set_volume(min(self.volume * 0.35, 0.08))
            except Exception as erro:
                print(f"Falha ao ajustar música: {erro}. Música interrompida.", flush=True)
                self.parar()

    def finalizar(self, duracao: float = 1.5) -> None:
        if not self.ativa:
            return
        try:
            volume_inicial = self.mixer.music.get_volume()
            for passo in range(1, 31):
                if not self.mixer.music.get_busy():
                    break
                self.mixer.music.set_volume(volume_inicial * (1 - passo / 30))
                time.sleep(duracao / 30)
        except Exception as erro:
            print(f"Falha ao finalizar música: {erro}", flush=True)
        finally:
            # Também executa em KeyboardInterrupt, sem aguardar a música inteira.
            self.parar()

    def parar(self) -> None:
        if self.mixer is not None:
            try:
                self.mixer.music.stop()
            except Exception:
                pass
        self.ativa = False

    def fechar(self) -> None:
        self.parar()
        if self.mixer is not None:
            try:
                self.mixer.quit()
            except Exception:
                pass
