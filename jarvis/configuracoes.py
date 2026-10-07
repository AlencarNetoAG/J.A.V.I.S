"""Preferências locais, sem credenciais."""
from dataclasses import dataclass, asdict
from pathlib import Path
import json

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO = RAIZ / "config.local.json"


@dataclass
class Configuracoes:
    modelo: str = "tiny"
    microfone: int | None = None
    voz: str | None = None
    velocidade: int = 150
    volume: float = 0.12
    musica: str = str(RAIZ / "assets" / "highway_to_hell.mp3")
    timeout_pergunta: float = 12.0
    captura_maxima: float = 12.0
    limiar: float = 0.01
    reduzir_movimento: bool = False
    sem_voz: bool = False
    sem_musica: bool = False

    def validar(self):
        if not (80 <= self.velocidade <= 300 and 0 <= self.volume <= 1
                and 3 <= self.timeout_pergunta <= 60 and 3 <= self.captura_maxima <= 30
                and 0.001 <= self.limiar <= 0.5):
            raise ValueError("Preferências fora dos limites.")
        return self


def carregar() -> Configuracoes:
    try:
        dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        permitidos = Configuracoes.__dataclass_fields__
        return Configuracoes(**{k: v for k, v in dados.items() if k in permitidos}).validar()
    except (OSError, ValueError, TypeError, AttributeError):
        return Configuracoes()


def salvar(config: Configuracoes):
    config.validar()
    ARQUIVO.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
