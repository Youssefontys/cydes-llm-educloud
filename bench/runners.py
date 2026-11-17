"""De vier varianten die dezelfde taak met dezelfde tools doen; alleen de manier van aanroepen verschilt.

  manual   één agent, function calling met de hand: de tools staan als tekst in de prompt en het model antwoordt met
           JSON die deze code zelf ontleedt (deelvraag 1).
  native   één agent, met de tool-aanroepen van Ollama zelf (het veld "tools"). De tussenstap: zo is te zien wat het
           verschil tussen manual en mcp veroorzaakt.
  mcp      als native, maar de tools komen van een MCP-server en worden daar uitgevoerd (deelvraag 2).
  multi    twee agents: een analist die het verkeer bekijkt en bevindingen doorgeeft, en een reviewer die ze
           controleert en het oordeel geeft (deelvraag 3). Zonder framework: twee keer dezelfde lus.

Alleen de standaardbibliotheek, behalve mcp voor de variant mcp."""
import json
import os
import time
import urllib.error
import urllib.request

from . import modbus

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MAX_STEPS = 12
TASK = ("You validate Modbus/TCP traffic against a security policy. Read the policy, read ALL transactions of the case "
        "(page through them until you have seen the total), and decide whether the traffic is valid or which single rule it breaks.")


def ollama(path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(OLLAMA_URL + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


class Stats(dict):
    """Wat één run kostte, opgeteld over alle aanroepen van het model."""

    def __init__(self):
        super().__init__(llm_calls=0, tool_calls=0, invalid_calls=0, prompt_tokens=0, output_tokens=0, eval_seconds=0.0, llm_seconds=0.0)

    def add(self, response, seconds):
        self["llm_calls"] += 1
        self["llm_seconds"] += seconds
        self["prompt_tokens"] += response.get("prompt_eval_count") or 0
        self["output_tokens"] += response.get("eval_count") or 0
        self["eval_seconds"] += (response.get("eval_duration") or 0) / 1e9


def chat(model, messages, stats, options, tools=None, json_mode=False):
    body = {"model": model, "messages": messages, "stream": False, "options": options}
    if tools:
        body["tools"] = tools
    if json_mode:
        body["format"] = "json"
    started = time.monotonic()
    response = ollama("/api/chat", body)
    stats.add(response, time.monotonic() - started)
    return response.get("message") or {}


class LocalTools:
    """De tools als gewone functies in dit proces."""

    def __init__(self, case):
        self.case = case

    def specs(self):
        return [modbus.schema(t) for t in modbus.TOOLS]

    def call(self, name, arguments):
        return modbus.call_tool(self.case, name, arguments)


def manual_loop(model, toolbox, final, stats, options, system, user):
    """Function calling met de hand: de tools als tekst, het antwoord als JSON die wij zelf ontleden."""
    listing = json.dumps([s["function"] for s in toolbox.specs()] + [modbus.schema(final)["function"]], indent=1)
    messages = [{"role": "system", "content": f"{system}\n\nYou have these tools:\n{listing}\n\nReply with exactly one JSON object and "
                 'nothing else: {"tool": "<name>", "arguments": {...}}. Call one tool per reply. Finish with the tool ' + final["name"] + "."},
                {"role": "user", "content": user}]
    for _ in range(MAX_STEPS):
        content = chat(model, messages, stats, options, json_mode=True).get("content", "")
        messages.append({"role": "assistant", "content": content})
        try:
            reply = json.loads(content)
            name, arguments = reply["tool"], reply.get("arguments") or {}
            if not isinstance(name, str) or not isinstance(arguments, dict):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            stats["invalid_calls"] += 1
            messages.append({"role": "user", "content": 'That was not valid. Reply with one JSON object: {"tool": "<name>", "arguments": {...}}.'})
            continue
        stats["tool_calls"] += 1
        if name == final["name"]:
            return arguments
        result, ok = toolbox.call(name, arguments)
        stats["invalid_calls"] += 0 if ok else 1
        messages.append({"role": "user", "content": "TOOL RESULT: " + json.dumps(result)})
    return None


def native_loop(model, toolbox, final, stats, options, system, user):
    """De tool-aanroepen van Ollama zelf: het model krijgt de schema's en antwoordt met tool_calls."""
    tools = toolbox.specs() + [modbus.schema(final)]
    messages = [{"role": "system", "content": f"{system} Use the tools. Call one tool at a time. Finish by calling {final['name']}."},
                {"role": "user", "content": user}]
    for _ in range(MAX_STEPS):
        message = chat(model, messages, stats, options, tools=tools)
        messages.append(message)
        calls = message.get("tool_calls") or []
        if not calls:
            stats["invalid_calls"] += 1
            messages.append({"role": "user", "content": f"You did not call a tool. Call a tool, or finish with {final['name']}."})
            continue
        for call in calls:
            function = call.get("function") or {}
            name, arguments = function.get("name"), function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = None
            stats["tool_calls"] += 1
            if name == final["name"] and isinstance(arguments, dict):
                return arguments
            result, ok = toolbox.call(name, arguments if isinstance(arguments, dict) else {}) if isinstance(arguments, dict) else ({"error": "arguments must be an object"}, False)
            stats["invalid_calls"] += 0 if ok else 1
            messages.append({"role": "tool", "tool_name": name or "", "content": json.dumps(result)})
    return None


def run_case(variant, model, case, options, mcp_bridge=None):
    """Eén case in één variant. Geeft het oordeel van het model (of None) en wat het kostte."""
    stats = Stats()
    user = f"Validate {case['id']}."
    if variant == "manual":
        answer = manual_loop(model, LocalTools(case), modbus.SUBMIT, stats, options, TASK, user)
    elif variant == "native":
        answer = native_loop(model, LocalTools(case), modbus.SUBMIT, stats, options, TASK, user)
    elif variant == "mcp":
        answer = native_loop(model, mcp_bridge.for_case(case), modbus.SUBMIT, stats, options, TASK, user)
    elif variant == "multi":
        findings = native_loop(model, LocalTools(case), modbus.REPORT, stats, options,
                               TASK + " You are the analyst: you do not give the verdict, you report what you found.", user)
        handed = (findings or {}).get("findings") or "The analyst gave no findings."
        answer = native_loop(model, LocalTools(case), modbus.SUBMIT, stats, options,
                             TASK + " You are the reviewer: an analyst looked at this case first. Check the analyst's findings "
                             "against the policy and the transactions before you decide; the analyst can be wrong.",
                             f"{user}\n\nFindings of the analyst:\n{handed}")
    else:
        raise ValueError(f"onbekende variant {variant!r}")
    verdict = (answer or {}).get("verdict")
    return (verdict if isinstance(verdict, str) else None), stats
