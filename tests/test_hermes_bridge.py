"""Hermes bridge + session capsule + introspection integration tests."""
import json

import pytest

from custodian.tools.registry import ToolRegistry
from custodian.adapters.pipeline import AdapterPipeline
from custodian.adapters.builtin import ContextAnchor, PiiRedactor
from integrations.hermes.bridge import HermesBridge
from integrations.hermes.capsule import SessionCapsule
from integrations.hermes.introspection import IntrospectionAdapter


@pytest.fixture
def echo_registry(tmp_path):
    """A minimal skills tree with one L0 echo tool that reports an env var."""
    d = tmp_path / "skills" / "test" / "echo-tool"
    (d / "scripts").mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: echo-tool\ndescription: echo\nversion: 1.0.0\n"
        "metadata:\n  custodian:\n    band: L0\n    cost_usd: 0.0\n    configured: true\n---\n"
    )
    (d / "scripts" / "execute.py").write_text(
        "import argparse,json,os\n"
        "p=argparse.ArgumentParser();p.add_argument('--msg',default='')\n"
        "a=p.parse_args()\n"
        "print(json.dumps({'ok':True,'echo':a.msg,'klen':len(os.environ.get('TEST_KEY',''))}))\n"
    )
    return ToolRegistry(tmp_path / "skills")


def test_basic_invoke(echo_registry):
    bridge = HermesBridge(registry=echo_registry, pipeline=AdapterPipeline())
    r = bridge.invoke("echo-tool", {"msg": "hi"})
    assert r["ok"] and r["echo"] == "hi"


def test_confabulation_wired_from_registry(echo_registry):
    bridge = HermesBridge(registry=echo_registry, pipeline=AdapterPipeline())
    r = bridge.invoke("echo-toool", {})
    assert not r["ok"] and "tool-confabulation-guard" in r["denied_by"]


def test_pre_deny_records_and_anchors(echo_registry):
    anchor = ContextAnchor({"forbidden_skills": ["echo-tool"]})
    bridge = HermesBridge(registry=echo_registry,
                          pipeline=AdapterPipeline([anchor]))
    r = bridge.invoke("echo-tool", {"msg": "x"})
    assert not r["ok"] and "anchor" in r
    assert bridge.capsule.denials == 1


def test_output_transform_marks_result(echo_registry):
    bridge = HermesBridge(registry=echo_registry,
                          pipeline=AdapterPipeline([PiiRedactor()]))
    r = bridge.invoke("echo-tool", {"msg": "mail me at bob@realmail.net"})
    assert "[PII:email]" in r["echo"]
    assert "pii-redactor" in r.get("transformed_by", [])


def test_warden_egress(echo_registry, tmp_path):
    from warden.vault import Vault
    from warden.broker import Broker
    v = Vault.create(path=tmp_path / "v.warden", passphrase="pp")
    v.add("test_key", "sekret-1234", env_var="TEST_KEY")
    b = Broker(v)
    b.grant("test_key", "skill:echo-tool", max_band="L2")
    bridge = HermesBridge(registry=echo_registry, pipeline=AdapterPipeline(), broker=b)
    r = bridge.invoke("echo-tool", {"msg": "go", "key": "warden://test_key"})
    assert r["ok"] and r["klen"] == len("sekret-1234")
    # the ref never remained in the args passed onward
    assert "key" not in r


def test_warden_egress_denied_without_grant(echo_registry, tmp_path):
    from warden.vault import Vault
    from warden.broker import Broker
    v = Vault.create(path=tmp_path / "v.warden", passphrase="pp")
    v.add("test_key", "sekret", env_var="TEST_KEY")
    bridge = HermesBridge(registry=echo_registry, pipeline=AdapterPipeline(),
                          broker=Broker(v))
    r = bridge.invoke("echo-tool", {"msg": "go", "key": "warden://test_key"})
    assert not r["ok"] and "warden" in r["denied_by"]


# -- capsule -----------------------------------------------------------------

def test_capsule_persists(tmp_path):
    p = tmp_path / "cap.json"
    c = SessionCapsule.load_or_create(p, goal="g", band="L2")
    c.record("http-get", ok=True)
    c.record("stripe-spend", ok=False, note="denied")
    reloaded = SessionCapsule.load(p)
    assert reloaded.goal == "g" and reloaded.denials == 1
    assert len(reloaded.history) == 2


def test_capsule_anchor_lists_history(tmp_path):
    c = SessionCapsule(goal="refund", path=str(tmp_path / "c.json"))
    c.record("stripe-refund", ok=True)
    block = c.render_anchor()
    assert "refund" in block and "stripe-refund" in block


def test_capsule_history_bounded(tmp_path):
    c = SessionCapsule(path=str(tmp_path / "c.json"))
    for i in range(80):
        c.record("x", ok=True)
    assert len(c.history) == 50


# -- introspection -----------------------------------------------------------

def test_introspection_status(echo_registry):
    cap = SessionCapsule(goal="g", band="L2", max_session_cost_usd=10)
    bridge = HermesBridge(registry=echo_registry,
                          pipeline=AdapterPipeline([IntrospectionAdapter(capsule=cap)]),
                          capsule=cap)
    r = bridge.invoke("custodian-status")
    assert r["ok"] and r["band"] == "L2" and r["budget_usd"] == 10


def test_introspection_vault_list_metadata_only(echo_registry, tmp_path):
    from warden.vault import Vault
    from warden.broker import Broker
    v = Vault.create(path=tmp_path / "v.warden", passphrase="pp")
    v.add("stripe_sk", "sk_live_secretzzz", env_var="STRIPE_SECRET_KEY")
    b = Broker(v)
    cap = SessionCapsule()
    bridge = HermesBridge(
        registry=echo_registry, capsule=cap,
        pipeline=AdapterPipeline([IntrospectionAdapter(capsule=cap, broker=b)]),
        broker=b)
    r = bridge.invoke("warden-vault-list")
    assert r["ok"]
    blob = json.dumps(r)
    assert "warden://stripe_sk" in blob
    assert "sk_live_secretzzz" not in blob  # value never present
