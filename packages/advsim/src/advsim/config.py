"""Simulation configuration: profiles, lifecycles, data-quality noise and database URLs."""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from advgen.build import ROOT

CONFIG = ROOT / "config" / "advsim"
MANIFEST = ROOT / "models" / "physical" / "manifest.json"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Cfg(dict):
    """Nested dict with dotted-path lookup: cfg.get_path('delivery.ctr.display', 0.001)."""

    def get_path(self, path: str, default=None):
        cur = self
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur


@dataclass
class Settings:
    profile_name: str
    profile: Cfg
    lifecycles: dict
    dq: Cfg
    column_rules: dict
    urls: dict[str, str] = field(default_factory=dict)


def load_settings(profile: str, dq_overrides: dict | None = None) -> Settings:
    base = load_yaml(CONFIG / "profiles" / "base.yaml")
    path = CONFIG / "profiles" / f"{profile}.yaml"
    if not path.exists():
        names = sorted(p.stem for p in (CONFIG / "profiles").glob("*.yaml") if p.stem != "base")
        raise SystemExit(f"unknown profile {profile!r}; available: {', '.join(names)}")
    prof = Cfg(deep_merge(base, load_yaml(path)))
    dq = Cfg(deep_merge(load_yaml(CONFIG / "dq.yaml"), prof.get("dq") or {}))
    if dq_overrides:
        dq = Cfg(deep_merge(dq, dq_overrides))
    return Settings(profile, prof, load_yaml(CONFIG / "lifecycles.yaml"), dq,
                    load_yaml(CONFIG / "column_rules.yaml"), database_urls())


def read_dotenv() -> dict[str, str]:
    env = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def database_urls() -> dict[str, str]:
    """<DB>_URL from the environment or .env, else the docker-compose default for the instance port."""
    dotenv = read_dotenv()
    password = os.environ.get("PGPASSWORD") or dotenv.get("PGPASSWORD", "postgres")
    systems = json.loads(MANIFEST.read_text())["systems"]
    urls = {}
    for db, meta in systems.items():
        key = f"{db.upper()}_URL"
        urls[db] = (os.environ.get(key) or dotenv.get(key)
                    or f"postgresql://postgres:{password}@localhost:{meta['port']}/{db}")
    return urls
