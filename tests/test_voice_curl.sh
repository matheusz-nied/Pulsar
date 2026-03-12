#!/bin/bash
# Script de verificação do critério de conclusão da Tarefa 2.3
# Critério: curl -X POST /voice -F "audio=@teste.wav" retorna JSON com transcrição, resposta e URL de áudio válida

set -e

echo "=== Teste do Critério de Conclusão - Tarefa 2.3 ==="
echo ""

# Arquivo de teste
AUDIO_FILE="tests/fixtures/audio_test.wav"

if [ ! -f "$AUDIO_FILE" ]; then
    echo "❌ Arquivo de teste não encontrado: $AUDIO_FILE"
    exit 1
fi

echo "📁 Arquivo de teste: $AUDIO_FILE"
echo ""

# Inicia servidor em background (se não estiver rodando)
echo "🚀 Verificando se servidor está rodando..."
if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "⚠️  Servidor não está rodando. Inicie com: python backend/main.py"
    exit 1
fi

echo "✅ Servidor está ativo"
echo ""

# Faz requisição POST
echo "📤 Enviando áudio para /voice..."
echo ""

RESPONSE=$(curl -s -X POST http://localhost:8000/voice \
    -F "audio=@$AUDIO_FILE" \
    -w "\n%{http_code}")

# Separa corpo e status code
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

echo "📊 Status HTTP: $HTTP_CODE"
echo ""

if [ "$HTTP_CODE" != "200" ]; then
    echo "❌ Erro: Status code esperado 200, recebido $HTTP_CODE"
    echo "Resposta: $BODY"
    exit 1
fi

# Valida JSON
echo "📋 Resposta JSON:"
echo "$BODY" | python -m json.tool
echo ""

# Extrai campos
TRANSCRICAO=$(echo "$BODY" | python -c "import sys, json; print(json.load(sys.stdin).get('transcricao', ''))")
RESPOSTA=$(echo "$BODY" | python -c "import sys, json; print(json.load(sys.stdin).get('resposta', ''))")
AUDIO_URL=$(echo "$BODY" | python -c "import sys, json; print(json.load(sys.stdin).get('audio_url', ''))")
SESSION_ID=$(echo "$BODY" | python -c "import sys, json; print(json.load(sys.stdin).get('session_id', ''))")

# Valida campos obrigatórios
echo "✅ Verificando campos obrigatórios..."

if [ -z "$TRANSCRICAO" ]; then
    echo "❌ Campo 'transcricao' está vazio"
    exit 1
fi
echo "   ✓ transcricao: $TRANSCRICAO"

if [ -z "$RESPOSTA" ]; then
    echo "❌ Campo 'resposta' está vazio"
    exit 1
fi
echo "   ✓ resposta: $RESPOSTA"

if [ -z "$AUDIO_URL" ]; then
    echo "❌ Campo 'audio_url' está vazio"
    exit 1
fi
echo "   ✓ audio_url: $AUDIO_URL"

if [ -z "$SESSION_ID" ]; then
    echo "❌ Campo 'session_id' está vazio"
    exit 1
fi
echo "   ✓ session_id: $SESSION_ID"

# Valida que audio_url aponta para arquivo .mp3
if [[ ! "$AUDIO_URL" =~ \.mp3$ ]]; then
    echo "❌ audio_url não termina com .mp3: $AUDIO_URL"
    exit 1
fi
echo "   ✓ audio_url termina com .mp3"

# Testa se o áudio está acessível
echo ""
echo "📥 Testando acesso ao áudio: GET $AUDIO_URL..."
AUDIO_RESPONSE=$(curl -s -w "\n%{http_code}" "http://localhost:8000$AUDIO_URL")
AUDIO_HTTP_CODE=$(echo "$AUDIO_RESPONSE" | tail -n1)

if [ "$AUDIO_HTTP_CODE" != "200" ]; then
    echo "❌ Erro ao acessar áudio: Status $AUDIO_HTTP_CODE"
    exit 1
fi

echo "✅ Áudio acessível via GET $AUDIO_URL"
echo ""

echo "🎉 CRITÉRIO DE CONCLUSÃO ATENDIDO!"
echo ""
echo "Resumo:"
echo "  - POST /voice retorna JSON válido"
echo "  - Campos obrigatórios presentes e não vazios"
echo "  - audio_url aponta para arquivo .mp3 válido"
echo "  - Áudio está acessível via GET"
