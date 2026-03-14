import time
import os
from dotenv import load_dotenv
from openai import OpenAI
import anthropic

load_dotenv()

PROMPT = "Explique em uma frase o que é computação em nuvem."
RUNS = 5

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

deepseek_client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

anthropic_client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

openai_model_1 = "gpt-5-nano"
openai_model_2 = "gpt-5-mini"
deepseek_model = "deepseek-chat"
claude_model = "claude-haiku-4-5"


def test_openai(model):
    start = time.time()

    r = openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": PROMPT}
        ],
        max_completion_tokens=500
    )

    end = time.time()

    text = r.choices[0].message.content

    return end - start, text


def test_deepseek(model):
    start = time.time()

    r = deepseek_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": PROMPT}
        ],
        max_tokens=500
    )

    end = time.time()

    text = r.choices[0].message.content

    return end - start, text


def test_claude(model):
    start = time.time()

    r = anthropic_client.messages.create(
        model=model,
        max_tokens=500,
        messages=[
            {"role": "user", "content": PROMPT}
        ]
    )

    end = time.time()

    text = r.content[0].text

    return end - start, text


def benchmark(name, func, model):
    times = []
    responses = []

    for i in range(RUNS):
        try:
            t, text = func(model)
            times.append(t)
            responses.append(text)

        except Exception as e:
            print(f"Erro em {name}: {e}")
            return None

    avg = sum(times) / len(times)

    print(f"\n{name}")
    print("tempos:", [round(t,2) for t in times])
    print("media:", round(avg,2), "s")

    print("\nRespostas completas por execução:")
    for i, response in enumerate(responses, 1):
        print(f"\nRun {i}:")
        print(response)

    print("\n----------------------------")

    return avg


print("\n===== INICIANDO BENCHMARK =====\n")

results = {}

results[openai_model_1] = benchmark("OpenAI #1", test_openai, openai_model_1)
results[openai_model_2] = benchmark("OpenAI #2", test_openai, openai_model_2)
results[deepseek_model] = benchmark("DeepSeek", test_deepseek, deepseek_model)
results[claude_model] = benchmark("Claude", test_claude, claude_model)


print("\n===== RANKING POR VELOCIDADE =====\n")

sorted_results = sorted(
    [(k, v) for k, v in results.items() if v is not None],
    key=lambda x: x[1]
)

for i, (model, time_avg) in enumerate(sorted_results, 1):
    print(f"{i}. {model} -> {round(time_avg,2)} s")