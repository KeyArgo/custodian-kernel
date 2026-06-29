# OpenCode Task: Implement Communication Tools

## Context

You are implementing real execute scripts for Custodian-governed communication tools.
The repo is at the current working directory. Tools are under `skills/communication/`.
Each tool already has a stub `scripts/execute.py`. Replace the stub with a real implementation.

## The execute.py contract

- Accept args via `argparse` (each input as `--key value`)
- Print exactly ONE line of JSON to stdout: `{"ok": true/false, "tool": "<name>", ...}`
- Exit 0 on success, 1 on failure
- If required env var is missing, print `{"ok": false, "stub": true, "tool": "...", "message": "Set XYZ_API_KEY"}` and exit 0 (not 1)
- Never raise unhandled exceptions — catch all and return `{"ok": false, "error": "..."}`

## Tools to implement

### 1. `skills/communication/email-send/scripts/execute.py`

Args: `--to`, `--subject`, `--body`, `--from` (optional, default SMTP_FROM env var)

Logic:
- If env var `SENDGRID_API_KEY` is set: use SendGrid API (`requests.post` to `https://api.sendgrid.com/v3/mail/send`)
- Else if `SMTP_HOST` is set: use `smtplib.SMTP` with SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASS
- Else: stub response

Return: `{"ok": true, "tool": "email-send", "to": "<to>", "method": "sendgrid"|"smtp"}`

### 2. `skills/communication/sms-send/scripts/execute.py`

Args: `--to` (phone with country code), `--body`

Logic: Twilio REST API (`requests.post`)
- URL: `https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json`
- Auth: HTTPBasicAuth(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
- From: TWILIO_FROM_NUMBER env var
- Required env vars: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
- On success: `{"ok": true, "tool": "sms-send", "sid": "<message_sid>", "to": "<to>"}`

### 3. `skills/communication/slack-message/scripts/execute.py`

Args: `--channel` (or use SLACK_DEFAULT_CHANNEL), `--text`, `--webhook-url` (or SLACK_WEBHOOK_URL)

Logic: `requests.post(webhook_url, json={"text": text, "channel": channel})`
Required env: SLACK_WEBHOOK_URL (or --webhook-url arg)
Return: `{"ok": true, "tool": "slack-message", "channel": channel}`

### 4. `skills/communication/discord-webhook/scripts/execute.py`

Args: `--webhook-url` (or DISCORD_WEBHOOK_URL), `--content`, `--username` (optional)

Logic: `requests.post(url, json={"content": content, "username": username})`
Return: `{"ok": true, "tool": "discord-webhook"}`

### 5. `skills/communication/webhook-post/scripts/execute.py`

Args: `--url`, `--payload` (JSON string), `--headers` (JSON string, optional)

Logic:
```python
import json, requests
payload = json.loads(args.payload) if args.payload else {}
headers = json.loads(args.headers) if args.headers else {"Content-Type": "application/json"}
r = requests.post(args.url, json=payload, headers=headers, timeout=10)
```
Return: `{"ok": r.ok, "tool": "webhook-post", "status": r.status_code, "body": r.text[:500]}`

### 6. `skills/communication/push-notification/scripts/execute.py`

Args: `--title`, `--message`, `--topic` (optional, default NTFY_TOPIC or "custodian")

Logic: ntfy.sh (no auth needed for public topics)
```python
requests.post(f"https://ntfy.sh/{topic}", data=message.encode(), headers={"Title": title})
```
If PUSHOVER_TOKEN and PUSHOVER_USER set: use Pushover API instead.
Return: `{"ok": true, "tool": "push-notification", "method": "ntfy"|"pushover"}`

## Dependencies

Only use stdlib + `requests`. Do NOT add new dependencies.
`requests` is already in requirements.txt.

## After implementing each tool, verify:

```bash
python3 skills/communication/<name>/scripts/execute.py --help
python3 skills/communication/webhook-post/scripts/execute.py --url https://httpbin.org/post --payload '{"test": 1}'
```

The webhook-post test should return ok:true since httpbin is public.
