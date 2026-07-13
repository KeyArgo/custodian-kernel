# Custodian Deployment Notes

## Enforcement Nodes

Three nodes run the custodian kernel. The enforcer tries the Spark chain
(spark-a, then spark-b) first (2s timeout each), falls back to argobox-lite
silently if every Spark node is unreachable.

### DGX Spark A — primary trust anchor
- **Host:** `bogart@10.0.0.50`
- **Service:** `enforce_server.py` on port 8095
- **Venv:** `/home/bogart/custodian-venv`
- **Code:** `/home/bogart/custodian-kernel/`
- **Log:** `/home/bogart/custodian-enforce.log`
- **Health:** `curl http://10.0.0.50:8095/health`

Start after reboot:
```bash
ssh bogart@10.0.0.50 "cd /home/bogart/custodian-kernel && nohup /home/bogart/custodian-venv/bin/python3 enforce_server.py > /home/bogart/custodian-enforce.log 2>&1 &"
```

### DGX Spark B — secondary trust anchor
- **Host:** `bogart@10.0.0.51`
- **Service:** `enforce_server.py` on port 8095
- **Venv:** `/home/bogart/custodian-venv`
- **Code:** `/home/bogart/custodian-kernel/`
- **Log:** `/home/bogart/custodian-enforce.log`
- **Health:** `curl http://10.0.0.51:8095/health`

Start after reboot:
```bash
ssh bogart@10.0.0.51 "cd /home/bogart/custodian-kernel && nohup /home/bogart/custodian-venv/bin/python3 enforce_server.py > /home/bogart/custodian-enforce.log 2>&1 &"
```

### argobox-lite — API server + local fallback
- **Host:** `argonaut@10.0.0.199` (jove network — your stable connection)
- **Service:** Flask app on port 8094
- **Code:** `/tmp/hermes-dash-v4/` ⚠️ **ephemeral — lost on reboot**
- **Venv:** `/tmp/hermes-dash-venv/`
- **Log:** `/tmp/hermes-dash.log`
- **Cloudflare tunnel:** running as argonaut, points at localhost:8094

> ⚠️ **IMPORTANT:** `/tmp/hermes-dash-v4` is in /tmp. If argobox-lite reboots,
> the app directory is gone. After a reboot you need to re-deploy:
> ```bash
> rsync -a custodian/ argonaut@10.0.0.199:/tmp/hermes-dash-v4/custodian/
> rsync -a dashboard/ argonaut@10.0.0.199:/tmp/hermes-dash-v4/dashboard/
> ssh argonaut@10.0.0.199 "cd /tmp/hermes-dash-v4/dashboard && nohup /tmp/hermes-dash-venv/bin/python3 app.py > /tmp/hermes-dash.log 2>&1 &"
> ```
> Or just run `./deploy-kernel.sh` which handles this automatically.
> If the path changed (argobox-lite rebuild), find the new path with:
> `ps aux | grep 'python app.py'` and update `LITE_APP_DIR` in `deploy-kernel.sh`.

---

## Updating the Kernel

After any code change:
```bash
./deploy-kernel.sh
```

If Spark's network (kronos) is saturated or down:
```bash
SKIP_SPARK=1 ./deploy-kernel.sh
```

If you only need to update the Spark:
```bash
SKIP_LITE=1 ./deploy-kernel.sh
```

---

## Removing the Spark from the Decision Path

To stop routing enforcement decisions through the Spark without touching code,
set this env var where Flask runs on argobox-lite:

```bash
export SPARK_ENFORCE_URL=''
```

Then restart Flask. The enforcer (`custodian/policy/enforcer.py`) checks this
at startup — empty string disables remote and uses local-only enforcement.

To make it permanent, add `SPARK_ENFORCE_URL=` to the secrets/operator.env file
on argobox-lite, or remove the enforcer.py → evaluator.py swap in engine.py:

```python
# custodian/packs/engine.py — revert this line to go back to local-only:
from custodian.policy.enforcer import decide   # ← current (Spark + fallback)
from custodian.policy.evaluator import decide  # ← revert to local-only
```

---

## Removing the Spark Entirely

1. Revert `engine.py` import (see above)
2. Delete `custodian/policy/enforcer.py`
3. Delete `spark-enforcement/`
4. Run `./deploy-kernel.sh`
5. Update website: remove Spark references from `pages-frontend/index.html`
   (search for "DGX Spark", "GB10", "Grace Blackwell")

---

## Failover Behaviour

| Spark status | What happens |
|---|---|
| Reachable, healthy | All enforcement decisions go to Spark |
| Slow (>2s) | Request times out, argobox-lite enforces locally |
| Down / unreachable | argobox-lite enforces locally, zero visible interruption |
| Wrong result | No validation — both nodes run identical code from same rsync |

Timeout is controlled by `SPARK_TIMEOUT` env var (default: `2` seconds).
