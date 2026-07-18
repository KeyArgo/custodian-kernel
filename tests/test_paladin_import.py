"""paladin import: bulk credential onboarding (.env / Bitwarden / 1Password /
discover). The invariant every test guards: reports and tool output carry
names, kinds, and counts — never secret values."""
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from paladin import importer as imp
from paladin import cli as paladin_cli
from paladin.errors import PaladinError
from paladin.vault import Vault

PP = "test-passphrase-123"


@pytest.fixture
def vault(tmp_path):
    return Vault.create(path=tmp_path / "v.paladin", passphrase=PP)


# -- kind inference -----------------------------------------------------------

@pytest.mark.parametrize("name,value,expected", [
    ("anything", "ghp_abcdef1234567890", "token"),
    ("anything", "github_pat_11ABC", "token"),
    ("anything", "tskey-auth-xyz", "token"),
    ("anything", "xoxb-1234-5678", "token"),
    ("anything", "re_123abc", "token"),
    ("anything", "hf_abc123", "token"),
    ("anything", "sk-proj-abc123", "secret"),
    ("anything", "sk_live_abc123", "secret"),
    ("anything", "rk_live_abc123", "secret"),
    ("anything", "pplx-abc123", "secret"),
    ("anything", "nvapi-abc123", "secret"),
    ("anything", "AKIAIOSFODNN7EXAMPLE", "secret"),
    ("my_api_key", "no-telltale-prefix", "secret"),
    ("db_token", "no-telltale-prefix", "token"),
    ("admin_password", "hunter2hunter2", "password"),
    ("mystery", "no-telltale-prefix", "password"),
])
def test_infer_kind(name, value, expected):
    assert imp.infer_kind(name, value) == expected


# -- .env parsing -------------------------------------------------------------

def test_parse_env_text_handles_real_world_lines():
    text = """
# a comment
STRIPE_KEY=sk_live_abc123
export GITHUB_TOKEN="ghp_xyz"
QUOTED='single'
EMPTY=
REF=$HOME/other
CMD=`whoami`
lower_case=value1
SPACED = padded   # trailing comment
"""
    cands = {c.env_var: c for c in imp.parse_env_text(text, "env:test")}
    assert cands["STRIPE_KEY"].value == "sk_live_abc123"
    assert cands["GITHUB_TOKEN"].value == "ghp_xyz"
    assert cands["QUOTED"].value == "single"
    assert cands["SPACED"].value == "padded"
    assert "EMPTY" not in cands           # no value
    assert "REF" not in cands             # $VAR reference, not a credential
    assert "CMD" not in cands             # command substitution
    assert cands["lower_case"].name == "lower_case"


def test_quoted_values_containing_hash_are_not_truncated():
    """Regression: comments were stripped BEFORE quotes, so a quoted credential
    containing " #" was silently cut short — PASS="Str0ng #Pass!" vaulted as
    "Str0ng", causing baffling downstream auth failures. A quoted value is
    literal; only an UNQUOTED trailing comment is stripped."""
    text = (
        'PASS="Str0ng #Pass!"\n'
        "TOK='ghp_abc #still-part-of-token'\n"
        'PLAIN=value #this is a real comment\n'
        'QUOTED_SPACES="a b c"\n'
    )
    cands = {c.env_var: c for c in imp.parse_env_text(text, "env:test")}
    assert cands["PASS"].value == "Str0ng #Pass!"
    assert cands["TOK"].value == "ghp_abc #still-part-of-token"
    assert cands["PLAIN"].value == "value"          # unquoted comment stripped
    assert cands["QUOTED_SPACES"].value == "a b c"  # inner spaces preserved


def test_collect_env_files_recursive_skips_junk_dirs(tmp_path):
    (tmp_path / ".env").write_text("A=1")
    sub = tmp_path / "proj"
    sub.mkdir()
    (sub / ".env.production").write_text("B=2")
    junk = tmp_path / "node_modules" / "pkg"
    junk.mkdir(parents=True)
    (junk / ".env").write_text("C=3")
    found = imp.collect_env_files(tmp_path, recursive=True)
    names = {str(p.relative_to(tmp_path)) for p in found}
    assert ".env" in names
    assert str(Path("proj") / ".env.production") in names
    assert not any("node_modules" in n for n in names)


# -- import into the vault ------------------------------------------------------

def _cand(name, value="v", **kw):
    return imp.Candidate(name=name, value=value, **kw)


def test_import_skips_existing_and_dedups_within_run(vault):
    vault.add("already", "old")
    report = imp.import_candidates(
        vault, [_cand("already", "new"), _cand("fresh"), _cand("fresh")])
    assert [e["name"] for e in report.imported] == ["fresh"]
    assert report.skipped_existing == ["already", "fresh"]
    # the existing entry was not overwritten
    assert vault._resolve_value("already") == "old"


def test_import_overwrite_rotates(vault):
    vault.add("key", "old")
    imp.import_candidates(vault, [_cand("key", "new")], skip_existing=False)
    assert vault._resolve_value("key") == "new"
    assert vault.meta("key")["rotations"] == 1


def test_import_dry_run_writes_nothing(vault):
    report = imp.import_candidates(vault, [_cand("a"), _cand("b")], dry_run=True)
    assert report.dry_run and len(report.imported) == 2
    assert vault.names() == []


def test_import_normalizes_awkward_names(vault):
    report = imp.import_candidates(
        vault, [_cand("My API Key (prod)!", "sk-abc")])
    assert report.imported[0]["name"] == "my_api_key_prod"
    assert report.imported[0]["kind"] == "secret"


def test_import_report_never_contains_values(vault):
    report = imp.import_candidates(
        vault, [_cand("k1", "SUPER-SECRET-VALUE-1"),
                _cand("k2", "SUPER-SECRET-VALUE-2")])
    assert "SUPER-SECRET" not in json.dumps(report.to_dict())


# -- git exposure flags ---------------------------------------------------------

def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8")


def test_git_exposure_flags(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    if _git("init", cwd=repo).returncode != 0:
        pytest.skip("git unavailable")
    tracked = repo / ".env"
    tracked.write_text("A=1")
    _git("add", ".env", cwd=repo)
    assert imp.git_exposure_flags(tracked) == ["git-tracked"]

    loose = repo / ".env.local"
    loose.write_text("B=2")
    assert imp.git_exposure_flags(loose) == ["git-unignored"]

    (repo / ".gitignore").write_text(".env.ignored\n")
    ignored = repo / ".env.ignored"
    ignored.write_text("C=3")
    assert imp.git_exposure_flags(ignored) == []

    outside = tmp_path / ".env"
    outside.write_text("D=4")
    assert imp.git_exposure_flags(outside) == []


# -- bitwarden / 1password (CLI mocked) -----------------------------------------

def _fake_run(responses):
    """subprocess.run stand-in: match on the leading args of each command."""
    def run(cmd, **kwargs):
        for prefix, payload in responses:
            if cmd[1:1 + len(prefix)] == prefix:
                return types.SimpleNamespace(
                    returncode=0, stdout=json.dumps(payload), stderr="")
        return types.SimpleNamespace(returncode=1, stdout="", stderr="no match")
    return run


def test_bitwarden_candidates_parse_items(monkeypatch):
    monkeypatch.setattr("paladin.importer.shutil.which",
                        lambda n: "bw" if n == "bw" else None)
    items = [{
        "name": "OpenAI API Key",
        "login": {"username": "me", "password": "sk-abc123"},
        "fields": [{"name": "org id", "value": "org-42"}],
    }]
    monkeypatch.setattr("paladin.importer.subprocess.run", _fake_run([
        (["status"], {"status": "unlocked"}),
        (["list", "items"], items),
    ]))
    cands = imp.bitwarden_candidates(search="api")
    by_name = {c.name: c for c in cands}
    assert by_name["openai_api_key"].value == "sk-abc123"
    assert by_name["openai_api_key/org_id"].value == "org-42"
    assert all(c.source.startswith("bitwarden:") for c in cands)


def test_bitwarden_locked_fails_with_unlock_hint(monkeypatch):
    monkeypatch.setattr("paladin.importer.shutil.which",
                        lambda n: "bw" if n == "bw" else None)
    monkeypatch.setattr("paladin.importer.subprocess.run", _fake_run([
        (["status"], {"status": "locked"}),
    ]))
    with pytest.raises(PaladinError, match="BW_SESSION"):
        imp.bitwarden_candidates()


def test_onepassword_candidates_parse_fields(monkeypatch):
    monkeypatch.setattr("paladin.importer.shutil.which",
                        lambda n: "op" if n == "op" else None)
    listing = [{"id": "uuid1", "title": "Stripe Live"}]
    item = {
        "id": "uuid1", "title": "Stripe Live",
        "fields": [
            {"label": "username", "value": "me@example.com", "type": "STRING"},
            {"label": "password", "value": "hunter2", "purpose": "PASSWORD"},
            {"label": "secret key", "value": "sk_live_xyz", "type": "CONCEALED"},
        ],
    }
    monkeypatch.setattr("paladin.importer.subprocess.run", _fake_run([
        (["whoami"], {"ok": True}),
        (["item", "list"], listing),
        (["item", "get", "uuid1"], item),
    ]))
    cands = imp.onepassword_candidates(vault="Main")
    by_name = {c.name: c for c in cands}
    assert by_name["stripe_live"].value == "hunter2"          # purpose=PASSWORD
    assert by_name["stripe_live/secret_key"].value == "sk_live_xyz"
    assert "username" not in json.dumps([c.name for c in cands])


# -- discover (report-only) -------------------------------------------------------

def test_discover_reports_without_importing(tmp_path, monkeypatch):
    home = tmp_path / "home"
    cwd = tmp_path / "proj"
    home.mkdir(); cwd.mkdir()
    (cwd / ".env").write_text("STRIPE_KEY=sk_live_abc\n")
    (home / ".bashrc").write_text(
        "export PATH=$PATH:/x\nexport MY_API_KEY=abc123\nexport EDITOR=vim\n")
    monkeypatch.setattr("paladin.importer.shutil.which", lambda n: None)

    report = imp.discover(home=home, cwd=cwd)
    assert report["ok"]
    assert report["env_files"][0]["entries"] == 1
    assert "paladin import env" in report["env_files"][0]["import_with"]
    rc = report["shell_rc_exports"][0]
    assert rc["names"] == ["MY_API_KEY"]          # PATH/EDITOR filtered out
    assert not report["bitwarden"]["installed"]
    # report-only, and no VALUES anywhere in it
    dumped = json.dumps(report)
    assert "sk_live_abc" not in dumped and "abc123" not in dumped


# -- CLI ---------------------------------------------------------------------------

def test_cli_import_env_json_report_is_value_free(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)
    vault_path = tmp_path / "v.paladin"
    Vault.create(path=vault_path, passphrase=PP)
    envf = tmp_path / ".env"
    envf.write_text("STRIPE_KEY=sk_live_SECRETVALUE\nGH_TOKEN=ghp_SECRETVALUE\n")
    rc = paladin_cli.main(["--vault", str(vault_path), "import", "env",
                           str(envf), "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    report = json.loads(out)
    assert report["imported_count"] == 2
    assert "SECRETVALUE" not in out
    reopened = Vault.open(path=vault_path, passphrase=PP)
    assert reopened._resolve_value("stripe_key") == "sk_live_SECRETVALUE"
    assert reopened.meta("gh_token")["kind"] == "token"


def test_cli_import_is_idempotent(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)
    vault_path = tmp_path / "v.paladin"
    Vault.create(path=vault_path, passphrase=PP)
    envf = tmp_path / ".env"
    envf.write_text("A_KEY=one\n")
    assert paladin_cli.main(["--vault", str(vault_path), "import", "env",
                             str(envf), "--json"]) == 0
    capsys.readouterr()
    assert paladin_cli.main(["--vault", str(vault_path), "import", "env",
                             str(envf), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["imported_count"] == 0
    assert report["skipped_existing"] == ["a_key"]


def test_cli_import_dry_run_previews_only(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)
    vault_path = tmp_path / "v.paladin"
    Vault.create(path=vault_path, passphrase=PP)
    envf = tmp_path / ".env"
    envf.write_text("A_KEY=one\n")
    assert paladin_cli.main(["--vault", str(vault_path), "import", "env",
                             str(envf), "--dry-run", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] and report["imported_count"] == 1
    assert Vault.open(path=vault_path, passphrase=PP).names() == []


def test_cli_import_discover_runs(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("paladin.importer.shutil.which", lambda n: None)
    monkeypatch.setattr("paladin.importer.Path.home", classmethod(
        lambda cls: tmp_path))
    monkeypatch.chdir(tmp_path)
    assert paladin_cli.main(["import", "discover", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True


def test_paladin_import_entry_point_forwards(monkeypatch, tmp_path, capsys):
    """`paladin-import discover` == `paladin import discover`."""
    monkeypatch.setattr("paladin.importer.shutil.which", lambda n: None)
    monkeypatch.setattr("paladin.importer.Path.home", classmethod(
        lambda cls: tmp_path))
    monkeypatch.chdir(tmp_path)
    assert paladin_cli.main_import(["discover", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


# -- the agent-facing bundled skill ---------------------------------------------

REPO = Path(__file__).resolve().parent.parent
SKILL_SCRIPT = (REPO / "custodian" / "bundled_skills" / "security"
                / "paladin-import" / "scripts" / "execute.py")


def test_skill_script_import_env_output_is_value_free(tmp_path, monkeypatch):
    """The registry pipes this script's stdout into the agent's context —
    it must carry names/kinds/counts, never values."""
    import os
    envf = tmp_path / ".env"
    envf.write_text("STRIPE_KEY=sk_live_AGENTMUSTNOTSEE\n")
    env = dict(os.environ)
    env["PALADIN_PASSPHRASE"] = PP
    env["PALADIN_HOME"] = str(tmp_path / "home")
    Vault.create(path=tmp_path / "home" / "vault.paladin", passphrase=PP)
    r = subprocess.run(
        [sys.executable, str(SKILL_SCRIPT), "--source", "env",
         "--path", str(envf)],
        capture_output=True, text=True, encoding="utf-8", env=env,
        cwd=str(REPO), timeout=60)
    assert r.returncode == 0, r.stderr
    assert "AGENTMUSTNOTSEE" not in r.stdout
    payload = json.loads(r.stdout)
    assert payload["ok"] and payload["imported_count"] == 1
    assert payload["imported"][0]["name"] == "stripe_key"
    # the value DID land in the vault
    v = Vault.open(path=tmp_path / "home" / "vault.paladin", passphrase=PP)
    assert v._resolve_value("stripe_key") == "sk_live_AGENTMUSTNOTSEE"


def test_skill_script_locked_vault_reports_instructions(tmp_path):
    import os
    envf = tmp_path / ".env"
    envf.write_text("A=1\n")
    env = {k: v for k, v in os.environ.items()
           if k not in ("PALADIN_PASSPHRASE", "PALADIN_KEYFILE",
                        "WARDEN_PASSPHRASE", "WARDEN_KEYFILE")}
    env["PALADIN_HOME"] = str(tmp_path / "nohome")
    r = subprocess.run(
        [sys.executable, str(SKILL_SCRIPT), "--source", "env",
         "--path", str(envf)],
        capture_output=True, text=True, encoding="utf-8", env=env,
        cwd=str(REPO), timeout=60)
    payload = json.loads(r.stdout)
    assert payload["ok"] is False and payload["locked"] is True
    assert "PALADIN_PASSPHRASE" in payload["message"]


def test_registry_discovers_paladin_import_tool():
    from custodian.tools.registry import default_registry
    tool = default_registry().get("paladin-import")
    assert tool is not None
    assert tool.band == "L2"
    assert tool.execute_script and tool.execute_script.exists()


# ---------------------------------------------------------------------------
# CSV import — offline importer for every password-manager export.
# ---------------------------------------------------------------------------

class TestCsvImport:
    def test_bitwarden_layout(self):
        text = ("folder,favorite,type,name,notes,fields,login_uri,"
                "login_username,login_password\n"
                ",,login,Stripe,,,https://stripe.com,me@x.com,sk_live_ABC\n"
                ",,login,GitHub,,,https://github.com,me,ghp_XYZ\n")
        got = {c.name: c.value for c in imp.parse_csv_text(text, "csv:t")}
        assert got == {"stripe": "sk_live_ABC", "github": "ghp_XYZ"}

    def test_chrome_layout(self):
        text = ("name,url,username,password\n"
                "AWS,https://aws.amazon.com,admin,AKIAIOSFODNN7\n")
        got = {c.name: c.value for c in imp.parse_csv_text(text, "csv:t")}
        assert got == {"aws": "AKIAIOSFODNN7"}

    def test_lastpass_layout_picks_name_not_username(self):
        text = ("url,username,password,totp,extra,name,grouping,fav\n"
                "https://x.com,u,glpat-tok,,,GitLab CI,,0\n")
        cands = imp.parse_csv_text(text, "csv:t")
        assert len(cands) == 1
        assert cands[0].name == "gitlab_ci"
        assert cands[0].value == "glpat-tok"

    def test_headerless_two_column_env_names(self):
        text = "STRIPE_KEY,sk_test_111\nDB_PASSWORD,hunter2xyz9longvalue\n"
        got = {c.name: c.value for c in imp.parse_csv_text(text, "csv:t")}
        assert got == {"stripe_key": "sk_test_111",
                       "db_password": "hunter2xyz9longvalue"}

    def test_two_column_with_key_value_header(self):
        text = "key,value\nMY_TOKEN,ghp_realtoken123\n"
        got = {c.name: c.value for c in imp.parse_csv_text(text, "csv:t")}
        assert got == {"my_token": "ghp_realtoken123"}

    def test_quoted_value_with_comma_preserved(self):
        # csv module handles quoting; a value with a comma must survive intact.
        text = 'name,password\nDB,"p,a,s,s word"\n'
        cands = imp.parse_csv_text(text, "csv:t")
        assert cands[0].value == "p,a,s,s word"

    def test_unrecognized_csv_raises_clearly(self):
        with pytest.raises(PaladinError, match="could not read this CSV"):
            imp.parse_csv_text("a,b,c\n1,2,3\n", "csv:t")

    def test_empty_values_skipped(self):
        text = "name,password\nHasKey,sk_x\nNoKey,\n"
        got = {c.name: c.value for c in imp.parse_csv_text(text, "csv:t")}
        assert got == {"haskey": "sk_x"}

    def test_import_report_is_value_free(self, tmp_path):
        csv = tmp_path / "export.csv"
        csv.write_text("name,password\nStripe,sk_live_SECRET_VALUE\n")
        report = imp.import_candidates(
            _fresh_vault(tmp_path), imp.candidates_from_csv(csv), dry_run=True)
        blob = json.dumps(report.to_dict())
        assert "sk_live_SECRET_VALUE" not in blob
        assert "stripe" in blob


# ---------------------------------------------------------------------------
# JSON import — flat object or array of {name, value}.
# ---------------------------------------------------------------------------

class TestJsonImport:
    def test_flat_object(self):
        got = {c.name: c.value for c in imp.parse_json_text(
            '{"STRIPE_KEY":"sk_live_9","AWS":"AKIAX"}', "json:t")}
        assert got == {"stripe_key": "sk_live_9", "aws": "AKIAX"}

    def test_nested_objects_and_bools_skipped(self):
        got = {c.name: c.value for c in imp.parse_json_text(
            '{"KEY":"v","nested":{"a":1},"flag":true,"n":5}', "json:t")}
        assert got == {"key": "v", "n": "5"}   # scalar int kept, dict/bool dropped

    def test_array_of_objects(self):
        got = {c.name: c.value for c in imp.parse_json_text(
            '[{"name":"gh","token":"ghp_1"},{"title":"api","secret":"sk-2"}]',
            "json:t")}
        assert got == {"gh": "ghp_1", "api": "sk-2"}

    def test_invalid_json_raises_clearly(self):
        with pytest.raises(PaladinError, match="not valid JSON"):
            imp.parse_json_text("{not json", "json:t")

    def test_wrong_shape_raises(self):
        with pytest.raises(PaladinError, match="object of name"):
            imp.parse_json_text('"just a string"', "json:t")


def _fresh_vault(tmp_path):
    return Vault.create(path=tmp_path / "v.paladin", passphrase="pp")
