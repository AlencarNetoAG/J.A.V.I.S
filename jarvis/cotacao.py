"""Consulta HTTPS da cotação de compra USD/BRL, sem cache ou fallback fixo."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math

import requests

URL = "https://economia.awesomeapi.com.br/json/last/USD-BRL"
FONTE = "AwesomeAPI"
# O Brasil não tem horário de verão atualmente; evita dependência de tzdata no Windows.
BRASILIA = timezone(timedelta(hours=-3), "Brasília")
FALHA = (
    "Bom dia, senhor. Não consegui consultar a cotação do dólar agora. "
    "Tente novamente em instantes."
)


class ErroCotacao(Exception):
    """Falha de rede ou resposta inválida da fonte."""


@dataclass(frozen=True)
class Cotacao:
    valor: Decimal
    atualizacao: datetime
    fonte: str = FONTE
    tipo: str = "compra (bid), referência de mercado"


def consultar_cotacao() -> Cotacao:
    try:
        # requests mantém verificação TLS habilitada. Não aceita redirecionamentos.
        resposta = requests.get(
            URL, timeout=(5, 10), allow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "Jarvis/1.0"},
        )
        if resposta.status_code != 200:
            raise ErroCotacao(f"A fonte respondeu HTTP {resposta.status_code}.")
        return validar_dados(resposta.json())
    except (requests.RequestException, ValueError) as erro:
        raise ErroCotacao("Falha na conexão ou no JSON da fonte.") from erro


def validar_dados(dados: object, agora: datetime | None = None) -> Cotacao:
    try:
        if not isinstance(dados, dict):
            raise ValueError("Objeto JSON esperado.")
        item = dados["USDBRL"]
        if item["code"] != "USD" or item["codein"] != "BRL":
            raise ValueError("Par de moedas incorreto.")
        valor = Decimal(str(item["bid"]))
        if not valor.is_finite() or not Decimal("0.005") <= valor <= Decimal("1000000"):
            raise ValueError("Cotação fora dos limites válidos.")
        timestamp = float(item["timestamp"])
        if isinstance(item["timestamp"], bool) or not math.isfinite(timestamp):
            raise ValueError("Timestamp inválido.")
        atualizacao = datetime.fromtimestamp(timestamp, tz=BRASILIA)
        agora = agora or datetime.now(BRASILIA)
        if atualizacao.year < 2000 or atualizacao > agora + timedelta(minutes=5):
            raise ValueError("Data da cotação inválida.")
        return Cotacao(valor, atualizacao)
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError, OSError) as erro:
        raise ErroCotacao("A fonte retornou uma cotação ou data inválida.") from erro


UNIDADES = ("zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove")
DEZ_A_DEZENOVE = ("dez", "onze", "doze", "treze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove")
DEZENAS = ("", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa")
CENTENAS = ("", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos", "oitocentos", "novecentos")


def numero_por_extenso(numero: int) -> str:
    if numero < 10:
        return UNIDADES[numero]
    if numero < 20:
        return DEZ_A_DEZENOVE[numero - 10]
    if numero < 100:
        dezena, unidade = divmod(numero, 10)
        return DEZENAS[dezena] + (" e " + UNIDADES[unidade] if unidade else "")
    if numero == 100:
        return "cem"
    if numero < 1000:
        centena, resto = divmod(numero, 100)
        return CENTENAS[centena] + (" e " + numero_por_extenso(resto) if resto else "")
    if numero < 1000000:
        milhares, resto = divmod(numero, 1000)
        prefixo = "mil" if milhares == 1 else numero_por_extenso(milhares) + " mil"
        conector = " e " if resto < 100 or resto % 100 == 0 else " "
        return prefixo + (conector + numero_por_extenso(resto) if resto else "")
    if numero == 1000000:
        return "um milhão"
    raise ValueError("Número fora dos limites.")


def valor_por_extenso(valor: Decimal) -> str:
    total_centavos = int(valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
    reais, centavos = divmod(total_centavos, 100)
    moeda = "real" if reais == 1 else "reais"
    if reais == 1000000:
        moeda = "de reais"
    texto = f"{numero_por_extenso(reais)} {moeda}"
    if centavos:
        texto += f" e {numero_por_extenso(centavos)} " + ("centavo" if centavos == 1 else "centavos")
    return texto


MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")


def resposta_falada(cotacao: Cotacao, agora: datetime | None = None) -> str:
    agora = agora or datetime.now(BRASILIA)
    texto = f"Bom dia, senhor. A cotação mais recente do dólar é de {valor_por_extenso(cotacao.valor)}."
    data = cotacao.atualizacao.astimezone(BRASILIA)
    if data.date() != agora.astimezone(BRASILIA).date():
        texto += (
            " A última atualização disponível é de "
            f"{numero_por_extenso(data.day)} de {MESES[data.month - 1]} "
            f"de {numero_por_extenso(data.year)}."
        )
    return texto
