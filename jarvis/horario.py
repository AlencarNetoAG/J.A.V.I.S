"""Hora de Salgueiro pelo banco de fusos IANA, independente do fuso do PC."""

from datetime import datetime
from zoneinfo import ZoneInfo

from .cotacao import numero_por_extenso

RECIFE = ZoneInfo("America/Recife")


def agora_recife() -> datetime:
    return datetime.now(RECIFE)


def horario_falado(agora: datetime) -> str:
    agora = agora.astimezone(RECIFE)
    hora, minuto = agora.hour, agora.minute
    if hora == 0:
        texto = "Agora é meia-noite"
    elif hora == 12:
        texto = "Agora é meio-dia"
    elif hora == 1:
        texto = "Agora é uma hora"
    else:
        horas = {2: "duas", 21: "vinte e uma", 22: "vinte e duas"}.get(hora, numero_por_extenso(hora))
        texto = f"Agora são {horas} horas"
    if minuto:
        texto += f" e {numero_por_extenso(minuto)} " + ("minuto" if minuto == 1 else "minutos")
    return texto + "."
