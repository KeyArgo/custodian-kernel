(function () {
  const TOUR_KEY = 'custodian_site_tour_v1';
  const HISTORY_KEY = 'custodian_nemotron_history';

  function isMobile() {
    return window.matchMedia('(max-width: 680px)').matches;
  }

  function nowIso() {
    return new Date().toISOString();
  }

  function defaultState() {
    return {
      mode: null,
      stage: null,
      assistant_behavior: 'on_request',
      assistant_dismissed: false,
      home_offer_seen: false,
      home_offer_dismissed: false,
      quick_console_started: false,
      deep_console_started: false,
      console_post_operator_seen: false,
      triage_tools_nudged: false,
      docs_nudged: false,
      operator_step: null,
      last_completed_action: null,
      pending_console_followup: false,
      pending_tools_followup: false,
      pending_docs_followup: false,
      events: [],
      updated_at: nowIso(),
    };
  }

  function getState() {
    try {
      const raw = JSON.parse(localStorage.getItem(TOUR_KEY) || '{}');
      return Object.assign(defaultState(), raw || {});
    } catch (_) {
      return defaultState();
    }
  }

  function saveState(state) {
    state.updated_at = nowIso();
    localStorage.setItem(TOUR_KEY, JSON.stringify(state));
    return state;
  }

  function patchState(patch) {
    const state = getState();
    Object.assign(state, patch || {});
    return saveState(state);
  }

  function setMode(mode) {
    const behavior = mode === 'free'
      ? 'on_request'
      : mode === 'quick'
        ? 'proactive'
        : 'milestone_only';
    return patchState({
      mode,
      assistant_behavior: behavior,
      assistant_dismissed: false,
    });
  }

  function dismissAssistant() {
    return patchState({ assistant_dismissed: true });
  }

  function enableAssistant() {
    return patchState({ assistant_dismissed: false });
  }

  function markHomeOfferSeen() {
    return patchState({ home_offer_seen: true });
  }

  function setStage(stage) {
    const state = getState();
    state.stage = stage;
    state.updated_at = nowIso();
    return saveState(state);
  }

  function recordEvent(type, payload) {
    const state = getState();
    const events = Array.isArray(state.events) ? state.events : [];
    events.push({
      type,
      payload: payload || {},
      ts: nowIso(),
    });
    state.events = events.slice(-30);
    return saveState(state);
  }

  function getHistory() {
    try {
      return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    } catch (_) {
      return [];
    }
  }

  function saveHistory(history) {
    localStorage.setItem(HISTORY_KEY, JSON.stringify((history || []).slice(-16)));
  }

  function onPage(page) {
    setStage(page);
    recordEvent('page_view', { page });
  }

  function markOperatorStep(step, details) {
    const state = getState();
    state.operator_step = step;
    if (details && details.completed) {
      state.last_completed_action = 'operator_step_' + step;
    }
    if (step === 8 && details && details.completed) {
      state.last_completed_action = 'operator_refund_approved';
      state.pending_console_followup = true;
      state.console_post_operator_seen = false;
    }
    return saveState(state);
  }

  function completeConsoleFollowup() {
    return patchState({
      pending_console_followup: false,
      console_post_operator_seen: true,
      last_completed_action: 'console_audit_followup',
    });
  }

  function nudgeTools() {
    return patchState({
      pending_tools_followup: true,
      triage_tools_nudged: true,
      last_completed_action: 'triage_explained',
    });
  }

  function completeTools() {
    return patchState({
      pending_tools_followup: false,
      pending_docs_followup: true,
      last_completed_action: 'tools_explained',
    });
  }

  function completeDocs() {
    return patchState({
      pending_docs_followup: false,
      docs_nudged: true,
      last_completed_action: 'docs_explained',
    });
  }

  function buildSiteContext(extra) {
    const state = getState();
    return Object.assign({
      mode: state.mode,
      stage: state.stage,
      assistant_behavior: state.assistant_behavior,
      operator_step: state.operator_step,
      last_completed_action: state.last_completed_action,
      pending_console_followup: state.pending_console_followup,
      pending_tools_followup: state.pending_tools_followup,
      pending_docs_followup: state.pending_docs_followup,
      mobile: isMobile(),
    }, extra || {});
  }

  window.CustodianTour = {
    TOUR_KEY,
    HISTORY_KEY,
    isMobile,
    getState,
    patchState,
    setMode,
    dismissAssistant,
    enableAssistant,
    markHomeOfferSeen,
    setStage,
    recordEvent,
    getHistory,
    saveHistory,
    onPage,
    markOperatorStep,
    completeConsoleFollowup,
    nudgeTools,
    completeTools,
    completeDocs,
    buildSiteContext,
  };
})();
