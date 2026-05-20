#!/usr/bin/env python3
import os, sys, json, argparse, logging
from datetime import datetime
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown

load_dotenv()
console = Console()
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    console.print("[red]❌ GROQ_API_KEY not found in .env[/red]")
    sys.exit(1)

from ceo_brain       import CEOBrain
from marketing_agent import MarketingAgent
from finance_agent   import FinanceAgent
from risk_agent      import RiskAgent
from short_term      import ShortTermMemory
from long_term       import LongTermMemory
from State           import AgentState


def run_health_check():
    console.rule("[bold teal]Health Check[/bold teal]")
    table = Table(show_header=True, show_lines=True)
    table.add_column("Agent",  style="cyan",  width=20)
    table.add_column("Status", style="green", width=12)
    table.add_column("Model",  style="white", width=25)
    agents = {
        "CEOBrain":       CEOBrain(api_key=GROQ_API_KEY),
        "MarketingAgent": MarketingAgent(api_key=GROQ_API_KEY),
        "FinanceAgent":   FinanceAgent(api_key=GROQ_API_KEY),
        "RiskAgent":      RiskAgent(api_key=GROQ_API_KEY),
    }
    for name, agent in agents.items():
        ok = agent.health_check()
        table.add_row(name, "✅ OK" if ok else "❌ FAIL", agent.model)
    lt = LongTermMemory()
    table.add_row("LongTermMemory", lt.status(), "ChromaDB")
    console.print(table)
    console.print("\n[green]✅ Health check complete![/green]\n")


def run_pipeline(user_input: str, company_context: str = "") -> dict:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    console.rule(f"[teal]Run {run_id}[/teal]")
    console.print(f"[dim]Idea: {user_input}[/dim]\n")

    state: AgentState = {
        "user_input": user_input, "company_context": company_context,
        "run_id": run_id, "timestamp": datetime.now().isoformat(),
        "research_output": "", "ceo_direction": "",
        "marketing_output": "", "finance_output": "",
        "risk_output": "", "final_output": "",
        "errors": [], "agent_log": [],
    }

    steps = [
        ("📊  Research",  _run_research),
        ("📣  Marketing", _run_marketing),
        ("💰  Finance",   _run_finance),
        ("⚠️   Risk",     _run_risk),
        ("👔  CEO",       _run_ceo),
    ]
    for label, fn in steps:
        with console.status(f"[teal]{label} thinking...[/teal]", spinner="dots"):
            state = fn(state)
        icon = "✅" if not state["errors"] else "⚠️"
        console.print(f"  {icon} {label} done")
    return state


def _run_research(state):
    try:
        r = CEOBrain(api_key=GROQ_API_KEY).think(
            f"Research this business idea: {state['user_input']}\n"
            "Cover: market size, target audience, top 3 competitors, opportunity."
        )
        log = list(state["agent_log"])
        log.append({"agent":"Research","timestamp":datetime.now().isoformat(),"status":"success","output_length":len(r.raw)})
        return {**state, "research_output": r.raw, "ceo_direction": r.recommendation or "", "agent_log": log}
    except Exception as exc:
        errors = list(state["errors"]); errors.append(f"Research: {exc}")
        return {**state, "errors": errors}

def _run_marketing(state):
    try:
        result = MarketingAgent(api_key=GROQ_API_KEY).run(state["user_input"], state["research_output"], state["ceo_direction"])
        log = list(state["agent_log"])
        log.append({"agent":"Marketing","timestamp":datetime.now().isoformat(),"status":"success","output_length":len(result.raw)})
        return {**state, "marketing_output": result.raw, "agent_log": log}
    except Exception as exc:
        errors = list(state["errors"]); errors.append(f"Marketing: {exc}")
        return {**state, "errors": errors}

def _run_finance(state):
    try:
        result = FinanceAgent(api_key=GROQ_API_KEY).run(state["user_input"], state["research_output"], state["marketing_output"])
        log = list(state["agent_log"])
        log.append({"agent":"Finance","timestamp":datetime.now().isoformat(),"status":"success","output_length":len(result.raw)})
        return {**state, "finance_output": result.raw, "agent_log": log}
    except Exception as exc:
        errors = list(state["errors"]); errors.append(f"Finance: {exc}")
        return {**state, "errors": errors}

def _run_risk(state):
    try:
        result = RiskAgent(api_key=GROQ_API_KEY).run(state["user_input"], state["research_output"], state["marketing_output"], state["finance_output"])
        log = list(state["agent_log"])
        log.append({"agent":"Risk","timestamp":datetime.now().isoformat(),"status":"success","output_length":len(result.raw)})
        return {**state, "risk_output": result.raw, "agent_log": log}
    except Exception as exc:
        errors = list(state["errors"]); errors.append(f"Risk: {exc}")
        return {**state, "errors": errors}

def _run_ceo(state):
    try:
        result = CEOBrain(api_key=GROQ_API_KEY).think(
            f"Synthesise all reports into final executive decision.\n\n"
            f"Request: {state['user_input']}\n"
            f"Research:\n{state['research_output'][:500]}\n"
            f"Marketing:\n{state['marketing_output'][:500]}\n"
            f"Finance:\n{state['finance_output'][:500]}\n"
            f"Risk:\n{state['risk_output'][:500]}"
        )
        log = list(state["agent_log"])
        log.append({"agent":"CEO","timestamp":datetime.now().isoformat(),"status":"success","output_length":len(result.raw)})
        return {**state, "final_output": result.raw, "agent_log": log}
    except Exception as exc:
        errors = list(state["errors"]); errors.append(f"CEO: {exc}")
        return {**state, "errors": errors}


def render_output(state: dict):
    table = Table(title="Agent Execution Log", show_lines=True)
    table.add_column("Agent",  style="cyan",  width=16)
    table.add_column("Status", style="green", width=10)
    table.add_column("Output", style="white", width=14)
    for log in state.get("agent_log", []):
        table.add_row(log["agent"], "✅ OK", f"{log.get('output_length',0):,} chars")
    console.print(table)

    for title, content, color in [
        ("Research",     state.get("research_output",""),  "blue"),
        ("Marketing",    state.get("marketing_output",""), "magenta"),
        ("Finance",      state.get("finance_output",""),   "yellow"),
        ("Risk",         state.get("risk_output",""),      "red"),
        ("CEO Decision", state.get("final_output",""),     "bold green"),
    ]:
        if content:
            console.print(Panel(Markdown(content), title=f"[{color}]{title}[/{color}]", border_style=color, padding=(1,2)))

    filename = f"run_{state.get('run_id','run')}.json"
    with open(filename, "w") as f:
        json.dump(state, f, indent=2)
    console.print(f"\n[dim]✅ Saved → {filename}[/dim]\n")


def interactive_cli():
    console.rule("[bold teal]CEO Agent SaaS — Multi-Agent System[/bold teal]")
    console.print("[dim]Research → Marketing → Finance → Risk → CEO[/dim]\n")
    short_mem = ShortTermMemory()
    long_mem  = LongTermMemory()
    console.print(f"[dim]Memory: {long_mem.status()}[/dim]\n")

    while True:
        try:
            user_input = input("💡 Business idea: ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not user_input: continue
        if user_input.lower() in ("exit", "quit", "/exit"): break

        context = input("🏢 Company context (Enter to skip): ").strip()
        state   = run_pipeline(user_input, context)
        render_output(state)
        short_mem.add("human", user_input)
        short_mem.add("ai", state.get("final_output",""))
        long_mem.save_goal(user_input)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--idea",    type=str)
    parser.add_argument("--context", type=str, default="")
    parser.add_argument("--health",  action="store_true")
    parser.add_argument("--test",    action="store_true")
    args = parser.parse_args()

    if args.health:
        run_health_check()
    elif args.test:
        import subprocess; subprocess.run(["pytest", "test_ceo_brain.py", "-v"])
    elif args.idea:
        render_output(run_pipeline(args.idea, args.context))
    else:
        interactive_cli()