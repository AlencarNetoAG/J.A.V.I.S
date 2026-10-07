"""Monta uma única resposta com os dados disponíveis e o horário de Recife."""

from datetime import datetime

from .clima import Clima, FALHA as FALHA_CLIMA, temperatura_falada
from .cotacao import Cotacao, FALHA as FALHA_COTACAO, resposta_falada
from .horario import horario_falado


def montar_saudacao(agora: datetime, clima: Clima | None, cotacao: Cotacao | None) -> str:
    partes = ["Bom dia, senhor.", horario_falado(agora)]
    if clima is None:
        partes.append(FALHA_CLIMA)
    else:
        partes.append(f"Em Salgueiro, Pernambuco, a temperatura é de {temperatura_falada(clima.temperatura)}, com {clima.condicao}.")
    if cotacao is None:
        partes.append(FALHA_COTACAO.removeprefix("Bom dia, senhor. "))
    else:
        partes.append(resposta_falada(cotacao, agora).removeprefix("Bom dia, senhor. "))
    return " ".join(partes)
