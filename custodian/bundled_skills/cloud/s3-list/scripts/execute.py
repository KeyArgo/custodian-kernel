#!/usr/bin/env python3
import argparse, json, os
p = argparse.ArgumentParser()
p.add_argument("--bucket", required=True)
p.add_argument("--prefix", default="")
p.add_argument("--limit", type=int, default=100)
a = p.parse_args()
key_id = os.environ.get("AWS_ACCESS_KEY_ID", "")
secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
if not key_id or not secret:
    print(json.dumps({"ok": False, "stub": True, "tool": "s3-list", "message": "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY to enable"})); exit(0)
try:
    import boto3
    s3 = boto3.client("s3", aws_access_key_id=key_id, aws_secret_access_key=secret)
    resp = s3.list_objects_v2(Bucket=a.bucket, Prefix=a.prefix, MaxKeys=a.limit)
    objects = [{"key": o["Key"], "size": o["Size"], "modified": o["LastModified"].isoformat()} for o in resp.get("Contents", [])]
    print(json.dumps({"ok": True, "tool": "s3-list", "bucket": a.bucket, "objects": objects, "count": len(objects)}))
except ImportError:
    print(json.dumps({"ok": False, "tool": "s3-list", "error": "pip install boto3"}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "s3-list", "error": str(e)}))
