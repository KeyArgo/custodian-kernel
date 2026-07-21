#!/usr/bin/env python3
import argparse, json, os
ALLOWED_OUTPUT_DIR = os.environ.get("CUSTODIAN_ALLOWED_WRITE_DIR", "/tmp")
p = argparse.ArgumentParser()
p.add_argument("--bucket", required=True)
p.add_argument("--key", required=True)
p.add_argument("--output", default=None, help="local path to save to")
a = p.parse_args()
key_id = os.environ.get("AWS_ACCESS_KEY_ID", "")
secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
if not key_id or not secret:
    print(json.dumps({"ok": False, "stub": True, "tool": "s3-get", "message": "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY to enable"})); exit(0)
try:
    import boto3
    s3 = boto3.client("s3", aws_access_key_id=key_id, aws_secret_access_key=secret)
    if a.output:
        # Declared L0 ("read-only, no real-world effects"), but --output
        # was passed straight to download_file() with no path validation --
        # S3-controlled bytes could overwrite any file the process can
        # write (~/.bashrc, a cron script, authorized_keys). Enforce the
        # same directory boundary as file-write.
        real = os.path.realpath(a.output)
        allowed_real = os.path.realpath(ALLOWED_OUTPUT_DIR)
        if real != allowed_real and not real.startswith(allowed_real + os.sep):
            raise PermissionError(f"--output must be under {ALLOWED_OUTPUT_DIR}")
        s3.download_file(a.bucket, a.key, a.output)
        print(json.dumps({"ok": True, "tool": "s3-get", "bucket": a.bucket, "key": a.key, "saved_to": a.output}))
    else:
        resp = s3.get_object(Bucket=a.bucket, Key=a.key)
        content = resp["Body"].read(4096).decode("utf-8", errors="replace")
        print(json.dumps({"ok": True, "tool": "s3-get", "bucket": a.bucket, "key": a.key, "content_preview": content}))
except ImportError:
    print(json.dumps({"ok": False, "tool": "s3-get", "error": "pip install boto3"}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "s3-get", "error": str(e)}))
