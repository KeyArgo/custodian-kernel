"""AdapterRegistry — discover, install, enable, and pin guard adapters.

Three sources, in trust order:

1. **Built-ins** (``custodian.adapters.builtin``) — ship with the
   kernel, always available, referenced by name.
2. **Entry points** — any installed package exposing the
   ``custodian.adapters`` entry-point group (pip-installable adapter
   packs).
3. **Local files** — ``custodian adapters install ./my_guard.py`` copies
   the file into the adapters dir and records its SHA-256 in the
   manifest. At load time the hash is re-checked; **a modified file
   refuses to load**. Same tamper-detection stance as the kernel's
   receipts: code you reviewed is the code that runs.

The manifest (``adapters.yaml``) is the single switchboard::

    enabled:
      - name: spend-sentinel
        config: {max_per_minute: 4}
      - name: pii-redactor
      - name: my-guard            # installed local adapter
        sha256: <pinned at install>

``load_pipeline()`` turns the manifest into a ready AdapterPipeline.
"""
from __future__ import annotations

import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Optional

import yaml

from custodian.adapters.base import Adapter
from custodian.adapters.builtin import ALL_BUILTINS
from custodian.adapters.pipeline import AdapterPipeline

DEFAULT_DIR = Path("~/.custodian/adapters").expanduser()
MANIFEST_NAME = "adapters.yaml"


class AdapterLoadError(Exception):
    pass


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entry_point_adapters() -> dict[str, type]:
    out: dict[str, type] = {}
    try:
        from importlib.metadata import entry_points
        for ep in entry_points(group="custodian.adapters"):
            try:
                cls = ep.load()
                if isinstance(cls, type) and issubclass(cls, Adapter):
                    out[cls.name] = cls
            except Exception:
                continue  # a broken third-party pack must not break discovery
    except Exception:
        pass
    return out


class AdapterRegistry:
    def __init__(self, adapters_dir: Optional[Path] = None) -> None:
        self.dir = Path(adapters_dir) if adapters_dir else DEFAULT_DIR
        self.manifest_path = self.dir / MANIFEST_NAME

    # -- discovery -------------------------------------------------------------

    def builtin_classes(self) -> dict[str, type]:
        return {cls.name: cls for cls in ALL_BUILTINS}

    def available(self) -> dict[str, dict]:
        """Everything that *could* be enabled: name → describe() dict."""
        out = {}
        for name, cls in {**self.builtin_classes(), **_entry_point_adapters()}.items():
            out[name] = cls().describe() | {"source": "builtin"
                                            if name in self.builtin_classes()
                                            else "entry-point"}
        for rec in self._manifest().get("installed", []):
            out[rec["name"]] = {
                "name": rec["name"], "category": rec.get("category", "?"),
                "source": rec["file"], "sha256": rec["sha256"][:16] + "…",
            }
        return out

    # -- manifest --------------------------------------------------------------

    def _manifest(self) -> dict:
        if not self.manifest_path.exists():
            return {"enabled": [], "installed": []}
        doc = yaml.safe_load(self.manifest_path.read_text()) or {}
        doc.setdefault("enabled", [])
        doc.setdefault("installed", [])
        return doc

    def _save_manifest(self, doc: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(yaml.safe_dump(doc, sort_keys=False))

    # -- install / enable / disable ---------------------------------------------

    def install(self, source: Path) -> dict:
        """Copy a local adapter file into the adapters dir and pin its hash."""
        source = Path(source)
        if not source.is_file() or source.suffix != ".py":
            raise AdapterLoadError(f"{source} is not a .py file")
        cls = self._class_from_file(source)
        self.dir.mkdir(parents=True, exist_ok=True)
        dest = self.dir / source.name
        if source.resolve() != dest.resolve():
            shutil.copy2(source, dest)
        record = {
            "name": cls.name,
            "file": dest.name,
            "sha256": _sha256_file(dest),
            "category": cls.category,
        }
        doc = self._manifest()
        doc["installed"] = [r for r in doc["installed"] if r["name"] != cls.name]
        doc["installed"].append(record)
        self._save_manifest(doc)
        return record

    def enable(self, name: str, config: Optional[dict] = None) -> None:
        if name not in self.available():
            raise AdapterLoadError(
                f"unknown adapter {name!r} — see `custodian adapters list`"
            )
        doc = self._manifest()
        doc["enabled"] = [e for e in doc["enabled"] if e["name"] != name]
        entry = {"name": name}
        if config:
            entry["config"] = config
        doc["enabled"].append(entry)
        self._save_manifest(doc)

    def disable(self, name: str) -> bool:
        doc = self._manifest()
        before = len(doc["enabled"])
        doc["enabled"] = [e for e in doc["enabled"] if e["name"] != name]
        self._save_manifest(doc)
        return len(doc["enabled"]) < before

    def enabled(self) -> list[dict]:
        return self._manifest()["enabled"]

    # -- loading -----------------------------------------------------------------

    def _class_from_file(self, path: Path) -> type:
        spec = importlib.util.spec_from_file_location(f"custodian_adapter_{path.stem}", path)
        if spec is None or spec.loader is None:
            raise AdapterLoadError(f"cannot import {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        for obj in vars(module).values():
            if (isinstance(obj, type) and issubclass(obj, Adapter)
                    and obj is not Adapter and getattr(obj, "name", None)):
                return obj
        raise AdapterLoadError(f"{path} defines no Adapter subclass")

    def _instantiate(self, name: str, config: Optional[dict]) -> Adapter:
        builtins = self.builtin_classes()
        if name in builtins:
            return builtins[name](config=config)
        eps = _entry_point_adapters()
        if name in eps:
            return eps[name](config=config)
        for rec in self._manifest()["installed"]:
            if rec["name"] == name:
                path = self.dir / rec["file"]
                if not path.exists():
                    raise AdapterLoadError(f"installed adapter file missing: {path}")
                actual = _sha256_file(path)
                if actual != rec["sha256"]:
                    raise AdapterLoadError(
                        f"adapter {name!r} REFUSED to load: {path} hash "
                        f"{actual[:16]}… does not match the pinned "
                        f"{rec['sha256'][:16]}… — the file changed since install. "
                        f"Re-run `custodian adapters install` after reviewing it."
                    )
                return self._class_from_file(path)(config=rec.get("config") or config)
        raise AdapterLoadError(f"unknown adapter {name!r}")

    def load_pipeline(self, extra: Optional[list[Adapter]] = None) -> AdapterPipeline:
        pipeline = AdapterPipeline()
        for entry in self.enabled():
            pipeline.add(self._instantiate(entry["name"], entry.get("config")))
        for adapter in extra or []:
            pipeline.add(adapter)
        return pipeline
