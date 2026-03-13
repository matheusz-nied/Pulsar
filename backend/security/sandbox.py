"""
sandbox.py — Sandboxing e confirmação verbal para ações críticas.

Responsável por:
- Identificar ações que requerem confirmação do usuário
- Gerenciar tokens de confirmação com expiração de 30 segundos
- Bloquear execução de ações destrutivas sem aprovação explícita
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from loguru import logger

ACOES_CRITICAS = ["fechar_app", "deletar_arquivo", "desligar_pc", "reiniciar_pc"]

DESCRICOES_ACOES: dict[str, str] = {
    "fechar_app": "fechar aplicativo",
    "deletar_arquivo": "deletar arquivo",
    "desligar_pc": "desligar o computador",
    "reiniciar_pc": "reiniciar o computador",
}

EXPIRACAO_SEGUNDOS = 30


class SecurityManager:
    """Gerencia confirmações de segurança para ações críticas do sistema."""

    def __init__(self) -> None:
        self.confirmacoes_pendentes: dict[str, dict[str, Any]] = {}

    def requer_confirmacao(self, acao: str, params: dict[str, Any]) -> str:
        """
        Registra uma ação crítica pendente e retorna mensagem de confirmação.

        Args:
            acao: Nome da tool crítica (ex: "fechar_app").
            params: Parâmetros originais da chamada da tool.

        Returns:
            Mensagem pedindo confirmação ao usuário com token parcial.
        """
        token = uuid.uuid4().hex
        expira_em = datetime.now() + timedelta(seconds=EXPIRACAO_SEGUNDOS)

        self.confirmacoes_pendentes[token] = {
            "acao": acao,
            "params": params,
            "expira_em": expira_em,
        }

        descricao = DESCRICOES_ACOES.get(acao, acao)
        detalhes = ", ".join(f"{k}={v}" for k, v in params.items()) if params else ""
        if detalhes:
            descricao = f"{descricao} ({detalhes})"

        logger.info(f"Confirmação requerida para '{acao}' — token: {token[:4]}...")

        return (
            f"⚠️ Ação crítica: {descricao}. "
            f"Confirme dizendo 'confirmar {token[:4]}' ou 'cancelar'."
        )

    def confirmar(self, token_parcial: str) -> tuple[bool, dict[str, Any] | None]:
        """
        Confirma uma ação pendente pelo prefixo do token.

        Args:
            token_parcial: Primeiros 4 caracteres do token de confirmação.

        Returns:
            Tupla (sucesso, dados_da_acao) — dados contêm "acao" e "params".
        """
        self._limpar_expirados()

        token_parcial = token_parcial.strip().lower()

        for token, dados in list(self.confirmacoes_pendentes.items()):
            if token.startswith(token_parcial):
                if datetime.now() > dados["expira_em"]:
                    del self.confirmacoes_pendentes[token]
                    logger.warning(f"Token {token[:4]} expirado")
                    return False, None

                resultado = {
                    "acao": dados["acao"],
                    "params": dados["params"],
                }
                del self.confirmacoes_pendentes[token]
                logger.info(f"Ação confirmada: {dados['acao']} via token {token[:4]}")
                return True, resultado

        logger.warning(f"Token parcial '{token_parcial}' não encontrado")
        return False, None

    def cancelar_todas(self) -> int:
        """
        Cancela todas as ações pendentes.

        Returns:
            Quantidade de ações que foram canceladas.
        """
        count = len(self.confirmacoes_pendentes)
        self.confirmacoes_pendentes.clear()
        if count:
            logger.info(f"{count} ação(ões) pendente(s) cancelada(s)")
        return count

    def is_critica(self, nome_tool: str) -> bool:
        """Verifica se a tool está na lista de ações críticas."""
        return nome_tool in ACOES_CRITICAS

    def tem_pendentes(self) -> bool:
        """Verifica se há ações pendentes (não expiradas)."""
        self._limpar_expirados()
        return bool(self.confirmacoes_pendentes)

    def _limpar_expirados(self) -> None:
        """Remove tokens expirados do dicionário de pendentes."""
        agora = datetime.now()
        expirados = [
            token
            for token, dados in self.confirmacoes_pendentes.items()
            if agora > dados["expira_em"]
        ]
        for token in expirados:
            del self.confirmacoes_pendentes[token]
        if expirados:
            logger.debug(f"{len(expirados)} token(s) expirado(s) removido(s)")


security_manager = SecurityManager()
