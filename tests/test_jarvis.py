"""Dados sintéticos apenas nos testes; produção sempre consulta a API."""

from datetime import datetime, timedelta
from decimal import Decimal
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import requests

from jarvis import app
from jarvis.clima import Clima, Localizacao
from jarvis.cotacao import (
    BRASILIA, Cotacao, ErroCotacao, FALHA, URL, consultar_cotacao,
    resposta_falada, validar_dados, valor_por_extenso,
)
from jarvis.reconhecimento import ErroMicrofone, Ouvinte, eh_ativacao
from jarvis.voz import ErroVoz, Voz

AGORA = datetime(2026, 10, 7, 10, 0, tzinfo=BRASILIA)


def dados(valor="5.2379", data=AGORA):
    return {"USDBRL": {"code": "USD", "codein": "BRL", "bid": valor, "timestamp": str(int(data.timestamp()))}}


class CotacaoTests(unittest.TestCase):
    def test_validacao_e_timestamp(self):
        cotacao = validar_dados(dados(), agora=AGORA)
        self.assertEqual(cotacao.valor, Decimal("5.2379"))
        self.assertEqual(cotacao.atualizacao, AGORA)

    def test_dados_invalidos(self):
        invalidos = [None, [], {}, {"USDBRL": None}]
        for valor in ("NaN", "Infinity", "-1", "0", "abc", True, "1000001"):
            invalidos.append(dados(valor))
        for campo, valor in (("code", "EUR"), ("codein", "USD"), ("timestamp", "abc"), ("timestamp", True), ("timestamp", "Infinity"), ("timestamp", "0")):
            item = dados()
            item["USDBRL"][campo] = valor
            invalidos.append(item)
        invalidos.append(dados(data=AGORA + timedelta(hours=1)))
        for item in invalidos:
            with self.subTest(item=item), self.assertRaises(ErroCotacao):
                validar_dados(item, agora=AGORA)

    @patch("jarvis.cotacao.requests.get")
    def test_consulta_nova_a_cada_chamada_e_timeout(self, get):
        get.return_value.status_code = 200
        get.return_value.json.side_effect = [dados("5.11"), dados("5.22")]
        self.assertEqual(consultar_cotacao().valor, Decimal("5.11"))
        self.assertEqual(consultar_cotacao().valor, Decimal("5.22"))
        self.assertEqual(get.call_count, 2)
        get.assert_called_with(URL, timeout=(5, 10), allow_redirects=False,
                               headers={"Accept": "application/json", "User-Agent": "Jarvis/1.0"})

    @patch("jarvis.cotacao.requests.get")
    def test_rede_http_json(self, get):
        for erro in (requests.Timeout(), requests.ConnectionError(), requests.exceptions.SSLError()):
            get.side_effect = erro
            with self.subTest(erro=erro), self.assertRaises(ErroCotacao):
                consultar_cotacao()
        get.side_effect = None
        for status in (301, 403, 429, 500):
            get.return_value.status_code = status
            with self.subTest(status=status), self.assertRaises(ErroCotacao):
                consultar_cotacao()
        get.return_value.status_code = 200
        get.return_value.json.side_effect = ValueError("invalid JSON")
        with self.assertRaises(ErroCotacao):
            consultar_cotacao()

    def test_reais_centavos_e_arredondamento(self):
        casos = {"5.2379": "cinco reais e vinte e quatro centavos", "1.01": "um real e um centavo", "2.00": "dois reais", "0.50": "zero reais e cinquenta centavos", "9.995": "dez reais"}
        for valor, esperado in casos.items():
            with self.subTest(valor=valor):
                self.assertEqual(valor_por_extenso(Decimal(valor)), esperado)

    def test_atualizacao_antiga_anunciada(self):
        antiga = Cotacao(Decimal("5"), AGORA - timedelta(days=1))
        texto = resposta_falada(antiga, agora=AGORA)
        self.assertIn("seis de outubro de dois mil e vinte e seis", texto)
        self.assertNotIn("última atualização", resposta_falada(Cotacao(Decimal("5"), AGORA), agora=AGORA))

    def test_data_comparada_em_brasilia(self):
        # 01h UTC ainda é o dia anterior em Brasília.
        from datetime import timezone
        agora = datetime(2026, 10, 8, 1, tzinfo=timezone.utc)
        self.assertNotIn("última atualização", resposta_falada(Cotacao(Decimal("5"), AGORA), agora))


class ReconhecimentoTests(unittest.TestCase):
    def test_frase_e_pontuacao(self):
        for texto in ("bom dia Jarvis", "BOM DIA, JARVIS!", "Bom dia… Jarvis.", "Olá, bom dia Jarvis!"):
            with self.subTest(texto=texto):
                self.assertTrue(eh_ativacao(texto))
        for texto in ("bom dia", "jarvis", "bom dia jarvisinho", "bom dia outro jarvis"):
            with self.subTest(texto=texto):
                self.assertFalse(eh_ativacao(texto))

    def test_microfone_fecha_antes_de_transcrever_e_reabre(self):
        import numpy as np
        estado = {"aberto": False, "streams": 0, "transcricoes": 0}

        class Stream:
            active = True

            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]

            def __enter__(self):
                estado["aberto"] = True
                estado["streams"] += 1
                voz = np.full(3200, 5000, dtype=np.int16).tobytes()
                silencio = np.zeros(3200, dtype=np.int16).tobytes()
                for bloco in [silencio, voz, voz, *([silencio] * 5)]:
                    self.callback(bloco, 3200, None, None)
                return self

            def __exit__(self, *args):
                estado["aberto"] = False

        def transcrever(audio, **kwargs):
            self.assertFalse(estado["aberto"])
            self.assertEqual(audio.dtype, np.float32)
            self.assertEqual(kwargs["language"], "pt")
            estado["transcricoes"] += 1
            texto = "olá" if estado["transcricoes"] == 1 else "bom dia Jarvis"
            return iter([SimpleNamespace(text=texto)]), None

        ouvinte = Ouvinte.__new__(Ouvinte)
        ouvinte.sd = SimpleNamespace(RawInputStream=Stream)
        ouvinte.np = np
        ouvinte.modelo = SimpleNamespace(transcribe=transcrever)
        ouvinte.dispositivo = None
        ouvinte.limiar = 0.01
        ouvinte.aguardar_ativacao()
        self.assertFalse(estado["aberto"])
        self.assertEqual(estado["streams"], 2)
        self.assertEqual(estado["transcricoes"], 2)


class AppTests(unittest.TestCase):
    def setUp(self):
        clima = Clima(Decimal("34.5"), "céu limpo", AGORA, Localizacao(-8.07417, -39.11917))
        for alvo, valor in (("jarvis.app.consultar_clima", clima), ("jarvis.app.agora_recife", AGORA)):
            mock = patch(alvo, return_value=valor)
            mock.start()
            self.addCleanup(mock.stop)

    @patch("jarvis.app.consultar_cotacao", side_effect=ErroCotacao("HTTP 503"))
    def test_falha_tem_resposta_exata(self, consultar):
        with patch("sys.stdout", new_callable=io.StringIO) as saida:
            texto = app.atender()
            self.assertIn(FALHA.removeprefix("Bom dia, senhor. "), texto)
            self.assertIn("trinta e quatro vírgula cinco graus", texto)
            self.assertEqual(texto.count("Bom dia, senhor."), 1)
        self.assertIn("Consultando cotação…", saida.getvalue())

    def test_texto_com_recuperacao_de_falha_e_saida(self):
        cotacao = Cotacao(Decimal("5.2379"), AGORA)
        with patch("builtins.input", side_effect=["oi", "BOM DIA, JARVIS!", "bom dia jarvis", "sair"]), \
             patch("jarvis.app.consultar_cotacao", side_effect=[ErroCotacao("timeout"), cotacao]) as consulta, \
             patch("jarvis.app.time.monotonic", side_effect=[0, 0, 5, 5]), \
             patch("sys.stdout", new_callable=io.StringIO) as saida:
            self.assertEqual(app.main(["--texto", "--sem-voz", "--sem-musica"]), 0)
        self.assertEqual(consulta.call_count, 2)
        texto = saida.getvalue()
        self.assertIn(FALHA.removeprefix("Bom dia, senhor. "), texto)
        self.assertIn("cinco reais e vinte e quatro centavos", texto)
        self.assertIn("AwesomeAPI", texto)
        self.assertIn("Jarvis encerrado.", texto)

    def test_duplicata_nao_consulta(self):
        with patch("builtins.input", side_effect=["bom dia jarvis", "bom dia jarvis", "sair"]), \
             patch("jarvis.app.consultar_cotacao", return_value=Cotacao(Decimal("5"), AGORA)) as consulta, \
             patch("jarvis.app.time.monotonic", side_effect=[0, 0, 1]), \
             patch("sys.stdout", new_callable=io.StringIO):
            app.main(["--texto", "--sem-voz", "--sem-musica"])
        self.assertEqual(consulta.call_count, 1)

    def test_ctrl_c_encerra(self):
        with patch("builtins.input", side_effect=KeyboardInterrupt), patch("sys.stdout", new_callable=io.StringIO) as saida:
            self.assertEqual(app.main(["--texto", "--sem-voz", "--sem-musica"]), 0)
        self.assertIn("Jarvis encerrado.", saida.getvalue())

    def test_voz_falha_sem_encerrar_e_tenta_novamente(self):
        with patch("builtins.input", side_effect=["bom dia jarvis", "bom dia jarvis", "sair"]), \
             patch("jarvis.app.consultar_cotacao", return_value=Cotacao(Decimal("5"), AGORA)), \
             patch("jarvis.app.Voz", side_effect=[ErroVoz("sem voz instalada"), SimpleNamespace(falar=lambda t: None, fechar=lambda: None)]) as voz, \
             patch("jarvis.app.time.monotonic", side_effect=[0, 0, 5, 5]), \
             patch("sys.stdout", new_callable=io.StringIO) as saida:
            self.assertEqual(app.main(["--texto", "--sem-musica"]), 0)
        self.assertEqual(voz.call_count, 2)
        self.assertIn("Problema de voz", saida.getvalue())

    def test_microfone_falha_sem_encerrar(self):
        with patch("jarvis.app.Ouvinte", side_effect=ErroMicrofone("sem permissão")), \
             patch("jarvis.app.time.sleep", side_effect=KeyboardInterrupt), \
             patch("sys.stdout", new_callable=io.StringIO) as saida:
            self.assertEqual(app.main(["--sem-musica"]), 0)
        self.assertIn("Problema de reconhecimento", saida.getvalue())


class VozTests(unittest.TestCase):
    def test_prioriza_portugues_brasileiro(self):
        from unittest.mock import Mock
        engine = Mock()
        pt = SimpleNamespace(id="pt-pt", name="Portuguese", languages=[b"\x05pt-pt"])
        br = SimpleNamespace(id="pt-br", name="Brazil", languages=[b"\x05pt-br"])
        engine.getProperty.return_value = [pt, br]
        modulo = SimpleNamespace(init=lambda **kwargs: engine)
        with patch.dict("sys.modules", {"pyttsx3": modulo}), patch("sys.stdout", new_callable=io.StringIO):
            voz = Voz(150)
            voz.falar("teste")
            voz.fechar()
        engine.setProperty.assert_any_call("voice", "pt-br")
        engine.setProperty.assert_any_call("rate", 150)
        engine.say.assert_called_once_with("teste")
        engine.runAndWait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
