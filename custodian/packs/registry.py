"""Pack registry: the proof that this is one reusable engine, not a refund bot.

Each entry binds a pack name to its PolicyPack class, its corpus directory, and
its kernel band policy. The CLI runner and the dashboard both resolve packs
through here, so adding a business operation is one registry line plus the pack
files -- no change to the engine, the verifier, or the kernel.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from custodian.packs.base import PolicyPack

_PACKS_DIR = Path(__file__).resolve().parent


@dataclass
class PackEntry:
    name: str
    factory: Callable[[], PolicyPack]
    corpus_dir: Path
    kernel_policy: Path
    blurb: str


def _refund_entry() -> PackEntry:
    from custodian.packs.refunds.pack import RefundPack
    base = _PACKS_DIR / "refunds"
    return PackEntry(
        name="refunds",
        factory=RefundPack,
        corpus_dir=base / "corpus",
        kernel_policy=base / "policy.yaml",
        blurb="Customer refunds. Always escalates to a human -- no autonomous refund path.",
    )


def _purchasing_entry() -> PackEntry:
    from custodian.packs.purchasing.pack import PurchasingPack
    base = _PACKS_DIR / "purchasing"
    return PackEntry(
        name="purchasing",
        factory=PurchasingPack,
        corpus_dir=base / "corpus",
        kernel_policy=base / "policy.yaml",
        blurb="Accounts payable. Small clean invoices from approved vendors pay autonomously; "
              "everything risky still escalates.",
    )


def _cloud_entry() -> PackEntry:
    from custodian.packs.cloud.pack import CloudProvisioningPack
    base = _PACKS_DIR / "cloud"
    return PackEntry(
        name="cloud",
        factory=CloudProvisioningPack,
        corpus_dir=base / "corpus",
        kernel_policy=base / "policy.yaml",
        blurb="Cloud compute provisioning (Modal, Azure, NVIDIA NIM). Small jobs on approved "
              "instance types provision autonomously; large or unusual requests escalate.",
    )


_REGISTRY = {
    "refunds": _refund_entry,
    "purchasing": _purchasing_entry,
    "cloud": _cloud_entry,
}


def available() -> list[str]:
    return list(_REGISTRY)


def get_pack(name: str) -> PackEntry:
    if name not in _REGISTRY:
        raise KeyError(f"unknown pack '{name}'. Available: {', '.join(available())}")
    return _REGISTRY[name]()
