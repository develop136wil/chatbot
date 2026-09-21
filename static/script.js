// script.js - Final Fixed Version (UI_TEXT Included)

console.log('SCRIPT_LOADED_FINAL_FIX');

// ==========================================
// [신규] 1. 스플래시 화면 로직
// ==========================================
function dismissSplash() {
    document.getElementById('splash-screen')?.remove();
}
// No forced minimum wait. CSS also hides the non-blocking splash if JS fails.
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', dismissSplash, {once: true});
else dismissSplash();

// --- 1. 전역 변수 ---
const chatBox = document.getElementById('chat-box');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const micBtn = document.getElementById('mic-btn');

const API_URL_CHAT = '/chat';
const API_URL_RESULT = '/get_result/';

let activeRequestController = null;
let activeRequestSequence = 0;

let currentResultIds = [];
let currentShownCount = 0;
let currentTotalFound = 0;

let isChatLoading = false;
window.isChatBusy = () => isChatLoading;
let pendingContext = null;
let currentQuestion = "";
let chatHistory = [];
const MAX_HISTORY_TURNS = 2;

// ============================================================
// [★핵심] 다국어 데이터베이스 (UI_TEXT) - 꿀팁 통합됨
// ============================================================
const UI_TEXT = window.CHAT_UI_TEXT;

const SHOW_MORE_KEYWORDS = new Set([
    "다음", "더", "더 보기", "더 보여줘", "계속", "이어서", "다음거", "다음꺼", "다른거", "다른 거", "또",
    "next", "more", "continue", "show more",
    "tiếp", "tiếp theo", "thêm", "xem thêm", "nữa", "tiếp tục",
    "更多", "继续", "下", "下一个", "还有吗"
]);

// Statistics use an opaque per-request ID, never the question text or destination URL.
const analyticsMessages = new WeakMap();
let suggestedAnalyticsText = null;
function analyticsSource() {
    try {
        const source = new URL(window.location.href).searchParams.get('utm_source');
        return source === null ? 'direct' : ['website','qr','partner'].includes(source) ? source : 'unknown';
    } catch (_) { return 'unknown'; }
}
function attachAnalyticsMetadata(body) {
    if (!body.analytics_id && window.crypto?.randomUUID) body.analytics_id = window.crypto.randomUUID();
    if (!body.entry_source) body.entry_source = analyticsSource();
    if (!body.input_method) {
        body.input_method = currentQuestion === suggestedAnalyticsText ? 'suggestion' : 'typed';
        suggestedAnalyticsText = null;
    }
}
async function trackSourceClick(message) {
    const state = analyticsMessages.get(message);
    if (!state || state.busy || state.sent) return;
    state.busy = true;
    try {
        const response = await fetch('/analytics/source-click', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({token:state.token}), keepalive:true});
        state.sent = response.ok;
    } catch (_) { /* Navigation is never blocked by statistics. */ }
    finally { state.busy = false; }
}

const REQUEST_MESSAGES = UI_TEXT;

function getRequestMessages() {
    return REQUEST_MESSAGES[window.currentLang || 'ko'] || REQUEST_MESSAGES.ko;
}

function sanitizeAssistantHtml(value) {
    const html = String(value || '');
    if (window.DOMPurify) {
        return window.DOMPurify.sanitize(html, {
            ADD_ATTR: ['target', 'rel', 'data-copy'],
            ALLOW_DATA_ATTR: true
        });
    }
    // 정화 라이브러리가 로드되지 않았을 때는 기능보다 안전을 우선합니다.
    const fallback = document.createElement('div');
    fallback.textContent = html;
    return fallback.innerHTML;
}

function formatAssistantAnswer(answer) {
    const rawAnswer = String(answer || '');
    const html = rawAnswer.includes('result-card') || !window.marked ? rawAnswer : marked.parse(rawAnswer);
    return sanitizeAssistantHtml(html);
}

// --- 2. 음성 인식 설정 ---
const isInIframe = window.self !== window.top;
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const canUseMic = SpeechRecognition && !isInIframe;

// --- 3. 버튼 토글 ---
function toggleInputButtons() {
    const text = userInput.value.trim();
    if (text.length > 0) {
        sendBtn.style.display = 'flex';
        micBtn.style.display = 'none';
    } else {
        if (canUseMic) {
            sendBtn.style.display = 'none';
            micBtn.style.display = 'flex';
        } else {
            sendBtn.style.display = 'flex';
            micBtn.style.display = 'none';
        }
    }
}
toggleInputButtons();
userInput.addEventListener('input', toggleInputButtons);

// --- 4. 이벤트 리스너 ---
sendBtn.addEventListener('click', () => {
    handleFormSubmit();
    setTimeout(toggleInputButtons, 10);
});

userInput.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
    if (this.scrollHeight > 120) {
        this.style.overflowY = "auto";
    } else {
        this.style.overflowY = "hidden";
    }
    toggleInputButtons();
});

userInput.addEventListener('keydown', (event) => {
    // Let the IME finish composing before intercepting Enter for submission.
    if (event.isComposing || event.keyCode === 229) return;
    if (event.key === 'Enter') {
        if (!event.shiftKey) {
            event.preventDefault();
            handleFormSubmit();
            setTimeout(() => {
                userInput.style.height = 'auto';
                toggleInputButtons();
            }, 10);
        }
    }
});

chatBox.addEventListener('click', async (event) => {
    if (event.target.classList.contains('clarify-btn')) {
        const buttonText = event.target.innerText;
        handleButtonClick(buttonText);
    }
    const detail = event.target.closest?.('.detail-link');
    if (detail) void trackSourceClick(detail.closest('.message'));
    const shareButton = event.target.closest?.('.card-share-btn');
    if (shareButton) await shareCard(shareButton);
});


function canStartChatRequest() {
    if (isChatLoading) return false;
    if (navigator.onLine === false) {
        syncInputAvailability();
        showToast(getRequestMessages().offline);
        return false;
    }
    return true;
}

// The API limit counts Unicode code points, including the existing language suffix.
const MAX_QUESTION_LENGTH = 2000;
function buildServerQuestion(question) {
    const names = {en: 'English', vi: 'Vietnamese', zh: 'Chinese'};
    const name = names[window.currentLang];
    return question + (name ? ' \n\n(System: Please answer strictly in ' + name + '.)' : '');
}

function validateQuestionLength(question) {
    if (Array.from(buildServerQuestion(question)).length <= MAX_QUESTION_LENGTH) return true;
    const limit = MAX_QUESTION_LENGTH - Array.from(buildServerQuestion('')).length;
    showToast(getRequestMessages().question_too_long.replace('{limit}', String(limit)));
    userInput.focus();
    return false;
}

// --- 5. 메인 로직 ---
async function handleFormSubmit() {
    if (!canStartChatRequest()) return;
    const question = userInput.value.trim();
    if (!question || !validateQuestionLength(question)) return;

    pendingContext = null;
    currentQuestion = question;
    clearButtons();
    setLoadingState(true);

    const serverQuestion = buildServerQuestion(question);

    let requestBody = {
        question: serverQuestion,
        language: window.currentLang || 'ko',
        action: "ask",
        last_result_ids: [...currentResultIds],
        shown_count: currentShownCount,
        // 현재 질문은 question으로 별도 전달합니다. 이전 대화만 문맥으로 보냅니다.
        // 그래야 새 대화의 정확 일치 질문은 공유 응답 캐시를 사용할 수 있습니다.
        chat_history: [...chatHistory]
    };

    if (SHOW_MORE_KEYWORDS.has(question.toLowerCase())) {
        requestBody.action = "more";
        requestBody.last_result_ids = currentResultIds;
        requestBody.shown_count = currentShownCount;
    }

    updateChatHistory("user", question);
    addMessageToBox('user', question);
    userInput.value = '';
    userInput.style.height = 'auto';
    syncInputOverlay();
    toggleInputButtons();

    await fetchChatResponse(requestBody);
}

async function handleButtonClick(buttonText) {
    if (!canStartChatRequest()) return;
    const newQuestion = pendingContext ? `${pendingContext} ${buttonText}` : buttonText;
    if (!validateQuestionLength(newQuestion)) return;
    pendingContext = null;
    clearButtons();
    addMessageToBox('user', newQuestion);
    currentQuestion = newQuestion;
    setLoadingState(true);

    const serverQuestion = buildServerQuestion(newQuestion);

    const requestBody = {
        input_method: "clarification",
        question: serverQuestion,
        language: window.currentLang || 'ko',
        action: "ask",
        last_result_ids: [...currentResultIds],
        shown_count: currentShownCount,
        chat_history: [...chatHistory]
    };
    updateChatHistory("user", newQuestion);
    await fetchChatResponse(requestBody);
}

// --- 7. Typewriter Effect (Streaming Emulation) ---
async function typeWriterEffect(element, htmlContent) {
    element.innerHTML = htmlContent;
    element.style.opacity = 1;
}

async function renderChatResponse(data, element, question, sequence) {
    if (sequence !== activeRequestSequence) return;
    if (data.status === 'error') {
        element.textContent = data.message || getRequestMessages().error;
        addContactActions(element);
        return;
    }
    if (!['complete', 'clarify'].includes(data.status)) throw new Error('Invalid response');
    await typeWriterEffect(element, formatAssistantAnswer(data.answer));
    if (sequence !== activeRequestSequence) return;
    translateCardButtons(element);
    if (data.analytics_token) analyticsMessages.set(element, {token:data.analytics_token, busy:false, sent:false});
    if (data.action === 'reset') {
        chatHistory = [];
        pendingContext = null;
        currentResultIds = [];
        currentShownCount = 0;
        currentTotalFound = 0;
        return;
    }
    document.querySelectorAll('.show-more-btn').forEach(button => button.remove());
    updateChatHistory('assistant', data.answer);
    currentResultIds = data.last_result_ids || [];
    currentTotalFound = data.total_found || 0;
    currentShownCount = data.shown_count ?? Math.min(2, currentResultIds.length);
    if (data.status === 'clarify') {
        pendingContext = question;
        createButtons(data.options || []);
    } else if (currentShownCount < currentResultIds.length) {
        const labels = Object.fromEntries(Object.entries(UI_TEXT).map(([lang, copy]) => [lang, copy.more]));
        const more = document.createElement('button');
        more.className = 'show-more-btn';
        more.type = 'button';
        more.textContent = labels[window.currentLang || 'ko'];
        more.onclick = () => {
            if (!canStartChatRequest()) return;
            userInput.value = labels[window.currentLang || 'ko'];
            handleFormSubmit();
        };
        element.appendChild(more);
    }
    if (data.status === 'complete') addContactActions(element);
}

function startLoadingTips(element, language) {
    const copy = UI_TEXT[language] || UI_TEXT.ko;
    const tips = copy.tips || [];
    const target = element.querySelector('.tip-text');
    if (!target || !tips.length) return () => {};
    target.setAttribute('aria-live', 'off');
    let last = -1;
    const show = () => {
        // Random first tip; subsequent tips cannot repeat immediately.
        const index = last < 0 ? Math.floor(Math.random() * tips.length)
            : (last + 1 + Math.floor(Math.random() * Math.max(1, tips.length - 1))) % tips.length;
        last = index;
        target.textContent = copy.tip_label + '\n' + tips[index];
    };
    show();
    const timer = setInterval(show, 7000);
    return () => clearInterval(timer);
}

async function fetchChatResponse(requestBody, resumeJobId = null) {
    attachAnalyticsMetadata(requestBody);
    const lang = window.currentLang || 'ko';
    const messages = getRequestMessages();
    const sequence = ++activeRequestSequence;
    document.querySelectorAll('.retry-btn').forEach(button => { button.disabled = true; });
    const question = currentQuestion;
    if (activeRequestController) activeRequestController.abort();
    const controller = new AbortController();
    activeRequestController = controller;
    const langData = UI_TEXT[lang] || UI_TEXT.ko;
    const loading = addMessageToBox('assistant', '<div class="skeleton-container"><div class="skeleton-box" style="width:90%"></div><div class="skeleton-box" style="width:70%"></div><div class="skeleton-box" style="width:85%"></div><div class="loading-copy"><p class="action-text"></p><p class="tip-text"></p></div></div>');
    const stopTips = startLoadingTips(loading, lang);
    const text = loading.querySelector('.action-text');
    if (text) text.textContent = langData.processing;
    const animation = setTimeout(() => {
        if (text) text.textContent = langData.slow;
    }, 15000);
    let jobId = resumeJobId;
    let timeout = setTimeout(() => controller.abort(), jobId ? 120000 : 45000);
    try {
        let data;
        if (!jobId) {
            const response = await fetch(API_URL_CHAT, {
                method:'POST', headers:{'Content-Type':'application/json'},
                body:JSON.stringify(requestBody), signal:controller.signal
            });
            if (!response.ok) throw requestHttpError(response, messages);
            data = await response.json();
            if (!data.status && data.job_id) jobId = data.job_id;
        }
        if (jobId) {
            clearTimeout(timeout);
            timeout = setTimeout(() => controller.abort(), 120000);
            data = await pollForResult(jobId, controller.signal);
        }
        if (sequence !== activeRequestSequence) return;
        clearTimeout(animation);
        if (data.status === 'error') {
            // Only an explicit worker failure can authorize the normal retry path.
            jobId = null;
            showRequestError(loading, data, requestBody, question, sequence);
        } else {
            await renderChatResponse(data, loading, question, sequence);
        }
    } catch (error) {
        if (sequence === activeRequestSequence) {
            showRequestError(loading, {
                message: error.name === 'AbortError' ? messages.timeout : (error.userMessage || messages.error),
                retryable: error.retryable !== false
            }, requestBody, question, sequence, error.retryDelay || 0, jobId);
        }
    } finally {
        stopTips();
        clearTimeout(timeout);
        clearTimeout(animation);
        if (sequence === activeRequestSequence) {
            activeRequestController = null;
            setLoadingState(false);
        }
    }
    if (sequence === activeRequestSequence) chatBox.scrollTop = chatBox.scrollHeight;
}

function requestHttpError(response, messages, polling = false) {
    const error = new Error('HTTP request failed');
    error.userMessage = response.status === 429 ? messages.rate_limit : messages.error;
    if (polling && [404, 410].includes(response.status)) error.userMessage = messages.result_unavailable;
    error.retryable = [408, 429, 500, 502, 503, 504].includes(response.status);
    error.retryDelay = retryDelay(response.headers?.get('Retry-After'));
    return error;
}

async function pollForResult(jobId, signal) {
    while (!signal.aborted) {
        const response = await fetch(API_URL_RESULT+jobId, {signal});
        if (!response.ok) throw requestHttpError(response, getRequestMessages(), true);
        const data = await response.json();
        if (data.status === 'complete' || data.status === 'error') return {...data, job_id:jobId};
        if (data.status !== 'pending') throw new Error('Invalid polling response');
        await waitForPoll(signal);
    }
    throw new DOMException('Aborted', 'AbortError');
}

// Abort pending delay immediately and remove listeners on either completion path.
function waitForPoll(signal) {
    return new Promise((resolve, reject) => {
        let timer;
        const abort = () => {
            clearTimeout(timer);
            signal.removeEventListener('abort', abort);
            reject(new DOMException('Aborted', 'AbortError'));
        };
        if (signal.aborted) { abort(); return; }
        signal.addEventListener('abort', abort, {once: true});
        timer = setTimeout(() => {
            signal.removeEventListener('abort', abort);
            resolve();
        }, 1000);
    });
}

// --- 6. 헬퍼 함수 ---
function addMessageToBox(role, content) {
    const rowElement = document.createElement('div');
    rowElement.classList.add('message-row', role);

    if (role === 'assistant') {
        const iconImg = document.createElement('img');
        iconImg.src = "/static/bot-icon.png";
        iconImg.className = "bot-profile-icon";
        iconImg.alt = "bot";
        rowElement.appendChild(iconImg);
    }

    const messageBubble = document.createElement('div');
    messageBubble.setAttribute('role', 'status');
    messageBubble.setAttribute('aria-live', 'polite');

    if (role === 'user') {
        messageBubble.classList.add('user-message');
    } else {
        messageBubble.classList.add('message', role);
    }

    if (role === 'assistant') {
        messageBubble.innerHTML = sanitizeAssistantHtml(content);
    } else {
        const p = document.createElement('p');
        p.textContent = String(content || '');
        messageBubble.appendChild(p);
    }

    rowElement.appendChild(messageBubble);
    chatBox.appendChild(rowElement);

    translateCardButtons(messageBubble);

    chatBox.scrollTop = chatBox.scrollHeight;
    return messageBubble;
}

function updateChatHistory(role, content) {
    chatHistory.push({ "role": role, "content": String(content).slice(0, 12000) });
    if (chatHistory.length > MAX_HISTORY_TURNS * 2) chatHistory.shift();
}

function createButtons(optionsArray) {
    const buttonContainer = document.createElement('div');
    buttonContainer.className = 'button-container';
    optionsArray.forEach(optionText => {
        const button = document.createElement('button');
        button.className = 'clarify-btn';
        button.innerText = optionText;
        buttonContainer.appendChild(button);
    });
    chatBox.appendChild(buttonContainer);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function clearButtons() {
    const existingContainer = document.querySelector('.button-container');
    if (existingContainer) existingContainer.remove();
}

// Email is composed by the user's mail app. Never attach chat history or send it here.
const CONTACT_EMAIL = 'chanyoung@devleop136.com';
function addContactActions(container, language = window.currentLang || 'ko') {
    if (container.querySelector('.contact-actions')) return;
    const copy = (UI_TEXT[language] || UI_TEXT.ko).contact;
    const details = document.createElement('details');
    details.className = 'contact-actions';
    const summary = document.createElement('summary');
    summary.textContent = copy.label;
    details.appendChild(summary);
    const content = document.createElement('div');
    content.className = 'contact-content';
    const email = document.createElement('a');
    email.href = 'mailto:' + CONTACT_EMAIL + '?subject=' + encodeURIComponent(copy.subject);
    email.textContent = CONTACT_EMAIL;
    email.setAttribute('aria-label', copy.open + ': ' + CONTACT_EMAIL);
    content.appendChild(email);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'contact-copy';
    button.textContent = copy.copy;
    const status = document.createElement('span');
    status.className = 'contact-status';
    status.setAttribute('role', 'status');
    button.onclick = async () => {
        button.disabled = true;
        try {
            if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
            await navigator.clipboard.writeText(CONTACT_EMAIL);
            status.textContent = copy.copied;
        } catch (_) {
            status.textContent = copy.copy_failed;
        } finally {
            button.disabled = false;
        }
    };
    content.appendChild(button);
    const note = document.createElement('p');
    note.textContent = copy.note;
    content.appendChild(note);
    content.appendChild(status);
    details.appendChild(content);
    container.appendChild(details);
}

// Network events must update controls without changing the active request state.
function syncInputAvailability() {
    const offline = navigator.onLine === false;
    const disabled = isChatLoading || offline;
    userInput.disabled = disabled;
    sendBtn.disabled = disabled;
    if (micBtn) micBtn.disabled = disabled;
    userInput.placeholder = offline ? getRequestMessages().offline
        : isChatLoading ? getRequestMessages().loading : getRequestMessages().placeholder;
}

function setLoadingState(isLoading) {
    isChatLoading = isLoading;
    document.querySelectorAll('.lang-btn, .suggestion-chip, .clarify-btn, .show-more-btn').forEach(button => { button.disabled = isLoading; });
    syncInputAvailability();
    if (isLoading) userInput.blur();
}
// --- 7. 음성 인식 로직 ---
let recognition;
if (canUseMic) {
    recognition = new SpeechRecognition();
    recognition.lang = 'ko-KR';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    micBtn.addEventListener('click', () => {
        if (micBtn.classList.contains('listening')) {
            recognition.stop();
        } else {
            recognition.lang = { ko: 'ko-KR', en: 'en-US', vi: 'vi-VN', zh: 'zh-CN' }[window.currentLang || 'ko'];
            recognition.start();
        }
    });
    recognition.addEventListener('start', () => { micBtn.classList.add('listening'); userInput.placeholder = getRequestMessages().listening; });
    recognition.addEventListener('end', () => { micBtn.classList.remove('listening'); userInput.placeholder = getRequestMessages().ready; });
    recognition.addEventListener('result', (event) => { userInput.value = event.results[0][0].transcript; toggleInputButtons(); });
    recognition.addEventListener('error', (event) => {
        micBtn.classList.remove('listening');
        userInput.placeholder = getRequestMessages().error;
        setTimeout(() => { userInput.placeholder = getRequestMessages().ready; }, 2000);
    });
} else {
    if (micBtn) micBtn.style.display = 'none';
    if (sendBtn) sendBtn.style.display = 'flex';
}

// Keyboard/viewport changes must not discard the answer the user is reading.
window.visualViewport?.addEventListener('resize', () => {
    syncHeaderHeight();
    syncInputOverlay();
});

function sendSuggestion(text) {
    if (!canStartChatRequest()) return;
    suggestedAnalyticsText = text;
    const userInput = document.getElementById('user-input');
    userInput.value = text;
    toggleInputButtons();
    setTimeout(() => {
        document.getElementById('send-btn').click();
    }, 300);
}

const toggleBtn = document.getElementById('suggestion-toggle-btn');
const suggestionContainer = document.querySelector('.suggestion-container');

function syncSuggestionOverlay() {
    if (!chatBox || !suggestionContainer) return;

    const isVisible = !suggestionContainer.classList.contains('hidden');
    chatBox.classList.toggle('suggestions-visible', isVisible);
    if (window.updateToggleText) window.updateToggleText();
    syncInputOverlay();

}

if (toggleBtn && suggestionContainer) {
    toggleBtn.addEventListener('click', () => {
        suggestionContainer.classList.toggle('hidden');
        toggleBtn.classList.toggle('active');
        syncSuggestionOverlay();
    });
}

window.addEventListener('load', syncSuggestionOverlay);

window.addEventListener('load', syncInputAvailability);

window.addEventListener('offline', () => {
    showToast(getRequestMessages().offline);
    syncInputAvailability();
});

window.addEventListener('online', () => {
    showToast(getRequestMessages().online);
    syncInputAvailability();
});

document.addEventListener('DOMContentLoaded', () => {
    const scrollBtn = document.getElementById('scroll-bottom-btn');
    const chatBoxEl = document.getElementById('chat-box');

    if (scrollBtn && chatBoxEl) {
        // 스크롤 버튼 표시 조건 체크 함수
        const checkScrollButton = () => {
            // [핵심 1] 스크롤이 가능한지 (내용이 화면보다 많은지) 확인
            const isScrollable = chatBoxEl.scrollHeight > chatBoxEl.clientHeight + 50;

            // [핵심 2] 사용자가 위로 스크롤했는지 확인 (하단에서 200px 이상 떨어졌는지)
            const isScrolledUp = chatBoxEl.scrollTop + chatBoxEl.clientHeight < chatBoxEl.scrollHeight - 200;

            // 두 조건 모두 만족해야 버튼 표시
            if (isScrollable && isScrolledUp) {
                scrollBtn.classList.add('show');
            } else {
                scrollBtn.classList.remove('show');
            }
        };

        // 스크롤 이벤트 리스너
        chatBoxEl.addEventListener('scroll', checkScrollButton);

        // 클릭 시 맨 아래로 이동
        scrollBtn.addEventListener('click', () => {
            chatBoxEl.scrollTo({
                top: chatBoxEl.scrollHeight,
                behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
            });
        });

        // 초기 체크 (페이지 로드 시)
        checkScrollButton();
    }
});

function tidyResultPresentation(container) {
    // Presentation only. Keep timestamps in the source/cache for freshness checks.
    const dateNote = /^(?:자료 수정|Document updated|Cập nhật tài liệu|资料更新)\s*[:：]\s*\d{4}-\d{2}-\d{2}\s*·/u;
    container.querySelectorAll('.result-card .source-note').forEach(note => {
        if (dateNote.test(note.textContent.trim())) note.remove();
    });
    // Remove only a stray leading comma before text, never numeric/grouping commas.
    container.querySelectorAll('.card-body li').forEach(item => {
        const first = item.firstChild;
        if (first?.nodeType === 3) {
            first.nodeValue = first.nodeValue.replace(/^\s*[,，]\s+(?=\p{L})/u, '');
        }
    });
    const redundantMoreHints = new Set([
        '아래 ‘더 보기’에서 다음 결과를 확인할 수 있어요.',
        'Use ‘Show more’ below to see the next results.',
        'Chọn ‘Xem thêm’ bên dưới để xem các kết quả tiếp theo.',
        '点击下方“更多”查看后续结果。'
    ]);
    container.querySelectorAll(':scope > p').forEach(note => {
        if (!redundantMoreHints.has(note.textContent.trim())) return;
        const divider = note.previousElementSibling;
        if (divider?.tagName === 'HR') divider.remove();
        note.remove();
    });
}

function decorateCardSubheadings(container) {
    // Display-only: applies to cached answers too, without rewriting source content.
    const heading = /^(?:운영\s*목적|기본\s*검사\s*\(무료\)|Purpose|Basic\s+(?:check|assessment)\s*\(free\)|Mục đích|Kiểm tra cơ bản\s*\(miễn phí\)|服务目的|基本检查\s*[（(]免费[）)])\s*[:：]\s*$/iu;
    container.querySelectorAll('.card-body li').forEach(item => {
        if (item.nextElementSibling && heading.test(item.textContent.trim())) {
            item.classList.add('card-subheading');
        }
    });
}

function translateCardButtons(container) {
    tidyResultPresentation(container);
    decorateCardSubheadings(container);
    const copy = getRequestMessages();
    container.querySelectorAll('.detail-link').forEach(el => { el.innerText = copy.detail; });
    container.querySelectorAll('.card-share-btn').forEach(el => { el.innerText = copy.share; });
}
// --- [UI Improvements] Toast & Suggestions ---

// 1. Toast Notification Function

function showToast(message) {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.setAttribute('role', 'status');
        container.setAttribute('aria-live', 'polite');
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));
    setTimeout(() => toast.remove(), 4000);
}

// 2. Suggestion Chip Scroll Fix (Prevent click jumping)
document.addEventListener('click', function(e) {
    if (e.target.classList.contains('suggestion-chip')) {
        e.preventDefault(); // Prevent default focus jump
        // Original onclick handler in createButtons/HTML will still fire
    }
});

function overlayMetrics(footerHeight, suggestionHeight, toggleHeight, expanded) {
    const footer = Math.max(0, Math.ceil(footerHeight));
    const overlay = Math.max(expanded ? Math.ceil(suggestionHeight) : 0, Math.ceil(toggleHeight) + 12);
    return { footer, bottomPadding: footer + overlay + 16 };
}

function syncInputOverlay() {
    const footer = document.querySelector('.chat-input-box');
    if (!footer || !chatBox || !suggestionContainer || !toggleBtn) return;
    const pinned = chatBox.scrollHeight - chatBox.scrollTop - chatBox.clientHeight < 100;
    const expanded = !suggestionContainer.classList.contains('hidden');
    const toggleRect = toggleBtn.getBoundingClientRect();
    const metrics = overlayMetrics(footer.getBoundingClientRect().height,
        suggestionContainer.getBoundingClientRect().height,
        toggleRect.height, expanded);
    document.documentElement.style.setProperty('--suggestion-toggle-width',
        Math.max(0, Math.ceil(toggleRect.width || 0)) + 'px');
    document.documentElement.style.setProperty('--chat-footer-height', metrics.footer + 'px');
    document.documentElement.style.setProperty('--chat-bottom-padding', metrics.bottomPadding + 'px');
    toggleBtn.setAttribute('aria-expanded', String(expanded));
    suggestionContainer.setAttribute('aria-hidden', String(!expanded));
    suggestionContainer.inert = !expanded;
    if (pinned) chatBox.scrollTop = chatBox.scrollHeight;
}

window.addEventListener('load', () => {
    syncInputOverlay();
    if (window.ResizeObserver) {
        const observer = new window.ResizeObserver(syncInputOverlay);
        [document.querySelector('.chat-input-box'), suggestionContainer, toggleBtn]
            .filter(Boolean).forEach(element => observer.observe(element));
    }
});
window.addEventListener('resize', syncInputOverlay);
userInput.addEventListener('input', () => requestAnimationFrame(syncInputOverlay));

async function shareCard(button) {
    const copy = getRequestMessages();
    const text = (button.dataset.copy || '').replace('🔗 자세히 보기:', '🔗 ' + copy.detail + ':');
    if (navigator.share && !isInIframe) {
        try {
            await navigator.share({ title: copy.share_title, text, url: window.location.href });
            return;
        } catch (error) {
            if (error.name === 'AbortError') return; // Cancel means cancel, not copy.
        }
    }
    try {
        await navigator.clipboard.writeText(text);
        showToast(copy.copied);
    } catch (_) {
        prompt(copy.copy_prompt, text);
    }
}

function retryDelay(value) {
    if (!value) return 0;
    const seconds = Number(value);
    const delay = Number.isFinite(seconds) ? seconds * 1000 : Date.parse(value) - Date.now();
    return Number.isFinite(delay) ? Math.max(0, Math.min(delay, 3600000)) : 0;
}

function showRequestError(element, data, requestBody, question, sequence, delay = 0, resumeJobId = null) {
    element.textContent = data.message || getRequestMessages().error;
    if (data.retryable === false || !requestBody) {
        addContactActions(element);
        return;
    }
    const retry = document.createElement('button');
    retry.className = 'retry-btn';
    const lang = requestBody.language || 'ko';
    const copy = UI_TEXT[lang] || UI_TEXT.ko;
    const readyAt = Date.now() + delay;
    retry.textContent = delay ? copy.retry_wait + ' (' + Math.ceil(delay / 1000) + 's)' : (resumeJobId ? copy.retry_result : copy.retry);
    retry.onclick = async () => {
        if (sequence !== activeRequestSequence || !canStartChatRequest()) return;
        const remaining = readyAt - Date.now();
        if (remaining > 0) {
            showToast(copy.retry_wait + ' (' + Math.ceil(remaining / 1000) + 's)');
            return;
        }
        // Reuse the original question/history; never auto-retry or add another user turn.
        if (window.changeLanguage) window.changeLanguage(lang);
        currentQuestion = question;
        retry.disabled = true;
        setLoadingState(true);
        await fetchChatResponse(requestBody, resumeJobId);
    };
    element.appendChild(retry);
    addContactActions(element);
}


function syncHeaderHeight() {
    const header = document.querySelector('.chat-topbar');
    if (header) document.documentElement.style.setProperty('--chat-top-height',
        Math.ceil(header.getBoundingClientRect().height) + 'px');
}
window.addEventListener('load', () => {
    syncHeaderHeight();
    const header = document.querySelector('.chat-topbar');
    if (header && window.ResizeObserver) new window.ResizeObserver(syncHeaderHeight).observe(header);
});
window.addEventListener('resize', syncHeaderHeight);
