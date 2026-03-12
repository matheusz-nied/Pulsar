"""
test_persistencia_database.py — Demonstra persistência de dados entre reinicializações.

Valida que alarmes, preferências e ações persistem após fechar/reabrir o DB.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from backend.memory.database import Database


async def demonstrar_persistencia() -> None:
    """
    Demonstra que dados persistem entre reinicializações do banco.
    
    1. Cria um DB e salva dados
    2. Fecha a conexão
    3. Cria nova instância e verifica que os dados ainda existem
    """
    logger.info("=" * 80)
    logger.info("DEMONSTRAÇÃO DE PERSISTÊNCIA DO BANCO DE DADOS")
    logger.info("=" * 80)
    
    # Usar banco de teste na pasta memory
    db_path = Path(__file__).parent.parent / "backend" / "memory" / "test_persistencia.db"
    
    # Limpar banco anterior se existir
    if db_path.exists():
        db_path.unlink()
        logger.info(f"Banco de teste anterior removido: {db_path}")
    
    # --- FASE 1: CRIAR E POPULAR ---
    logger.info("\n[FASE 1] Criando banco e populando com dados...")
    
    db1 = Database()
    db1.db_path = str(db_path)
    await db1.inicializar()
    
    # Salvar alarme
    alarme_id = str(uuid.uuid4())
    horario_alarme = (datetime.now() + timedelta(hours=2)).isoformat()
    await db1.salvar_alarme(alarme_id, horario_alarme, "Reunião importante às 15h")
    logger.info(f"✓ Alarme salvo: {alarme_id}")
    
    # Salvar preferências
    await db1.set_preferencia("idioma", "pt-BR")
    await db1.set_preferencia("voz_tts", "pt-BR-FranciscaNeural")
    await db1.set_preferencia("tema", "dark")
    logger.info("✓ Preferências salvas: idioma, voz_tts, tema")
    
    # Registrar ações
    await db1.registrar_acao("music", "Tocou Spotify: Bohemian Rhapsody", "sucesso")
    await db1.registrar_acao("calendar", "Criou evento: Reunião de equipe", "sucesso")
    await db1.registrar_acao("system", "Abriu aplicativo: Chrome", "sucesso")
    logger.info("✓ 3 ações registradas no histórico")
    
    # Verificar dados antes de fechar
    alarmes_antes = await db1.buscar_alarmes_ativos()
    prefs_antes = await db1.listar_preferencias()
    acoes_antes = await db1.buscar_acoes_recentes()
    
    logger.info(f"\nDados no DB antes de fechar:")
    logger.info(f"  - Alarmes ativos: {len(alarmes_antes)}")
    logger.info(f"  - Preferências: {len(prefs_antes)}")
    logger.info(f"  - Ações no histórico: {len(acoes_antes)}")
    
    # Fechar conexão
    await db1.fechar()
    logger.info("\n✓ Conexão do DB1 fechada")
    
    # --- FASE 2: REINICIALIZAR E VERIFICAR ---
    logger.info("\n[FASE 2] Reinicializando banco e verificando persistência...")
    
    db2 = Database()
    db2.db_path = str(db_path)
    await db2.inicializar()
    logger.info("✓ Nova instância DB2 criada e inicializada")
    
    # Buscar dados
    alarmes_depois = await db2.buscar_alarmes_ativos()
    prefs_depois = await db2.listar_preferencias()
    acoes_depois = await db2.buscar_acoes_recentes()
    
    logger.info(f"\nDados no DB depois de reinicializar:")
    logger.info(f"  - Alarmes ativos: {len(alarmes_depois)}")
    logger.info(f"  - Preferências: {len(prefs_depois)}")
    logger.info(f"  - Ações no histórico: {len(acoes_depois)}")
    
    # --- VALIDAÇÃO ---
    logger.info("\n[VALIDAÇÃO] Verificando integridade dos dados...")
    
    sucesso = True
    
    # Validar alarmes
    if len(alarmes_depois) != len(alarmes_antes):
        logger.error(f"❌ Alarmes: esperado {len(alarmes_antes)}, obtido {len(alarmes_depois)}")
        sucesso = False
    else:
        alarme_recuperado = alarmes_depois[0]
        if alarme_recuperado["id"] == alarme_id:
            logger.success(f"✓ Alarme persistiu: {alarme_recuperado['mensagem']}")
        else:
            logger.error("❌ Alarme recuperado é diferente do original")
            sucesso = False
    
    # Validar preferências
    if len(prefs_depois) != len(prefs_antes):
        logger.error(f"❌ Preferências: esperado {len(prefs_antes)}, obtido {len(prefs_depois)}")
        sucesso = False
    else:
        logger.success(f"✓ Preferências persistiram: {prefs_depois}")
        if prefs_depois.get("idioma") != "pt-BR":
            logger.error("❌ Preferência 'idioma' incorreta")
            sucesso = False
    
    # Validar histórico
    if len(acoes_depois) != len(acoes_antes):
        logger.error(f"❌ Histórico: esperado {len(acoes_antes)}, obtido {len(acoes_depois)}")
        sucesso = False
    else:
        logger.success(f"✓ Histórico persistiu: {len(acoes_depois)} ações")
        for acao in acoes_depois:
            logger.info(f"    - [{acao['tipo']}] {acao['descricao']}")
    
    # --- TESTE ADICIONAL: Modificar dados ---
    logger.info("\n[TESTE ADICIONAL] Modificando dados e verificando...")
    
    # Marcar alarme como disparado
    await db2.marcar_disparado(alarme_id)
    alarmes_apos_marcar = await db2.buscar_alarmes_ativos()
    if len(alarmes_apos_marcar) == 0:
        logger.success("✓ Alarme marcado como disparado e não aparece mais em ativos")
    else:
        logger.error("❌ Alarme marcado como disparado mas ainda aparece em ativos")
        sucesso = False
    
    # Adicionar nova preferência
    await db2.set_preferencia("modo_silencioso", "false")
    prefs_final = await db2.listar_preferencias()
    if len(prefs_final) == 4 and prefs_final.get("modo_silencioso") == "false":
        logger.success("✓ Nova preferência adicionada com sucesso")
    else:
        logger.error("❌ Falha ao adicionar nova preferência")
        sucesso = False
    
    # Fechar segunda conexão
    await db2.fechar()
    
    # --- FASE 3: VERIFICAÇÃO FINAL ---
    logger.info("\n[FASE 3] Verificação final após todas as modificações...")
    
    db3 = Database()
    db3.db_path = str(db_path)
    await db3.inicializar()
    
    alarmes_final = await db3.buscar_alarmes_ativos()
    prefs_final = await db3.listar_preferencias()
    acoes_final = await db3.buscar_acoes_recentes()
    
    logger.info(f"Estado final do banco:")
    logger.info(f"  - Alarmes ativos: {len(alarmes_final)} (esperado: 0)")
    logger.info(f"  - Preferências: {len(prefs_final)} (esperado: 4)")
    logger.info(f"  - Ações no histórico: {len(acoes_final)} (esperado: 3)")
    
    if len(alarmes_final) == 0 and len(prefs_final) == 4 and len(acoes_final) == 3:
        logger.success("\n✅ TODOS OS DADOS PERSISTIRAM CORRETAMENTE!")
    else:
        logger.error("\n❌ FALHA NA PERSISTÊNCIA DOS DADOS")
        sucesso = False
    
    await db3.fechar()
    
    # --- RESULTADO ---
    logger.info("\n" + "=" * 80)
    if sucesso:
        logger.success("✅ CRITÉRIO DE CONCLUSÃO ATENDIDO")
        logger.success("✅ Todos os dados persistem entre reinicializações do banco")
    else:
        logger.error("❌ CRITÉRIO DE CONCLUSÃO NÃO ATENDIDO")
    logger.info("=" * 80)
    
    # Limpar banco de teste
    if db_path.exists():
        db_path.unlink()
        logger.info(f"\nBanco de teste removido: {db_path}")


if __name__ == "__main__":
    asyncio.run(demonstrar_persistencia())
