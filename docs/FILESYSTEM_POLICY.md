# Filesystem Policy — per-harness, per-model read/write scopes

## Purpose

`FilesystemPolicy` governs which filesystem paths an agent harness may
read or write for a given model.  Each rule is scoped to exactly one
harness and one access direction (read or write), with optional model
specificity.  Deny roots always win over allow roots; malformed state
denies all access.

## Rule format

| Field         | Type            | Default | Description |
|---------------|-----------------|---------|-------------|
| `harness`     | `str`           | —       | Harness name (required; never `"*"`) |
| `access`      | `"read"`/`"write"` | —    | Direction governed |
| `model`       | `str`           | `"*"`   | Model name or `"*"` for all |
| `allow_roots` | `[str,...]`     | `[]`    | Prefixes the harness may access |
| `deny_roots`  | `[str,...]`     | `[]`    | Prefixes the harness must never access |
| `enforcement` | `"routed"`/`"brokered"` | `"routed"` | Enforcement strategy |
| `rule_id`     | `str`           | auto    | UUID (set at creation) |

At least one of `allow_roots` or `deny_roots` must be non-empty.

## Security properties

### Cross-process atomicity (`fcntl.flock`)

Every `add`, `remove`, and `list` call acquires a `fcntl.flock` on the
policy file: exclusive for mutations, shared for reads.  This prevents
lost updates when multiple agent processes modify the policy concurrently.

Read-modify-write cycles (`add`, `remove`) hold the exclusive lock for
the entire duration — no concurrent writer can overwrite a sibling's
change between the read and the write.

### Canonicalisation (`os.path.realpath`)

All paths returned by `fence_config` are canonicalised via
`os.path.realpath`:

- `~` is expanded to the user's home directory;
- `..` components are collapsed;
- symlinks are followed to their real target.

A symlink planted inside an allow-root that points at a deny-root is
resolved to the deny-root itself before matching.

### Deny-root precedence

If an allow root equals or is a subdirectory of a deny root, it is
automatically removed from the allow list at enforcement time.
This ensures a deny root can never be undermined by a broader allow.

### Fail-closed on malformed state

When the policy file is corrupt (invalid JSON, wrong type), `fence_config`
returns a deny-all fence (`allow_paths: [], forbidden_paths: ["/"]`)
instead of falling through to inherited defaults.

### Per-harness / per-model isolation

- Rules are indexed by `(harness, access, model)`.
- An exact model match is preferred over a wildcard (`"*"`) match.
- `read` and `write` rules are completely independent — a read rule
  never affects write access and vice versa.

## API

```python
class FilesystemPolicy:
    def __init__(self, path: Path) -> None: ...
    def list(self) -> list[FilesystemRule]: ...
    def add(self, rule: FilesystemRule) -> None: ...
    def remove(self, rule_id: str) -> bool: ...
    def effective(self, *, harness: str, model: str, access: str) -> FilesystemRule | None: ...
    def fence_config(self, *, harness: str, model: str, access: str,
                     inherited_allow: list[str], inherited_deny: list[str]) -> dict: ...
```

`fence_config` returns a dict consumed by the `PathFence` adapter:

| Key                | Type       | Description |
|--------------------|------------|-------------|
| `allow_paths`      | `[str]`    | Canonicalised allow prefixes |
| `forbidden_paths`  | `[str]`    | Canonicalised deny prefixes (inherited + rule) |
| `source`           | `str`      | `"harness-default"`, `"malformed-policy"`, or a `rule_id` |
| `enforcement`      | `str`      | `"routed"` or `"brokered"` |

## Example

```json
[
  {
    "harness": "codex",
    "access": "read",
    "model": "*",
    "allow_roots": ["/workspace"],
    "deny_roots": ["~/.ssh", "~/.aws"],
    "enforcement": "routed"
  },
  {
    "harness": "codex",
    "access": "write",
    "model": "gpt-4",
    "allow_roots": ["/workspace/output"],
    "deny_roots": [],
    "enforcement": "brokered"
  }
]
```
