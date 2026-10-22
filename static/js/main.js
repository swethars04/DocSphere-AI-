// Predefined suggested prompts per sector classification
const PREDEFINED_PROMPTS = {
    'Automobile': [
        "Compare Scope 1 and Scope 2 greenhouse gas emissions.",
        "Which companies in the sector have committed to Net Zero targets?",
        "Show corporate water consumption and recycling trends.",
        "Compare sustainability targets and compliance for FY2026."
    ],
    'IT': [
        "Compare energy efficiency and electricity consumption across IT centers.",
        "What are the waste management and e-waste recycling metrics?",
        "Compare gender diversity and women representation in IT leadership.",
        "Describe the cybersecurity governance and data privacy measures."
    ],
    'Banking': [
        "Show the share of paperless banking transactions and digital footprints.",
        "What are the ESG integration criteria for investment/loan portfolios?",
        "Compare corporate social responsibility (CSR) spending in community development.",
        "Detail board diversity and risk management committee policies."
    ],
    'Pharmaceuticals': [
        "Analyze water recycling ratios and effluent treatment safeguards.",
        "What are the waste disposal protocols for hazardous chemical substances?",
        "Compare employee safety training hours and injury rates.",
        "What product quality control and compliance certifications are listed?"
    ],
    'Energy': [
        "Benchmark renewable energy generation capacity vs non-renewable.",
        "Detail carbon footprint mitigation initiatives and targets.",
        "What are the rehabilitation and land usage compensation policies?",
        "Compare green energy capital expenditure budgets."
    ]
};

// Sector Onboarding & Suggested Prompt Functions
function handleSectorChange(newSector) {
    localStorage.setItem('preferred_sector', newSector);
    
    // Sync all dropdowns
    const select = document.getElementById('sector-select');
    if (select) select.value = newSector;
    
    // Refresh welcome prompts if active
    const stream = document.getElementById('message-stream');
    if (stream && stream.querySelector('.chat-welcome-container')) {
        renderWelcomePrompts(stream);
    }
}

async function renderWelcomePrompts(stream) {
    const reportId = document.body.getAttribute('data-report-id');
    let prompts = [];
    
    try {
        const response = await fetch(`/chat/prompts/${reportId}`);
        const data = await response.json();
        prompts = data.prompts || [];
    } catch (err) {
        console.error("Error fetching predefined prompts:", err);
        prompts = [
            "What are the carbon footprint mitigation targets?",
            "Compare the Scope 1 and Scope 2 greenhouse emissions.",
            "What employee diversity and inclusion metrics are disclosed?",
            "Explain the governance risk management policies."
        ];
    }
    
    let promptsHtml = "";
    prompts.forEach(p => {
        promptsHtml += `
            <div class="prompt-card" onclick="submitSuggestedPrompt('${p.replace(/'/g, "\\'")}')">
                <div class="prompt-card-icon"><i class="fas fa-arrow-right"></i></div>
                <div class="prompt-card-text">${p}</div>
            </div>
        `;
    });

    stream.innerHTML = `
        <div class="chat-welcome-container">
            <div class="chat-welcome-icon"><i class="fas fa-leaf"></i></div>
            <h2>AI Sustainability Intelligence Assistant</h2>
            <p class="text-slate-400 text-sm max-w-[600px] mx-auto mb-6">
                Ask any question about the ESG performance of this company or choose a suggested analysis prompt below:
            </p>
            
            <div class="prompts-grid">
                ${promptsHtml}
            </div>
        </div>
    `;
    renderReferences([]);
}

function submitSuggestedPrompt(promptText) {
    const textarea = document.getElementById('chat-input');
    if (textarea) {
        textarea.value = promptText;
        // Auto trigger size adjustment
        textarea.style.height = 'auto';
        textarea.style.height = textarea.scrollHeight + 'px';
        
        const sendBtn = document.getElementById('chat-send-btn');
        if (sendBtn) {
            sendBtn.click();
        }
    }
}

function showOnboardingModal() {
    if (document.querySelector('.onboarding-overlay')) return;
    
    const overlay = document.createElement('div');
    overlay.className = 'onboarding-overlay';
    
    overlay.innerHTML = `
        <div class="onboarding-modal">
            <h2 class="onboarding-title"><i class="fas fa-leaf text-emerald-500 mr-2"></i>Sustainability Intelligence</h2>
            <p class="onboarding-subtitle">
                Welcome! Please select your industry sector to customize the dynamic prompt suggestions and explore ESG insights tailored for your domain:
            </p>
            
            <div class="onboarding-grid">
                <div class="onboarding-card" onclick="selectSectorFromOnboarding('Automobile')">
                    <div class="onboarding-card-icon"><i class="fas fa-car"></i></div>
                    <div class="onboarding-card-title">Automobile Sector</div>
                </div>
                <div class="onboarding-card" onclick="selectSectorFromOnboarding('IT')">
                    <div class="onboarding-card-icon"><i class="fas fa-laptop"></i></div>
                    <div class="onboarding-card-title">Information Technology</div>
                </div>
                <div class="onboarding-card" onclick="selectSectorFromOnboarding('Banking')">
                    <div class="onboarding-card-icon"><i class="fas fa-university"></i></div>
                    <div class="onboarding-card-title">Banking & Financial</div>
                </div>
                <div class="onboarding-card" onclick="selectSectorFromOnboarding('Pharmaceuticals')">
                    <div class="onboarding-card-icon"><i class="fas fa-prescription-bottle-medical"></i></div>
                    <div class="onboarding-card-title">Pharmaceuticals</div>
                </div>
                <div class="onboarding-card" onclick="selectSectorFromOnboarding('Energy')">
                    <div class="onboarding-card-icon"><i class="fas fa-bolt"></i></div>
                    <div class="onboarding-card-title">Power & Energy</div>
                </div>
            </div>
        </div>
    `;
    
    document.body.appendChild(overlay);
}

function selectSectorFromOnboarding(sector) {
    handleSectorChange(sector);
    const overlay = document.querySelector('.onboarding-overlay');
    if (overlay) {
        overlay.remove();
    }
}

// Theme Toggle Logic
function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    const themeToggleBtn = document.getElementById('theme-toggle');
    
    if (savedTheme === 'light') {
        document.body.classList.add('light-theme');
        if (themeToggleBtn) themeToggleBtn.innerHTML = '<i class="fas fa-moon"></i>';
    } else {
        document.body.classList.remove('light-theme');
        if (themeToggleBtn) themeToggleBtn.innerHTML = '<i class="fas fa-sun"></i>';
    }
}

function toggleTheme() {
    const themeToggleBtn = document.getElementById('theme-toggle');
    if (document.body.classList.contains('light-theme')) {
        document.body.classList.remove('light-theme');
        localStorage.setItem('theme', 'dark');
        if (themeToggleBtn) themeToggleBtn.innerHTML = '<i class="fas fa-sun"></i>';
    } else {
        document.body.classList.add('light-theme');
        localStorage.setItem('theme', 'light');
        if (themeToggleBtn) themeToggleBtn.innerHTML = '<i class="fas fa-moon"></i>';
    }
}

// Loader Utilities
function showLoader(title, subtitle = "This may take a moment...") {
    const loader = document.getElementById('loader-overlay');
    if (loader) {
        document.getElementById('loader-title').innerText = title;
        document.getElementById('loader-subtext').innerText = subtitle;
        loader.style.display = 'flex';
    }
}

function hideLoader() {
    const loader = document.getElementById('loader-overlay');
    if (loader) {
        loader.style.display = 'none';
    }
}

// Upload Forms Handler
function initUploadForms() {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const fileForm = document.getElementById('file-upload-form');
    const urlForm = document.getElementById('url-upload-form');
    
    if (dropZone && fileInput) {
        // Drag events
        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                dropZone.classList.add('drag-over');
            }, false);
        });
        
        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => {
                e.preventDefault();
                dropZone.classList.remove('drag-over');
            }, false);
        });
        
        dropZone.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files.length) {
                fileInput.files = files;
                handleFileUpload(files[0]);
            }
        });
        
        dropZone.addEventListener('click', () => {
            fileInput.click();
        });
        
        fileInput.addEventListener('change', () => {
            if (fileInput.files.length) {
                handleFileUpload(fileInput.files[0]);
            }
        });
    }
    
    if (urlForm) {
        urlForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const urlInput = document.getElementById('report-url');
            if (urlInput && urlInput.value.trim() !== "") {
                handleUrlUpload(urlInput.value.trim());
            }
        });
    }
}

function handleFileUpload(file) {
    const formData = new FormData();
    formData.append('file', file);
    
    showLoader("Uploading Report...", "Validating file format and secure uploading...");
    
    fetch('/upload', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json().then(data => ({ status: response.status, body: data })))
    .then(res => {
        if (res.status === 200 && res.body.success) {
            showLoader("Parsing & Generating Index...", "Extracting facts, setting up vector store, and running ESG AI summarizer...");
            // Keep loader visible briefly, then reload
            setTimeout(() => {
                window.location.href = `/?report_id=${res.body.report_id}`;
            }, 1000);
        } else {
            hideLoader();
            alert(res.body.message || "Failed to upload report.");
        }
    })
    .catch(err => {
        hideLoader();
        console.error(err);
        alert("An error occurred during file upload.");
    });
}

function handleUrlUpload(url) {
    showLoader("Downloading Report...", "Fetching file from remote URL and validating...");
    
    fetch('/upload-url', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ url: url })
    })
    .then(response => response.json().then(data => ({ status: response.status, body: data })))
    .then(res => {
        if (res.status === 200 && res.body.success) {
            showLoader("Parsing & Indexing...", "Extracting facts, setting up vector store, and running ESG AI summarizer...");
            setTimeout(() => {
                window.location.href = `/?report_id=${res.body.report_id}`;
            }, 1000);
        } else {
            hideLoader();
            alert(res.body.message || "Failed to download report from URL.");
        }
    })
    .catch(err => {
        hideLoader();
        console.error(err);
        alert("An error occurred during remote download.");
    });
}

// Chat Session and Message Logic
let currentSessionId = null;

function initChatWorkspace(reportId) {
    const msgInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send-btn');
    const newChatBtn = document.getElementById('new-chat-btn');
    
    if (newChatBtn) {
        newChatBtn.addEventListener('click', () => {
            createNewSession(reportId);
        });
    }
    
    if (msgInput && sendBtn) {
        sendBtn.addEventListener('click', () => {
            sendMessage(reportId);
        });
        
        msgInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage(reportId);
            }
        });
    }
    
    // Load existing sessions
    loadSessions(reportId).then(() => {
        if (!currentSessionId) {
            createNewSession(reportId);
        }
    });
}

async function loadSessions(reportId) {
    try {
        const response = await fetch(`/chat/sessions/${reportId}`);
        const sessions = await response.json();
        
        const container = document.getElementById('sessions-list');
        if (!container) return;
        
        container.innerHTML = "";
        
        if (sessions.length > 0) {
            sessions.forEach(session => {
                const item = document.createElement('div');
                item.className = `session-tab ${currentSessionId === session.session_id ? 'active' : ''}`;
                item.innerHTML = `<i class="far fa-comments mr-2"></i> ${session.title}`;
                item.addEventListener('click', () => {
                    selectSession(session.session_id);
                });
                container.appendChild(item);
            });
            
            // Auto-select first session if none active
            if (!currentSessionId) {
                selectSession(sessions[0].session_id);
            }
        }
    } catch (err) {
        console.error("Error loading chat sessions:", err);
    }
}

async function createNewSession(reportId) {
    try {
        const title = `Session ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
        const response = await fetch(`/chat/session/create/${reportId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: title })
        });
        
        const session = await response.json();
        currentSessionId = session.session_id;
        
        // Reload list and messages
        await loadSessions(reportId);
        selectSession(currentSessionId);
    } catch (err) {
        console.error("Error creating session:", err);
    }
}

function selectSession(sessionId) {
    currentSessionId = sessionId;
    
    // Update active class in sidebar tabs
    const tabs = document.querySelectorAll('.session-tab');
    tabs.forEach(t => t.classList.remove('active'));
    
    // Find the correct tab and mark active
    const activeTab = Array.from(tabs).find(t => t.innerText.includes(sessionId));
    // Alternatively load list again which resolves classes
    
    // Load messages
    loadMessages(sessionId);
    
    // Update download link
    const downloadBtn = document.getElementById('download-chat-btn');
    if (downloadBtn) {
        downloadBtn.href = `/chat/session/${sessionId}/download`;
        downloadBtn.style.display = 'inline-flex';
    }
}

async function loadMessages(sessionId) {
    const stream = document.getElementById('message-stream');
    if (!stream) return;
    
    stream.innerHTML = '<div class="text-center text-slate-500 py-8">Loading conversation...</div>';
    
    try {
        const response = await fetch(`/chat/session/${sessionId}/messages`);
        const messages = await response.json();
        
        stream.innerHTML = "";
        
        if (messages.length === 0) {
            renderWelcomePrompts(stream);
            return;
        }
        
        messages.forEach(msg => {
            appendMessageBubble(msg.role, msg.content, msg.confidence_score, msg.references);
        });
        
        scrollToBottom();
    } catch (err) {
        stream.innerHTML = '<div class="text-center text-red-500 py-8">Failed to load conversation history.</div>';
        console.error(err);
    }
}

function appendMessageBubble(role, content, confidence = null, references = []) {
    const stream = document.getElementById('message-stream');
    if (!stream) return;
    
    // Remove empty state message if it is there
    const emptyState = stream.querySelector('.empty-references-state');
    if (emptyState) {
        stream.innerHTML = "";
    }
    
    const container = document.createElement('div');
    container.className = `chat-bubble-container ${role === 'user' ? 'user' : 'assistant'}`;
    
    const sender = document.createElement('div');
    sender.className = 'bubble-sender';
    sender.innerText = role === 'user' ? 'You' : 'AI Assistant';
    container.appendChild(sender);
    
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    
    if (role === 'assistant') {
        // Parse markdown content
        bubble.innerHTML = marked.parse(content);
    } else {
        bubble.innerText = content;
    }
    container.appendChild(bubble);
    
    // Add confidence tag if assistant response
    if (role === 'assistant' && confidence !== null) {
        const meta = document.createElement('div');
        meta.className = 'bubble-meta';
        
        let label = "Low";
        let colorClass = "confidence-low";
        if (confidence >= 0.8) {
            label = "High";
            colorClass = "confidence-high";
        } else if (confidence >= 0.4) {
            label = "Medium";
            colorClass = "confidence-medium";
        }
        
        meta.innerHTML = `
            <span class="confidence-score">
                <i class="fas fa-shield-alt"></i> Grounding Confidence: <strong class="${colorClass}">${label}</strong>
            </span>
        `;
        
        if (references && references.length > 0) {
            const refLink = document.createElement('a');
            refLink.href = "#";
            refLink.className = "text-emerald-500 underline ml-2 hover:text-emerald-400";
            refLink.innerHTML = `<i class="fas fa-list-ol"></i> View ${references.length} Sources`;
            refLink.addEventListener('click', (e) => {
                e.preventDefault();
                renderReferences(references);
            });
            meta.appendChild(refLink);
        }
        
        container.appendChild(meta);
    }
    
    stream.appendChild(container);
    scrollToBottom();
}

function sendMessage(reportId) {
    const msgInput = document.getElementById('chat-input');
    if (!msgInput || !currentSessionId) return;
    
    const question = msgInput.value.trim();
    if (question === "") return;
    
    // Append user message bubble
    appendMessageBubble('user', question);
    msgInput.value = "";
    
    // Create and append Typing Indicator bubble
    const stream = document.getElementById('message-stream');
    const typingIndicator = document.createElement('div');
    typingIndicator.className = 'chat-bubble-container assistant typing-indicator-container';
    typingIndicator.innerHTML = `
        <div class="bubble-sender">AI Assistant</div>
        <div class="chat-bubble flex items-center gap-1 py-3 px-4">
            <span class="loader-spinner !w-4 !h-4 !border-2"></span> Generating answer...
        </div>
    `;
    stream.appendChild(typingIndicator);
    scrollToBottom();
    
    // Post query
    fetch(`/chat/${reportId}/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            message: question,
            session_id: currentSessionId
        })
    })
    .then(res => res.json())
    .then(data => {
        // Remove typing indicator
        const indicators = stream.querySelectorAll('.typing-indicator-container');
        indicators.forEach(i => i.remove());
        
        if (data.success) {
            let confVal = 0.1;
            if (data.confidence === 'High') confVal = 0.9;
            else if (data.confidence === 'Medium') confVal = 0.5;
            
            appendMessageBubble('assistant', data.answer, confVal, data.references);
            
            // Re-load sessions to update titles (if first message changed it)
            loadSessions(reportId);
        } else {
            appendMessageBubble('assistant', `**Error:** ${data.message || "Failed to retrieve answer."}`, 0);
        }
    })
    .catch(err => {
        const indicators = stream.querySelectorAll('.typing-indicator-container');
        indicators.forEach(i => i.remove());
        console.error(err);
        appendMessageBubble('assistant', "**Network Error:** Failed to establish connection to Flask server.", 0);
    });
}

function renderReferences(references) {
    const list = document.getElementById('modal-citations-list');
    const modal = document.getElementById('citations-modal');
    if (!list || !modal) return;
    
    list.innerHTML = "";
    
    if (!references || references.length === 0) {
        list.innerHTML = `
            <div class="empty-references-state text-center py-6 text-slate-500">
                <p>No active citations found.</p>
            </div>
        `;
        return;
    }
    
    references.forEach((ref, index) => {
        const card = document.createElement('div');
        card.className = 'ref-card';
        
        const sourceTitle = ref.source;
        
        card.innerHTML = `
            <div class="ref-source font-bold text-emerald-500 mb-1" title="${ref.source}">[${index + 1}] ${sourceTitle}</div>
            <div class="ref-text text-sm text-slate-300 leading-relaxed bg-slate-900/50 p-3 rounded-lg border border-slate-800">${ref.text}</div>
            <div class="text-[10px] text-slate-500 mt-2 text-right">Similarity Match: ${(ref.score * 100).toFixed(1)}%</div>
        `;
        list.appendChild(card);
    });
    
    // Open the citations modal
    modal.style.display = 'flex';
}

function initCitationsModal() {
    const modal = document.getElementById('citations-modal');
    const closeBtn = document.getElementById('close-citations-modal');
    
    if (!modal || !closeBtn) return;
    
    closeBtn.addEventListener('click', () => {
        modal.style.display = 'none';
    });
    
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.style.display = 'none';
        }
    });
}

function scrollToBottom() {
    const stream = document.getElementById('message-stream');
    if (stream) {
        stream.scrollTop = stream.scrollHeight;
    }
}

// Reset / Delete Report Action
function resetReportKnowledgeBase(reportId) {
    if (confirm("Are you sure you want to delete this report and reset its knowledge base? This action will permanently remove all parsed facts, vector indices, and chat logs.")) {
        showLoader("Resetting Knowledge Base...", "Deleting vector index files and database archives...");
        
        fetch(`/reset/${reportId}`, {
            method: 'POST'
        })
        .then(res => res.json())
        .then(data => {
            hideLoader();
            if (data.success) {
                window.location.href = "/";
            } else {
                alert(data.message || "Failed to reset report knowledge base.");
            }
        })
        .catch(err => {
            hideLoader();
            console.error(err);
            alert("Error trying to reset knowledge base.");
        });
    }
}

function initCompanySearch() {
    const searchInput = document.getElementById('company-search-input');
    const searchBtn = document.getElementById('company-search-btn');
    
    if (!searchInput || !searchBtn) return;
    
    const triggerSearch = () => {
        const companyName = searchInput.value.trim();
        if (companyName === "") return;
        
        showLoader("Search & Scraping Pipeline Active", `Querying corporate filing boards for '${companyName}'...`);
        
        // Progress stage simulations for better visual feedback
        let progressStages = [
            "Connecting to exchange disclosure boards...",
            "Searching announcements for BRSR sustainability filings...",
            "Filing package located! Initiating download...",
            "Extracting document contexts, units, and values...",
            "Running offline sentence-transformer model...",
            "Building cosine-similarity FAISS vector index...",
            "Running Groq summary and profile extractor...",
            "Structuring citations and saving report database..."
        ];
        
        let stageIdx = 0;
        const progressInterval = setInterval(() => {
            if (stageIdx < progressStages.length) {
                const subtext = document.getElementById('loader-subtext');
                if (subtext) {
                    subtext.innerText = progressStages[stageIdx];
                }
                stageIdx++;
            }
        }, 1200);

        fetch('/search_company', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ company_name: companyName })
        })
        .then(res => {
            clearInterval(progressInterval);
            return res.json();
        })
        .then(data => {
            hideLoader();
            if (data.success) {
                // Redirect to the newly indexed company's dashboard!
                window.location.href = `/?report_id=${data.report_id}`;
            } else {
                alert(data.message || "Failed to search/scrape report for this company.");
            }
        })
        .catch(err => {
            clearInterval(progressInterval);
            hideLoader();
            console.error("Error during company search:", err);
            alert("An error occurred during the search/scraping pipeline.");
        });
    };
    
    searchBtn.addEventListener('click', triggerSearch);
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            triggerSearch();
        }
    });
}

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    
    const themeBtn = document.getElementById('theme-toggle');
    if (themeBtn) {
        themeBtn.addEventListener('click', toggleTheme);
    }
    
    // Sync sector dropdown state on load and bind event listeners
    const sectorSelect = document.getElementById('sector-select');
    if (sectorSelect) {
        const savedSector = localStorage.getItem('preferred_sector') || 'IT';
        sectorSelect.value = savedSector;
        sectorSelect.addEventListener('change', (e) => {
            handleSectorChange(e.target.value);
        });
    }

    // Check onboarding modal triggers
    if (!localStorage.getItem('preferred_sector')) {
        showOnboardingModal();
    }

    // Initialize company search triggers
    initCompanySearch();

    // Initialize citations modal dismissal triggers
    initCitationsModal();

    // Check which page we are on
    const isIndexPage = document.getElementById('drop-zone') !== null;
    const isChatPage = document.getElementById('message-stream') !== null;
    
    if (isIndexPage) {
        initUploadForms();
    }
    
    if (isChatPage) {
        // Retrieve report ID from URL path or body attribute
        const reportId = document.body.dataset.reportId;
        if (reportId) {
            initChatWorkspace(parseInt(reportId));
        }
    }
});
