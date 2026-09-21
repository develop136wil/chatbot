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
const API_URL_FEEDBACK = '/feedback';

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
        return;
    }
    if (!['complete', 'clarify'].includes(data.status)) throw new Error('Invalid response');
    await typeWriterEffect(element, formatAssistantAnswer(data.answer));
    if (sequence !== activeRequestSequence) return;
    translateCardButtons(element);
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
    if (data.status === 'complete' && data.job_id) {
        addFeedbackButtons(element, data.job_id, question, data.answer);
    }
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

// [★수정] 피드백 버튼 추가 함수 (다국어 지원)
function addFeedbackButtons(messageElement, jobId, question, answer) {
    const lang = window.currentLang || 'ko';
    const textData = UI_TEXT[lang].feedback; // 해당 언어의 피드백 텍스트 가져오기

    const feedbackContainer = document.createElement('div');
    feedbackContainer.className = 'feedback-container';

    const feedbackMsg = document.createElement('p');
    feedbackMsg.textContent = textData.question; // "답변이 도움이 되었나요?" (번역됨)
    feedbackContainer.appendChild(feedbackMsg);

    const btnGroup = document.createElement('div');
    btnGroup.className = 'feedback-btn-group';

    const goodBtn = document.createElement('button');
    goodBtn.className = 'feedback-btn';
    goodBtn.textContent = '👍';
    goodBtn.onclick = () => submitFeedback(jobId, question, answer, '👍', feedbackContainer, "");
    btnGroup.appendChild(goodBtn);

    const badBtn = document.createElement('button');
    badBtn.className = 'feedback-btn';
    badBtn.textContent = '👎';
    badBtn.onclick = () => showFeedbackInput(feedbackContainer, jobId, question, answer, '👎');
    btnGroup.appendChild(badBtn);

    feedbackContainer.appendChild(btnGroup);
    messageElement.appendChild(feedbackContainer);
}

// [★수정] 피드백 입력창 (다국어 지원)
function showFeedbackInput(container, jobId, question, answer, feedbackType) {
    const lang = window.currentLang || 'ko';
    const textData = UI_TEXT[lang].feedback;

    container.innerHTML = '';
    const reasonContainer = document.createElement('div');
    reasonContainer.className = 'reason-container';

    // 이유 태그도 번역된 걸로 표시
    const reasons = textData.reasons;

    reasons.forEach(reasonText => {
        const chip = document.createElement('button');
        chip.textContent = reasonText;
        chip.className = 'reason-chip';

        chip.onclick = () => {
            Array.from(reasonContainer.children).forEach(c => c.classList.remove('selected'));
            chip.classList.add('selected');
            if (!container.querySelector('.feedback-input-wrapper')) {
                showCommentInput(container, jobId, question, answer, feedbackType, reasonText);
            } else {
                const existingInput = container.querySelector('.feedback-input-wrapper');
                const draft = existingInput?.querySelector('input')?.value || '';
                if (existingInput) existingInput.remove();
                showCommentInput(container, jobId, question, answer, feedbackType, reasonText, draft);
            }
        };
        reasonContainer.appendChild(chip);
    });
    container.appendChild(reasonContainer);
}

// [★수정] 코멘트 입력창 (다국어 지원)
function showCommentInput(container, jobId, question, answer, feedbackType, selectedReason, draft = "") {
    const lang = window.currentLang || 'ko';
    const textData = UI_TEXT[lang].feedback;

    const inputWrapper = document.createElement('div');
    inputWrapper.className = 'feedback-input-wrapper';

    const input = document.createElement('input');
    input.type = "text";
    input.className = 'feedback-input';
    input.placeholder = textData.input_placeholder; // "자세한 상황을..." (번역됨)
    input.maxLength = 1000;
    input.value = draft;

    const sendBtn = document.createElement('button');
    sendBtn.textContent = textData.send; // "전송" (번역됨)
    sendBtn.className = 'feedback-send-btn';

    sendBtn.onclick = () => {
        const historyStr = JSON.stringify(chatHistory.slice(-4));
        submitFeedback(jobId, question, answer, feedbackType, container, input.value.trim(), selectedReason, historyStr);
    };

    inputWrapper.appendChild(input);
    inputWrapper.appendChild(sendBtn);
    container.appendChild(inputWrapper);

    setTimeout(() => input.focus(), 100);
}

// Keep the form nodes (and their draft values) until storage is confirmed.
const feedbackRequests = new WeakMap();
const FEEDBACK_TIMEOUT_MS = 15000;

async function submitFeedback(jobId, question, answer, feedbackType, containerElement, comment, reason = "", historyStr = "") {
    let state = feedbackRequests.get(containerElement);
    if (state?.busy || state?.saved) return;
    const lang = window.currentLang || 'ko';
    const copy = UI_TEXT[lang] || UI_TEXT.ko;
    const textData = copy.feedback;
    if (!state) {
        const status = document.createElement('p');
        status.className = 'feedback-status';
        status.setAttribute('role', 'status');
        status.setAttribute('aria-live', 'polite');
        state = {busy: false, saved: false, retryAt: 0, status};
        feedbackRequests.set(containerElement, state);
    }
    // Reattach after the user reopens the reason form following a failed vote.
    containerElement.appendChild(state.status);
    if (navigator.onLine === false) {
        state.status.textContent = copy.offline;
        return;
    }
    if (state.retryAt > Date.now()) {
        state.status.textContent = copy.retry_wait + ' (' + Math.ceil((state.retryAt - Date.now()) / 1000) + 's)';
        return;
    }
    state.busy = true;
    state.status.textContent = textData.sending;
    const controls = Array.from(containerElement.querySelectorAll('button, input'));
    const disabledBefore = controls.map(control => Boolean(control.disabled));
    controls.forEach(control => { control.disabled = true; });
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FEEDBACK_TIMEOUT_MS);
    try {
        const response = await fetch('/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: controller.signal,
            body: JSON.stringify({
                job_id: jobId, question: question,
                answer: String(answer).slice(0, 12000), feedback: feedbackType,
                comment: comment, reason: reason,
                chat_history: String(historyStr).slice(0, 20000)
            })
        });
        if (!response.ok) {
            if (response.status === 429) {
                state.retryAt = Date.now() + retryDelay(response.headers?.get('Retry-After'));
            }
            const error = new Error('Feedback HTTP ' + response.status);
            error.rateLimited = response.status === 429;
            throw error;
        }
        const result = await response.json();
        if (result.status !== 'success') throw new Error('Feedback not saved');
        state.saved = true;
        const thanksText = feedbackType === '👍' ? textData.thanks_good : textData.thanks_bad;
        containerElement.innerHTML = '<p class="feedback-success">' + thanksText + '</p>';
    } catch (error) {
        state.status.textContent = error.rateLimited ? copy.rate_limit : textData.send_failed;
    } finally {
        clearTimeout(timer);
        state.busy = false;
        if (!state.saved) controls.forEach((control, index) => { control.disabled = disabledBefore[index]; });
    }
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
    if (data.retryable === false || !requestBody) return;
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
