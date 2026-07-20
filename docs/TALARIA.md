# Talaria has moved

The Hermes Agent + NemoClaw integration suite (formerly `talaria/` in this
repo) now lives in its own repository and PyPI package:

- Repo: https://github.com/inovinlabs/talaria
- Package: `pip install custodian-talaria`

It depends on this kernel through a normal version pin
(`custodian-kernel[paladin]>=0.4.0,<0.5`) rather than being versioned in
lockstep with it. See that repo's README for the full feature set,
quickstart, and the BlindKey feature comparison.

`paladin` (the credential broker) stays in this repo — it is brand-neutral
and has no Hermes-specific code, unlike `talaria`.
