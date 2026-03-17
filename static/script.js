const noteContent = document.getElementById('note-content');
const contextSelect = document.getElementById('context-select');
const sessionId = "default_user";

let isTtsEnabled = false;
let recognition;
let availableVoices = [];
let preferredVoiceIndex = 0;
const synth = window.speechSynthesis;

let currentOffset = 0;
const limit = 10;
let currentSearch = "";
let searchTimeout;

function populateVoices() {
    availableVoices = synth.getVoices().filter(v => v.lang.includes('pl'));
    availableVoices.forEach((voice, index) => {
        if (voice.name.toLowerCase().includes('google')) {
            preferredVoiceIndex = index;
        }
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
    if (availableVoices.length > 0) {
        utterance.voice = availableVoices[preferredVoiceIndex];
    }
    synth.speak(utterance);
}

async function fetchContexts() {
    const resp = await fetch('/contexts');
    const data = await resp.json();
    const current = contextSelect.value;
    contextSelect.innerHTML = '';
    data.contexts.forEach(ctx => {
        const opt = document.createElement('option');
        opt.value = ctx; opt.innerText = ctx;
        contextSelect.appendChild(opt);
    });
    if (data.contexts.includes(current)) contextSelect.value = current;
}

async function createContextAPI(name) {
    await fetch('/contexts', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name})
    });
}

async function createNewContext() {
    const name = prompt("Name (alphanumeric):");
    if (!name) return;
    const clean = name.replace(/[^a-zA-Z0-9_-]/g, "").toLowerCase();
    await createContextAPI(clean);
    await fetchContexts();
    contextSelect.value = clean;
    changeContext();
}

async function deleteCurrentContext() {
    const ctx = contextSelect.value;
    if (ctx && confirm(`Delete ${ctx}?`)) {
        await fetch(`/contexts/${ctx}`, { method: 'DELETE' });
        location.reload();
    }
}

async function initApp() {
    populateVoices();
    await fetchModels();
    await fetchContexts();
    if (contextSelect.options.length === 0) { await createContextAPI("general"); await fetchContexts(); }
    loadHistory();
}

async function fetchModels() {
    const resp = await fetch('/models');
    const data = await resp.json();
    const sel = document.getElementById('model-select');
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
    const resp = await fetch(`/history?session_id=${sessionId}&context_name=${ctx}`);
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
    while ((match = chartRegex.exec(text)) !== null) {
        const before = text.substring(lastIndex, match.index);
        if (before.trim()) {
            const d = document.createElement('div'); d.innerHTML = marked.parse(before);
            container.appendChild(d);
        }
        const can = document.createElement('div');
        can.className = "my-6 p-3 sm:p-4 bg-gray-50 rounded-xl border border-gray-100 h-[250px] sm:h-[300px] relative w-full";
        const c = document.createElement('canvas'); can.appendChild(c);
        container.appendChild(can);
        try {
            const cfg = JSON.parse(match[1].trim());
            cfg.options = cfg.options || {}; cfg.options.maintainAspectRatio = false;
            new Chart(c, cfg);
        } catch (e) {}
        lastIndex = chartRegex.lastIndex;
    }
    const rem = text.substring(lastIndex);
    if (rem.trim()) {
        const d = document.createElement('div'); d.innerHTML = marked.parse(rem);
        container.appendChild(d);
    }
}

async function sendQuery() {
    const ctx = contextSelect.value;
    const input = document.getElementById('query-input');
    const model = document.getElementById('model-select').value;
    const q = input.value;
    if(!q) return;
    input.value = '';
    const u = document.createElement('div');
    u.className = "border-l-4 border-blue-500 pl-4 py-1 mb-6 bg-gray-50/50 rounded-r-lg";
    u.innerHTML = `<h4 class="text-[10px] font-bold text-blue-500 uppercase mb-1 pt-2">Question</h4><p class="text-[15px] sm:text-base font-medium text-gray-900 pb-2">${q}</p>`;
    noteContent.appendChild(u);
    noteContent.scrollTop = noteContent.scrollHeight;
    
    try {
        const resp = await fetch('/query', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({question: q, session_id: sessionId, context_name: ctx, model_name: model})
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
        const resp = await fetch('/add_document', {
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
    const url = `/documents?context_name=${ctx}&limit=${limit}&offset=${currentOffset}${currentSearch ? '&search=' + encodeURIComponent(currentSearch) : ''}`;
    const resp = await fetch(url);
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
    await fetch(`/documents?context_name=${ctx}&doc_id=${id}`, { method: 'DELETE' });
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
    if(!document.getElementById('docs-panel').classList.contains('hidden')) {
        loadDocs();
    }
}

async function clearChat() {
    const ctx = contextSelect.value;
    await fetch(`/session/${sessionId}?context_name=${ctx}`, { method: 'DELETE' });
    loadHistory();
}

document.getElementById('query-input').addEventListener('keypress', (e) => { if (e.key === 'Enter') sendQuery(); });