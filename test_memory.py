"""Script de teste para validar SessionMemory e PersistentMemory."""

from backend.agent.memory import session_memory, persistent_memory


def test_session_memory():
    """Testa SessionMemory: adicionar, recuperar, limpar."""
    print("\n=== Teste SessionMemory ===")
    
    session_id = "test_session_001"
    
    # Adiciona 3 mensagens
    session_memory.add_message(session_id, "user", "Olá, como você está?")
    session_memory.add_message(session_id, "assistant", "Olá! Estou bem, obrigado. Como posso ajudar?")
    session_memory.add_message(session_id, "user", "Qual é a previsão do tempo hoje?")
    
    # Recupera histórico
    history = session_memory.get_history(session_id)
    print(f"✓ Histórico recuperado: {len(history)} mensagens")
    for i, msg in enumerate(history, 1):
        print(f"  {i}. [{msg['role']}]: {msg['content'][:50]}...")
    
    # Lista sessões
    sessions = session_memory.list_sessions()
    print(f"✓ Sessões ativas: {sessions}")
    
    # Testa limite MAX_HISTORY
    print(f"\n=== Teste limite MAX_HISTORY ({session_memory.MAX_HISTORY}) ===")
    session_id_limit = "test_limit"
    for i in range(25):
        session_memory.add_message(session_id_limit, "user", f"Mensagem {i+1}")
    
    history_limit = session_memory.get_history(session_id_limit)
    print(f"✓ Adicionadas 25 mensagens, mantidas: {len(history_limit)}")
    assert len(history_limit) == session_memory.MAX_HISTORY, "Limite não aplicado!"
    
    # Limpa sessão
    session_memory.clear_session(session_id)
    history_after_clear = session_memory.get_history(session_id)
    print(f"✓ Sessão limpa: {len(history_after_clear)} mensagens restantes")
    assert len(history_after_clear) == 0, "Sessão não foi limpa!"


def test_persistent_memory():
    """Testa PersistentMemory: salvar e carregar do JSON."""
    print("\n=== Teste PersistentMemory ===")
    
    session_id = "test_persistent_001"
    
    # Cria histórico de teste
    test_history = [
        {"role": "user", "content": "Mensagem 1"},
        {"role": "assistant", "content": "Resposta 1"},
        {"role": "user", "content": "Mensagem 2"},
    ]
    
    # Salva
    persistent_memory.save(session_id, test_history)
    print(f"✓ Histórico salvo: {len(test_history)} mensagens")
    
    # Carrega
    loaded_history = persistent_memory.load(session_id)
    print(f"✓ Histórico carregado: {len(loaded_history)} mensagens")
    
    # Valida
    assert len(loaded_history) == len(test_history), "Histórico carregado diferente!"
    assert loaded_history == test_history, "Conteúdo diferente!"
    print("✓ Conteúdo validado: correspondência exata")
    
    # Testa carregamento de sessão inexistente
    empty_history = persistent_memory.load("session_inexistente")
    print(f"✓ Sessão inexistente retorna lista vazia: {len(empty_history)} itens")
    assert len(empty_history) == 0, "Deveria retornar lista vazia!"


def test_integration():
    """Testa integração: SessionMemory + PersistentMemory."""
    print("\n=== Teste Integração ===")
    
    session_id = "test_integration_001"
    
    # Adiciona mensagens via SessionMemory
    session_memory.add_message(session_id, "user", "Primeira mensagem")
    session_memory.add_message(session_id, "assistant", "Primeira resposta")
    session_memory.add_message(session_id, "user", "Segunda mensagem")
    
    # Pega histórico e salva
    history = session_memory.get_history(session_id)
    persistent_memory.save(session_id, history)
    print(f"✓ {len(history)} mensagens salvas via integração")
    
    # Limpa sessão em memória
    session_memory.clear_session(session_id)
    
    # Recarrega do disco
    reloaded = persistent_memory.load(session_id)
    print(f"✓ {len(reloaded)} mensagens recarregadas do JSON")
    
    # Restaura na SessionMemory
    for msg in reloaded:
        session_memory.add_message(session_id, msg["role"], msg["content"])
    
    final_history = session_memory.get_history(session_id)
    print(f"✓ Histórico restaurado: {len(final_history)} mensagens")
    assert final_history == reloaded, "Histórico restaurado difere!"


if __name__ == "__main__":
    print("🧪 Iniciando testes de memória...\n")
    
    try:
        test_session_memory()
        test_persistent_memory()
        test_integration()
        
        print("\n" + "="*50)
        print("✅ TODOS OS TESTES PASSARAM!")
        print("="*50)
        
    except AssertionError as e:
        print(f"\n❌ TESTE FALHOU: {e}")
    except Exception as e:
        print(f"\n❌ ERRO: {e}")
        raise
