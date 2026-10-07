"""Síntese local com uma voz portuguesa instalada no computador."""


class ErroVoz(Exception):
    pass


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
        if self.engine is not None:
            try:
                self.engine.stop()
            except Exception:
                pass
