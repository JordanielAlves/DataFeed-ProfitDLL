#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Módulo de Calendário e Sazonalidade do Dólar Futuro na B3.
Extrai features temporais macro/cíclicas: month_week_phase, days_to_rollover, is_payroll_week.
"""

import numpy as np
from datetime import date, datetime, timedelta

def get_market_calendar_features(dt: datetime) -> dict:
    """
    Calcula as Fases Sazonais do Dólar Futuro na B3 (WDO/DOL).
    """
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt[:19])
        
    d = dt.date()
    
    # 1. Encontrar o 1º dia útil do mês atual e o 1º dia útil do próximo mês
    month_start = date(d.year, d.month, 1)
    
    if d.month == 12:
        next_month_start = date(d.year + 1, 1, 1)
    else:
        next_month_start = date(d.year, d.month + 1, 1)
        
    first_biz_day_current = np.busday_offset(month_start, 0, roll='forward').astype(date)
    first_biz_day_next = np.busday_offset(next_month_start, 0, roll='forward').astype(date)
    
    # 2. Dias úteis até a rolagem (1º dia útil do mês seguinte)
    days_to_rollover = np.busday_count(d, first_biz_day_next)
    
    # 3. Qual é o dia útil atual dentro do mês?
    current_biz_day = np.busday_count(first_biz_day_current, d) + 1
    
    # 4. Fase do Mês (1, 2, 3, 4)
    # Semana 1: 1 a 5
    # Semana 2: 6 a 10
    # Semana 3: 11 a 15
    # Semana 4: > 15
    if current_biz_day <= 5:
        phase = 1
    elif current_biz_day <= 10:
        phase = 2
    elif current_biz_day <= 15:
        phase = 3
    else:
        phase = 4
        
    # 5. É semana de Payroll? (Payroll = 1ª sexta do mês)
    first_friday = month_start
    while first_friday.weekday() != 4:
        first_friday += timedelta(days=1)
        
    is_payroll_week = 1 if (d <= first_friday and (first_friday - d).days < 7) else 0
    
    return {
        "month_week_phase": float(phase),
        "days_to_rollover": float(days_to_rollover),
        "is_payroll_week": float(is_payroll_week)
    }

if __name__ == "__main__":
    test_dt = datetime(2026, 7, 17)
    feats = get_market_calendar_features(test_dt)
    print(f"Features para {test_dt.strftime('%d/%m/%Y')}: {feats}")
