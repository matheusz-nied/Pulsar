"""
test_database.py — Testes para o módulo de banco de dados SQLite.

Valida operações CRUD em todas as tabelas (alarmes, preferências, histórico).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from backend.memory.database import Database


# --- Fixtures ---

@pytest_asyncio.fixture
async def temp_database(tmp_path: Path) -> Database:
    """
    Cria um banco de dados temporário para testes.
    
    Args:
        tmp_path: Diretório temporário fornecido pelo pytest.
        
    Returns:
        Instância de Database configurada com banco temporário.
    """
    db = Database()
    db.db_path = str(tmp_path / "test.db")
    await db.inicializar()
    return db


# --- Testes de Alarmes ---

@pytest.mark.asyncio
async def test_salvar_alarme(temp_database: Database) -> None:
    """Testa salvar um alarme no banco."""
    alarme_id = str(uuid.uuid4())
    horario = (datetime.now() + timedelta(hours=1)).isoformat()
    mensagem = "Lembrete de teste"
    
    await temp_database.salvar_alarme(alarme_id, horario, mensagem)
    
    alarmes = await temp_database.buscar_alarmes_ativos()
    assert len(alarmes) == 1
    assert alarmes[0]["id"] == alarme_id
    assert alarmes[0]["mensagem"] == mensagem


@pytest.mark.asyncio
async def test_buscar_alarmes_ativos(temp_database: Database) -> None:
    """Testa buscar alarmes ativos (não disparados)."""
    # Criar 2 alarmes ativos e 1 disparado
    alarme_id1 = str(uuid.uuid4())
    alarme_id2 = str(uuid.uuid4())
    alarme_id3 = str(uuid.uuid4())
    
    horario = datetime.now().isoformat()
    
    await temp_database.salvar_alarme(alarme_id1, horario, "Alarme 1")
    await temp_database.salvar_alarme(alarme_id2, horario, "Alarme 2")
    await temp_database.salvar_alarme(alarme_id3, horario, "Alarme 3")
    
    # Marcar alarme 2 como disparado
    await temp_database.marcar_disparado(alarme_id2)
    
    # Buscar ativos
    ativos = await temp_database.buscar_alarmes_ativos()
    assert len(ativos) == 2
    
    ids_ativos = {a["id"] for a in ativos}
    assert alarme_id1 in ids_ativos
    assert alarme_id3 in ids_ativos
    assert alarme_id2 not in ids_ativos


@pytest.mark.asyncio
async def test_marcar_disparado(temp_database: Database) -> None:
    """Testa marcar um alarme como disparado."""
    alarme_id = str(uuid.uuid4())
    horario = datetime.now().isoformat()
    
    await temp_database.salvar_alarme(alarme_id, horario, "Teste")
    
    # Verificar que está ativo
    ativos = await temp_database.buscar_alarmes_ativos()
    assert len(ativos) == 1
    
    # Marcar como disparado
    await temp_database.marcar_disparado(alarme_id)
    
    # Verificar que não está mais ativo
    ativos = await temp_database.buscar_alarmes_ativos()
    assert len(ativos) == 0


@pytest.mark.asyncio
async def test_deletar_alarme(temp_database: Database) -> None:
    """Testa deletar um alarme."""
    alarme_id = str(uuid.uuid4())
    horario = datetime.now().isoformat()
    
    await temp_database.salvar_alarme(alarme_id, horario, "Teste")
    
    # Verificar que existe
    ativos = await temp_database.buscar_alarmes_ativos()
    assert len(ativos) == 1
    
    # Deletar
    removido = await temp_database.deletar_alarme(alarme_id)
    assert removido is True
    
    # Verificar que não existe mais
    ativos = await temp_database.buscar_alarmes_ativos()
    assert len(ativos) == 0
    
    # Tentar deletar novamente (não deve encontrar)
    removido = await temp_database.deletar_alarme(alarme_id)
    assert removido is False


# --- Testes de Preferências ---

@pytest.mark.asyncio
async def test_set_e_get_preferencia(temp_database: Database) -> None:
    """Testa salvar e recuperar uma preferência."""
    await temp_database.set_preferencia("idioma", "pt-BR")
    
    valor = await temp_database.get_preferencia("idioma")
    assert valor == "pt-BR"


@pytest.mark.asyncio
async def test_atualizar_preferencia(temp_database: Database) -> None:
    """Testa atualizar uma preferência existente."""
    await temp_database.set_preferencia("voz_tts", "pt-BR-FranciscaNeural")
    
    # Atualizar
    await temp_database.set_preferencia("voz_tts", "pt-BR-AntonioNeural")
    
    valor = await temp_database.get_preferencia("voz_tts")
    assert valor == "pt-BR-AntonioNeural"


@pytest.mark.asyncio
async def test_get_preferencia_inexistente(temp_database: Database) -> None:
    """Testa buscar preferência que não existe."""
    valor = await temp_database.get_preferencia("chave_inexistente")
    assert valor is None


@pytest.mark.asyncio
async def test_listar_preferencias(temp_database: Database) -> None:
    """Testa listar todas as preferências."""
    await temp_database.set_preferencia("idioma", "pt-BR")
    await temp_database.set_preferencia("voz_tts", "pt-BR-FranciscaNeural")
    await temp_database.set_preferencia("tema", "dark")
    
    prefs = await temp_database.listar_preferencias()
    assert len(prefs) == 3
    assert prefs["idioma"] == "pt-BR"
    assert prefs["voz_tts"] == "pt-BR-FranciscaNeural"
    assert prefs["tema"] == "dark"


@pytest.mark.asyncio
async def test_deletar_preferencia(temp_database: Database) -> None:
    """Testa deletar uma preferência."""
    await temp_database.set_preferencia("teste", "valor")
    
    # Verificar que existe
    valor = await temp_database.get_preferencia("teste")
    assert valor == "valor"
    
    # Deletar
    removido = await temp_database.deletar_preferencia("teste")
    assert removido is True
    
    # Verificar que não existe mais
    valor = await temp_database.get_preferencia("teste")
    assert valor is None


# --- Testes de Histórico de Ações ---

@pytest.mark.asyncio
async def test_registrar_acao(temp_database: Database) -> None:
    """Testa registrar uma ação no histórico."""
    acao_id = await temp_database.registrar_acao(
        tipo="music",
        descricao="Tocou música Bohemian Rhapsody",
        resultado="sucesso",
    )
    
    assert acao_id > 0
    
    acoes = await temp_database.buscar_acoes_recentes(limite=10)
    assert len(acoes) == 1
    assert acoes[0]["tipo"] == "music"
    assert acoes[0]["descricao"] == "Tocou música Bohemian Rhapsody"


@pytest.mark.asyncio
async def test_buscar_acoes_recentes(temp_database: Database) -> None:
    """Testa buscar ações recentes com limite."""
    # Registrar 5 ações
    for i in range(5):
        await temp_database.registrar_acao(
            tipo="test",
            descricao=f"Ação {i}",
        )
    
    # Buscar com limite de 3
    acoes = await temp_database.buscar_acoes_recentes(limite=3)
    assert len(acoes) == 3
    
    # Verificar ordem (mais recente primeiro)
    assert acoes[0]["descricao"] == "Ação 4"
    assert acoes[1]["descricao"] == "Ação 3"
    assert acoes[2]["descricao"] == "Ação 2"


@pytest.mark.asyncio
async def test_buscar_acoes_por_tipo(temp_database: Database) -> None:
    """Testa filtrar ações por tipo."""
    await temp_database.registrar_acao("music", "Tocou música")
    await temp_database.registrar_acao("calendar", "Criou evento")
    await temp_database.registrar_acao("music", "Pausou música")
    await temp_database.registrar_acao("system", "Abriu aplicativo")
    
    acoes_music = await temp_database.buscar_acoes_por_tipo("music")
    assert len(acoes_music) == 2
    assert all(a["tipo"] == "music" for a in acoes_music)


@pytest.mark.asyncio
async def test_limpar_historico_antigo(temp_database: Database) -> None:
    """Testa limpeza de histórico antigo."""
    # Registrar ação recente
    await temp_database.registrar_acao("test", "Ação recente")
    
    # Simular ação antiga (manual no DB)
    import aiosqlite
    data_antiga = (datetime.now() - timedelta(days=100)).isoformat()
    async with aiosqlite.connect(temp_database.db_path) as conn:
        await conn.execute(
            """
            INSERT INTO historico_acoes (tipo, descricao, resultado, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            ("test", "Ação antiga", None, data_antiga),
        )
        await conn.commit()
    
    # Verificar que temos 2 ações
    acoes = await temp_database.buscar_acoes_recentes(limite=100)
    assert len(acoes) == 2
    
    # Limpar ações antigas (>90 dias)
    removidos = await temp_database.limpar_historico_antigo(dias=90)
    assert removidos == 1
    
    # Verificar que sobrou apenas 1
    acoes = await temp_database.buscar_acoes_recentes(limite=100)
    assert len(acoes) == 1
    assert acoes[0]["descricao"] == "Ação recente"
