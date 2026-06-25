#!/usr/bin/env bash
# The "one-click moment" demo: walks the real NemoClaw sandbox through the
# complete Custodian arc in one narrated run, for screen recording or a live
# demo. This is NOT a simulation -- every step is a real Stripe test-mode
# call, a real Twilio Verify SMS, and a real kernel-enforced kill switch.
#
# It cannot be fully automated end-to-end, by design: steps 2 and 6 send a
# real SMS code to the operator's phone and the script pauses for it. That
# pause IS the point -- it's the same human-in-the-loop boundary the whole
# project demonstrates, not a rough edge to engineer away.
#
# Usage: scripts/demo_moment.sh <sandbox-name> <approved-by-name>
# Example: scripts/demo_moment.sh hermes-hackathon Operator
set -euo pipefail

SANDBOX="${1:?Usage: demo_moment.sh <sandbox-name> <approved-by-name>}"
APPROVER="${2:?Usage: demo_moment.sh <sandbox-name> <approved-by-name>}"
SCRIPTS_DIR="/sandbox/.hermes/skills/payments/stripe-spend/scripts"

exec_remote() {
    nemohermes "$SANDBOX" exec -- python3 "$SCRIPTS_DIR/$@"
}

banner() {
    echo
    echo "================================================================"
    echo "  $1"
    echo "================================================================"
}

pause_for_code() {
    echo
    read -rp ">>> Enter the Twilio Verify code from the operator's phone: " CODE
    echo "$CODE"
}

banner "STEP 1 -- autonomous spend, within authority (no human needed)"
echo "Requesting an \$85.00 spend the agent is allowed to make on its own..."
exec_remote spend.py --amount 85.00 --description "Demo: cloud backup storage renewal"
echo
echo "--> That PaymentIntent ID is what we'll refund in step 6."
read -rp "Press Enter to continue to the over-budget request... "

banner "STEP 2 -- over-budget spend, real escalation (REAL SMS incoming)"
echo "Requesting \$3,500.00 -- this exceeds the current band. Watch your phone."
set +e
exec_remote spend.py --amount 3500.00 --description "Demo: NAS license renewal"
set -e
echo
echo "--> The agent CANNOT proceed past this point. There is no override flag."
CODE=$(pause_for_code)

banner "STEP 3 -- human approves with the real Twilio Verify code"
exec_remote approve.py "$CODE" --approved-by "$APPROVER"
read -rp "Press Enter to continue to the kill switch... "

banner "STEP 4 -- engage the kill switch"
exec_remote kill_toggle.py engage --by "$APPROVER" --reason "demo: proving the override is absolute"
echo
echo "Now attempting an in-budget spend that would normally succeed instantly..."
set +e
exec_remote spend.py --amount 40.00 --description "Demo: this should be denied"
set -e
echo
echo "--> Denied regardless of band/cap. No exceptions, no override flag exists."
read -rp "Press Enter to release the kill switch... "

banner "STEP 5 -- release the kill switch"
exec_remote kill_toggle.py release --by "$APPROVER"
read -rp "Press Enter to continue to the refund (REAL SMS incoming again)... "

banner "STEP 6 -- refund always escalates, even for a tiny amount"
echo "Requesting a refund of the step-1 charge. Unlike spend, refunds have NO autonomous path at all."
echo "You'll need the PaymentIntent ID printed in step 1 -- paste it below."
read -rp ">>> PaymentIntent ID from step 1: " PI_ID
set +e
exec_remote refund.py --payment-intent-id "$PI_ID" --amount 85.00 --description "Demo: refund -- double-billed"
set -e
CODE=$(pause_for_code)

banner "STEP 7 -- human approves the refund"
exec_remote approve.py "$CODE" --approved-by "$APPROVER"

banner "DONE -- the complete arc just ran for real"
cat <<'EOF'
What just happened, all real, no simulation:
  1. An AI agent requested money autonomously, within its authority band.
  2. It requested more than its band allows -- and could not act on it,
     full stop, until a human approved via a code the agent never saw.
  3. A kill switch denied a normally-fine request instantly, no override.
  4. Releasing the kill switch returned the system to normal evaluation.
  5. A refund request escalated unconditionally -- refunds have no
     autonomous path at all, regardless of amount.

Watch it land live at https://rein.argobox.com -- the audit feed, kernel
policy log, and decision pipeline all update in real time as this runs.
EOF
