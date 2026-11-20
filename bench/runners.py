"""De vijf varianten die dezelfde taak doen; alleen de manier waarop het model bij het bewijs komt, verschilt.

  direct   variant 0, zonder tools: het beleid, de registers en alle transacties staan in de prompt, en het model geeft
           in één antwoord het oordeel. De referentie: wat levert het ophalen met tools op, en wat kost het?
  manual   één agent, function calling met de hand: de tools staan als tekst in de prompt en het model antwoordt met
           JSON die deze code zelf ontleedt (deelvraag 1, variant A).
  native   één agent, met de tool-aanroepen van Ollama zelf (het veld "tools"). De tussenstap: zo is te zien wat het
           verschil tussen manual en mcp veroorzaakt.
  mcp      als native, maar de tools komen van een MCP-server en worden daar uitgevoerd (deelvraag 2, variant B).
  multi    twee agents: een analist die het verkeer bekijkt en bevindingen doorgeeft, en een reviewer die ze
           controleert en het oordeel geeft (deelvraag 3, variant C). Zonder framework: twee keer dezelfde lus.

Alleen de standaardbibliotheek, behalve mcp voor de variant mcp."""
import json
import os
import time
import urllib.request

from .datasets import REPORT, schema

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MAX_STEPS = 12
TASK = ("You validate Modbus/TCP traffic against a security policy. Read the policy, read ALL transactions of the case "
        "(page through them until you have seen the total), and decide whether the traffic is valid or which single rule it breaks.")
VARIANTS = ("direct", "manual", "native", "mcp", "multi")


def ollama(path, body=None, timeout=900):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(OLLAMA_URL + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


class Stats(dict):
    """Wat één run kostte, opgeteld over alle aanroepen van het model."""

    def __init__(self):
        super().__init__(llm_calls=0, tool_calls=0, invalid_calls=0, prompt_tokens=0, output_tokens=0, eval_seconds=0.0, llm_seconds=0.0,
                         policy_seen=False, transactions_seen=0, transactions_total=None, register_calls=0)

    def add(self, response, seconds):
        self["llm_calls"] += 1
        self["llm_seconds"] += seconds
        self["prompt_tokens"] += response.get("prompt_eval_count") or 0
        self["output_tokens"] += response.get("eval_count") or 0
        self["eval_seconds"] += (response.get("eval_duration") or 0) / 1e9


def _track_evidence(stats, name, arguments, result, ok):
    """Hield het model genoeg bewijs op voordat het oordeelde? Alleen tellen, geen aanroep tegenhouden."""
    if not ok:
        return
    if name == "get_policy":
        stats["policy_seen"] = True
    elif name == "get_transactions" and isinstance(result, dict):
        start = arguments.get("start", 0) if isinstance(arguments, dict) else 0
        stats["transactions_seen"] = max(stats["transactions_seen"], start + len(result.get("transactions") or []))
        if "total" in result:
            stats["transactions_total"] = result["total"]
    elif "register" in name:
        stats["register_calls"] += 1


def _evidence_complete(stats):
    """None: deze variant gebruikte geen tools (direct). Anders: beleid gezien en alle transacties opgehaald."""
    if stats["transactions_total"] is None:
        return None
    return stats["policy_seen"] and stats["transactions_seen"] >= stats["transactions_total"]


def _missing_evidence(stats):
    """None: genoeg bewijs om te oordelen. Anders een zin voor het model over wat nog moet, in plaats van het oordeel
    zomaar te accepteren (bleek bij een eerdere meting bijna nooit compleet: 0-5% van de runs)."""
    if not stats["policy_seen"]:
        return "You have not called get_policy yet. Call it before you give your answer."
    if stats["transactions_total"] is None:
        return "You have not called get_transactions yet. Call it before you give your answer."
    if stats["transactions_seen"] < stats["transactions_total"]:
        return (f"You have only seen {stats['transactions_seen']} of {stats['transactions_total']} transactions. "
                "Call get_transactions again with a higher start before you give your answer.")
    if stats["register_calls"] < 1:
        return "You have not checked a register map or register info yet. Call that tool before you give your answer."
    return None


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

    def __init__(self, dataset, case):
        self.dataset, self.case = dataset, case

    def specs(self):
        return [schema(t) for t in self.dataset.tools()]

    def call(self, name, arguments):
        return self.dataset.call(self.case, name, arguments)


def _finish_or_call(stats, toolbox, name, arguments, final):
    """Verwerkt één tool-aanroep met geldige argumenten (een dict); gedeeld door manual_loop en native_loop.

    (True, None, de argumenten) als het de laatste tool was en er genoeg bewijs is. Anders (False, is_result, tekst):
    is_result zegt of tekst een echte tool-uitkomst is (manual zet er dan "TOOL RESULT: " voor) of een duwtje omdat
    er nog bewijs ontbreekt."""
    if name == final["name"]:
        missing = _missing_evidence(stats)
        if missing:
            stats["invalid_calls"] += 1
            return False, False, missing
        return True, None, arguments
    result, ok = toolbox.call(name, arguments)
    stats["invalid_calls"] += 0 if ok else 1
    _track_evidence(stats, name, arguments, result, ok)
    return False, True, json.dumps(result)


def _verdict(reply, dataset):
    verdict = reply.get("verdict") if isinstance(reply, dict) else None
    return verdict if verdict in dataset.verdicts else None


def _reason(reply):
    reason = reply.get("reason") if isinstance(reply, dict) else None
    return reason[:300] if isinstance(reason, str) else None


def _confidence(reply):
    confidence = reply.get("confidence") if isinstance(reply, dict) else None
    return confidence if confidence in ("low", "medium", "high") else None


def direct(model, dataset, case, stats, options):
    """Variant 0: geen tools, alles in de prompt, één antwoord."""
    verdicts = ", ".join(dataset.verdicts)
    messages = [{"role": "system", "content": "You validate Modbus/TCP traffic against a security policy. All evidence is below. "
                 f'Reply with one JSON object and nothing else: {{"verdict": "<one of: {verdicts}>", "reason": "<one sentence>"}}.'},
                {"role": "user", "content": f"Validate {case['id']}.\n\n" + json.dumps(dataset.evidence(case))}]
    content = chat(model, messages, stats, options, json_mode=True).get("content", "")
    try:
        reply = json.loads(content)
    except ValueError:
        stats["invalid_calls"] += 1
        return None
    if _verdict(reply, dataset) is None:
        stats["invalid_calls"] += 1
    return reply


def manual_loop(model, toolbox, final, stats, options, system, user):
    """Function calling met de hand: de tools als tekst, het antwoord als JSON die wij zelf ontleden."""
    listing = json.dumps([s["function"] for s in toolbox.specs()] + [schema(final)["function"]], indent=1)
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
        done, is_result, text = _finish_or_call(stats, toolbox, name, arguments, final)
        if done:
            return text
        messages.append({"role": "user", "content": ("TOOL RESULT: " + text) if is_result else text})
    return None


def native_loop(model, toolbox, final, stats, options, system, user):
    """De tool-aanroepen van Ollama zelf: het model krijgt de schema's en antwoordt met tool_calls."""
    tools = toolbox.specs() + [schema(final)]
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
            if not isinstance(arguments, dict):
                stats["invalid_calls"] += 1
                messages.append({"role": "tool", "tool_name": name or "", "content": json.dumps({"error": "arguments must be an object"})})
                continue
            done, _, text = _finish_or_call(stats, toolbox, name, arguments, final)
            if done:
                return text
            messages.append({"role": "tool", "tool_name": name or "", "content": text})
    return None


def run_case(variant, model, dataset, case, options, mcp_bridge=None):
    """Eén case in één variant. Geeft het oordeel van het model (of None) en wat het kostte."""
    stats, submit = Stats(), dataset.submit()
    user = f"Validate {case['id']}."
    if variant == "direct":
        answer = direct(model, dataset, case, stats, options)
    elif variant == "manual":
        answer = manual_loop(model, LocalTools(dataset, case), submit, stats, options, TASK, user)
    elif variant == "native":
        answer = native_loop(model, LocalTools(dataset, case), submit, stats, options, TASK, user)
    elif variant == "mcp":
        answer = native_loop(model, mcp_bridge.for_case(case), submit, stats, options, TASK, user)
    elif variant == "multi":
        findings = native_loop(model, LocalTools(dataset, case), REPORT, stats, options,
                               TASK + " You are the analyst: you do not give the verdict, you report what you found.", user)
        handed = (findings or {}).get("findings") or "The analyst gave no findings."
        answer = native_loop(model, LocalTools(dataset, case), submit, stats, options,
                             TASK + " You are the reviewer: an analyst looked at this case first. Check the analyst's findings "
                             "against the policy and the transactions before you decide; the analyst can be wrong.",
                             f"{user}\n\nFindings of the analyst:\n{handed}")
    else:
        raise ValueError(f"onbekende variant {variant!r}")
    stats["evidence_complete"] = _evidence_complete(stats)
    return _verdict(answer, dataset), _reason(answer), _confidence(answer), stats
