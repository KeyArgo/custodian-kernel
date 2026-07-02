/**
 * nemo-guide.js — Nemotron cross-page tour guide for Custodian
 *
 * Canonical tour path (from docs/SITE-FLOWCHART.md):
 *   Home → Console → Operator → Console (audit return) → Triage → Tools → Docs
 *
 * Behaviour:
 * - Creates a persistent Nemotron bubble + panel on every tour page.
 * - Auto-greets on first arrival at each new page; pulses (no auto-open) on return.
 * - On pages that already have a page-specific Nemotron widget (operator, triage),
 *   injects a tour-nav strip into their existing panel instead of spawning a
 *   second bubble.
 * - Shows "Next →" chip after greeting (context-aware for Console audit return).
 * - Resets per-page dismiss on navigation so Nemotron re-greets each new stop.
 * - Never auto-opens on mobile (≤680 px).
 */
(function () {
  'use strict';

  /* ─── Tour sequence ─────────────────────────────────────────── */
  // Console appears twice in the story (explain → prove → audit-return),
  // so we track the "audit return" as a virtual step via pending_console_followup.
  const TOUR_STEPS = [
    { path: '/',         label: 'Home',      idx: 0 },
    { path: '/console',  label: 'Console',   idx: 1 },
    { path: '/operator', label: 'Operator',  idx: 2 },
    { path: '/triage',   label: 'Triage',    idx: 3 },
    { path: '/tools',    label: 'Tools',     idx: 4 },
    { path: '/docs',     label: 'Docs',      idx: 5 },
  ];

  function nextStepFor(path, siteState) {
    // Console is context-sensitive:
    //   first visit  → go to Operator
    //   post-operator return → go to Triage
    if (path === '/console') {
      const postOp = siteState && siteState.pending_console_followup;
      return postOp ? { path: '/triage', label: 'Triage' } : { path: '/operator', label: 'Operator' };
    }
    // Operator always sends back to Console (audit return)
    if (path === '/operator') return { path: '/console', label: 'Console (audit)' };

    const step = TOUR_STEPS.find(t => t.path === path);
    if (!step) return null;
    const next = TOUR_STEPS.find(t => t.idx === step.idx + 1);
    return next ? { path: next.path, label: next.label } : null;
  }

  /* ─── Page-specific content ──────────────────────────────────── */
  // Greeting prompts are framed as visitor questions so Nemotron knows it is
  // answering a person, not generating its own monologue about itself.
  const PAGE_CFG = {
    '/': {
      greeting: "Hi — I just landed on this page. Who are you, what is Custodian, and what should I do first?",
      suggests: [
        "Why can't you just prompt the AI to stay in budget?",
        "What makes kernel enforcement different from a rate limit?",
        "What problem does Custodian solve that other tools don't?",
      ],
    },
    '/console': {
      greeting_first: "I just opened the Console. What am I looking at and where do I start?",
      greeting_postop: "I just came back from the Operator Panel where I ran all the steps. What should I look at here now?",
      suggests_first: [
        "What does the Console actually show that the operator panel doesn't?",
        "How does the kernel decide whether to allow or block a spend request?",
        "Why is the audit log tamper-evident?",
      ],
      suggests_postop: [
        "What exactly is recorded in the audit log for each step I ran?",
        "If I had hit the kill switch earlier, what would the log show?",
        "Why does refund always escalate — why no autonomous refund path?",
      ],
    },
    '/operator': {
      greeting: "I'm on the Operator Panel. What do I do first, and what will I see happen?",
      suggests: [
        "Why does refund always escalate — no autonomous refund path?",
        "What does the kill switch actually block at the kernel level?",
        "What's the difference between the authority band and the session budget?",
      ],
    },
    '/triage': {
      greeting: "What is this page and what should I try here?",
      suggests: [
        "What kinds of lies can the verifier actually catch?",
        "Why can't the AI just approve if it believes the customer?",
        "What would it take to fool the verifier rather than the AI?",
      ],
    },
    '/tools': {
      greeting: "What am I looking at on this page and why does it matter?",
      suggests: [
        "What happens if an agent calls a tool not in the registry?",
        "How are tools categorized — is there a trust tier?",
        "Can new tools be added at runtime, or only at config time?",
      ],
    },
    '/docs': {
      greeting: "I've seen the demo — now I want to understand how it actually works. Where do I start?",
      suggests: [
        "How does the kernel actually enforce limits — is it a firewall?",
        "What's NemoClaw and how does it relate to Nemotron?",
        "How does the audit log prevent tampering?",
      ],
    },
  };

  /* ─── Identify current page ──────────────────────────────────── */
  const currentPath = window.location.pathname.replace(/\/$/, '') || '/';
  const pageCfg = PAGE_CFG[currentPath];
  if (!pageCfg) return; // not a tour page

  /* ─── Site-tour shared state (from site-tour.js) ─────────────── */
  function getSiteTourState() {
    try { return JSON.parse(localStorage.getItem('custodian_site_tour_v1') || '{}'); }
    catch (_) { return {}; }
  }

  const siteState = getSiteTourState();
  const isPostOp  = currentPath === '/console' && !!siteState.pending_console_followup;

  const nextStep  = nextStepFor(currentPath, siteState);

  /* ─── Guide-specific state (per-page dismiss + visit tracking) ── */
  const NG_KEY      = 'custodian_ng_v1';
  // Use the same history key as site-tour.js and operator.html so Nemotron
  // carries context across all pages (console → operator → triage → tools → docs).
  const NG_HIST_KEY = 'custodian_nemotron_history';
  const NG_PATH_KEY = 'custodian_ng_last_path'; // sessionStorage — resets on tab close

  function getGuideState() {
    try { return Object.assign({ dismissed: {}, visited: [] }, JSON.parse(localStorage.getItem(NG_KEY) || '{}')); }
    catch (_) { return { dismissed: {}, visited: [] }; }
  }
  function saveGuideState(s) { try { localStorage.setItem(NG_KEY, JSON.stringify(s)); } catch (_) {} return s; }
  function getHistory() { try { return JSON.parse(localStorage.getItem(NG_HIST_KEY) || '[]'); } catch (_) { return []; } }
  function saveHistory(h) { try { localStorage.setItem(NG_HIST_KEY, JSON.stringify((h || []).slice(-16))); } catch (_) {} }

  // Detect genuine navigation (tab reuse across pages) vs same-page reload.
  // sessionStorage survives reload but resets on tab close — perfect nav detector.
  const _lastPath  = sessionStorage.getItem(NG_PATH_KEY);
  const _navigated = _lastPath !== currentPath;
  if (_navigated) {
    sessionStorage.setItem(NG_PATH_KEY, currentPath);
    try {
      // Reset shared dismiss so operator.html / triage.html auto-open again.
      const s = getSiteTourState();
      s.assistant_dismissed = false;
      localStorage.setItem('custodian_site_tour_v1', JSON.stringify(s));
      // Reset per-page guide dismiss so Nemotron reopens on every navigation.
      const gs = getGuideState();
      if (gs.dismissed) delete gs.dismissed[currentPath];
      saveGuideState(gs);
    } catch (_) {}
  }

  // Track visit
  const guideState   = getGuideState();
  const isFirstVisit = !(guideState.visited || []).includes(currentPath);
  // Open on first visit, explicit post-operator return, OR any navigation.
  const isNewArrival = isFirstVisit || isPostOp || _navigated;
  if (isFirstVisit) {
    guideState.visited = [...(guideState.visited || []), currentPath];
    saveGuideState(guideState);
  }

  /* ─── Pages with existing Nemotron widgets ───────────────────── */
  const EXISTING = {
    '/operator': { panelId: 'op-nemo-panel' },
    '/triage':   { panelId: 'tr-nemo-panel' },
    '/console':  { panelId: 'nemotron-chat-panel' },
  };

  if (EXISTING[currentPath]) {
    injectTourNavIntoExistingPanel(EXISTING[currentPath]);
    return;
  }

  /* ─── CSS ────────────────────────────────────────────────────── */
  const CSS = `
    #ng-bubble {
      position: fixed; bottom: 24px; right: 24px;
      width: 52px; height: 52px; border-radius: 50%;
      background: #08100a; border: 2px solid #76b900;
      cursor: pointer; display: flex; align-items: center; justify-content: center;
      font-size: 1.4em; z-index: 1200;
      box-shadow: 0 4px 20px rgba(118,185,0,.35);
      transition: transform .15s, box-shadow .2s;
      font-family: inherit; padding: 0; line-height: 1;
    }
    #ng-bubble:hover { transform: scale(1.08); box-shadow: 0 6px 30px rgba(118,185,0,.6); }
    @keyframes ng-pulse {
      0%   { box-shadow: 0 4px 20px rgba(118,185,0,.35); }
      45%  { box-shadow: 0 4px 36px rgba(118,185,0,.85), 0 0 0 9px rgba(118,185,0,.1); }
      100% { box-shadow: 0 4px 20px rgba(118,185,0,.35); }
    }
    #ng-bubble.ng-pulse { animation: ng-pulse 2.4s ease-in-out 0.3s 1; }
    #ng-panel {
      position: fixed; bottom: 86px; right: 24px;
      width: 346px; max-height: 550px;
      background: #060c08; border: 1px solid #1e3020;
      border-radius: 16px; display: none; flex-direction: column;
      z-index: 1201; box-shadow: 0 8px 44px rgba(0,0,0,.82);
      overflow: hidden;
      font-family: 'Space Grotesk', -apple-system, BlinkMacSystemFont, sans-serif;
      font-size: 14px;
    }
    .ng-hdr {
      display: flex; align-items: center; gap: 10px;
      padding: 12px 14px; border-bottom: 1px solid #1a2a10;
      background: rgba(118,185,0,.04); flex-shrink: 0;
    }
    .ng-breadcrumb {
      display: flex; align-items: center; gap: 4px;
      padding: 7px 14px 2px; flex-shrink: 0; flex-wrap: wrap;
    }
    .ng-bc-step {
      font-size: .6em; padding: 2px 8px; border-radius: 8px;
      border: 1px solid #1a2a10; color: #2e4a2e;
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      letter-spacing: .03em; text-decoration: none; cursor: default;
      transition: border-color .15s, color .15s;
    }
    .ng-bc-step.ng-cur  { border-color: rgba(118,185,0,.55); color: #76b900; background: rgba(118,185,0,.08); }
    .ng-bc-step.ng-done { color: #2a4a2a; text-decoration: line-through; text-decoration-color: #2a4a2a; }
    .ng-bc-step.ng-lnk  { cursor: pointer; }
    .ng-bc-step.ng-lnk:hover { border-color: rgba(118,185,0,.3); color: #5a9a5a; }
    .ng-body {
      flex: 1; overflow-y: auto; padding: 12px 14px;
      display: flex; flex-direction: column; gap: 9px;
      min-height: 80px; max-height: 290px;
      font-size: .84em; line-height: 1.6; color: #c8d8c0;
    }
    .ng-bot { align-self: flex-start; background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.07); border-radius: 12px 12px 12px 3px; padding: 8px 12px; max-width: 95%; word-break: break-word; }
    .ng-usr { align-self: flex-end; background: rgba(118,185,0,.1); border: 1px solid rgba(118,185,0,.2); border-radius: 12px 12px 3px 12px; padding: 8px 12px; max-width: 90%; word-break: break-word; }
    .ng-suggests { display: flex; flex-direction: column; gap: 5px; align-self: flex-start; max-width: 97%; margin-top: 3px; }
    .ng-slbl { font-size: .65em; letter-spacing: .1em; text-transform: uppercase; color: rgba(118,185,0,.38); font-family: monospace; }
    .ng-chip { background: rgba(118,185,0,.06); border: 1px solid rgba(118,185,0,.26); color: #9fd968; border-radius: 9px; padding: 7px 11px; font-family: inherit; font-size: .85em; text-align: left; cursor: pointer; display: flex; align-items: flex-start; gap: 6px; transition: background .15s, border-color .15s; }
    .ng-chip::before { content: '→'; color: rgba(118,185,0,.4); flex-shrink: 0; }
    .ng-chip:hover { background: rgba(118,185,0,.14); border-color: rgba(118,185,0,.5); color: #c0ff88; }
    .ng-next { align-self: flex-start; margin-top: 6px; background: rgba(118,185,0,.12); border: 1px solid rgba(118,185,0,.48); color: #9fd968; border-radius: 9px; padding: 9px 15px; font-family: inherit; font-size: .88em; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 7px; text-decoration: none; transition: background .15s; }
    .ng-next:hover { background: rgba(118,185,0,.24); color: #c0ff88; }
    .ng-foot { border-top: 1px solid #1a2a10; padding: 9px 11px; display: flex; gap: 7px; flex-shrink: 0; }
    .ng-inp { flex: 1; background: #0e1a10; border: 1px solid #2a3a1a; border-radius: 8px; color: #ccc; font-size: .85em; padding: 8px 11px; outline: none; font-family: inherit; transition: border-color .15s; }
    .ng-inp:focus { border-color: rgba(118,185,0,.4); }
    .ng-snd { background: rgba(118,185,0,.14); border: 1px solid #76b900; color: #76b900; border-radius: 8px; padding: 8px 13px; cursor: pointer; font-family: inherit; font-size: .9em; transition: background .15s; }
    .ng-snd:hover { background: rgba(118,185,0,.28); }
    @media (max-width: 680px) {
      #ng-panel { width: calc(100vw - 24px); right: 12px; bottom: 80px; max-height: 66vh; }
      .ng-body  { max-height: 44vh; }
    }
  `;
  const sEl = document.createElement('style');
  sEl.textContent = CSS;
  document.head.appendChild(sEl);

  /* ─── Widget HTML ────────────────────────────────────────────── */
  const bubble = document.createElement('button');
  bubble.id = 'ng-bubble'; bubble.title = 'Ask Nemotron'; bubble.innerHTML = '🤖';

  const panel = document.createElement('div');
  panel.id = 'ng-panel';
  panel.innerHTML = `
    <div class="ng-hdr">
      <span style="font-size:1.1em;line-height:1">🤖</span>
      <div style="flex:1;min-width:0">
        <div style="font-size:.78em;font-weight:700;color:#76b900;letter-spacing:.04em">Nemotron 3 Super</div>
        <div style="font-size:.67em;color:#3a5a3a">intelligence layer · tour guide</div>
      </div>
      <button id="ng-close" style="all:unset;cursor:pointer;color:#6a8a6a;font-size:.75em;font-weight:700;
        padding:5px 9px;border:1px solid rgba(118,185,0,.2);border-radius:4px;letter-spacing:.04em;
        white-space:nowrap" title="Minimize">✕</button>
    </div>
    <div class="ng-breadcrumb" id="ng-bc"></div>
    <div class="ng-body" id="ng-body"></div>
    <div class="ng-foot">
      <input id="ng-inp" class="ng-inp" type="text" placeholder="Ask Nemotron…">
      <button id="ng-snd" class="ng-snd">→</button>
    </div>`;

  document.body.appendChild(bubble);
  document.body.appendChild(panel);

  /* ─── Breadcrumb ─────────────────────────────────────────────── */
  const bcEl     = document.getElementById('ng-bc');
  const visited  = getGuideState().visited || [];
  TOUR_STEPS.forEach((t, i) => {
    if (i > 0) { const sep = document.createElement('span'); sep.style.cssText = 'color:#1e3020;font-size:.6em;align-self:center'; sep.textContent = '›'; bcEl.appendChild(sep); }
    const isCur  = t.path === currentPath;
    const isDone = !isCur && visited.includes(t.path);
    const isLnk  = !isCur && t.path;
    const el = isLnk ? document.createElement('a') : document.createElement('span');
    el.className = 'ng-bc-step' + (isCur ? ' ng-cur' : '') + (isDone ? ' ng-done' : '') + (isLnk ? ' ng-lnk' : '');
    el.textContent = t.label;
    if (isLnk) el.href = t.path;
    bcEl.appendChild(el);
  });

  /* ─── Chat ───────────────────────────────────────────────────── */
  const body   = document.getElementById('ng-body');
  let history  = getHistory();
  let opened   = false;

  // Fallback greetings shown when the API is unreachable.
  const FALLBACK_GREET = {
    '/':        "Hi — I'm Nemotron, the AI reasoning layer inside Custodian. This system puts a kernel-enforced authority layer between me and real money. Head to the Operator Panel to try it live.",
    '/tools':   "You're looking at the full tool registry — every action I can request, all governed by the same kernel authority.",
    '/docs':    "This is the architecture behind everything you've seen — kernel enforcement, authority bands, the verifier layer, and the audit trail.",
  };

  // Build the greeting prompt sent to the API.
  // First contact → intro question. Return visit → short bridging instruction.
  function buildGreetMsg(path, cfg, hist, postOp) {
    const PAGE_NAME = { '/': 'the home page', '/tools': 'the Tools page', '/docs': 'the Docs page' };
    if (postOp) return cfg.greeting_postop;
    if (hist.length === 0) {
      // True first contact — use the intro question
      return path === '/console' ? cfg.greeting_first : cfg.greeting;
    }
    // Returning user — bridge from the conversation, no re-introduction
    return `[TOUR CONTINUATION] The visitor just navigated to ${PAGE_NAME[path] || path}. In 1-2 sentences: ` +
      `acknowledge the tour so far and tell them what's on this page. Under 50 words. No re-introduction.`;
  }

  // Jump-key → real page path so [[jump:KEY|label]] renders as a real link.
  const JUMP_PAGE_MAP = {
    operator: '/operator',
    pipeline: '/console', verdict: '/console', authority: '/console',
    audit: '/console',   policy:  '/console', playground: '/console',
  };

  function addMsg(text, role) {
    const el = document.createElement('div');
    el.className = role === 'user' ? 'ng-usr' : 'ng-bot';
    if (role !== 'user') {
      // Render [[jump:KEY|label]] as real page links; strip other markers cleanly.
      const parts = text.split(/(\[\[jump:\w+\|[^\]]+\]\])/);
      parts.forEach(part => {
        const m = part.match(/^\[\[jump:(\w+)\|([^\]]+)\]\]$/);
        if (m) {
          const a = document.createElement('a');
          a.href = JUMP_PAGE_MAP[m[1]] || '/console';
          a.textContent = m[2];
          a.style.cssText = 'color:#9fd968;text-decoration:underline;cursor:pointer';
          el.appendChild(a);
        } else {
          const clean = part.replace(/\[\[(?:entry|suggest):[^\]]*\]\]/g, '');
          if (clean) el.appendChild(document.createTextNode(clean));
        }
      });
    } else {
      el.textContent = text;
    }
    body.appendChild(el); body.scrollTop = body.scrollHeight;
    return el;
  }

  function renderSuggests(list) {
    if (!list || !list.length) return;
    const wrap = document.createElement('div'); wrap.className = 'ng-suggests';
    const lbl = document.createElement('div'); lbl.className = 'ng-slbl'; lbl.textContent = 'Ask Nemotron'; wrap.appendChild(lbl);
    list.forEach(q => {
      const btn = document.createElement('button'); btn.className = 'ng-chip'; btn.textContent = q;
      btn.addEventListener('click', () => { wrap.remove(); sendQ(q); });
      wrap.appendChild(btn);
    });
    body.appendChild(wrap); body.scrollTop = body.scrollHeight;
  }

  function renderNext() {
    if (!nextStep) return;
    const a = document.createElement('a');
    a.className = 'ng-next'; a.href = nextStep.path;
    const label = isPostOp ? `Return to ${nextStep.label}` : `Next: ${nextStep.label}`;
    a.innerHTML = `${label} <span style="opacity:.6">→</span>`;
    body.appendChild(a); body.scrollTop = body.scrollHeight;
  }

  function sendQ(q) {
    addMsg(q, 'user');
    history.push({ role: 'user', content: q });
    const thinking = addMsg('…', 'bot');

    const siteCtx = window.CustodianTour
      ? window.CustodianTour.buildSiteContext({ ng_page: currentPath, ng_post_op: isPostOp })
      : { ng_page: currentPath, ng_post_op: isPostOp };

    fetch('/api/v1/nemotron/ask', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q, history: history.slice(-6), page: currentPath.replace(/^\//, '') || 'home', site_context: siteCtx }),
    })
    .then(r => r.json())
    .then(d => {
      thinking.remove();
      const ans = d.answer || "Ask me anything about what you're seeing.";
      addMsg(ans, 'bot');
      history.push({ role: 'assistant', content: ans });
      saveHistory(history);
    })
    .catch(() => { thinking.remove(); addMsg("Ask me anything about what you're seeing here.", 'bot'); });
  }

  function openPanel() {
    panel.style.display = 'flex';
    bubble.style.display = 'none';
    bubble.classList.remove('ng-pulse');

    if (!opened) {
      opened = true;

      const greetMsg = buildGreetMsg(currentPath, pageCfg, history, isPostOp);

      const thinking = addMsg('…', 'bot');
      fetch('/api/v1/nemotron/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: greetMsg,
          history: history.slice(-4),   // carry context from previous pages
          page: currentPath.replace(/^\//, '') || 'home',
          site_context: { ng_page: currentPath, ng_post_op: isPostOp, first_visit: isFirstVisit, has_history: history.length > 0 },
        }),
      })
      .then(r => r.json())
      .then(d => {
        thinking.remove();
        const raw = d.answer || FALLBACK_GREET[currentPath] || "Ask me anything about what you're seeing.";
        addMsg(raw, 'bot');
        history.push({ role: 'assistant', content: raw });
        saveHistory(history);
        const suggests = currentPath === '/console'
          ? (isPostOp ? pageCfg.suggests_postop : pageCfg.suggests_first)
          : pageCfg.suggests;
        setTimeout(() => { renderSuggests(suggests); renderNext(); }, 350);
      })
      .catch(() => {
        thinking.remove();
        addMsg(FALLBACK_GREET[currentPath] || "Ask me anything about what you're seeing here.", 'bot');
        const suggests = currentPath === '/console'
          ? (isPostOp ? pageCfg.suggests_postop : pageCfg.suggests_first)
          : pageCfg.suggests;
        setTimeout(() => { renderSuggests(suggests); renderNext(); }, 200);
      });
    }
    document.getElementById('ng-inp').focus();
  }

  function closePanel() {
    panel.style.display = 'none';
    bubble.style.display = 'flex';
    const s = getGuideState();
    s.dismissed = s.dismissed || {};
    s.dismissed[currentPath] = true;
    saveGuideState(s);
  }

  bubble.addEventListener('click', openPanel);
  document.getElementById('ng-close').addEventListener('click', closePanel);

  const inp = document.getElementById('ng-inp');
  document.getElementById('ng-snd').addEventListener('click', () => { const q = inp.value.trim(); if (!q) return; inp.value = ''; body.querySelectorAll('.ng-suggests').forEach(e => e.remove()); sendQ(q); });
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') { const q = inp.value.trim(); if (!q) return; inp.value = ''; body.querySelectorAll('.ng-suggests').forEach(e => e.remove()); sendQ(q); } });

  /* ─── Auto-open logic ────────────────────────────────────────── */
  const freshState  = getGuideState();
  const isDismissed = (freshState.dismissed || {})[currentPath];
  const isMobile    = window.matchMedia('(max-width: 680px)').matches;

  if (!isMobile && !isDismissed && isNewArrival) {
    setTimeout(openPanel, 1400);
  } else if (!isMobile && !isDismissed) {
    bubble.classList.add('ng-pulse');
  }

  /* ══════════════════════════════════════════════════════════════
     Tour-nav injection for operator.html + triage.html
     (those pages have their own bubble — we add a tour strip to
     their existing panel instead of spawning a second bubble)
     ══════════════════════════════════════════════════════════════ */
  function injectTourNavIntoExistingPanel({ panelId }) {
    const INJECT_CSS = `
      .ng-ext-wrap { border-top: 1px solid #1a2a10; padding: 10px 14px; display: flex; flex-direction: column; gap: 7px; flex-shrink: 0; background: rgba(118,185,0,.02); }
      .ng-ext-bc   { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
      .ng-ext-step { font-size: .6em; padding: 2px 8px; border-radius: 8px; border: 1px solid #1a2a10; color: #2e4a2e; font-family: 'JetBrains Mono', monospace; letter-spacing: .03em; text-decoration: none; cursor: default; }
      .ng-ext-step.c { border-color: rgba(118,185,0,.5); color: #76b900; background: rgba(118,185,0,.07); }
      .ng-ext-step.d { color: #2a4a2a; text-decoration: line-through; text-decoration-color: #2a4a2a; }
      .ng-ext-step.l { cursor: pointer; }
      .ng-ext-step.l:hover { border-color: rgba(118,185,0,.3); color: #5a9a5a; }
      .ng-ext-next { display: inline-flex; align-items: center; gap: 6px; background: rgba(118,185,0,.12); border: 1px solid rgba(118,185,0,.45); color: #9fd968; border-radius: 9px; padding: 8px 14px; font-size: .84em; font-weight: 600; text-decoration: none; transition: background .15s; }
      .ng-ext-next:hover { background: rgba(118,185,0,.24); color: #c0ff88; }
    `;
    const s = document.createElement('style'); s.textContent = INJECT_CSS; document.head.appendChild(s);

    function doInject() {
      if (document.getElementById('ng-ext-injected')) return;
      const panelEl = document.getElementById(panelId);
      if (!panelEl) return;

      const wrap = document.createElement('div'); wrap.className = 'ng-ext-wrap'; wrap.id = 'ng-ext-injected';

      // Breadcrumb
      const bc = document.createElement('div'); bc.className = 'ng-ext-bc';
      const v2 = getGuideState().visited || [];
      TOUR_STEPS.forEach((t, i) => {
        if (i > 0) { const sep = document.createElement('span'); sep.style.cssText = 'color:#1e3020;font-size:.6em;align-self:center'; sep.textContent = '›'; bc.appendChild(sep); }
        const isCur  = t.path === currentPath;
        const isDone = !isCur && v2.includes(t.path);
        const isLnk  = !isCur && t.path;
        const el = isLnk ? document.createElement('a') : document.createElement('span');
        el.className = 'ng-ext-step' + (isCur ? ' c' : '') + (isDone ? ' d' : '') + (isLnk ? ' l' : '');
        el.textContent = t.label;
        if (isLnk) el.href = t.path;
        bc.appendChild(el);
      });
      wrap.appendChild(bc);

      // Next chip
      const nxt = nextStepFor(currentPath, getSiteTourState());
      if (nxt) {
        const a = document.createElement('a'); a.className = 'ng-ext-next'; a.href = nxt.path;
        const lbl = currentPath === '/operator' ? `Back to ${nxt.label}` : `Next: ${nxt.label}`;
        a.innerHTML = `${lbl} <span style="opacity:.6">→</span>`;
        wrap.appendChild(a);
      }
      panelEl.appendChild(wrap);
    }

    function observe() {
      doInject();
      const target = document.getElementById(panelId);
      if (target) { const obs = new MutationObserver(doInject); obs.observe(target, { attributes: true, attributeFilter: ['style'] }); }
    }

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', observe); }
    else { observe(); }
  }

})();
