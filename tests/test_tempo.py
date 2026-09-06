"""Testes de conversão e limites temporais para busca (R6.3)."""

from __future__ import annotations

from datetime import datetime, timezone

from segundocerebro.retrieve.tempo import converter_limites_temporais


def test_anos_isolados() -> None:
    t_min, t_max = converter_limites_temporais(depois_de="2024", antes_de="2024")
    assert t_min is not None and t_max is not None

    dt_min = datetime.fromtimestamp(t_min, tz=timezone.utc)
    dt_max = datetime.fromtimestamp(t_max, tz=timezone.utc)

    assert dt_min.year == 2024 and dt_min.month == 1 and dt_min.day == 1
    assert dt_min.hour == 0 and dt_min.minute == 0 and dt_min.second == 0

    assert dt_max.year == 2024 and dt_max.month == 12 and dt_max.day == 31
    assert dt_max.hour == 23 and dt_max.minute == 59 and dt_max.second == 59


def test_ano_mes() -> None:
    t_min, t_max = converter_limites_temporais(depois_de="2024-02", antes_de="2024-02")
    assert t_min is not None and t_max is not None

    dt_min = datetime.fromtimestamp(t_min, tz=timezone.utc)
    dt_max = datetime.fromtimestamp(t_max, tz=timezone.utc)

    assert dt_min.year == 2024 and dt_min.month == 2 and dt_min.day == 1
    # 2024 é ano bissexto: fevereiro tem 29 dias
    assert dt_max.year == 2024 and dt_max.month == 2 and dt_max.day == 29
    assert dt_max.hour == 23 and dt_max.minute == 59


def test_data_completa() -> None:
    t_min, t_max = converter_limites_temporais(depois_de="2024-07-15", antes_de="2024-07-15")
    assert t_min is not None and t_max is not None

    dt_min = datetime.fromtimestamp(t_min, tz=timezone.utc)
    dt_max = datetime.fromtimestamp(t_max, tz=timezone.utc)

    assert dt_min.year == 2024 and dt_min.month == 7 and dt_min.day == 15
    assert dt_min.hour == 0 and dt_min.minute == 0
    assert dt_max.year == 2024 and dt_max.month == 7 and dt_max.day == 15
    assert dt_max.hour == 23 and dt_max.minute == 59


def test_intervalo_aberto_ou_invalido() -> None:
    # Apenas depois_de
    t_min, t_max = converter_limites_temporais(depois_de="2024-01-01", antes_de="")
    assert t_min is not None
    assert t_max is None

    # Apenas antes_de
    t_min, t_max = converter_limites_temporais(depois_de="", antes_de="2024-12-31")
    assert t_min is None
    assert t_max is not None

    # Vazio e lixo
    assert converter_limites_temporais("", "") == (None, None)
    assert converter_limites_temporais("invalido", "xyz") == (None, None)
