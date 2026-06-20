"""Run a bench task against an agent implementation: rollout(s) + grading + report.

    peico-eval TASK --agent module:make_agent           # one trial
    peico-eval TASK --agent module:make_agent -k 5 -v   # five trials, verbose

TASK is a path to a task YAML, or a bare task id resolved under the bench's
``tasks/`` directory. ``--agent`` is the import path of a factory
``(Environment) -> AgentClient`` the bench calls to build the agent — the only
place the agent is named, resolved at runtime so the bench never statically
depends on any agent.

Each trial gets a fresh isolated world (World.from_seed), applies the task setup,
snapshots the baseline, runs the rollout, snapshots the final state, and grades
the two gates. Reports pass^k across customer-simulator seeds.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

from . import changeset as cs
from .checks import GradeContext, build_check
from .config import settings
from .environment import Environment
from .llm import Model
from .orchestrator import run_rollout
from .task import load_task
from .world import World

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


@dataclass
class TrialResult:
    passed: bool
    verdicts: list
    rollout: object


def _resolve_agent_factory(spec: str):
    """Import a factory from ``module:function`` (or ``module.function``)."""
    if ":" in spec:
        mod_name, _, fn_name = spec.partition(":")
    else:
        mod_name, _, fn_name = spec.rpartition(".")
    if not mod_name or not fn_name:
        raise SystemExit(f"--agent must be 'module:function', got {spec!r}")
    try:
        mod = importlib.import_module(mod_name)
    except ImportError as exc:
        raise SystemExit(
            f"could not import agent module {mod_name!r}: {exc}\n"
            f"Is the agent installed in this environment?"
        )
    try:
        return getattr(mod, fn_name)
    except AttributeError:
        raise SystemExit(f"{mod_name!r} has no attribute {fn_name!r}")


def _resolve_task_path(arg: str) -> Path:
    p = Path(arg)
    if p.exists():
        return p
    for cand in (settings.tasks_dir / arg, settings.tasks_dir / f"{arg}.yaml"):
        if cand.exists():
            return cand
    raise SystemExit(f"task not found: {arg} (looked in {settings.tasks_dir})")


def _snapshot(world) -> dict:
    con = world.connect(writable=False)
    try:
        return cs.snapshot(con)
    finally:
        con.close()


def _apply_setup(world, setup) -> None:
    if not setup:
        return
    con = world.connect(writable=True)
    try:
        for stmt in setup:
            con.execute(stmt)
        con.commit()
    finally:
        con.close()


def run_trial(task, make_agent, *, sim_model, judge_model, verbose=False) -> TrialResult:
    world = World.from_seed()
    try:
        _apply_setup(world, task.setup)
        baseline = _snapshot(world)
        env = Environment(world)

        def on_event(role, text):
            if verbose:
                who = f"{DIM}customer{RESET}" if role == "customer" else "rep"
                print(f"  {who}> {text}")

        rollout = run_rollout(task, env, make_agent, sim_model, on_event=on_event)
        final = _snapshot(world)

        ctx = GradeContext(
            task=task, transcript=rollout.transcript,
            baseline=baseline, final=final, judge_model=judge_model,
        )
        verdicts = [build_check(spec).run(ctx) for spec in task.checks]
        checks_pass = all(v.passed for v in verdicts if v.required)
        # A task passes only if the required checks pass AND the agent terminated.
        passed = checks_pass and rollout.completed
        return TrialResult(passed, verdicts, rollout)
    finally:
        world.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="peico-eval", description="Run a PEICO bench task against an agent")
    parser.add_argument("task", help="path to a task YAML, or a task id under tasks/")
    parser.add_argument("--agent", required=True, help="agent factory import path, e.g. peico_agent.adapter:make_agent")
    parser.add_argument("--trials", "-k", type=int, default=1, help="number of trials (pass^k)")
    parser.add_argument("--sim-model", help="user-simulator model override")
    parser.add_argument("--judge-model", help="judge model override")
    parser.add_argument("--verbose", "-v", action="store_true", help="print the transcript")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    settings.require_world()
    task = load_task(_resolve_task_path(args.task))
    make_agent = _resolve_agent_factory(args.agent)

    sim_model = Model(args.sim_model or settings.sim_model)
    judge_model = Model(args.judge_model or settings.judge_model)

    print(f"Task: {task.task_id}  |  persona: {task.persona.name}  |  trials: {args.trials}")
    print(f"agent={args.agent}  sim={sim_model.name}  judge={judge_model.name}\n")

    results: list[TrialResult] = []
    for i in range(args.trials):
        if args.verbose:
            print(f"{DIM}--- trial {i + 1}/{args.trials} ---{RESET}")
        r = run_trial(
            task, make_agent, sim_model=sim_model,
            judge_model=judge_model, verbose=args.verbose,
        )
        results.append(r)
        tag = f"{GREEN}PASS{RESET}" if r.passed else f"{RED}FAIL{RESET}"
        done = "completed" if r.rollout.completed else f"{RED}incomplete{RESET}"
        print(f"\nTrial {i + 1}: {tag}  ({r.rollout.turns} msgs, {done}, stop={r.rollout.stopped_reason})")
        for v in r.verdicts:
            mark = f"{GREEN}ok{RESET}" if v.passed else f"{RED}XX{RESET}"
            flag = " (stochastic)" if v.stochastic else ""
            req = "" if v.required else " (advisory)"
            print(f"  [{mark}] {v.name}{flag}{req}: {v.detail}")
        print()

    passed = sum(1 for r in results if r.passed)
    print(f"=== {task.task_id}: pass^{args.trials} = {passed}/{args.trials} ===")
    print(f"{DIM}sim:   {sim_model.usage}{RESET}")
    print(f"{DIM}judge: {judge_model.usage}{RESET}")
    return 0 if passed == args.trials else 1


if __name__ == "__main__":
    raise SystemExit(main())
