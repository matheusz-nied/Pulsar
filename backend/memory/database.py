"""
database.py — Gerenciamento de dados estruturados com SQLite.

Responsável por:
- Criar e gerenciar tabelas para alarmes, preferências e histórico de ações
- Fornecer interface assíncrona com aiosqlite
- Operações CRUD para cada tabela
- Inicialização automática das tabelas no startup
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger


# --- Configuração do caminho do banco ---

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = _PROJECT_ROOT / "backend" / "memory" / "assistente.db"


# --- Classe Database ---

class Database:
    """
    Gerenciador de banco de dados SQLite para o assistente virtual.
    
    Gerencia três tabelas principais:
    - alarmes: Para agendamento de notificações
    - preferencias: Para armazenar configurações do usuário
    - historico_acoes: Para registrar ações realizadas pelo assistente
    """

    def __init__(self) -> None:
        """Inicializa o gerenciador do banco de dados."""
        self.db_path = str(DB_PATH)
        self._conn: aiosqlite.Connection | None = None
        logger.debug(f"Database inicializado com caminho: {self.db_path}")

    async def inicializar(self) -> None:
        """
        Inicializa o banco de dados criando as tabelas necessárias.
        
        Deve ser chamado no startup da aplicação FastAPI.
        Cria o diretório se não existir e todas as tabelas necessárias.
        """
        try:
            # Garantir que o diretório existe
            db_dir = Path(self.db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            
            # Criar conexão e tabelas
            async with aiosqlite.connect(self.db_path) as conn:
                # Habilitar foreign keys
                await conn.execute("PRAGMA foreign_keys = ON")
                
                # Tabela de alarmes
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS alarmes (
                        id TEXT PRIMARY KEY,
                        horario TEXT NOT NULL,
                        mensagem TEXT NOT NULL,
                        criado_em TEXT NOT NULL,
                        disparado INTEGER DEFAULT 0
                    )
                """)
                
                # Tabela de preferências
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS preferencias (
                        chave TEXT PRIMARY KEY,
                        valor TEXT NOT NULL,
                        atualizado_em TEXT NOT NULL
                    )
                """)
                
                # Tabela de histórico de ações
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS historico_acoes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tipo TEXT NOT NULL,
                        descricao TEXT NOT NULL,
                        resultado TEXT,
                        timestamp TEXT NOT NULL
                    )
                """)
                
                await conn.commit()
                
            logger.success(f"Banco de dados inicializado com sucesso: {self.db_path}")
            
        except Exception as e:
            logger.error(f"Erro ao inicializar banco de dados: {e}")
            raise

    # --- Métodos de Alarmes ---

    async def salvar_alarme(
        self,
        id: str,
        horario: str,
        mensagem: str,
    ) -> None:
        """
        Salva um novo alarme no banco de dados.
        
        Args:
            id: Identificador único do alarme (UUID).
            horario: Horário do alarme no formato ISO 8601.
            mensagem: Mensagem a ser exibida quando o alarme disparar.
        """
        try:
            criado_em = datetime.now().isoformat()
            
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute(
                    """
                    INSERT INTO alarmes (id, horario, mensagem, criado_em, disparado)
                    VALUES (?, ?, ?, ?, 0)
                    """,
                    (id, horario, mensagem, criado_em),
                )
                await conn.commit()
                
            logger.info(f"Alarme salvo: id={id}, horario={horario}")
            
        except Exception as e:
            logger.error(f"Erro ao salvar alarme: {e}")
            raise

    async def buscar_alarmes_ativos(self) -> list[dict[str, Any]]:
        """
        Busca todos os alarmes que ainda não foram disparados.
        
        Returns:
            Lista de dicionários com os dados dos alarmes ativos.
        """
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    """
                    SELECT id, horario, mensagem, criado_em
                    FROM alarmes
                    WHERE disparado = 0
                    ORDER BY horario ASC
                    """
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
                    
        except Exception as e:
            logger.error(f"Erro ao buscar alarmes ativos: {e}")
            raise

    async def marcar_disparado(self, id: str) -> None:
        """
        Marca um alarme como disparado.
        
        Args:
            id: Identificador do alarme a ser marcado.
        """
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute(
                    "UPDATE alarmes SET disparado = 1 WHERE id = ?",
                    (id,),
                )
                await conn.commit()
                
            logger.info(f"Alarme marcado como disparado: id={id}")
            
        except Exception as e:
            logger.error(f"Erro ao marcar alarme como disparado: {e}")
            raise

    async def deletar_alarme(self, id: str) -> bool:
        """
        Remove um alarme do banco de dados.
        
        Args:
            id: Identificador do alarme a ser removido.
            
        Returns:
            True se o alarme foi removido, False se não foi encontrado.
        """
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                cursor = await conn.execute(
                    "DELETE FROM alarmes WHERE id = ?",
                    (id,),
                )
                await conn.commit()
                
                removido = cursor.rowcount > 0
                
            if removido:
                logger.info(f"Alarme deletado: id={id}")
            else:
                logger.warning(f"Alarme não encontrado para deletar: id={id}")
                
            return removido
            
        except Exception as e:
            logger.error(f"Erro ao deletar alarme: {e}")
            raise

    # --- Métodos de Preferências ---

    async def set_preferencia(self, chave: str, valor: str) -> None:
        """
        Salva ou atualiza uma preferência do usuário.
        
        Args:
            chave: Chave da preferência (ex: "idioma", "voz_tts").
            valor: Valor da preferência.
        """
        try:
            atualizado_em = datetime.now().isoformat()
            
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute(
                    """
                    INSERT INTO preferencias (chave, valor, atualizado_em)
                    VALUES (?, ?, ?)
                    ON CONFLICT(chave) 
                    DO UPDATE SET valor = ?, atualizado_em = ?
                    """,
                    (chave, valor, atualizado_em, valor, atualizado_em),
                )
                await conn.commit()
                
            logger.info(f"Preferência salva: {chave}={valor}")
            
        except Exception as e:
            logger.error(f"Erro ao salvar preferência: {e}")
            raise

    async def get_preferencia(self, chave: str) -> str | None:
        """
        Recupera o valor de uma preferência.
        
        Args:
            chave: Chave da preferência a ser recuperada.
            
        Returns:
            Valor da preferência ou None se não existir.
        """
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                async with conn.execute(
                    "SELECT valor FROM preferencias WHERE chave = ?",
                    (chave,),
                ) as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else None
                    
        except Exception as e:
            logger.error(f"Erro ao buscar preferência: {e}")
            raise

    async def listar_preferencias(self) -> dict[str, str]:
        """
        Lista todas as preferências armazenadas.
        
        Returns:
            Dicionário com todas as preferências {chave: valor}.
        """
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    "SELECT chave, valor FROM preferencias ORDER BY chave"
                ) as cursor:
                    rows = await cursor.fetchall()
                    return {row["chave"]: row["valor"] for row in rows}
                    
        except Exception as e:
            logger.error(f"Erro ao listar preferências: {e}")
            raise

    async def deletar_preferencia(self, chave: str) -> bool:
        """
        Remove uma preferência do banco de dados.
        
        Args:
            chave: Chave da preferência a ser removida.
            
        Returns:
            True se a preferência foi removida, False se não foi encontrada.
        """
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                cursor = await conn.execute(
                    "DELETE FROM preferencias WHERE chave = ?",
                    (chave,),
                )
                await conn.commit()
                
                removido = cursor.rowcount > 0
                
            if removido:
                logger.info(f"Preferência deletada: {chave}")
            else:
                logger.warning(f"Preferência não encontrada para deletar: {chave}")
                
            return removido
            
        except Exception as e:
            logger.error(f"Erro ao deletar preferência: {e}")
            raise

    # --- Métodos de Histórico de Ações ---

    async def registrar_acao(
        self,
        tipo: str,
        descricao: str,
        resultado: str | None = None,
    ) -> int:
        """
        Registra uma ação executada pelo assistente.
        
        Args:
            tipo: Tipo da ação (ex: "music", "calendar", "system", "web").
            descricao: Descrição da ação realizada.
            resultado: Resultado da ação (opcional).
            
        Returns:
            ID da ação registrada.
        """
        try:
            timestamp = datetime.now().isoformat()
            
            async with aiosqlite.connect(self.db_path) as conn:
                cursor = await conn.execute(
                    """
                    INSERT INTO historico_acoes (tipo, descricao, resultado, timestamp)
                    VALUES (?, ?, ?, ?)
                    """,
                    (tipo, descricao, resultado, timestamp),
                )
                await conn.commit()
                acao_id = cursor.lastrowid
                
            logger.debug(f"Ação registrada: tipo={tipo}, id={acao_id}")
            return acao_id if acao_id else 0
            
        except Exception as e:
            logger.error(f"Erro ao registrar ação: {e}")
            raise

    async def buscar_acoes_recentes(self, limite: int = 50) -> list[dict[str, Any]]:
        """
        Busca as ações mais recentes do histórico.
        
        Args:
            limite: Número máximo de ações a retornar (padrão: 50).
            
        Returns:
            Lista de dicionários com os dados das ações.
        """
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    """
                    SELECT id, tipo, descricao, resultado, timestamp
                    FROM historico_acoes
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (limite,),
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
                    
        except Exception as e:
            logger.error(f"Erro ao buscar ações recentes: {e}")
            raise

    async def buscar_acoes_por_tipo(
        self,
        tipo: str,
        limite: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Busca ações do histórico filtradas por tipo.
        
        Args:
            tipo: Tipo de ação a filtrar.
            limite: Número máximo de ações a retornar (padrão: 50).
            
        Returns:
            Lista de dicionários com os dados das ações.
        """
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    """
                    SELECT id, tipo, descricao, resultado, timestamp
                    FROM historico_acoes
                    WHERE tipo = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (tipo, limite),
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
                    
        except Exception as e:
            logger.error(f"Erro ao buscar ações por tipo: {e}")
            raise

    async def limpar_historico_antigo(self, dias: int = 90) -> int:
        """
        Remove ações do histórico mais antigas que o número de dias especificado.
        
        Args:
            dias: Número de dias para manter no histórico (padrão: 90).
            
        Returns:
            Número de registros removidos.
        """
        try:
            from datetime import timedelta
            
            data_limite = (datetime.now() - timedelta(days=dias)).isoformat()
            
            async with aiosqlite.connect(self.db_path) as conn:
                cursor = await conn.execute(
                    "DELETE FROM historico_acoes WHERE timestamp < ?",
                    (data_limite,),
                )
                await conn.commit()
                removidos = cursor.rowcount
                
            logger.info(f"Histórico limpo: {removidos} registros removidos (>{dias} dias)")
            return removidos
            
        except Exception as e:
            logger.error(f"Erro ao limpar histórico antigo: {e}")
            raise

    async def fechar(self) -> None:
        """
        Fecha a conexão com o banco de dados.
        
        Deve ser chamado no shutdown da aplicação.
        """
        if self._conn:
            try:
                await self._conn.close()
                logger.debug("Conexão com banco de dados fechada")
            except Exception as e:
                logger.error(f"Erro ao fechar conexão com banco: {e}")


# --- Instância Global ---

db = Database()
