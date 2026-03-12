#!/usr/bin/env python3
"""
Script de teste manual para alarmes.
Uso: python test_alarm.py
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Adicionar raiz do projeto ao path
sys.path.insert(0, str(Path(__file__).parent))


async def main():
    from backend.tools.system import (
        cancelar_alarme,
        definir_alarme,
        iniciar_scheduler,
        listar_alarmes,
        parar_scheduler,
    )

    print("=" * 60)
    print("🧪 TESTE DE ALARMES")
    print("=" * 60)

    # Iniciar scheduler
    iniciar_scheduler()
    print("\n✅ Scheduler iniciado\n")

    # Calcular horário daqui a 1 minuto e 10 segundos
    agora = datetime.now()
    daqui_1min = agora + timedelta(seconds=70)
    horario = daqui_1min.strftime("%H:%M")
    
    # Calcular segundos até o alarme
    segundos_ate_alarme = (daqui_1min - agora).total_seconds()

    print(f"⏰ Agendando alarme para: {horario}")
    print(f"   Hora atual: {agora.strftime('%H:%M:%S')}")
    print(f"   Alarme em: ~{int(segundos_ate_alarme)} segundos\n")

    # Definir alarme
    resultado = await definir_alarme(horario, "🔔 TESTE: Este é um alarme de teste!")
    print(resultado)
    print()

    # Listar alarmes
    print("📋 Alarmes agendados:")
    lista = await listar_alarmes()
    print(lista)
    print()

    print(f"⏳ Aguardando {int(segundos_ate_alarme) + 5} segundos para o alarme disparar...")
    print("   Observe os logs abaixo:\n")

    # Aguardar o alarme disparar (tempo do alarme + 5 segundos de buffer)
    await asyncio.sleep(segundos_ate_alarme + 5)

    print("\n" + "=" * 60)
    print("✅ Teste concluído!")
    print("=" * 60)
    print("\nO alarme deveria ter disparado acima.")
    print("Verifique se você viu:")
    print("  • Log: '🔔 ALARME DISPARADO'")
    print("  • Tentativa de sintetizar áudio (pode falhar se TTS não configurado)")
    print("  • Tentativa de enviar Telegram (só funciona se configurado)")
    print()

    # Parar scheduler
    parar_scheduler()
    print("✅ Scheduler encerrado\n")


if __name__ == "__main__":
    asyncio.run(main())
