"""
price_utils.py
Utilitário Central de Normalização de Escala e Formatação de Preços B3.
Garante consistência absoluta entre Banco de Dados, Machine Learning e Exibição ao Usuário.
"""

import sys
from typing import Union

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def get_ticker_scale(ticker: str) -> float:
    """
    Retorna o fator de escala padrão da DLL/DB para o ativo.
    WDO/DOL = 10.0 (Preço no banco é 10x a cotação real da B3).
    WIN/IND = 1.0 (Preço no banco já está em pontos reais).
    DI1     = 1000.0 ou 1.0 dependendo do contrato.
    """
    if not ticker:
        return 1.0
    t = ticker.upper()
    if t.startswith("WDO") or t.startswith("DOL"):
        return 10.0
    elif t.startswith("WIN") or t.startswith("IND"):
        return 1.0
    return 1.0


def to_real_points(price_raw: Union[float, int], ticker: str = "WDO") -> float:
    """
    Converte qualquer preço bruto (raw do DB ou DLL) para PONTOS REAIS DA B3.
    Lida com variações históricas de forma robusta e defensiva.
    
    Exemplos para WDO:
      51650.00 -> 5165.00
      5165.00  -> 5165.00
      516500.0 -> 5165.00
    """
    if price_raw is None:
        return 0.0
    p = float(price_raw)
    if p == 0:
        return 0.0
    
    t = ticker.upper() if ticker else "WDO"
    
    if t.startswith("WDO") or t.startswith("DOL"):
        # Dólar futuro na B3 oscila historicamente entre 1.500 e 8.000 pontos
        if 1500.0 <= p <= 8000.0:
            return round(p, 2)
        elif 15000.0 <= p <= 80000.0:
            return round(p / 10.0, 2)
        elif 150000.0 <= p <= 800000.0:
            return round(p / 100.0, 2)
        elif 150.0 <= p <= 800.0:
            return round(p * 10.0, 2)
        return round(p / 10.0, 2)

    elif t.startswith("WIN") or t.startswith("IND"):
        # Índice futuro na B3 oscila entre 50.000 e 250.000 pontos
        if 50000.0 <= p <= 250000.0:
            return round(p, 2)
        elif 5000.0 <= p <= 25000.0:
            return round(p * 10.0, 2)
        elif 500000.0 <= p <= 2500000.0:
            return round(p / 10.0, 2)
        return round(p, 2)

    elif t.startswith("DI1"):
        # Taxa de juros DI (ex: 13.75% a.a.)
        if 1.0 <= p <= 40.0:
            return round(p, 3)
        elif 100.0 <= p <= 4000.0:
            return round(p / 100.0, 3)
        elif 10000.0 <= p <= 400000.0:
            return round(p / 10000.0, 3)
        return round(p, 3)

    return round(p, 2)


def to_db_price(price_real: float, ticker: str = "WDO") -> float:
    """
    Converte pontos reais da B3 para o formato nativo da tabela trades/book_events.
    """
    scale = get_ticker_scale(ticker)
    return round(price_real * scale, 2)


def format_price_b3(price: Union[float, int], ticker: str = "WDO") -> str:
    """
    Formata o preço no padrão visual brasileiro solicitado pelo usuário:
    Ex: 5.160,00 | 5.160,50 | 5.161,00 | 134.500 | 13,725%
    
    Aceita preço bruto ou preço real e converte automaticamente.
    """
    if price is None:
        return "N/A"
    
    real_pts = to_real_points(price, ticker)
    t = ticker.upper() if ticker else "WDO"
    
    if t.startswith("WDO") or t.startswith("DOL"):
        inteiro = int(real_pts)
        decimal = int(round((real_pts - inteiro) * 100))
        inteiro_str = f"{inteiro:,}".replace(",", ".")
        return f"{inteiro_str},{decimal:02d}"

    elif t.startswith("WIN") or t.startswith("IND"):
        inteiro = int(round(real_pts))
        inteiro_str = f"{inteiro:,}".replace(",", ".")
        return f"{inteiro_str}"

    elif t.startswith("DI1"):
        return f"{real_pts:.3f}%".replace(".", ",")

    inteiro = int(real_pts)
    decimal = int(round((real_pts - inteiro) * 100))
    inteiro_str = f"{inteiro:,}".replace(",", ".")
    return f"{inteiro_str},{decimal:02d}"


if __name__ == "__main__":
    print("=== TESTES DE CONVERSAO E FORMATACAO B3 ===")
    assert to_real_points(51650.0, "WDOU26") == 5165.0
    assert to_real_points(5165.5, "WDOU26") == 5165.5
    assert format_price_b3(51650.0, "WDOU26") == "5.165,00"
    assert format_price_b3(51605.0, "WDOU26") == "5.160,50"
    assert format_price_b3(51610.0, "WDOU26") == "5.161,00"
    assert format_price_b3(134500.0, "WINV26") == "134.500"
    assert format_price_b3(13.725, "DI1F27") == "13,725%"
    print("Sucesso: Todos os testes de price_utils passaram com 100% de precisao!")
