// static/js/script.js — Smart ATS frontend logic
'use strict';

const API_BASE = `${window.location.protocol}//${window.location.host}`;

document.addEventListener('DOMContentLoaded', () => {
    /* ---------------- Element refs ---------------- */
    const $ = (id) => document.getElementById(id);
    const submitBtn = $('submit-btn');
    const heroEval = $('hero-eval');
    const jdInput = $('jd');
    const charCount = $('char-count');
    const resumeInput = $('resume');
    const dropArea = $('drop-area');
    const dropText = $('drop-text');
    const acceptText = $('accept-text');
    const filePreview = $('file-preview');
    const fileName = $('file-name');
    const fileRemove = $('file-remove');
    const fileIco = document.querySelector('.file-ico');
    const resultsContainer = $('results-container');
    const resultsContent = $('results-content');
    const errorContainer = $('error-container');
    const loader = $('loader');
    const resultReset = $('result-reset');
    const themeToggle = $('theme-toggle');
    const themeIcon = document.querySelector('.theme-icon');
    const navBurger = $('nav-burger');
    const header = document.querySelector('.site-header');
    const historyList = $('history-list');
    const historyRefresh = $('history-refresh');
    const uploadRadios = document.querySelectorAll('input[name="upload-type"]');

    // Holds the most recent analysis context, used by the AI Career Toolkit
    let lastContext = null;

    /* ---------------- Toasts ---------------- */
    const toastStack = $('toast-stack');
    function toast(message, type = 'info', timeout = 3800) {
        if (!toastStack) return;
        const el = document.createElement('div');
        el.className = `toast ${type}`;
        const icons = { success: '✅', error: '⚠️', info: 'ℹ️' };
        const ico = document.createElement('span');
        ico.textContent = icons[type] || '';
        const msg = document.createElement('span');
        msg.textContent = message;           // textContent → no HTML injection
        el.append(ico, msg);
        toastStack.appendChild(el);
        setTimeout(() => {
            el.classList.add('out');
            el.addEventListener('animationend', () => el.remove());
        }, timeout);
    }

    /* ---------------- Theme ---------------- */
    function applyTheme(theme) {
        document.body.classList.toggle('light', theme === 'light');
        if (themeIcon) themeIcon.textContent = theme === 'light' ? '☀️' : '🌙';
        localStorage.setItem('smartats_theme', theme);
    }
    applyTheme(localStorage.getItem('smartats_theme') || 'dark');
    themeToggle?.addEventListener('click', () => {
        applyTheme(document.body.classList.contains('light') ? 'dark' : 'light');
    });

    /* ---------------- Mobile nav ---------------- */
    navBurger?.addEventListener('click', () => header.classList.toggle('nav-open'));
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', () => header.classList.remove('nav-open'));
    });

    /* ---------------- 3D tilt effect ---------------- */
    const supportsHover = window.matchMedia('(hover: hover)').matches;
    if (supportsHover) {
        document.querySelectorAll('[data-tilt]').forEach(el => {
            const strength = parseFloat(el.dataset.tiltStrength || '8');
            el.addEventListener('pointermove', (e) => {
                const r = el.getBoundingClientRect();
                const px = (e.clientX - r.left) / r.width;
                const py = (e.clientY - r.top) / r.height;
                const rx = (0.5 - py) * strength;
                const ry = (px - 0.5) * strength;
                el.style.transform = `perspective(900px) rotateX(${rx}deg) rotateY(${ry}deg)`;
            });
            el.addEventListener('pointerleave', () => { el.style.transform = ''; });
        });
    }

    /* drop-area pointer glow */
    dropArea?.addEventListener('pointermove', (e) => {
        const r = dropArea.getBoundingClientRect();
        dropArea.style.setProperty('--mx', `${e.clientX - r.left}px`);
        dropArea.style.setProperty('--my', `${e.clientY - r.top}px`);
    });

    /* ---------------- Reveal on scroll ---------------- */
    const io = new IntersectionObserver((entries) => {
        entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
    }, { threshold: 0.12 });
    document.querySelectorAll('.reveal').forEach(el => io.observe(el));

    /* scroll progress bar */
    const scrollBar = $('scroll-bar');
    function updateScrollBar() {
        const h = document.documentElement;
        const scrolled = h.scrollTop / (h.scrollHeight - h.clientHeight || 1);
        if (scrollBar) scrollBar.style.width = `${Math.min(100, scrolled * 100)}%`;
    }
    window.addEventListener('scroll', updateScrollBar, { passive: true });
    updateScrollBar();

    /* nav active state on scroll */
    const sections = ['home', 'analyzer', 'features', 'history'].map($).filter(Boolean);
    const navObserver = new IntersectionObserver((entries) => {
        entries.forEach(e => {
            if (e.isIntersecting) {
                document.querySelectorAll('.nav-link').forEach(l =>
                    l.classList.toggle('active', l.getAttribute('href') === `#${e.target.id}`));
            }
        });
    }, { threshold: 0.4 });
    sections.forEach(s => navObserver.observe(s));

    /* ---------------- JD char counter ---------------- */
    jdInput?.addEventListener('input', () => {
        if (charCount) charCount.textContent = jdInput.value.length;
        checkFormReady();
    });

    /* ---------------- Upload type toggle ---------------- */
    function updateAcceptForType(type) {
        clearFile();
        if (type === 'image') {
            resumeInput.setAttribute('accept', 'image/*');
            dropText.innerHTML = 'Drag &amp; drop your image, or <span class="link">browse</span>';
            acceptText.textContent = 'JPG, PNG, WEBP accepted · max 10MB';
        } else {
            resumeInput.setAttribute('accept', '.pdf');
            dropText.innerHTML = 'Drag &amp; drop your PDF, or <span class="link">browse</span>';
            acceptText.textContent = 'Only PDF files are accepted · max 10MB';
        }
    }
    uploadRadios.forEach(r => r.addEventListener('change', (e) => updateAcceptForType(e.target.value)));

    /* ---------------- File handling ---------------- */
    function onFileSelected(file) {
        if (!file) return;
        const MAX = 10 * 1024 * 1024;
        if (file.size > MAX) {
            toast('File is larger than 10MB.', 'error');
            clearFile();
            return;
        }
        fileName.textContent = file.name;
        if (fileIco) fileIco.textContent = file.type.startsWith('image') ? '🖼️' : '📄';
        filePreview.classList.remove('hidden');
        checkFormReady();
    }
    function clearFile() {
        resumeInput.value = '';
        filePreview.classList.add('hidden');
        checkFormReady();
    }

    resumeInput?.addEventListener('change', () => onFileSelected(resumeInput.files?.[0]));
    fileRemove?.addEventListener('click', (e) => { e.stopPropagation(); clearFile(); });

    if (dropArea) {
        ['dragenter', 'dragover'].forEach(evt =>
            dropArea.addEventListener(evt, (e) => { e.preventDefault(); dropArea.classList.add('dragover'); }));
        ['dragleave', 'drop'].forEach(evt =>
            dropArea.addEventListener(evt, (e) => { e.preventDefault(); dropArea.classList.remove('dragover'); }));
        dropArea.addEventListener('drop', (e) => {
            const files = e.dataTransfer?.files;
            if (files?.length) {
                const dt = new DataTransfer();
                dt.items.add(files[0]);
                resumeInput.files = dt.files;
                onFileSelected(files[0]);
            }
        });
        dropArea.addEventListener('click', (e) => {
            if (e.target.closest('.file-remove')) return;
            resumeInput.click();
        });
    }

    /* ---------------- Form readiness ---------------- */
    function checkFormReady() {
        const hasJD = jdInput?.value.trim().length > 0;
        const hasFile = resumeInput?.files?.length > 0;
        if (submitBtn) submitBtn.disabled = !(hasJD && hasFile);
    }

    /* ---------------- Loader / view state ---------------- */
    const LOADER_MESSAGES = [
        'Reading your resume…',
        'Extracting skills & keywords…',
        'Matching against the job description…',
        'Scoring ATS compatibility…',
        'Writing your personalized feedback…',
    ];
    let loaderTimer = null;
    const loaderTextEl = loader?.querySelector('.loader-text');

    function showLoader(on) {
        resultsContainer.classList.remove('hidden');
        loader.classList.toggle('hidden', !on);
        resultsContent.classList.toggle('hidden', on);
        clearInterval(loaderTimer);
        if (on) {
            let i = 0;
            if (loaderTextEl) loaderTextEl.textContent = LOADER_MESSAGES[0];
            loaderTimer = setInterval(() => {
                i = (i + 1) % LOADER_MESSAGES.length;
                if (loaderTextEl) {
                    loaderTextEl.style.opacity = '0';
                    setTimeout(() => {
                        loaderTextEl.textContent = LOADER_MESSAGES[i];
                        loaderTextEl.style.opacity = '1';
                    }, 200);
                }
            }, 2200);
            resultsContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }
    function showError(message) {
        errorContainer.textContent = `⚠️ ${message}`;
        errorContainer.classList.remove('hidden');
        toast(message, 'error');
    }
    function clearError() { errorContainer.classList.add('hidden'); }

    /* ---------------- Score helpers ---------------- */
    function parseScore(val) {
        if (val == null) return 0;
        const m = String(val).match(/\d+(\.\d+)?/);
        return m ? Math.min(100, Math.round(parseFloat(m[0]))) : 0;
    }
    function verdictFor(score) {
        if (score >= 75) return { cls: 'v-strong', text: '🚀 Strong match' };
        if (score >= 50) return { cls: 'v-mid', text: '⚖️ Moderate match' };
        return { cls: 'v-low', text: '🔧 Needs work' };
    }
    function scoreColor(score) {
        if (score >= 75) return '#34d399';
        if (score >= 50) return '#fbbf24';
        return '#fb7185';
    }

    /* ---------------- Render results ---------------- */
    function displayResults(data) {
        const score = parseScore(data['JD Match']);
        const verdict = verdictFor(score);
        const color = scoreColor(score);
        const circ = 327; // 2πr, r=52
        const offset = circ - (circ * score) / 100;
        const keywords = Array.isArray(data.MissingKeywords) ? data.MissingKeywords : [];
        const summary = data['Profile Summary'] || 'No summary provided.';
        const health = data._ats_health || null;
        const triage = data.KeywordTriage || null;
        const entrySignal = data.entry_level_signal === true;

        resultsContent.innerHTML = `
            ${entrySignal ? `<div class="info-banner"><span>🎓 Heads up — this role likely targets <strong>3+ years</strong> of experience. Focus on the <em>quick wins</em> below and lean on transferable strengths.</span><button class="banner-close" aria-label="Dismiss">✕</button></div>` : ''}
            ${health ? buildAtsHealthHtml(health) : ''}
            <div class="result-top">
                <div class="score-card" style="--band:${color}">
                    <div class="score-ring-wrap">
                        <svg class="score-svg" viewBox="0 0 120 120">
                            <defs>
                                <linearGradient id="scoreGrad" x1="0" y1="0" x2="120" y2="120">
                                    <stop offset="0" stop-color="#8b5cf6"></stop>
                                    <stop offset="1" stop-color="${color}"></stop>
                                </linearGradient>
                            </defs>
                            <circle class="score-bg" cx="60" cy="60" r="52"></circle>
                            <circle class="score-fg" cx="60" cy="60" r="52" stroke="url(#scoreGrad)"
                                stroke-dasharray="${circ}" stroke-dashoffset="${circ}"></circle>
                        </svg>
                        <div class="score-center">
                            <span class="num" data-target="${score}" style="color:${color}">0%</span>
                            <span class="lbl">JD Match</span>
                        </div>
                    </div>
                    <span class="score-verdict ${verdict.cls}">${verdict.text}</span>
                </div>
                <div class="result-block profile-summary">
                    <h3><span class="ico">📝</span> Profile Summary &amp; Feedback</h3>
                    <p>${escapeHtml(summary)}</p>
                </div>
            </div>
            ${buildKeywordsHtml(triage, keywords)}
        `;

        // animate ring + count up
        requestAnimationFrame(() => {
            const fg = resultsContent.querySelector('.score-fg');
            if (fg) fg.style.strokeDashoffset = offset;
            animateCount(resultsContent.querySelector('.num'), score);
        });

        // celebrate strong matches
        if (score >= 80 && !prefersReducedMotion) setTimeout(celebrate, 600);

        // Save context for the Career Toolkit and reveal its CTA
        lastContext = {
            jd: jdInput.value.trim(),
            resume_text: data._resume_text || '',
            evaluation_id: data._evaluation_id || null,
            analysis: {
                'JD Match': data['JD Match'],
                'MissingKeywords': keywords,
                'Profile Summary': summary,
            },
        };
        resetToolkit();
        toolkitCta?.classList.remove('hidden');

        clearError();
        resultsContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function animateCount(el, target) {
        if (!el) return;
        const dur = 1300, start = performance.now();
        function step(now) {
            const t = Math.min(1, (now - start) / dur);
            const eased = 1 - Math.pow(1 - t, 3);
            el.textContent = `${Math.round(eased * target)}%`;
            if (t < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
    }

    function escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = String(str);
        return d.innerHTML;
    }

    // Build the ATS Health card (deterministic checks from the server)
    function buildAtsHealthHtml(h) {
        const rows = (h.checks || []).map(c => `
            <li class="ats-check ${c.ok ? 'ok' : 'bad'}">
                <span class="ats-ico">${c.ok ? '✓' : '✕'}</span>
                <span class="ats-row"><strong>${escapeHtml(c.label)}</strong><span>${escapeHtml(c.detail)}</span></span>
            </li>`).join('');
        const allGood = h.parse_ok && h.passed === h.total;
        const cls = allGood ? 'v-strong' : (h.passed >= Math.ceil(h.total / 2) ? 'v-mid' : 'v-low');
        const badge = h.is_scanned ? 'Needs attention' : `${h.passed}/${h.total} passed`;
        return `
            <div class="result-block ats-health">
                <h3><span class="ico">🩺</span> ATS Health Check <span class="ats-badge ${cls}">${badge}</span></h3>
                <ul class="ats-list">${rows}</ul>
            </div>`;
    }

    // Build the keyword section: triaged groups when available, else flat list
    function buildKeywordsHtml(triage, keywords) {
        const must = (triage && Array.isArray(triage.must_have)) ? triage.must_have : [];
        const nice = (triage && Array.isArray(triage.nice_to_have)) ? triage.nice_to_have : [];
        const wins = (triage && Array.isArray(triage.quick_wins)) ? triage.quick_wins : [];
        const hasTriage = must.length || nice.length || wins.length;

        if (!hasTriage) {
            const flat = keywords.length
                ? keywords.map((k, i) => `<span class="keyword" style="animation-delay:${i * 40}ms">${escapeHtml(k)}</span>`).join('')
                : '<span class="no-missing">🎉 No missing keywords — your resume covers the role well!</span>';
            return `<div class="result-block"><h3><span class="ico">🔑</span> Missing Keywords ${keywords.length ? `<span class="muted-count">(${keywords.length})</span>` : ''}</h3><div class="keywords">${flat}</div></div>`;
        }

        const chips = (arr, cls) => arr.map((k, i) =>
            `<span class="keyword ${cls}" style="animation-delay:${i * 40}ms">${escapeHtml(String(k))}</span>`).join('');

        const winsHtml = wins.length ? `
            <div class="kw-group">
                <div class="kw-group-head"><span class="kw-dot quickwin"></span> Quick wins <span class="muted-count">${wins.length}</span></div>
                <div class="quickwin-list">
                    ${wins.map(w => `<div class="quickwin"><span class="keyword kw-quickwin">${escapeHtml(String(w.keyword || ''))}</span><span class="qw-how">${escapeHtml(String(w.how_to_add || ''))}</span></div>`).join('')}
                </div>
            </div>` : '';
        const mustHtml = must.length ? `
            <div class="kw-group">
                <div class="kw-group-head"><span class="kw-dot must"></span> Must-have <span class="muted-count">${must.length}</span></div>
                <div class="keywords">${chips(must, 'kw-must')}</div>
            </div>` : '';
        const niceHtml = nice.length ? `
            <div class="kw-group">
                <div class="kw-group-head"><span class="kw-dot nice"></span> Nice-to-have <span class="muted-count">${nice.length}</span></div>
                <div class="keywords">${chips(nice, 'kw-nice')}</div>
            </div>` : '';

        return `<div class="result-block"><h3><span class="ico">🔑</span> Keyword Gaps, Triaged</h3><div class="kw-groups">${winsHtml}${mustHtml}${niceHtml}</div></div>`;
    }

    // Safe date formatting (SQLite UTC timestamps); guards 'Invalid Date'
    function formatDate(raw) {
        if (!raw) return '';
        let d = new Date(String(raw).replace(' ', 'T') + 'Z');
        if (isNaN(d)) d = new Date(raw);
        return isNaN(d) ? '' : d.toLocaleString();
    }

    // Clipboard copy with a fallback for non-secure (http) contexts
    function copyText(text) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text);
        }
        return new Promise((resolve) => {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            try { document.execCommand('copy'); } catch (_) { /* ignore */ }
            ta.remove();
            resolve();
        });
    }

    /* ---------------- Submit ---------------- */
    async function handleSubmit() {
        const jd = jdInput.value.trim();
        const file = resumeInput.files?.[0];
        if (!jd || !file) { showError('Please provide both a job description and a resume.'); return; }

        clearError();
        showLoader(true);
        submitBtn.classList.add('loading');
        submitBtn.disabled = true;

        const formData = new FormData();
        formData.append('jd', jd);
        formData.append('resume', file);

        try {
            const res = await fetch(`${API_BASE}/evaluate`, { method: 'POST', body: formData, credentials: 'include' });
            const result = await res.json();
            if (res.status === 401) {
                // Session expired or logged out — prompt sign-in instead of erroring out.
                showLoader(false);
                resultsContainer.classList.add('hidden');
                openAuth('login');
                toast('Please log in to analyze your resume.', 'error');
                return;
            }
            if (!res.ok) {
                throw new Error(result.raw_response ? `${result.error}: ${result.raw_response}` : (result.error || 'Unknown error'));
            }
            showLoader(false);
            displayResults(result);
            toast('Analysis complete!', 'success');
            loadHistory();
            loadStats();
        } catch (err) {
            showLoader(false);
            resultsContainer.classList.add('hidden');
            showError(err.message);
        } finally {
            submitBtn.classList.remove('loading');
            checkFormReady();
        }
    }
    submitBtn?.addEventListener('click', (e) => { e.preventDefault(); handleSubmit(); });

    /* hero CTA + reset */
    heroEval?.addEventListener('click', () => {
        // Guests get the sign-up prompt; logged-in users jump to the analyzer.
        if (!document.body.classList.contains('authed')) { openAuth('register'); return; }
        $('analyzer')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    resultReset?.addEventListener('click', () => {
        resultsContainer.classList.add('hidden');
        resetToolkit();
        $('analyzer')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });

    /* ---------------- History ---------------- */
    async function loadHistory() {
        try {
            const res = await fetch(`${API_BASE}/history`, { credentials: 'include' });
            const rows = await res.json();
            if (!Array.isArray(rows) || rows.length === 0) {
                historyList.innerHTML = '<p class="history-empty">No analyses yet. Run one above!</p>';
                return;
            }
            historyList.innerHTML = rows.map(row => {
                const score = parseScore(row.response?.['JD Match']);
                const color = scoreColor(score);
                const date = formatDate(row.created_at);
                return `
                    <div class="history-item">
                        <div class="hist-score" style="color:${color}">${score}%</div>
                        <div class="hist-meta">
                            <div class="hist-file">${escapeHtml(row.filename || 'resume')} <span style="color:var(--muted);font-weight:400">· ${row.upload_type || ''}</span></div>
                            <div class="hist-jd">${escapeHtml((row.jd || '').slice(0, 110))}…</div>
                        </div>
                        <div class="hist-date">${date}</div>
                    </div>`;
            }).join('');
        } catch (err) {
            historyList.innerHTML = '<p class="history-empty">Couldn\'t load history.</p>';
        }
    }
    historyRefresh?.addEventListener('click', loadHistory);

    /* ---------------- Authentication ---------------- */
    const signinBtn = $('signin-btn');
    const userMenu = $('user-menu');
    const userAvatar = $('user-avatar');
    const userDropdown = $('user-dropdown');
    const userNameEl = $('user-name');
    const userEmailEl = $('user-email');
    const logoutBtn = $('logout-btn');
    const authOverlay = $('auth-overlay');
    const authClose = $('auth-close');
    const authForm = $('auth-form');
    const authTabs = document.querySelector('.auth-tabs');
    const authTabBtns = document.querySelectorAll('.auth-tab');
    const nameField = document.querySelector('.name-field');
    const auName = $('au-name');
    const auEmail = $('au-email');
    const auPassword = $('au-password');
    const authError = $('auth-error');
    const authSubmit = $('auth-submit');
    const authTitle = $('auth-title');
    const authSub = $('auth-sub');
    const authSwitchText = $('auth-switch-text');
    const authSwitchBtn = $('auth-switch-btn');

    let authMode = 'login';

    function initials(name, email) {
        if (name && name.trim()) {
            const parts = name.trim().split(/\s+/);
            return (parts[0][0] + (parts[1]?.[0] || '')).toUpperCase();
        }
        return (email || '?')[0].toUpperCase();
    }

    function setUser(user) {
        const authed = !!user;
        // Drives the login gate: body.guest hides the tools, body.authed reveals them.
        document.body.classList.toggle('authed', authed);
        document.body.classList.toggle('guest', !authed);
        if (user) {
            signinBtn?.classList.add('hidden');
            userMenu?.classList.remove('hidden');
            if (userAvatar) userAvatar.textContent = initials(user.name, user.email);
            if (userNameEl) userNameEl.textContent = user.name || 'User';
            if (userEmailEl) userEmailEl.textContent = user.email || '';
            // Reveal gated sections the scroll-observer skipped while they were hidden.
            document.querySelectorAll('#analyzer, #history, #dashboard').forEach(el => el.classList.add('in'));
        } else {
            signinBtn?.classList.remove('hidden');
            userMenu?.classList.add('hidden');
            userDropdown?.classList.add('hidden');
            // Back to the guest view — clear any open report/toolkit so nothing lingers.
            resultsContainer?.classList.add('hidden');
            resetToolkit();
        }
    }

    function setAuthMode(mode) {
        authMode = mode;
        const reg = mode === 'register';
        authTabs?.classList.toggle('reg', reg);
        authTabBtns.forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
        nameField?.classList.toggle('hidden', !reg);
        authTitle.textContent = reg ? 'Create your account' : 'Welcome back';
        authSub.textContent = reg
            ? 'Sign up to save and track your resume analyses.'
            : 'Sign in to save and track your resume analyses.';
        authSubmit.querySelector('.btn-label').textContent = reg ? 'Create account' : 'Sign In';
        authSwitchText.textContent = reg ? 'Already have an account?' : 'New here?';
        authSwitchBtn.textContent = reg ? 'Sign in instead' : 'Create an account';
        auPassword.setAttribute('autocomplete', reg ? 'new-password' : 'current-password');
        // "Forgot password?" only makes sense when signing in.
        document.getElementById('auth-forgot')?.classList.toggle('hidden', reg);
        authError.classList.add('hidden');
    }

    function openAuth(mode = 'login') {
        hideOtpStep();
        setAuthMode(mode);
        authOverlay?.classList.remove('hidden');
        authOverlay?.setAttribute('aria-hidden', 'false');
        setTimeout(() => (reg => reg ? auName : auEmail)(mode === 'register')?.focus(), 80);
    }
    function closeAuth() {
        authOverlay?.classList.add('hidden');
        authOverlay?.setAttribute('aria-hidden', 'true');
        authForm?.reset();
        otpForm?.reset();
        forgotForm?.reset();
        resetForm?.reset();
        clearSpecial();
        authError.classList.add('hidden');
    }

    signinBtn?.addEventListener('click', () => openAuth('login'));
    $('gate-register')?.addEventListener('click', () => openAuth('register'));
    $('gate-login')?.addEventListener('click', () => openAuth('login'));
    authClose?.addEventListener('click', closeAuth);
    authOverlay?.addEventListener('click', (e) => { if (e.target === authOverlay) closeAuth(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && authOverlay && !authOverlay.classList.contains('hidden')) closeAuth(); });
    authTabBtns.forEach(b => b.addEventListener('click', () => setAuthMode(b.dataset.mode)));
    authSwitchBtn?.addEventListener('click', () => setAuthMode(authMode === 'login' ? 'register' : 'login'));

    authForm?.addEventListener('submit', async (e) => {
        e.preventDefault();
        authError.classList.add('hidden');
        const email = auEmail.value.trim();
        const payload = { email, password: auPassword.value };
        if (authMode === 'register') payload.name = auName.value.trim();

        authSubmit.classList.add('loading');
        authSubmit.disabled = true;
        try {
            const res = await fetch(`${API_BASE}/api/${authMode}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(payload),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Something went wrong.');

            // Registration no longer logs in immediately — it emails a code first.
            if (authMode === 'register' && data.needs_otp) {
                showOtpStep(data.email || email, data.delivery);
                return;
            }
            setUser(data.user);
            closeAuth();
            toast('Signed in successfully!', 'success');
            loadHistory();
            loadStats();
        } catch (err) {
            authError.textContent = err.message;
            authError.classList.remove('hidden');
        } finally {
            authSubmit.classList.remove('loading');
            authSubmit.disabled = false;
        }
    });

    /* ---------------- OTP / forgot / reset (modal special views) ---------------- */
    const authModal = document.querySelector('.auth-modal');
    const otpForm = $('otp-form');
    const otpInput = $('otp-input');
    const otpError = $('otp-error');
    const otpSubmit = $('otp-submit');
    const otpEmailLabel = $('otp-email-label');
    const otpResend = $('otp-resend');
    const otpBack = $('otp-back');
    const forgotForm = $('forgot-form');
    const forgotEmail = $('forgot-email');
    const forgotError = $('forgot-error');
    const forgotMsg = $('forgot-msg');
    const forgotSubmit = $('forgot-submit');
    const forgotLink = $('forgot-link');
    const forgotBack = $('forgot-back');
    const resetForm = $('reset-form');
    const resetPassword = $('reset-password');
    const resetPassword2 = $('reset-password2');
    const resetError = $('reset-error');
    const resetSubmit = $('reset-submit');
    const specialForms = [otpForm, forgotForm, resetForm];
    let pendingEmail = null;     // email awaiting OTP verification
    let pendingResetToken = null; // token from the emailed reset link

    // Swap the modal into a single "special" form (verify / forgot / reset).
    function showSpecial(formEl) {
        authModal?.classList.add('modal-special');
        specialForms.forEach(f => f?.classList.add('hidden'));
        formEl?.classList.remove('hidden');
    }
    function clearSpecial() {
        authModal?.classList.remove('modal-special');
        specialForms.forEach(f => f?.classList.add('hidden'));
        pendingEmail = null;
        pendingResetToken = null;
    }

    function showOtpStep(email, delivery) {
        pendingEmail = email;
        showSpecial(otpForm);
        if (otpEmailLabel) otpEmailLabel.textContent = email;
        if (authTitle) authTitle.textContent = 'Verify your email';
        if (authSub) authSub.textContent = 'One quick step to secure your account.';
        otpError?.classList.add('hidden');
        if (otpInput) otpInput.value = '';
        setTimeout(() => otpInput?.focus(), 80);
        toast(delivery === 'email'
            ? 'We emailed you a 6-digit code.'
            : 'Dev mode: your code was printed to the server console.', 'info', 5200);
    }
    // Kept as the generic "leave any special view" used by openAuth/closeAuth.
    function hideOtpStep() { clearSpecial(); }

    function showForgotStep() {
        showSpecial(forgotForm);
        if (authTitle) authTitle.textContent = 'Reset your password';
        if (authSub) authSub.textContent = 'We’ll email you a secure reset link.';
        forgotError?.classList.add('hidden');
        forgotMsg?.classList.add('hidden');
        if (forgotEmail) forgotEmail.value = auEmail?.value.trim() || '';
        setTimeout(() => forgotEmail?.focus(), 80);
    }

    function showResetStep(token) {
        pendingResetToken = token;
        showSpecial(resetForm);
        if (authTitle) authTitle.textContent = 'Set a new password';
        if (authSub) authSub.textContent = 'Choose a new password to finish.';
        resetError?.classList.add('hidden');
        if (resetPassword) resetPassword.value = '';
        if (resetPassword2) resetPassword2.value = '';
        setTimeout(() => resetPassword?.focus(), 80);
    }

    otpBack?.addEventListener('click', () => { clearSpecial(); setAuthMode('register'); });
    forgotLink?.addEventListener('click', showForgotStep);
    forgotBack?.addEventListener('click', () => { clearSpecial(); setAuthMode('login'); });

    // Only allow digits in the code box.
    otpInput?.addEventListener('input', () => {
        otpInput.value = otpInput.value.replace(/\D/g, '').slice(0, 6);
    });

    otpForm?.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!pendingEmail) return;
        otpError.classList.add('hidden');
        const otp = (otpInput.value || '').trim();
        if (!/^\d{6}$/.test(otp)) {
            otpError.textContent = 'Enter the 6-digit code.';
            otpError.classList.remove('hidden');
            return;
        }
        otpSubmit.classList.add('loading');
        otpSubmit.disabled = true;
        try {
            const res = await fetch(`${API_BASE}/api/verify-otp`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ email: pendingEmail, otp }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Could not verify the code.');
            const name = data.user?.name;
            setUser(data.user);
            hideOtpStep();
            closeAuth();
            toast(`Welcome, ${name || 'there'}! Your account is ready.`, 'success');
            loadHistory();
            loadStats();
            if (!prefersReducedMotion) setTimeout(celebrate, 300);
        } catch (err) {
            otpError.textContent = err.message;
            otpError.classList.remove('hidden');
        } finally {
            otpSubmit.classList.remove('loading');
            otpSubmit.disabled = false;
        }
    });

    otpResend?.addEventListener('click', async () => {
        if (!pendingEmail) return;
        otpError.classList.add('hidden');
        otpResend.disabled = true;
        try {
            const res = await fetch(`${API_BASE}/api/resend-otp`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ email: pendingEmail }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Could not resend the code.');
            toast(data.delivery === 'email'
                ? 'A new code is on its way.'
                : 'Dev mode: new code printed to the server console.', 'info', 5200);
        } catch (err) {
            otpError.textContent = err.message;
            otpError.classList.remove('hidden');
        } finally {
            setTimeout(() => { otpResend.disabled = false; }, 1200);
        }
    });

    /* request a password-reset link */
    forgotForm?.addEventListener('submit', async (e) => {
        e.preventDefault();
        forgotError.classList.add('hidden');
        forgotMsg.classList.add('hidden');
        const email = forgotEmail.value.trim();
        if (!email) {
            forgotError.textContent = 'Please enter your email.';
            forgotError.classList.remove('hidden');
            return;
        }
        forgotSubmit.classList.add('loading');
        forgotSubmit.disabled = true;
        try {
            const res = await fetch(`${API_BASE}/api/forgot-password`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ email }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Something went wrong.');
            // Generic message either way — we don't reveal whether the email exists.
            forgotMsg.textContent = data.message || 'If that email is registered, a reset link is on its way.';
            forgotMsg.classList.remove('hidden');
            toast('Check your email for the reset link.', 'info', 5200);
        } catch (err) {
            forgotError.textContent = err.message;
            forgotError.classList.remove('hidden');
        } finally {
            forgotSubmit.classList.remove('loading');
            forgotSubmit.disabled = false;
        }
    });

    /* set a new password using the emailed token */
    resetForm?.addEventListener('submit', async (e) => {
        e.preventDefault();
        resetError.classList.add('hidden');
        const pw = resetPassword.value;
        const pw2 = resetPassword2.value;
        if (pw.length < 6) {
            resetError.textContent = 'Password must be at least 6 characters.';
            resetError.classList.remove('hidden');
            return;
        }
        if (pw !== pw2) {
            resetError.textContent = 'The two passwords don’t match.';
            resetError.classList.remove('hidden');
            return;
        }
        resetSubmit.classList.add('loading');
        resetSubmit.disabled = true;
        try {
            const res = await fetch(`${API_BASE}/api/reset-password`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ token: pendingResetToken, password: pw }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Could not reset your password.');
            clearSpecial();
            setAuthMode('login');
            if (auEmail) auEmail.focus();
            toast('Password reset! Please sign in with your new password.', 'success', 5200);
        } catch (err) {
            resetError.textContent = err.message;
            resetError.classList.remove('hidden');
        } finally {
            resetSubmit.classList.remove('loading');
            resetSubmit.disabled = false;
        }
    });

    // avatar dropdown
    userAvatar?.addEventListener('click', (e) => { e.stopPropagation(); userDropdown?.classList.toggle('hidden'); });
    document.addEventListener('click', (e) => {
        if (userMenu && !userMenu.contains(e.target)) userDropdown?.classList.add('hidden');
    });

    logoutBtn?.addEventListener('click', async () => {
        try {
            await fetch(`${API_BASE}/api/logout`, { method: 'POST', credentials: 'include' });
        } catch (_) { /* ignore */ }
        setUser(null);
        toast('Signed out.', 'info');
        loadHistory();
        loadStats();
    });

    async function fetchMe() {
        try {
            const res = await fetch(`${API_BASE}/api/me`, { credentials: 'include' });
            const data = await res.json();
            setUser(data.user);
            if (data.user) { loadHistory(); loadStats(); }
        } catch (_) { setUser(null); }
    }

    /* ---------------- AI Career Toolkit ---------------- */
    const toolkitCta = $('toolkit-cta');
    const toolkitBtn = $('toolkit-btn');
    const toolkitPanel = $('toolkit-panel');
    const coverLetterEl = $('cover-letter');
    const interviewListEl = $('interview-list');
    const resumeTipsEl = $('resume-tips');
    const skillRoadmapEl = $('skill-roadmap');
    const coverCopyBtn = $('cover-copy');
    const coverDownloadBtn = $('cover-download');

    function resetToolkit() {
        toolkitPanel?.classList.add('hidden');
        toolkitCta?.classList.add('hidden');
        if (coverLetterEl) coverLetterEl.textContent = '';
        if (interviewListEl) interviewListEl.innerHTML = '';
        if (resumeTipsEl) resumeTipsEl.innerHTML = '';
        if (skillRoadmapEl) skillRoadmapEl.innerHTML = '';
    }

    async function generateToolkit() {
        if (!lastContext) return;
        toolkitBtn.classList.add('loading');
        toolkitBtn.disabled = true;
        try {
            const res = await fetch(`${API_BASE}/toolkit`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(lastContext),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Could not generate toolkit.');
            renderToolkit(data);
            toolkitCta.classList.add('hidden');
            toolkitPanel.classList.remove('hidden');
            toolkitPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
            toast('Your career toolkit is ready!', 'success');
        } catch (err) {
            toast(err.message, 'error');
        } finally {
            toolkitBtn.classList.remove('loading');
            toolkitBtn.disabled = false;
        }
    }

    function renderToolkit(data) {
        // Cover letter
        if (coverLetterEl) coverLetterEl.textContent = data.cover_letter || 'No cover letter generated.';

        // Interview Q&A
        const qs = Array.isArray(data.interview_questions) ? data.interview_questions : [];
        interviewListEl.innerHTML = qs.length ? qs.map((q, i) => `
            <div class="qa-item">
                <div class="qa-q"><span class="qa-num">${i + 1}</span><span>${escapeHtml(q.question || q.q || '')}</span><span class="chev">▾</span></div>
                <div class="qa-a"><div class="qa-a-inner"><span class="tip-label">💡 Tip:</span> ${escapeHtml(q.tip || '')}</div></div>
            </div>`).join('') : '<p class="muted">No questions generated.</p>';

        // Resume tips — copy reads from the <p> text (no attribute injection)
        const tips = Array.isArray(data.resume_tips) ? data.resume_tips : [];
        resumeTipsEl.innerHTML = tips.length ? tips.map(t => `
            <div class="tip-item">
                <span class="tip-bullet">✦</span>
                <p>${escapeHtml(t)}</p>
                <button class="tip-copy" title="Copy" aria-label="Copy">📋</button>
            </div>`).join('') : '<p class="muted">No tips generated.</p>';

        // Skill roadmap
        const skills = Array.isArray(data.skill_roadmap) ? data.skill_roadmap : [];
        skillRoadmapEl.innerHTML = skills.length ? skills.map(s => `
            <div class="skill-card">
                <div class="skill-name">${escapeHtml(s.skill || '')}</div>
                <p class="skill-why">${escapeHtml(s.why || '')}</p>
                <p class="skill-how"><strong>How to learn:</strong> ${escapeHtml(s.how || '')}</p>
            </div>`).join('') : '<p class="muted">No roadmap generated.</p>';

        // Personal brand
        renderBrand(data);
    }

    function renderBrand(data) {
        const brandEl = $('brand-content');
        if (!brandEl) return;
        const pitch = data.elevator_pitch || '';
        const li = data.linkedin || {};
        const headline = li.headline || '';
        const about = li.about || '';
        const pivot = data.pivot || {};
        const hasPivot = pivot.likely_concern && pivot.rebuttal;

        brandEl.innerHTML = `
            <div class="brand-card">
                <div class="brand-card-head"><h4>🎤 30-second pitch</h4>
                    <div class="brand-tools">
                        <button class="brand-speak btn btn-ghost btn-sm" title="Read aloud">🔊 Read aloud</button>
                        <button class="brand-copy btn btn-ghost btn-sm">📋 Copy</button>
                    </div>
                </div>
                <p class="brand-pitch">${escapeHtml(pitch)}</p>
            </div>
            <div class="brand-card">
                <div class="brand-card-head"><h4>💼 LinkedIn headline</h4>
                    <div class="brand-tools"><span class="brand-charcount">${headline.length}/120</span>
                        <button class="brand-copy btn btn-ghost btn-sm">📋 Copy</button></div>
                </div>
                <p class="brand-headline">${escapeHtml(headline)}</p>
            </div>
            <div class="brand-card">
                <div class="brand-card-head"><h4>📝 LinkedIn “About”</h4>
                    <div class="brand-tools"><button class="brand-copy btn btn-ghost btn-sm">📋 Copy</button></div>
                </div>
                <p class="brand-about">${escapeHtml(about)}</p>
            </div>
            ${hasPivot ? `
            <div class="brand-card pivot-card">
                <div class="brand-card-head"><h4>🧭 Address the pivot</h4></div>
                <p class="pivot-concern"><strong>Likely concern:</strong> ${escapeHtml(pivot.likely_concern)}</p>
                <p class="pivot-rebuttal"><strong>Your answer:</strong> ${escapeHtml(pivot.rebuttal)}</p>
            </div>` : ''}
        `;
    }

    toolkitBtn?.addEventListener('click', generateToolkit);

    // tab switching
    document.querySelectorAll('.tk-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const target = tab.dataset.tab;
            document.querySelectorAll('.tk-tab').forEach(t => t.classList.toggle('active', t === tab));
            document.querySelectorAll('.tk-body').forEach(b => b.classList.toggle('active', b.dataset.body === target));
        });
    });

    // Q&A accordion + all copy/speak buttons (event delegation)
    toolkitPanel?.addEventListener('click', (e) => {
        const q = e.target.closest('.qa-q');
        if (q) { q.parentElement.classList.toggle('open'); return; }

        const tipCopy = e.target.closest('.tip-copy');
        if (tipCopy) {
            const text = tipCopy.parentElement.querySelector('p')?.textContent || '';
            copyText(text).then(() => {
                tipCopy.textContent = '✓'; toast('Copied to clipboard', 'success');
                setTimeout(() => (tipCopy.textContent = '📋'), 1500);
            });
            return;
        }

        const brandCopy = e.target.closest('.brand-copy');
        if (brandCopy) {
            const text = brandCopy.closest('.brand-card')?.querySelector('p')?.textContent || '';
            copyText(text).then(() => toast('Copied to clipboard', 'success'));
            return;
        }

        const speak = e.target.closest('.brand-speak');
        if (speak) {
            const text = speak.closest('.brand-card')?.querySelector('.brand-pitch')?.textContent || '';
            if ('speechSynthesis' in window && text) {
                window.speechSynthesis.cancel();
                window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
                toast('Reading your pitch aloud…', 'info');
            } else {
                toast('Text-to-speech isn\'t available in this browser.', 'error');
            }
            return;
        }

        const expCopy = e.target.closest('.exp-copy');
        if (expCopy) {
            const text = expCopy.closest('.exp-bullet')?.querySelector('.exp-after')?.textContent || '';
            copyText(text).then(() => {
                expCopy.textContent = '✓'; toast('Bullet copied', 'success');
                setTimeout(() => (expCopy.textContent = '📋'), 1500);
            });
            return;
        }
    });

    /* ---------------- Experience Builder ---------------- */
    const expInput = $('exp-input');
    const expGenerate = $('exp-generate');
    const expOutput = $('exp-output');

    async function generateExperience() {
        if (!lastContext) { toast('Run an analysis first.', 'error'); return; }
        const raw = expInput?.value.trim() || '';
        expGenerate.classList.add('loading');
        expGenerate.disabled = true;
        try {
            const res = await fetch(`${API_BASE}/experience-coach`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ ...lastContext, raw_input: raw }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Could not generate bullets.');
            renderExperience(data);
            toast('Bullet points ready!', 'success');
        } catch (err) {
            toast(err.message, 'error');
        } finally {
            expGenerate.classList.remove('loading');
            expGenerate.disabled = false;
        }
    }
    expGenerate?.addEventListener('click', generateExperience);

    function renderExperience(data) {
        if (!expOutput) return;
        const bullets = Array.isArray(data.bullets) ? data.bullets : [];
        const plausCls = { strong: 'v-strong', partial: 'v-mid', none: 'v-low' };
        const plausLabel = { strong: 'Strong fit', partial: 'Partial — verify', none: 'No basis — skip' };
        const note = data.note ? `<p class="exp-note">💬 ${escapeHtml(data.note)}</p>` : '';
        expOutput.innerHTML = note + (bullets.length ? bullets.map(b => {
            const p = (b.plausibility || 'partial').toLowerCase();
            const covered = Array.isArray(b.jd_keywords_covered) ? b.jd_keywords_covered : [];
            return `
                <div class="exp-bullet">
                    <div class="exp-bullet-head">
                        <span class="exp-source">${escapeHtml(b.source || 'Experience')}</span>
                        <span class="plaus-badge ${plausCls[p] || 'v-mid'}">${escapeHtml(plausLabel[p] || p)}</span>
                        <button class="exp-copy" title="Copy" aria-label="Copy">📋</button>
                    </div>
                    <p class="exp-after">${escapeHtml(b.polished_bullet || '')}</p>
                    ${covered.length ? `<div class="exp-covered">${covered.map(k => `<span class="kw-pill">${escapeHtml(String(k))}</span>`).join('')}</div>` : ''}
                </div>`;
        }).join('') : '<p class="muted">No bullets generated. Try adding a short description above.</p>');
    }

    // cover letter copy / download
    coverCopyBtn?.addEventListener('click', () => {
        copyText(coverLetterEl.textContent || '').then(() => toast('Cover letter copied!', 'success'));
    });
    coverDownloadBtn?.addEventListener('click', () => {
        const blob = new Blob([coverLetterEl.textContent || ''], { type: 'text/plain' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'cover-letter.txt';
        a.click();
        URL.revokeObjectURL(a.href);
    });

    /* ---------------- Delightful extras ---------------- */
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Lightweight canvas confetti (no library)
    function celebrate() {
        const canvas = document.createElement('canvas');
        canvas.className = 'confetti-canvas';
        document.body.appendChild(canvas);
        const ctx = canvas.getContext('2d');
        const w = canvas.width = window.innerWidth;
        const h = canvas.height = window.innerHeight;
        const colors = ['#8b5cf6', '#22d3ee', '#ec4899', '#34d399', '#fbbf24'];
        const pieces = Array.from({ length: 150 }, () => ({
            x: Math.random() * w, y: -20 - Math.random() * h * 0.4,
            r: 4 + Math.random() * 7, c: colors[Math.floor(Math.random() * colors.length)],
            vx: -2.5 + Math.random() * 5, vy: 2 + Math.random() * 4,
            rot: Math.random() * Math.PI, vrot: -0.25 + Math.random() * 0.5,
        }));
        const start = performance.now();
        (function frame(now) {
            const elapsed = now - start;
            ctx.clearRect(0, 0, w, h);
            pieces.forEach(p => {
                p.x += p.vx; p.y += p.vy; p.vy += 0.05; p.rot += p.vrot;
                ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot);
                ctx.globalAlpha = Math.max(0, 1 - elapsed / 2800);
                ctx.fillStyle = p.c; ctx.fillRect(-p.r / 2, -p.r / 2, p.r, p.r * 0.6);
                ctx.restore();
            });
            if (elapsed < 2800) requestAnimationFrame(frame);
            else canvas.remove();
        })(start);
    }

    // Ctrl/Cmd + Enter runs the analysis
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && submitBtn && !submitBtn.disabled) {
            e.preventDefault();
            handleSubmit();
        }
    });

    // Scroll-to-top button
    const toTop = $('to-top');
    window.addEventListener('scroll', () => {
        toTop?.classList.toggle('show', window.scrollY > 500);
    }, { passive: true });
    toTop?.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));

    // Dismiss the entry-level banner
    resultsContent?.addEventListener('click', (e) => {
        if (e.target.closest('.banner-close')) e.target.closest('.info-banner')?.remove();
    });

    // Download / print report
    $('report-download')?.addEventListener('click', () => window.print());

    /* ---------------- Progress Dashboard ---------------- */
    const dashboard = $('dashboard');
    const dashCount = $('dash-count');
    const dashAvg = $('dash-avg');
    const dashBest = $('dash-best');
    const dashSpark = $('dash-spark');
    const dashMissingWrap = $('dash-missing-wrap');
    const dashMissing = $('dash-missing');

    function drawSparkline(points) {
        if (!dashSpark) return;
        const scores = points.map(p => p.score);
        if (scores.length < 2) {
            dashSpark.innerHTML = `<span class="spark-single">${scores[0] != null ? scores[0] + '%' : '—'}</span>`;
            return;
        }
        const W = 220, H = 56, pad = 6;
        const max = Math.max(...scores, 100), min = Math.min(...scores, 0);
        const range = (max - min) || 1;
        const step = (W - pad * 2) / (scores.length - 1);
        const coords = scores.map((s, i) => {
            const x = pad + i * step;
            const y = H - pad - ((s - min) / range) * (H - pad * 2);
            return [x, y];
        });
        const line = coords.map(c => `${c[0].toFixed(1)},${c[1].toFixed(1)}`).join(' ');
        const area = `${pad},${H - pad} ${line} ${(W - pad).toFixed(1)},${H - pad}`;
        const last = coords[coords.length - 1];
        dashSpark.innerHTML = `
            <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="spark-svg">
                <defs><linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stop-color="var(--accent)" stop-opacity="0.35"></stop>
                    <stop offset="1" stop-color="var(--accent)" stop-opacity="0"></stop>
                </linearGradient></defs>
                <polygon points="${area}" fill="url(#sparkFill)"></polygon>
                <polyline points="${line}" fill="none" stroke="var(--accent)" stroke-width="2.5"
                    stroke-linecap="round" stroke-linejoin="round"></polyline>
                <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="3.5" fill="var(--accent-2)"></circle>
            </svg>`;
    }

    async function loadStats() {
        if (!dashboard) return;
        try {
            const res = await fetch(`${API_BASE}/api/stats`, { credentials: 'include' });
            const s = await res.json();
            if (!s || !s.count) { dashboard.classList.add('hidden'); return; }
            dashboard.classList.remove('hidden');
            if (dashCount) dashCount.textContent = s.count;
            if (dashAvg) dashAvg.textContent = `${s.avg}%`;
            if (dashBest) dashBest.textContent = `${s.best}%`;
            drawSparkline(s.last10 || []);
            const tm = Array.isArray(s.top_missing) ? s.top_missing : [];
            if (tm.length && dashMissing) {
                dashMissingWrap.classList.remove('hidden');
                dashMissing.innerHTML = tm.map(m =>
                    `<span class="keyword kw-must">${escapeHtml(m.keyword)} <span class="kw-count-inline">×${m.count}</span></span>`).join('');
            } else {
                dashMissingWrap?.classList.add('hidden');
            }
        } catch (_) {
            dashboard.classList.add('hidden');
        }
    }

    /* ---------------- Init ---------------- */
    updateAcceptForType('pdf');
    checkFormReady();
    fetchMe();   // resolves auth state, then loads history/stats only when logged in

    // Arrived from a password-reset email (…/?reset_token=…)? Open the reset form
    // and strip the token from the address bar so it isn't left in history.
    const resetTokenParam = new URLSearchParams(window.location.search).get('reset_token');
    if (resetTokenParam) {
        openAuth('login');
        showResetStep(resetTokenParam);
        history.replaceState(null, '', window.location.pathname);
    }
});
