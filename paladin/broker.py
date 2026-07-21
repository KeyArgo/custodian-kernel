"""The Broker — the only door between an agent and a secret value.

The rules it enforces:

1. **Grants first.** Every resolution passes ``GrantPolicy.check`` —
   deny-by-default, band-ceilinged, expirable.
2. **Egress only.** There is no public "give me the plaintext" method
   for agent code. Secrets leave the broker exclusively as environment
   variables of a *subprocess* (or a NemoClaw sandbox exec) that the
   broker itself launches. The agent gets the child's stdout — never
   the env.
3. **Everything audited.** Resolve, deny, grant, revoke — all land in
   the hash-chained audit log.
4. **Leak tripwire.** Every value that crosses egress registers its
   SHA-256 (of the value, and per-token) in ``leak_sentinel``. The
   secret-leak-guard adapter hashes candidate tokens in tool output and
   trips if any match — catching a secret coming *back* into the
   agent's context even though the agent never saw it go out.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import os
import re
import ssl
import subprocess
from pathlib import Path
from typing import Mapping, Optional, Sequence
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urlsplit, urlunsplit

from paladin.audit import AuditLog
from paladin.errors import EgressDeniedError, GrantDeniedError, UnknownRefError
from paladin.grants import GrantPolicy
from paladin.refs import SecretRef
from paladin.vault import Vault

AUDIT_FILENAME = "audit.jsonl"

# Bounds for the sandboxed-egress path. A hostile child cannot make Paladin
# stream unbounded data or hang forever on a slow-loris upstream.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
DEFAULT_EGRESS_TIMEOUT = 30.0
_HTTP_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
)
# RFC 7230 header field-name token — used to reject any child-supplied or
# inject header name that could smuggle CRLF / control chars into the request.
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_RESERVED_REQUEST_HEADERS = frozenset({
    "host", "content-length", "transfer-encoding", "connection",
    "proxy-connection", "upgrade", "trailer", "te",
})


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _safe_header_value(value: object) -> str:
    text = str(value)
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise EgressDeniedError("header values cannot contain control characters")
    return text


class LeakSentinel:
    """In-memory registry of hashes of every value that crossed egress.

    Stores only SHA-256 digests — holding the sentinel never yields a
    secret. ``seen()`` answers: does this exact token match any value
    (or any whitespace-split token of a value) that Paladin released?
    """

    def __init__(self) -> None:
        self._hashes: set[str] = set()

    @staticmethod
    def _h(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8", "surrogatepass")).hexdigest()

    def register(self, value: str) -> None:
        self._hashes.add(self._h(value))
        for tok in value.split():
            if len(tok) >= 8:  # skip trivially guessable fragments
                self._hashes.add(self._h(tok))

    def seen(self, token: str) -> bool:
        return len(token) >= 8 and self._h(token) in self._hashes

    def __len__(self) -> int:
        return len(self._hashes)


class Broker:
    """Grant-gated, audited egress for one vault."""

    def __init__(self, vault: Vault, audit_path: Optional[Path] = None) -> None:
        self.vault = vault
        self.grants = GrantPolicy(vault)
        self.audit = AuditLog(
            audit_path or vault.path.parent / AUDIT_FILENAME, vault.audit_key()
        )
        self.leak_sentinel = LeakSentinel()

    # -- internal resolution (audited, grant-gated) ---------------------------

    def _resolve(self, ref: SecretRef | str, requester: str, band: str) -> str:
        ref = SecretRef.parse(str(ref))
        try:
            grant = self.grants.check(ref.name, requester, band)
        except GrantDeniedError:
            self.audit.append("deny", ref.name, requester, band, "no matching grant")
            raise
        try:
            value = self.vault._resolve_value(ref.name)
        except UnknownRefError:
            self.audit.append("deny", ref.name, requester, band, "unknown ref")
            raise
        self.audit.append("resolve", ref.name, requester, band,
                          f"grant={grant.ref_pattern}")
        self.leak_sentinel.register(value)
        return value

    # -- egress surfaces -------------------------------------------------------

    def build_env(self, refs: Mapping[str, SecretRef | str], requester: str,
                  band: str = "L0", base_env: Optional[Mapping[str, str]] = None) -> dict:
        """Materialize {ENV_VAR: value} for the given {ENV_VAR: ref} map.

        Host-side glue (bridge/executor) may call this to hand an env to a
        transport it controls. It must never be exposed to agent code as a
        tool — the tool surface is spawn()/NemoClaw exec only.
        """
        env = dict(base_env if base_env is not None else os.environ)
        for var, ref in refs.items():
            env[var] = self._resolve(ref, requester, band)
        return env

    def env_for_profile(self, profile: str, requester: str, band: str = "L0",
                        base_env: Optional[Mapping[str, str]] = None) -> dict:
        """Env-manager mode: materialize every entry in a profile under its
        configured env var name (e.g. the whole `prod` profile at once)."""
        env = dict(base_env if base_env is not None else os.environ)
        for meta in self.vault.iter_meta(profile):
            var = meta["env_var"]
            env[var] = self._resolve(SecretRef(meta["name"]), requester, band)
        return env

    def spawn(self, cmd: Sequence[str], refs: Mapping[str, SecretRef | str],
              requester: str, band: str = "L0", profile: Optional[str] = None,
              timeout: Optional[float] = None,
              capture_output: bool = True) -> subprocess.CompletedProcess:
        """Run `cmd` with secrets injected into its environment.

        This is the canonical egress: the child process sees the values;
        the caller sees only the CompletedProcess. shell=False always —
        cmd is an argv list, never a string handed to a shell.
        """
        env = self.build_env(refs, requester, band)
        if profile:
            env = self.env_for_profile(profile, requester, band, base_env=env)
        return subprocess.run(
            list(cmd), env=env, timeout=timeout,
            capture_output=capture_output, text=True, shell=False,
        )

    # -- sandboxed egress (the credential never enters the child) -------------

    def egress_request(self, descriptor: Mapping, requester: str, band: str = "L0",
                       allow_refs: Optional[set] = None,
                       timeout: float = DEFAULT_EGRESS_TIMEOUT) -> dict:
        """Perform ONE authenticated outbound HTTP(S) call for a sandboxed
        child, injecting a vault secret the child never sees.

        The child sends an *unauthenticated* ``descriptor`` naming a ref and
        how to inject it; this method resolves that ref (grant-gated +
        audited), enforces the entry's ``allowed_hosts`` ceiling AND the
        grant's egress scope (both must pass — the grant narrows, never
        widens), attaches the credential, makes the call, and returns the
        response with the credential stripped. The plaintext value lives only
        in a local variable here — it never crosses back to the child, which
        gets only ``{status, headers, body}``.

        ``requester`` and ``band`` are set by the trusted caller (the gateway
        that owns this run), NEVER read from the descriptor — a child cannot
        choose its own identity or escalate its band. ``allow_refs``, when
        given, is a per-run allow-list that further restricts which ref names
        this child may name, intersected with whatever its grants permit.
        """
        # -- parse + shape-check the untrusted descriptor (no secrets yet) ----
        if not isinstance(descriptor, Mapping) or "ref" not in descriptor:
            raise EgressDeniedError("egress descriptor must name a 'ref'")
        ref = SecretRef.parse(str(descriptor["ref"]))
        method = str(descriptor.get("method", "GET")).upper()
        if method not in _HTTP_METHODS:
            raise EgressDeniedError(f"unsupported method {method!r}")
        parts = urlsplit(str(descriptor.get("url", "")))
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise EgressDeniedError("url must be an absolute http(s) URL with a host")
        if parts.username is not None or parts.password is not None:
            raise EgressDeniedError("url must not contain user information")
        if parts.fragment:
            raise EgressDeniedError("url fragments are not permitted for egress")
        host = parts.hostname
        if parts.scheme != "https" and not _is_loopback_host(host):
            raise EgressDeniedError(
                "credential egress requires HTTPS (plain HTTP is allowed only "
                "for loopback development endpoints)"
            )
        path = parts.path or "/"

        # -- per-run allow-list (cheapest deny, before any vault access) ------
        if allow_refs is not None and ref.name not in allow_refs:
            self.audit.append("deny", ref.name, requester, band,
                              "ref outside per-run allow-list")
            raise EgressDeniedError(f"ref {ref.name!r} not permitted for this run")

        # -- grant gate (deny-by-default) -------------------------------------
        try:
            grant = self.grants.check(ref.name, requester, band)
        except GrantDeniedError:
            self.audit.append("deny", ref.name, requester, band, "no matching grant")
            raise

        # -- host ceiling (entry) then egress scope (grant) — deny BEFORE we
        #    ever materialize the plaintext value ------------------------------
        try:
            allowed_hosts = self.vault.meta(ref.name).get("allowed_hosts") or []
        except UnknownRefError:
            self.audit.append("deny", ref.name, requester, band, "unknown ref")
            raise
        if allowed_hosts and host not in allowed_hosts:
            self.audit.append("deny", ref.name, requester, band,
                              f"host {host} not in entry allowed_hosts")
            raise EgressDeniedError(
                f"host {host!r} is not in the allowed_hosts for {ref.name!r}"
            )
        if not grant.scope_allows(host, method, path):
            self.audit.append("deny", ref.name, requester, band,
                              f"grant scope forbids {method} {host}{path}")
            raise EgressDeniedError(
                f"grant does not permit {method} to {host}{path}"
            )

        # -- everything checked: resolve and inject ---------------------------
        value = self.vault._resolve_value(ref.name)
        self.leak_sentinel.register(value)
        try:
            headers = self._safe_headers(descriptor.get("headers"))
            headers, final_url = self._apply_injection(
                headers, parts, descriptor.get("inject"), value)
            body = descriptor.get("body")
            result = self._perform(method, final_url, headers, body, timeout)
            result = self._redact_response(result, value)
        finally:
            value = None  # drop the plaintext reference promptly
        self.audit.append("egress", ref.name, requester, band,
                          f"{host} {method} {path} -> {result['status']}")
        return result

    def _safe_headers(self, raw) -> dict:
        """Validate child-supplied headers. Rejects non-token names and drops
        Host (set from the URL by http.client — a child-supplied Host could
        desync SNI from the routed connection)."""
        headers: dict[str, str] = {}
        if raw is None:
            return headers
        if not isinstance(raw, Mapping):
            raise EgressDeniedError("headers must be a mapping")
        for name, val in raw.items():
            name = str(name)
            if not _HEADER_NAME_RE.match(name):
                raise EgressDeniedError(f"invalid header name {name!r}")
            if name.lower() in _RESERVED_REQUEST_HEADERS:
                raise EgressDeniedError(
                    f"request framing header {name!r} is controlled by Paladin"
                )
            headers[name] = _safe_header_value(val)
        return headers

    def _apply_injection(self, headers: dict, parts, inject, value: str):
        """Attach the credential per the child's inject spec. Returns
        (headers, final_url). The child names WHERE the secret goes, never
        the value itself."""
        if not isinstance(inject, Mapping):
            raise EgressDeniedError("egress descriptor must carry an 'inject' spec")
        url = urlunsplit(parts)
        if "header" in inject:
            name = str(inject["header"])
            fmt = str(inject.get("format", "{value}"))
            if not _HEADER_NAME_RE.match(name):
                raise EgressDeniedError(f"invalid inject header name {name!r}")
            if fmt.count("{value}") != 1:
                raise EgressDeniedError("inject format must contain {value} exactly once")
            # Drop any client-supplied header of the same name (any case) so it
            # cannot pre-seed or shadow the injected credential header.
            headers = {k: v for k, v in headers.items() if k.lower() != name.lower()}
            headers[name] = _safe_header_value(fmt.replace("{value}", value))
            return headers, url
        if "query" in inject:
            param = str(inject["query"])
            q = parse_qsl(parts.query, keep_blank_values=True)
            q.append((param, value))
            url = urlunsplit((parts.scheme, parts.netloc, parts.path,
                              urlencode(q), parts.fragment))
            return headers, url
        raise EgressDeniedError("inject must specify 'header' or 'query'")

    @staticmethod
    def _redact_response(result: dict, value: str) -> dict:
        """Ensure a reflecting upstream cannot return a credential to a child.

        Also redacts both encoded forms of ``value``: query injection
        (``_apply_injection``'s "query" branch) sends the value through
        ``urlencode()``, which percent-encodes via ``quote_plus`` -- so a
        secret containing ``+``, ``/``, or ``=`` (the base64 alphabet, a
        common shape for API keys) never appears on the wire in its raw
        form at all. Matching only the raw value here left a reflecting
        upstream (e.g. an "invalid api_key=..." error echoing the request)
        free to hand the credential straight back in its encoded --
        trivially reversible -- form. Found in review, reproduced: a
        value containing '+' survived this redaction unchanged.

        Checking only ``quote_plus``'s encoding was itself incomplete:
        ``quote_plus`` and stdlib ``quote()`` (default ``safe='/'``) encode
        differently at exactly the '/' character -- quote_plus escapes it
        to %2F, quote() leaves it literal. A reflecting upstream that
        happens to URL-encode via quote() instead of quote_plus() (e.g. an
        error page echoing a raw query string) leaked a credential
        containing '/' in a form this check didn't recognize. Found in
        review, reproduced: 'sk_test_AbC/def+123=' survived as
        'sk_test_AbC/def%2B123%3D' -- the '/' never got redacted.
        """
        if not value:
            return result
        marker = "[REDACTED:paladin-value]"
        encodings = (quote_plus(value), quote(value))
        cleaned = dict(result)
        body = str(cleaned.get("body", "")).replace(value, marker)
        for encoded in encodings:
            body = body.replace(encoded, marker)
        cleaned["body"] = body
        headers = {}
        for key, header_value in (cleaned.get("headers") or {}).items():
            text = str(header_value).replace(value, marker)
            for encoded in encodings:
                text = text.replace(encoded, marker)
            headers[str(key)] = text
        cleaned["headers"] = headers
        return cleaned

    def _perform(self, method: str, url: str, headers: dict, body,
                 timeout: float) -> dict:
        """Make the outbound call with stdlib http.client (no new dep) and
        return a bounded {status, headers, body}."""
        parts = urlsplit(url)
        path_q = parts.path or "/"
        if parts.query:
            path_q += "?" + parts.query
        body_bytes = body.encode("utf-8") if isinstance(body, str) else body
        if parts.scheme == "https":
            conn = http.client.HTTPSConnection(
                parts.hostname, parts.port, timeout=timeout,
                context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(
                parts.hostname, parts.port, timeout=timeout)
        try:
            conn.request(method, path_q, body=body_bytes, headers=headers)
            resp = conn.getresponse()
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
            truncated = len(raw) > MAX_RESPONSE_BYTES
            raw = raw[:MAX_RESPONSE_BYTES]
            return {
                "status": resp.status,
                "headers": {k: v for k, v in resp.getheaders()},
                "body": raw.decode("utf-8", "replace"),
                "truncated": truncated,
            }
        finally:
            conn.close()

    # -- passthrough management (CLI convenience, all audited) ----------------

    def grant(self, ref_pattern: str, requester: str, max_band: str = "L2",
              ttl_seconds: Optional[float] = None, note: str = "",
              allowed_hosts: Optional[list] = None,
              methods: Optional[list] = None, path_prefix: str = ""):
        g = self.grants.grant(ref_pattern, requester, max_band, ttl_seconds, note,
                              allowed_hosts=allowed_hosts, methods=methods,
                              path_prefix=path_prefix)
        scope = ""
        if allowed_hosts or methods or path_prefix:
            scope = (f" scope=hosts:{','.join(allowed_hosts or []) or '*'}"
                     f"/methods:{','.join(methods or []) or '*'}"
                     f"/path:{path_prefix or '*'}")
        self.audit.append("grant", ref_pattern, requester, max_band, note + scope)
        return g

    def revoke(self, ref_pattern: str, requester: str) -> int:
        removed = self.grants.revoke(ref_pattern, requester)
        self.audit.append("revoke", ref_pattern, requester, "-", f"removed={removed}")
        return removed
