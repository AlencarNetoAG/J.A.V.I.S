"""Roteamento de frases completas; a saudação tem prioridade."""
import re
from .reconhecimento import eh_ativacao


def interpretar(texto: str) -> tuple[str, str]:
    if eh_ativacao(texto):
        return "bom_dia", ""
    match = re.search(r"\bjarvis\b", texto, re.IGNORECASE)
    if not match:
        return "ignorar", ""
    pergunta = texto[match.end():].strip(" \t\n,.;:!?—-")
    return ("pergunta", pergunta) if pergunta else ("aguardar", "")
