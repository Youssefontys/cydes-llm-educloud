"""Minimale multi-agent-demo: twee CrewAI-agents (onderzoeker, schrijver) die samenwerken,
allebei op het lokale, CPU-only Ollama-model. Status: voorbeeld, nog niet getest tegen een
echte CrewAI-installatie op deze VM. Bedoeld als startpunt, niet als afgerond product.

Gebruik (op de VM, in de venv die bootstrap-openllm.sh aanmaakt):
    python3 multi_agent_demo.py "een onderwerp naar keuze"
"""
import os
import sys

from crewai import LLM, Agent, Crew, Task

MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
llm = LLM(model=f"ollama/{MODEL}", base_url="http://127.0.0.1:11434")

researcher = Agent(
    role="Onderzoeker",
    goal="Vind beknopte, correcte feiten over het gegeven onderwerp",
    backstory="Een zorgvuldige onderzoeker die nooit feiten verzint.",
    llm=llm,
)

writer = Agent(
    role="Schrijver",
    goal="Maak van het onderzoek een korte, duidelijke paragraaf",
    backstory="Een schrijver die het kort en simpel houdt.",
    llm=llm,
)

research_task = Task(
    description="Zoek feiten over: {topic}",
    expected_output="3 bullet points met feiten",
    agent=researcher,
)

writing_task = Task(
    description="Schrijf een korte paragraaf op basis van het onderzoek",
    expected_output="Een paragraaf, maximaal 5 zinnen",
    agent=writer,
    context=[research_task],
)

crew = Crew(agents=[researcher, writer], tasks=[research_task, writing_task])

if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "Apache CloudStack"
    result = crew.kickoff(inputs={"topic": topic})
    print(result)
