"""Condições atuais do Open-Meteo, com localização e atualização validadas."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math

import requests

from .cotacao import numero_por_extenso
from .horario import RECIFE, agora_recife
from .reconhecimento import normalizar

GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"
URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = (3, 5)
FALHA = "Não consegui consultar as condições atuais do tempo em Salgueiro agora."

CONDICOES = {
    0: "céu limpo", 1: "céu predominantemente limpo", 2: "céu parcialmente nublado",
    3: "céu encoberto", 45: "nevoeiro", 48: "nevoeiro com formação de gelo",
    51: "garoa leve", 53: "garoa moderada", 55: "garoa intensa",
    56: "garoa congelante leve", 57: "garoa congelante intensa",
    61: "chuva leve", 63: "chuva moderada", 65: "chuva intensa",
    66: "chuva congelante leve", 67: "chuva congelante intensa",
    71: "neve leve", 73: "neve moderada", 75: "neve intensa", 77: "grãos de neve",
    80: "pancadas de chuva leves", 81: "pancadas de chuva moderadas", 82: "pancadas de chuva fortes",
    85: "pancadas de neve leves", 86: "pancadas de neve fortes",
    95: "trovoadas", 96: "trovoadas com granizo leve", 99: "trovoadas com granizo intenso",
}


class ErroClima(Exception):
    pass


@dataclass(frozen=True)
class Localizacao:
    latitude: float
    longitude: float
    nome: str = "Salgueiro"
    estado: str = "Pernambuco"
    pais: str = "Brasil"


@dataclass(frozen=True)
class Clima:
    temperatura: Decimal
    condicao: str
    atualizacao: datetime
    localizacao: Localizacao
    fonte: str = "Open-Meteo (condições atuais estimadas por modelos meteorológicos)"


def _json(url: str, parametros: dict):
    try:
        resposta = requests.get(url, params=parametros, timeout=TIMEOUT, allow_redirects=False)
        if resposta.status_code != 200:
            raise ErroClima(f"A fonte de clima respondeu HTTP {resposta.status_code}.")
        return resposta.json()
    except (requests.RequestException, ValueError) as erro:
        raise ErroClima("Falha na conexão ou no JSON da fonte de clima.") from erro


def validar_localizacao(dados: object) -> Localizacao:
    try:
        candidatos = []
        for item in dados["results"]:
            if (normalizar(item.get("name", "")) == "salgueiro"
                    and item.get("country_code") == "BR"
                    and normalizar(item.get("admin1", "")) == "pernambuco"
                    and item.get("feature_code") == "PPL"
                    and item.get("timezone") == "America/Recife"):
                lat, lon = float(item["latitude"]), float(item["longitude"])
                # Checagem geográfica adicional da região de Salgueiro-PE.
                if not math.isfinite(lat) or not math.isfinite(lon) or not (-8.4 < lat < -7.8 and -39.5 < lon < -38.8):
                    raise ValueError("Coordenadas inconsistentes.")
                candidatos.append(Localizacao(lat, lon))
        if len(candidatos) != 1:
            raise ValueError("Salgueiro-PE ausente ou ambígua.")
        return candidatos[0]
    except (KeyError, TypeError, ValueError, AttributeError) as erro:
        raise ErroClima("Não foi possível confirmar Salgueiro, Pernambuco, Brasil.") from erro


def validar_clima(dados: object, local: Localizacao, agora: datetime | None = None) -> Clima:
    try:
        if dados["timezone"] != "America/Recife":
            raise ValueError("Fuso incorreto.")
        lat, lon = float(dados["latitude"]), float(dados["longitude"])
        # A API retorna o centro da célula da grade, que pode diferir da cidade.
        if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat - local.latitude) > 0.15 or abs(lon - local.longitude) > 0.15:
            raise ValueError("Grade meteorológica fora da localização solicitada.")
        unidades = dados["current_units"]
        if unidades["temperature_2m"] != "°C" or unidades["time"] != "unixtime":
            raise ValueError("Unidades inesperadas.")
        item = dados["current"]
        temperatura = Decimal(str(item["temperature_2m"]))
        if not temperatura.is_finite() or not Decimal("-100") <= temperatura <= Decimal("70"):
            raise ValueError("Temperatura inválida.")
        codigo = item["weather_code"]
        if isinstance(codigo, bool) or not isinstance(codigo, int) or codigo not in CONDICOES:
            raise ValueError("Condição meteorológica inválida.")
        timestamp = item["time"]
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            raise ValueError("Data inválida.")
        atualizacao = datetime.fromtimestamp(timestamp, tz=RECIFE)
        agora = agora or agora_recife()
        idade = agora - atualizacao
        if idade > timedelta(minutes=90) or idade < -timedelta(minutes=5):
            raise ValueError("Dados antigos ou com data futura: não são condições atuais.")
        return Clima(temperatura, CONDICOES[codigo], atualizacao, local)
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError, OSError) as erro:
        raise ErroClima(f"Dados meteorológicos inválidos: {erro}") from erro


def consultar_clima() -> Clima:
    local = validar_localizacao(_json(GEOCODING, {
        "name": "Salgueiro", "count": 10, "language": "pt", "countryCode": "BR", "format": "json",
    }))
    dados = _json(URL, {
        "latitude": local.latitude, "longitude": local.longitude,
        "current": "temperature_2m,weather_code", "timezone": "America/Recife",
        "temperature_unit": "celsius", "timeformat": "unixtime",
    })
    return validar_clima(dados, local)


def temperatura_falada(valor: Decimal) -> str:
    arredondado = valor.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    decimos = int(abs(arredondado) * 10)
    inteiro, decimal = divmod(decimos, 10)
    texto = ("menos " if arredondado < 0 else "") + numero_por_extenso(inteiro)
    if decimal:
        texto += " vírgula " + numero_por_extenso(decimal)
    return texto + (" grau Celsius" if abs(arredondado) == 1 else " graus Celsius")
