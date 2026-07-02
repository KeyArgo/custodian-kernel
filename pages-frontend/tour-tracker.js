/**
 * tour-tracker.js — per-user interaction tracker for Nemotron context
 *
 * Records every meaningful thing this browser's user has done across the site
 * so Nemotron always knows what they've seen, what they've completed, and what
 * to guide them toward next.
 *
 * Storage: localStorage 'custodian_tour_track_v1' (per-browser, per-user).
 * API:     window.TourTracker — call track(), then pass buildContext() into
 *          any Nemotron API call as tracker_context.
 */
(function () {
  'use strict';

  const KEY = 'custodian_tour_track_v1';

  const ALL_CONSOLE_TABS  = ['audit', 'policy', 'try', 'stripe'];
  const ALL_OPERATOR_STEPS = [0, 1, 2, 3, 4, 5, 6, 7, 8];
  const TOUR_PAGES = ['/', '/console', '/operator', '/triage', '/tools', '/docs'];

  const OPERATOR_STEP_LABELS = {
    0: 'Earn $1200 (uncapped revenue)',
    1: 'Spend $85 autonomously (within band)',
    2: 'Request $3500 escalation (SMS sent)',
    3: 'Approve $3500 override (SMS code)',
    4: 'Engage kill switch',
    5: 'Prove kill switch blocks spend',
    6: 'Release kill switch',
    7: 'Refund $85 (escalation sent)',
    8: 'Approve refund (SMS code)',
  };

  const CONSOLE_TAB_LABELS = {
    audit:  'Audit Feed',
    policy: 'Kernel Policy log',
    try:    'Try It Yourself (sandbox)',
    stripe: 'Live Stripe Balance',
  };

  /* ── Storage helpers ─────────────────────────────────────────────── */
  function get() {
    try { return JSON.parse(localStorage.getItem(KEY) || '{}'); }
    catch (_) { return {}; }
  }

  function save(s) {
    try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (_) {}
  }

  /* ── Core track function ─────────────────────────────────────────── */
  function track(eventType, detail) {
    const s   = get();
    const now = Math.floor(Date.now() / 1000);

    s.last_action = { type: eventType, detail: detail || null, ts: now };

    switch (eventType) {
      case 'page_visit': {
        const pages = s.pages_visited || [];
        if (!pages.includes(detail)) pages.push(detail);
        s.pages_visited = pages;
        break;
      }
      case 'console_tab': {
        const tabs = s.console_tabs_seen || [];
        if (!tabs.includes(detail)) tabs.push(detail);
        s.console_tabs_seen = tabs;
        break;
      }
      case 'operator_step': {
        const n     = Number(detail);
        const steps = s.operator_steps_done || [];
        if (!steps.includes(n)) steps.push(n);
        steps.sort((a, b) => a - b);
        s.operator_steps_done = steps;
        if (steps.length >= ALL_OPERATOR_STEPS.length) s.operator_complete = true;
        break;
      }
      case 'triage_run': {
        const runs = s.triage_runs || [];
        runs.push({ ...(typeof detail === 'object' ? detail : { scenario: detail }), ts: now });
        s.triage_runs = runs.slice(-20);
        break;
      }
      case 'tool_expand': {
        const tools = s.tools_expanded || [];
        if (!tools.includes(detail)) tools.push(detail);
        s.tools_expanded = tools;
        break;
      }
    }

    save(s);
    return s;
  }

  /* ── Context builder — sent to Nemotron on every API call ────────── */
  function buildContext() {
    const s     = get();
    const pages = s.pages_visited || [];
    const tabs  = s.console_tabs_seen || [];
    const steps = s.operator_steps_done || [];
    const runs  = s.triage_runs || [];

    const operator_complete    = !!(s.operator_complete || steps.length >= ALL_OPERATOR_STEPS.length);
    const console_tabs_unseen  = ALL_CONSOLE_TABS.filter(t => !tabs.includes(t));
    const operator_steps_remaining = ALL_OPERATOR_STEPS.filter(n => !steps.includes(n));

    // Human-readable summaries for the model
    const steps_done_labels     = steps.map(n => `Step ${n}: ${OPERATOR_STEP_LABELS[n] || n}`);
    const steps_remain_labels   = operator_steps_remaining.map(n => `Step ${n}: ${OPERATOR_STEP_LABELS[n] || n}`);
    const tabs_seen_labels      = tabs.map(t => CONSOLE_TAB_LABELS[t] || t);
    const tabs_unseen_labels    = console_tabs_unseen.map(t => CONSOLE_TAB_LABELS[t] || t);
    const pages_not_visited     = TOUR_PAGES.filter(p => !pages.includes(p));

    // Derive what to suggest next
    let suggested_next;
    if (!pages.includes('/'))         suggested_next = 'home page (start of tour)';
    else if (!pages.includes('/console'))  suggested_next = '/console — explain the system';
    else if (!pages.includes('/operator')) suggested_next = '/operator — run the live demo';
    else if (!operator_complete)           suggested_next = `/operator — complete remaining steps (${operator_steps_remaining.join(', ')})`;
    else if (!pages.includes('/console'))  suggested_next = '/console — audit return (see what was recorded)';
    else if (runs.length === 0)            suggested_next = '/triage — prove AI alone is not enough';
    else if (!pages.includes('/tools'))    suggested_next = '/tools — see scope beyond payments';
    else if (!pages.includes('/docs'))     suggested_next = '/docs — understand the architecture';
    else                                   suggested_next = 'tour complete — all pages visited and demo done';

    return {
      // What they've visited
      pages_visited:           pages,
      pages_not_yet_visited:   pages_not_visited,
      // Console tab tracking
      console_tabs_seen:       tabs_seen_labels,
      console_tabs_not_seen:   tabs_unseen_labels,
      // Operator progress
      operator_steps_done:     steps_done_labels,
      operator_steps_remaining: steps_remain_labels,
      operator_complete,
      // Triage
      triage_runs_count:       runs.length,
      last_triage:             runs.length > 0 ? runs[runs.length - 1] : null,
      // Tools
      tools_expanded:          s.tools_expanded || [],
      // Last thing they did
      last_action:             s.last_action || null,
      // What to guide them toward
      suggested_next,
    };
  }

  function reset() {
    try { localStorage.removeItem(KEY); } catch (_) {}
  }

  window.TourTracker = { track, get, buildContext, reset };
})();
