const noteContent = document.getElementById('note-content');
const contextSelect = document.getElementById('context-select');

let isTtsEnabled = false;
let recognition;
let availableVoices = [];
let preferredVoiceIndex = 0;
const synth = window.speechSynthesis;

let currentOffset = 0;
const limit = 10;
let currentSearch = "";
let searchTimeout;

const chartColors = [
    '#ff3b30',
    '#ff9500',
    '#ffcc00',
    '#34c759',
    '#007aff',
    '#5856d6',
    '#af52de',
    '#ff2d55',
    '#a2845e' 
];

const sessionId = "global_user_session";

let authHeader = localStorage.getItem('auth_data');

async function apiFetch(url, options = {}) {
    if (authHeader) {
        options.headers = {
            ...options.headers,
            'Authorization': 'Basic ' + authHeader
        };
    }
    const resp = await fetch(url, options);
    if (resp.status === 401) {
        localStorage.removeItem('auth_data');
        authHeader = null;
        document.getElementById('auth-modal').classList.remove('hidden');
    }
    return resp;
}

async function handleAuthAction() {
    const user = document.getElementById('auth-user').value;
    const pass = document.getElementById('auth-pass').value;
    try {
        const resp = await fetch('/auth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: user, password: pass })
        });
        if (resp.ok) {
            authHeader = btoa(user + ":" + pass);
            localStorage.setItem('auth_data', authHeader);
            document.getElementById('auth-modal').classList.add('hidden');
            await initApp();
        } else {
            const data = await resp.json();
            alert(data.detail || "Authentication failed.");
        }
    } catch (err) {
        alert("Server error.");
    }
}

async function checkAuth() {
    if (!authHeader) return false;
    try {
        const resp = await apiFetch('/models');
        if (resp.ok) {
            document.getElementById('auth-modal').classList.add('hidden');
            return true;
        }
    } catch (e) {}
    document.getElementById('auth-modal').classList.remove('hidden');
    return false;
}

function toggleDarkMode() {
    document.documentElement.classList.toggle('dark');
    const isDark = document.documentElement.classList.contains('dark');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
    
    if (typeof Chart !== 'undefined') {
        Chart.defaults.color = isDark ? '#e5e5ea' : '#1d1d1f';
        Chart.defaults.borderColor = isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';

        for (let id in Chart.instances) {
            Chart.instances[id].update();
        }
    }
}

function initDarkMode() {
    const savedTheme = localStorage.getItem('theme');
    const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const isDark = savedTheme === 'dark' || (!savedTheme && systemPrefersDark);
    
    if (isDark) document.documentElement.classList.add('dark');
    
    if (typeof Chart !== 'undefined') {
        Chart.defaults.color = isDark ? '#e5e5ea' : '#1d1d1f';
        Chart.defaults.borderColor = isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';
    }
}

document.getElementById('auth-pass').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleAuthAction();
});

document.getElementById('auth-user').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') document.getElementById('auth-pass').focus();
});

function populateVoices() {
    availableVoices = synth.getVoices().filter(v => v.lang.includes('pl'));
    availableVoices.forEach((voice, index) => {
        if (voice.name.toLowerCase().includes('google')) preferredVoiceIndex = index;
    });
}

if (speechSynthesis.onvoiceschanged !== undefined) {
    speechSynthesis.onvoiceschanged = populateVoices;
}

if ('webkitSpeechRecognition' in window) {
    recognition = new webkitSpeechRecognition();
    recognition.lang = 'pl-PL';
    recognition.onresult = (e) => {
        document.getElementById('query-input').value = e.results[0][0].transcript;
        sendQuery();
    };
    recognition.onend = () => document.getElementById('mic-btn').classList.remove('mic-active');
    recognition.onerror = () => document.getElementById('mic-btn').classList.remove('mic-active');
}

function toggleMic() {
    if (!recognition) return alert("STT not supported.");
    document.getElementById('mic-btn').classList.add('mic-active');
    recognition.start();
}

function toggleTTS() {
    isTtsEnabled = !isTtsEnabled;
    const btn = document.getElementById('tts-toggle');
    btn.classList.toggle('tts-active', isTtsEnabled);
    if (!isTtsEnabled) synth.cancel();
}

function speak(text) {
    if (!isTtsEnabled) return;
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(text.replace(/\[CHART\][\s\S]*?\[\/CHART\]/g, '').replace(/[#*`]/g, ''));
    utterance.lang = 'pl-PL';
    if (availableVoices.length > 0) utterance.voice = availableVoices[preferredVoiceIndex];
    synth.speak(utterance);
}

async function fetchContexts() {
    try {
        const resp = await apiFetch(`/contexts?t=${Date.now()}`);
        if (!resp.ok) return;
        const data = await resp.json();
        const current = contextSelect.value;
        contextSelect.innerHTML = '';
        if (data.contexts) {
            data.contexts.forEach(ctx => {
                const opt = document.createElement('option');
                opt.value = ctx; opt.innerText = ctx;
                contextSelect.appendChild(opt);
            });
        }
        if (data.contexts && data.contexts.includes(current)) contextSelect.value = current;
    } catch (err) {
        console.error("Error loading contexts.", err);
    }
}

async function createContextAPI(name) {
    await apiFetch('/contexts', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name})
    });
}

function createNewContext() {
    const modal = document.getElementById('context-modal');
    const input = document.getElementById('new-context-name');
    input.value = '';
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    setTimeout(() => input.focus(), 100);
}

function closeContextModal() {
    const modal = document.getElementById('context-modal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
}

async function submitNewContext() {
    const input = document.getElementById('new-context-name');
    const name = input.value;
    if (!name) return;
    
    const clean = name.replace(/[^a-zA-Z0-9_-]/g, "").toLowerCase();
    
    await createContextAPI(clean);
    await fetchContexts();
    contextSelect.value = clean;
    changeContext();
    closeContextModal();
}

document.getElementById('new-context-name').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') submitNewContext();
});

async function deleteCurrentContext() {
    const ctx = contextSelect.value;
    if (ctx && confirm(`Delete ${ctx}?`)) {
        await apiFetch(`/contexts/${ctx}`, { method: 'DELETE' });
        location.reload();
    }
}

async function initApp() {
    const isAuthenticated = await checkAuth();
    if (!isAuthenticated) {
        document.getElementById('welcome-msg').innerText = "Please log in to continue.";
        return;
    }
    populateVoices();
    await fetchModels();
    await fetchContexts();
    if (contextSelect.options.length === 0) { 
        await createContextAPI("general"); 
        await fetchContexts(); 
    }
    loadHistory();
}

async function fetchModels() {
    const resp = await apiFetch('/models');
    if (!resp.ok) return;
    const data = await resp.json();
    const sel = document.getElementById('model-select');
    sel.innerHTML = '';
    data.models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m; opt.innerText = m.replace('models/', '');
        if(m.includes('gemini-3.1-flash-lite')) opt.selected = true;
        sel.appendChild(opt);
    });
}

async function loadHistory() {
    const ctx = contextSelect.value;
    if (!ctx) return;
    const resp = await apiFetch(`/history?session_id=${sessionId}&context_name=${ctx}&t=${Date.now()}`);
    if (!resp.ok) return;
    const data = await resp.json();
    noteContent.innerHTML = '';
    if (data.history && data.history.length > 0) {
        data.history.forEach(msg => {
            const div = document.createElement('div');
            if (msg.role === 'user') {
                div.className = "border-l-4 border-blue-500 pl-4 py-1 mb-6 bg-gray-50/50 rounded-r-lg";
                div.innerHTML = `<h4 class="text-[10px] font-bold text-blue-500 uppercase mb-1 pt-2">Question</h4><p class="text-[15px] sm:text-base font-medium text-gray-900 pb-2">${msg.content}</p>`;
            } else {
                div.className = "prose max-w-none pb-8 border-b border-gray-100";
                div.innerHTML = `<h4 class="text-[10px] font-bold text-gray-400 uppercase mb-3 tracking-widest">Knowledge Analysis</h4>`;
                const c = document.createElement('div');
                c.className = "text-[14px] sm:text-[15px] text-gray-800 leading-relaxed";
                div.appendChild(c);
                renderMarkdownWithCharts(msg.content, c);
            }
            noteContent.appendChild(div);
        });
        noteContent.scrollTop = noteContent.scrollHeight;
    } else {
        noteContent.innerHTML = `<div class="text-center text-gray-400 mt-20 font-light italic">Start chatting in '${ctx}'...</div>`;
    }
}

function renderMarkdownWithCharts(text, container) {
    container.innerHTML = "";
    const chartRegex = /\[CHART\]([\s\S]*?)\[\/CHART\]/g;
    let lastIndex = 0; let match;
    const isDark = document.documentElement.classList.contains('dark');

    while ((match = chartRegex.exec(text)) !== null) {
        const before = text.substring(lastIndex, match.index);
        if (before.trim()) {
            const d = document.createElement('div');
            d.innerHTML = marked.parse(before);
            container.appendChild(d);
        }

        const can = document.createElement('div');
        can.className = "chart-container my-6 p-3 sm:p-4 bg-gray-50 dark:bg-[#1a1c23] rounded-xl relative w-full h-[300px]";
        const c = document.createElement('canvas');
        can.appendChild(c);
        container.appendChild(can);

        try {
            let rawJson = match[1].trim();
            rawJson = rawJson.replace(/```json/gi, '').replace(/```/g, '').trim();
            
            const cfg = JSON.parse(rawJson);
            cfg.options = cfg.options || {};
            cfg.options.maintainAspectRatio = false;

            cfg.data.datasets.forEach((ds) => {
                const type = cfg.type.toLowerCase();
                
                if (type === 'pie' || type === 'doughnut') {
                    ds.backgroundColor = chartColors;
                    ds.borderColor = isDark ? '#1c1c1e' : '#ffffff';
                    ds.borderWidth = 2;
                } else {
                    if (!ds.backgroundColor || ds.backgroundColor === '#007aff' || ds.backgroundColor === '#ccc') {
                        if (ds.data.length > 1) {
                            ds.backgroundColor = chartColors.slice(0, ds.data.length);
                        } else {
                            ds.backgroundColor = chartColors[0];
                        }
                    }
                }
            });

            new Chart(c, cfg);
        } catch (e) {
            console.error("Chart error:", e);
            c.outerHTML = `<div class="flex items-center justify-center h-full text-red-500 text-xs font-medium">Błąd renderowania wykresu. Zbyt skomplikowane dane.</div>`;
        }
        lastIndex = chartRegex.lastIndex;
    }
    const rem = text.substring(lastIndex);
    if (rem.trim()) {
        const d = document.createElement('div');
        d.innerHTML = marked.parse(rem);
        container.appendChild(d);
    }
}

let isAnalysisMode = false;

function setMode(mode) {
    isAnalysisMode = (mode === 'analyze');
    const chatBtn = document.getElementById('mode-chat-btn');
    const analyzeBtn = document.getElementById('mode-analyze-btn');

    if (isAnalysisMode) {
        analyzeBtn.className = "px-4 py-1.5 text-xs font-bold rounded-full bg-white dark:bg-[#3a3a3c] text-gray-900 dark:text-white shadow-sm transition-all";
        chatBtn.className = "px-4 py-1.5 text-xs font-bold rounded-full text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-all";
    } else {
        chatBtn.className = "px-4 py-1.5 text-xs font-bold rounded-full bg-white dark:bg-[#3a3a3c] text-gray-900 dark:text-white shadow-sm transition-all";
        analyzeBtn.className = "px-4 py-1.5 text-xs font-bold rounded-full text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-all";
    }
}

function askForHelp() {
const manualPrompt = `Act as the official documentation for Context Notes. Explain comprehensively how the application works using clear headings and bullet points. Cover these core features:
1. Contexts: Isolated workspaces. Each context maintains its own independent chat history and vector database memory.
2. Knowledge Base (Memory): Users paste text to be processed by AI into short, atomic facts. These facts are permanently stored in ChromaDB and automatically retrieved via semantic search to provide context-aware answers.
3. Interaction Modes: 'Ask' mode is for standard conversation and semantic retrieval (top 15 relevant facts). 'Analyze' mode forces the AI to aggregate database facts (up to 500 records) and generate visual charts or statistical summaries using Chart.js.
4. Features: Mention speech-to-text (microphone), text-to-speech (speaker), dark mode toggle, and dynamic LLM model switching.
Tone: Professional, highly informative, concise and friendly. Format: Markdown.`;

    const displayQ = "Explain me";
    sendQuery(manualPrompt, displayQ);
}

async function sendQuery(customQuery = null, customDisplay = null) {
    const ctx = contextSelect.value;
    const input = document.getElementById('query-input');
    const model = document.getElementById('model-select').value;
    
    const isCustom = typeof customQuery === 'string';
    let q = isCustom ? customQuery : input.value;
    let visibleQ = (typeof customDisplay === 'string') ? customDisplay : q;
    
    if(!q) return;
    
    if (!isCustom) {
        input.value = '';
    }

    const u = document.createElement('div');
    u.className = "border-l-4 border-blue-500 pl-4 py-1 mb-6 bg-gray-50/50 rounded-r-lg";
    u.innerHTML = `<h4 class="text-[10px] font-bold text-blue-500 uppercase mb-1 pt-2">Question</h4><p class="text-[15px] sm:text-base font-medium text-gray-900 pb-2">${visibleQ}</p>`;
    noteContent.appendChild(u);
    noteContent.scrollTop = noteContent.scrollHeight;

    let finalQuery = q;
    if (isAnalysisMode && !isCustom) {
        finalQuery = "analyze: " + q;
    }

    try {
        const resp = await apiFetch('/query', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({question: finalQuery, session_id: sessionId, context_name: ctx, model_name: model})
        });
        const data = await resp.json();
        const a = document.createElement('div');
        a.className = "prose max-w-none pb-8 border-b border-gray-100";
        a.innerHTML = `<h4 class="text-[10px] font-bold text-gray-400 uppercase mb-3 tracking-widest">Knowledge Analysis</h4>`;
        const c = document.createElement('div'); 
        c.className = "text-[14px] sm:text-[15px] text-gray-800 leading-relaxed";
        a.appendChild(c); noteContent.appendChild(a);
        renderMarkdownWithCharts(data.answer, c);
        noteContent.scrollTop = noteContent.scrollHeight;
        speak(data.answer);
    } catch (err) {}
}

async function addDoc() {
    const ctx = contextSelect.value;
    const btn = event.target;
    const text = document.getElementById('doc-input').value;
    const model = document.getElementById('model-select').value;
    if(!text || !ctx || !model) return;
    btn.disabled = true;
    btn.textContent = "Processing...";
    try {
        const resp = await apiFetch('/add_document', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text: text, context_name: ctx, model_name: model})
        });
        if (!resp.ok) {
            const errData = await resp.json();
            throw new Error(errData.detail || "API Error");
        }
        document.getElementById('doc-input').value = '';
        currentOffset = 0;
        loadDocs();
    } catch (err) {
        alert("Failed to process document:\n" + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = "Extract Facts";
    }
}

async function loadDocs() {
    const ctx = contextSelect.value;
    if (!ctx) return;
    const url = `/documents?context_name=${ctx}&limit=${limit}&offset=${currentOffset}${currentSearch ? '&search=' + encodeURIComponent(currentSearch) : ''}&t=${Date.now()}`;
    const resp = await apiFetch(url);
    if (!resp.ok) return;
    const data = await resp.json();
    const list = document.getElementById('docs-list');
    list.innerHTML = data.documents.length ? data.documents.map(d => `
        <div class="flex justify-between items-start gap-3 p-3 bg-white rounded-lg border border-gray-200 shadow-sm text-[13px] leading-snug hover:bg-gray-50 transition-colors">
            <span class="flex-1 text-gray-700">${d.content}</span>
            <button onclick="deleteDoc('${d.id}')" class="text-gray-300 hover:text-red-500 px-2 text-lg font-light transition-colors">×</button>
        </div>
    `).join('') : '<p class="text-xs text-gray-400 italic text-center py-4">No results found.</p>';
    document.getElementById('prev-btn').disabled = currentOffset === 0;
    document.getElementById('next-btn').disabled = data.documents.length < limit || (currentOffset + limit >= data.total);
    const pageNum = Math.floor(currentOffset / limit) + 1;
    document.getElementById('page-input').value = pageNum;
}

function filterDocs() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        currentSearch = document.getElementById('search-docs').value;
        currentOffset = 0;
        loadDocs();
    }, 400);
}

function prevPage() {
    if (currentOffset >= limit) {
        currentOffset -= limit;
        loadDocs();
    }
}

function nextPage() {
    currentOffset += limit;
    loadDocs();
}

function goToPage() {
    const page = parseInt(document.getElementById('page-input').value);
    if (page > 0) {
        currentOffset = (page - 1) * limit;
        loadDocs();
    }
}

async function deleteDoc(id) {
    const ctx = contextSelect.value;
    await apiFetch(`/documents?context_name=${ctx}&doc_id=${id}`, { method: 'DELETE' });
    loadDocs();
}

function toggleDocs() { 
    const panel = document.getElementById('docs-panel');
    panel.classList.toggle('hidden');
    if(!panel.classList.contains('hidden')) {
        currentOffset = 0;
        document.getElementById('search-docs').value = "";
        currentSearch = "";
        loadDocs();
    }
}

function changeContext() { 
    currentOffset = 0;
    loadHistory(); 
    if(!document.getElementById('docs-panel').classList.contains('hidden')) loadDocs();
}

async function clearChat() {
    const ctx = contextSelect.value;
    await apiFetch(`/session/${sessionId}?context_name=${ctx}`, { method: 'DELETE' });
    loadHistory();
}

document.getElementById('query-input').addEventListener('keypress', (e) => { if (e.key === 'Enter') sendQuery(); });