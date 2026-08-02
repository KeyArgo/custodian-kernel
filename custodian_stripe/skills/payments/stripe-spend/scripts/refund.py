#!/usr/bin/env python3
"""Authority-gated Stripe refund. Peer to spend.py, same trust boundary.

Unlike spend.py, this script has NO autonomous path at all -- there is no
band, no per-action cap, no session cap to check. Every refund, regardless
of amount, requires the human operator's real Twilio Verify code. That is
deliberate: reversing a charge is a different risk shape than making one,
and the simplest, most honest policy for it is 'always ask a human.'

Also verifies the referenced PaymentIntent was a real prior 'executed'
spend in this skill's own audit log, and that the refund amount does not
exceed what was actually charged -- the agent cannot request a refund
against a payment that never happened, or for more than was paid.
"""
import argparse
import json
import sqlite3
import sys

import _core


def _check_kill_switch():
    db_path = _core.SKILL_DIR / 'state' / 'custodian.db'
    if not db_path.exists():
        return False, '', ''
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute('SELECT killed, reason, by FROM kill_switch WHERE id = 1').fetchone()
        conn.close()
        if row is None:
            return False, '', ''
        return bool(row[0]), row[1] or '', row[2] or ''
    except sqlite3.Error:
        return False, '', ''


def _find_original_charge(payment_intent_id):
    """Returns the charged amount for a prior real 'executed' spend with this
    PaymentIntent ID, or None if no such charge exists in this skill's own
    audit log."""
    if not _core.LOG_FILE.exists():
        return None
    for line in _core.LOG_FILE.read_text().splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get('event') == 'executed' and record.get('payment_intent_id') == payment_intent_id:
            return record['amount']
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--payment-intent-id', required=True, help='The real PaymentIntent ID to refund')
    p.add_argument('--amount', type=float, required=True, help='USD amount to refund')
    p.add_argument('--description', required=True)
    p.add_argument('--denied-by', default=None, help='Human operator name, to log a denial')
    args = p.parse_args()

    killed, kill_reason, kill_by = _check_kill_switch()
    if killed:
        _core.append_log({
            'event': 'refund_denied', 'amount': args.amount, 'description': args.description,
            'payment_intent_id': args.payment_intent_id, 'denied_by': kill_by or 'operator',
            'reason': f'kill switch engaged: {kill_reason}' if kill_reason else 'kill switch engaged',
        })
        print(f"[authority] DENIED -- kill switch is engaged (by {kill_by or 'operator'}"
              f"{f', reason: ' + kill_reason if kill_reason else ''}).")
        print('[authority] This overrides every refund request, with no exceptions. '
              'Run `kill_toggle.py release --by <name>` to release it.')
        sys.exit(3)

    if args.denied_by:
        _core.append_log({
            'event': 'refund_denied', 'amount': args.amount, 'description': args.description,
            'payment_intent_id': args.payment_intent_id, 'denied_by': args.denied_by,
        })
        print(f'[audit] logged: refund_denied (by {args.denied_by})')
        print('No Stripe call made.')
        return

    original_amount = _find_original_charge(args.payment_intent_id)
    if original_amount is None:
        print(f'[authority] REJECTED -- {args.payment_intent_id} is not a real, prior executed '
              'charge in this skill\'s own audit log. Cannot refund a payment that never happened.')
        sys.exit(1)
    # Cumulative check: compare against what's LEFT to refund, not the original
    # charge. Without subtracting prior refunds, three $100 refunds against a
    # $100 charge each passed (>$100 total refunded). execute_refund re-checks
    # this authoritatively; rejecting here avoids escalating a doomed refund to
    # a human for a Twilio code.
    already_refunded = _core.refunded_amount(args.payment_intent_id)
    remaining = round(original_amount - already_refunded, 2)
    if args.amount > remaining:
        print(f'[authority] REJECTED -- refund amount ${args.amount:.2f} exceeds the ${remaining:.2f} '
              f'still refundable on {args.payment_intent_id} '
              f'(${original_amount:.2f} charged, ${already_refunded:.2f} already refunded).')
        sys.exit(1)

    import notify
    reason_str = f'refund of ${args.amount:.2f} against {args.payment_intent_id} -- all refunds require human approval, no exceptions'
    state = _core.load_state()
    try:
        notify.write_pending(args.amount, args.description, reason_str,
                              kind='refund', payment_intent_id=args.payment_intent_id)
    except notify.PendingEscalationExistsError as e:
        # See spend.py's identical handling: refuse rather than clobber a
        # still-live escalation someone else is waiting to approve.
        _core.append_log({
            'event': 'refund_denied', 'amount': args.amount, 'description': args.description,
            'payment_intent_id': args.payment_intent_id, 'band': state['band'],
            'reason': f'another escalation is already pending: {e}',
        })
        print(f'[authority] DENIED -- {e}')
        print('[authority] Only one escalation can be pending at a time. Wait for the '
              'current one to be approved or to expire, then retry.')
        sys.exit(2)
    notify.send_approval_code(args.amount, args.description)
    _core.append_log({
        'event': 'refund_escalation_required', 'amount': args.amount, 'description': args.description,
        'payment_intent_id': args.payment_intent_id, 'band': state['band'], 'reason': reason_str,
    })
    print(f'[authority] REFUND ESCALATION REQUIRED -- {reason_str}')
    print('[authority] A one-time approval code has been sent to the human operator\'s phone via Twilio Verify.')
    print('[audit] logged: refund_escalation_required')
    print('This script cannot execute the refund under any circumstances -- there is no '
          'override flag. The human must run `approve.py <code-from-their-phone> --approved-by <name>`.')
    sys.exit(2)


if __name__ == '__main__':
    main()
