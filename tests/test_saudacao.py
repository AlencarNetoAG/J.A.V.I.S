"""Rede e dispositivos simulados; não utiliza a música do usuário."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import io
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import requests

from jarvis import app
from jarvis.clima import (
    Clima, ErroClima, Localizacao, consultar_clima, temperatura_falada,
    validar_clima, validar_localizacao,
)
from jarvis.cotacao import Cotacao, ErroCotacao
from jarvis.horario import RECIFE, horario_falado
from jarvis.musica import Musica
from jarvis.saudacao import montar_saudacao

AGORA = datetime(2026, 10, 7, 12, 10, tzinfo=RECIFE)
LOCAL = Localizacao(-8.07417, -39.11917)
CLIMA = Clima(Decimal("34.5"), "céu limpo", AGORA - timedelta(minutes=10), LOCAL)
COTACAO = Cotacao(Decimal("5.2379"), AGORA)


def geocoding():
    return {"results": [{"name": "Salgueiro", "country_code": "BR", "admin1": "Pernambuco", "feature_code": "PPL", "timezone": "America/Recife", "latitude": LOCAL.latitude, "longitude": LOCAL.longitude}]}


def meteorologia():
    return {"timezone": "America/Recife", "latitude": -8.08, "longitude": -39.12,
            "current_units": {"temperature_2m": "°C", "time": "unixtime"},
            "current": {"temperature_2m": 34.5, "weather_code": 0, "time": int(CLIMA.atualizacao.timestamp())}}


class ClimaTests(unittest.TestCase):
    def test_local_exclui_homonimo_e_aeroporto(self):
        dados = geocoding()
        dados["results"].extend([
            {**dados["results"][0], "admin1": "Rio de Janeiro", "latitude": -21.5224, "longitude": -42.13786},
            {**dados["results"][0], "feature_code": "AIRF"},
        ])
        self.assertEqual(validar_localizacao(dados), LOCAL)
        for campo, valor in (("name", "Outra"), ("admin1", "Ceará"), ("country_code", "PT"), ("timezone", "America/Sao_Paulo"), ("latitude", "nan")):
            dados = geocoding()
            dados["results"][0][campo] = valor
            with self.subTest(campo=campo), self.assertRaises(ErroClima):
                validar_localizacao(dados)
        with self.assertRaises(ErroClima):
            validar_localizacao({"results": []})
        with self.assertRaises(ErroClima):
            validar_localizacao({"results": geocoding()["results"] * 2})

    def test_clima_atual_e_unidades(self):
        resultado = validar_clima(meteorologia(), LOCAL, AGORA)
        self.assertEqual(resultado.temperatura, CLIMA.temperatura)
        self.assertEqual(resultado.condicao, "céu limpo")
        self.assertEqual(resultado.atualizacao, CLIMA.atualizacao)
        for campo, valor in (("temperature_2m", None), ("temperature_2m", "NaN"), ("temperature_2m", 99), ("weather_code", 999), ("weather_code", True), ("time", True), ("time", "abc"), ("time", int((AGORA - timedelta(hours=2)).timestamp())), ("time", int((AGORA + timedelta(hours=1)).timestamp()))):
            dados = meteorologia()
            dados["current"][campo] = valor
            with self.subTest(campo=campo, valor=valor), self.assertRaises(ErroClima):
                validar_clima(dados, LOCAL, AGORA)
        for campo, valor in (("timezone", "UTC"), ("latitude", 1), ("longitude", float("nan")), ("current_units", {"temperature_2m": "°F", "time": "unixtime"})):
            dados = meteorologia()
            dados[campo] = valor
            with self.subTest(campo=campo), self.assertRaises(ErroClima):
                validar_clima(dados, LOCAL, AGORA)

    def test_previsao_diaria_nao_e_usada_como_atual(self):
        dados = meteorologia()
        del dados["current"]
        dados["daily"] = {"temperature_2m_max": [34.5]}
        with self.assertRaises(ErroClima):
            validar_clima(dados, LOCAL, AGORA)

    @patch("jarvis.clima.agora_recife", return_value=AGORA)
    @patch("jarvis.clima.requests.get")
    def test_consulta_verifica_cidade_depois_current(self, get, agora):
        get.side_effect = [SimpleNamespace(status_code=200, json=lambda: geocoding()), SimpleNamespace(status_code=200, json=lambda: meteorologia())]
        self.assertEqual(consultar_clima(), CLIMA)
        self.assertEqual(get.call_count, 2)
        chamada = get.call_args
        self.assertEqual(chamada.kwargs["params"]["current"], "temperature_2m,weather_code")
        self.assertEqual(chamada.kwargs["params"]["timezone"], "America/Recife")
        self.assertNotIn("daily", chamada.kwargs["params"])
        self.assertEqual(chamada.kwargs["timeout"], (3, 5))
        self.assertFalse(chamada.kwargs["allow_redirects"])

    @patch("jarvis.clima.requests.get")
    def test_falhas_de_rede_e_json(self, get):
        for erro in (requests.Timeout(), requests.ConnectionError(), requests.exceptions.SSLError()):
            get.side_effect = erro
            with self.subTest(erro=erro), self.assertRaises(ErroClima):
                consultar_clima()
        get.side_effect = None
        get.return_value.status_code = 429
        with self.assertRaises(ErroClima):
            consultar_clima()
        get.return_value.status_code = 200
        get.return_value.json.side_effect = ValueError("JSON inválido")
        with self.assertRaises(ErroClima):
            consultar_clima()

    def test_temperatura_pronuncia(self):
        for valor, texto in (("34.55", "trinta e quatro vírgula seis graus Celsius"), ("-1", "menos um grau Celsius"), ("1", "um grau Celsius"), ("0", "zero graus Celsius")):
            self.assertEqual(temperatura_falada(Decimal(valor)), texto)


class HorarioSaudacaoTests(unittest.TestCase):
    def test_fuso_recife_independe_do_fuso_entrada(self):
        self.assertEqual(horario_falado(datetime(2026, 10, 7, 4, 1, tzinfo=timezone.utc)), "Agora é uma hora e um minuto.")
        self.assertEqual(horario_falado(datetime(2026, 10, 7, 3, 0, tzinfo=timezone.utc)), "Agora é meia-noite.")
        self.assertEqual(horario_falado(AGORA), "Agora é meio-dia e dez minutos.")
        self.assertEqual(horario_falado(AGORA.replace(hour=2, minute=0)), "Agora são duas horas.")
        self.assertEqual(horario_falado(AGORA.replace(hour=22, minute=30)), "Agora são vinte e duas horas e trinta minutos.")

    def test_saudacao_completa_e_falhas_parciais(self):
        texto = montar_saudacao(AGORA, CLIMA, COTACAO)
        self.assertIn("meio-dia e dez minutos", texto)
        self.assertIn("trinta e quatro vírgula cinco graus Celsius, com céu limpo", texto)
        self.assertIn("cinco reais e vinte e quatro centavos", texto)
        self.assertEqual(texto.count("Bom dia, senhor."), 1)
        self.assertIn("A cotação mais recente", montar_saudacao(AGORA, None, COTACAO))
        self.assertIn("temperatura é de", montar_saudacao(AGORA, CLIMA, None))
        self.assertIn("Não consegui consultar", montar_saudacao(AGORA, None, None))
        self.assertIn("meio-dia", montar_saudacao(AGORA, None, None))

    def test_cotacao_antiga_tem_data(self):
        cotacao = Cotacao(Decimal("5"), AGORA - timedelta(days=1))
        self.assertIn("seis de outubro", montar_saudacao(AGORA, CLIMA, cotacao))

    def test_consultas_em_paralelo(self):
        barreira = threading.Barrier(2)
        def dolar():
            barreira.wait(timeout=2)
            return COTACAO
        def clima():
            barreira.wait(timeout=2)
            return CLIMA
        with patch("jarvis.app.consultar_cotacao", side_effect=dolar), patch("jarvis.app.consultar_clima", side_effect=clima), patch("jarvis.app.agora_recife", return_value=AGORA), patch("sys.stdout", new_callable=io.StringIO):
            texto = app.atender()
        self.assertIn("cinco reais", texto)
        self.assertIn("trinta e quatro", texto)

    def test_clima_falha_dolar_continua(self):
        with patch("jarvis.app.consultar_cotacao", return_value=COTACAO), patch("jarvis.app.consultar_clima", side_effect=ErroClima("timeout")), patch("sys.stdout", new_callable=io.StringIO) as saida:
            texto = app.atender()
        self.assertIn("Não consegui consultar as condições atuais", texto)
        self.assertIn("cinco reais", texto)
        self.assertIn("Consulta de clima indisponível", saida.getvalue())


class MusicaTests(unittest.TestCase):
    def test_arquivo_ausente_continua(self):
        with tempfile.TemporaryDirectory() as pasta, patch("sys.stdout", new_callable=io.StringIO) as saida:
            musica = Musica(str(Path(pasta) / "inexistente.mp3"))
            musica.iniciar()
            musica.finalizar()
        self.assertFalse(musica.ativa)
        self.assertIn("Música ausente", saida.getvalue())

    def test_play_sem_bloquear_volume_fade_e_sem_sobreposicao(self):
        mixer = Mock()
        mixer.get_init.return_value = True
        mixer.music.get_volume.return_value = 0.07
        mixer.music.get_busy.return_value = True
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "teste.mp3"
            arquivo.write_bytes(b"fixture; decoder simulado")
            with patch.dict("sys.modules", {"pygame": SimpleNamespace(mixer=mixer)}), patch("jarvis.musica.time.sleep"), patch("sys.stdout", new_callable=io.StringIO):
                musica = Musica(str(arquivo), 0.2)
                musica.iniciar()
                musica.iniciar()  # Para o canal anterior antes de novo play.
                musica.abaixar_para_fala()
                musica.finalizar()
                musica.fechar()
        self.assertEqual(mixer.music.play.call_count, 2)
        self.assertGreaterEqual(mixer.music.stop.call_count, 3)
        volumes = [c.args[0] for c in mixer.music.set_volume.call_args_list]
        self.assertAlmostEqual(volumes[2], 0.07)
        fade = volumes[3:]
        self.assertTrue(all(a >= b for a, b in zip(fade, fade[1:])))
        self.assertAlmostEqual(fade[-1], 0)
        self.assertFalse(musica.ativa)

    def test_erro_decoder_continua(self):
        mixer = Mock()
        mixer.music.load.side_effect = RuntimeError("MP3 inválido")
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "erro.mp3"
            arquivo.touch()
            with patch.dict("sys.modules", {"pygame": SimpleNamespace(mixer=mixer)}), patch("sys.stdout", new_callable=io.StringIO) as saida:
                musica = Musica(str(arquivo))
                musica.iniciar()
        self.assertFalse(musica.ativa)
        self.assertIn("A saudação continuará", saida.getvalue())

    def test_ctrl_c_durante_fade_para_imediatamente(self):
        musica = Musica("nao_usado.mp3")
        musica.mixer = Mock()
        musica.mixer.music.get_volume.return_value = 0.1
        musica.ativa = True
        with patch("jarvis.musica.time.sleep", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            musica.finalizar()
        musica.mixer.music.stop.assert_called_once()
        self.assertFalse(musica.ativa)

    def test_sequencia_so_retoma_microfone_apos_fade(self):
        eventos = []
        musica = SimpleNamespace(
            iniciar=lambda: eventos.append("musica"),
            abaixar_para_fala=lambda: eventos.append("volume baixo"),
            finalizar=lambda: eventos.append("fade completo"),
            parar=lambda: eventos.append("parar"), fechar=lambda: eventos.append("fechar musica"),
        )
        chamadas = iter([None, KeyboardInterrupt])
        def ouvir():
            eventos.append("microfone")
            if next(chamadas) is KeyboardInterrupt:
                raise KeyboardInterrupt
        voz = SimpleNamespace(falar=lambda texto: eventos.append("fala"), fechar=lambda: eventos.append("fechar voz"))
        with patch("jarvis.app.Ouvinte", return_value=SimpleNamespace(aguardar_ativacao=ouvir)), patch("jarvis.app.Musica", return_value=musica), patch("jarvis.app.Voz", return_value=voz), patch("jarvis.app.atender", side_effect=lambda: eventos.append("consulta") or "Bom dia"), patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(app.main([]), 0)
        self.assertEqual(eventos[:8], ["microfone", "musica", "consulta", "volume baixo", "fala", "fade completo", "parar", "microfone"])

    def test_ctrl_c_na_fala_interrompe_todos_audios(self):
        musica, voz = Mock(), Mock()
        voz.falar.side_effect = KeyboardInterrupt
        with patch("builtins.input", return_value="bom dia Jarvis"), patch("jarvis.app.Musica", return_value=musica), patch("jarvis.app.Voz", return_value=voz), patch("jarvis.app.atender", return_value="Bom dia"), patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(app.main(["--texto"]), 0)
        musica.parar.assert_called_once()
        musica.fechar.assert_called_once()
        voz.fechar.assert_called_once()
        musica.finalizar.assert_not_called()

    def test_ctrl_c_na_consulta_para_musica_sem_aguardar_rede(self):
        musica = Mock()
        executor = Mock()
        executor.submit.return_value.result.side_effect = KeyboardInterrupt
        with patch("builtins.input", return_value="bom dia Jarvis"), patch("jarvis.app.Musica", return_value=musica), patch("jarvis.app.ThreadPoolExecutor", return_value=executor), patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(app.main(["--texto", "--sem-voz"]), 0)
        executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
        musica.parar.assert_called_once()
        musica.fechar.assert_called_once()
        musica.finalizar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
