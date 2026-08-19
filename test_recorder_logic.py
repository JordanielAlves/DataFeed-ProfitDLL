"""
test_recorder_logic.py
Script de verificação automatizada para validação lógica das correções:
  1. Bug 5: Reset dos contadores em `DataRecorder._agent_cache` após `_flush_agents`.
  2. Bug 3: Drenagem em lote de múltiplos itens da fila em `_writer_loop`.
"""

import sys
import os
import time
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

# Garantir que o diretório atual está no sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_recorder import DataRecorder, _EVT_TRADE, _EVT_STOP
from profit_bridge import TradeEvent, TRADE_TYPE_BUY, TRADE_TYPE_SELL


class TestDataRecorderLogic(unittest.TestCase):

    @patch("psycopg2.extras.execute_values")
    @patch("psycopg2.connect")
    def test_bug5_agent_cache_incremental_reset(self, mock_connect, mock_execute_values):
        """Verifica se os contadores incrementais do _agent_cache são zerados após _flush_agents."""
        # Mock do cursor e conexão
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        recorder = DataRecorder()
        # Simular que já existe uma sessão aberta para o ativo
        recorder._sessions["WDOK25"] = 101

        # 1º Negócio: Agente 100 compra 5 contratos de WDO
        evt1 = TradeEvent(
            ticker="WDOK25",
            trade_number=1,
            ts=datetime.now(),
            price=5400.0,
            qty=5,
            volume=27000.0,
            buy_agent=100,
            sell_agent=200,
            trade_type=TRADE_TYPE_BUY
        )
        recorder._buffer_trade(evt1)

        # Verificar se acumulou no cache em memória
        from datetime import date
        today = date.today()
        key_buy = (today, "WDOK25", 100)
        self.assertEqual(recorder._agent_cache[key_buy]["buy_qty"], 5)
        self.assertTrue(recorder._agent_cache[key_buy]["dirty"])

        # Executar _flush_agents (com DB mockado)
        recorder._flush_agents()

        # VERIFICAÇÃO BUG 5: Os contadores no cache DEVEM ter sido zerados após o commit bem-sucedido!
        self.assertEqual(recorder._agent_cache[key_buy]["buy_qty"], 0, "O contador buy_qty deve ser zerado após flush para evitar contagem exponencial no SQL (Bug 5)")
        self.assertEqual(recorder._agent_cache[key_buy]["buy_trades"], 0)
        self.assertFalse(recorder._agent_cache[key_buy]["dirty"])

        # 2º Negócio posterior: Agente 100 compra mais 3 contratos
        evt2 = TradeEvent(
            ticker="WDOK25",
            trade_number=2,
            ts=datetime.now(),
            price=5401.0,
            qty=3,
            volume=16203.0,
            buy_agent=100,
            sell_agent=200,
            trade_type=TRADE_TYPE_BUY
        )
        recorder._buffer_trade(evt2)

        # O novo saldo no cache incremental deve ser EXATAMENTE 3 (e não 8 = 5+3)
        self.assertEqual(recorder._agent_cache[key_buy]["buy_qty"], 3, "O cache deve reter apenas o novo delta (3) entre os flushes")
        self.assertTrue(recorder._agent_cache[key_buy]["dirty"])

    @patch("data_recorder.DataRecorder._flush")
    @patch("data_recorder.DataRecorder._flush_agents")
    def test_bug3_batch_draining_in_writer_loop(self, mock_flush_agents, mock_flush):
        """Verifica se o laço de drenagem (get_nowait) esvazia múltiplos itens de uma vez no _writer_loop."""
        recorder = DataRecorder()
        recorder._sessions["WDOK25"] = 101

        # Inserir 15 trades rápidos diretamente na fila
        for i in range(15):
            evt = TradeEvent(
                ticker="WDOK25",
                trade_number=i+1,
                ts=datetime.now(),
                price=5400.0,
                qty=1,
                volume=5400.0,
                buy_agent=100,
                sell_agent=200,
                trade_type=TRADE_TYPE_BUY
            )
            recorder._queue.put((_EVT_TRADE, evt))

        # Inserir sinal de parada ao final
        recorder._queue.put((_EVT_STOP, None))

        # Executar o writer_loop de forma síncrona (ele vai ler os eventos e parar ao encontrar _EVT_STOP)
        recorder._writer_loop()

        # Verificar que todos os 15 trades foram processados/bufferizados e a fila esvaziada
        self.assertEqual(recorder._stats["trades"], 15, "Todos os 15 trades da fila devem ser consumidos pelo batch draining do _writer_loop")
        self.assertTrue(recorder._queue.empty(), "A fila deve ser completamente esvaziada")


if __name__ == "__main__":
    print("=== Executando Testes de Verificação do DataRecorder (Bug 5 & Bug 3) ===")
    unittest.main(verbosity=2)
