"""Preferências locais, sem credenciais."""
from dataclasses import dataclass, asdict, field
from pathlib import Path
import json

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO = RAIZ / "config.local.json"


@dataclass
class Configuracoes:
    modelo: str = "tiny"
    microfone: int | None = None
    microfone_identidade: list[str] | None = None
    voz: str | None = None
    velocidade: int = 150
    volume: float = 0.12
    volume_voz: float = 1.0
    musica: str = str(RAIZ / "assets" / "highway_to_hell.mp3")
    timeout_pergunta: float = 12.0
    captura_maxima: float = 12.0
    limiar: float = 0.01
    reduzir_movimento: bool = False
    sem_voz: bool = False
    sem_musica: bool = False
    pc_suspenso: bool = False
    permissoes_pc: dict = field(default_factory=lambda:{"arquivos":True,"aplicativos":True,"audio":True,"spotify":True})
    pastas_autorizadas: list[str] = field(default_factory=list)
    fones_midia_externa: bool = False

    def validar(self):
        if not (80 <= self.velocidade <= 300 and 0 <= self.volume <= 1
                and 0 <= self.volume_voz <= 1
                and 3 <= self.timeout_pergunta <= 60 and 3 <= self.captura_maxima <= 30
                and 0.001 <= self.limiar <= 0.5):
            raise ValueError("Preferências fora dos limites.")
        if self.microfone_identidade is not None and (not isinstance(self.microfone_identidade, list)
                or len(self.microfone_identidade) != 2 or not all(isinstance(v, str) for v in self.microfone_identidade)):
            raise ValueError("Identidade do microfone inválida.")
        if type(self.pc_suspenso) is not bool or type(self.fones_midia_externa) is not bool:
            raise ValueError("Permissão inválida.")
        if not isinstance(self.permissoes_pc,dict) or set(self.permissoes_pc)!={"arquivos","aplicativos","audio","spotify"} or not all(type(v) is bool for v in self.permissoes_pc.values()):
            raise ValueError("Categorias de permissão inválidas.")
        if not isinstance(self.pastas_autorizadas,list) or len(self.pastas_autorizadas)>30 or not all(isinstance(p,str) and p for p in self.pastas_autorizadas):
            raise ValueError("Pastas autorizadas inválidas.")
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
