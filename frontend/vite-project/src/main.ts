/**
 * Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
 * This software is proprietary and confidential. Unauthorised use is prohibited.
 *
 * meldra.ai — INTERACTIVE PORTAL SHELL CONTROLLER
 *
 * Local Modules:
 * - `./style.css`: Core design system, color variables, layout grid, glassmorphism templates, animations.
 * - `./api.ts`: API interface layer mapping front-end interactions to the FastAPI backend (Port 8000).
 */
import './style.css';
import { api, tokenStore } from './api';
import type { ChatMessage, CSVUploadResponse } from './api';


// ─────────────────────────────────────────
// STATE MANAGEMENT
// ─────────────────────────────────────────
interface AppState {
  chatHistory: ChatMessage[];
  uploadedFilePath: string | null;
  uploadedFileName: string | null;
  uploadedSchema: { name: string; type: string }[] | null;
  activeTab: string;
}

const state: AppState = {
  chatHistory: [],
  uploadedFilePath: null,
  uploadedFileName: null,
  uploadedSchema: null,
  activeTab: 'chat-tab',
};

// ─────────────────────────────────────────
// DOM SELECTORS
// ─────────────────────────────────────────
const tabButtons = document.querySelectorAll('.tab-btn');
const tabContents = document.querySelectorAll('.tab-content');

// AWS Config DOM
const customAwsToggle = document.getElementById('custom-aws-toggle') as HTMLInputElement;
const awsConfigForm = document.getElementById('aws-config-form') as HTMLDivElement;
const awsDemoInfo = document.getElementById('aws-demo-info') as HTMLDivElement;
const awsRegionInput = document.getElementById('aws-region') as HTMLInputElement;
const awsS3UriInput = document.getElementById('aws-s3-uri') as HTMLInputElement;
const awsAccessKeyInput = document.getElementById('aws-access-key') as HTMLInputElement;
const awsSecretKeyInput = document.getElementById('aws-secret-key') as HTMLInputElement;
const btnConnectAws = document.getElementById('btn-connect-aws') as HTMLButtonElement;

// Chat DOM
const chatMessages = document.getElementById('chat-messages') as HTMLDivElement;
const chatInputText = document.getElementById('chat-input-text') as HTMLInputElement;
const btnSendMessage = document.getElementById('btn-send-message') as HTMLButtonElement;
const btnClearChat = document.getElementById('btn-clear-chat') as HTMLButtonElement;

// Ingest DOM
const dropZone = document.getElementById('drop-zone') as HTMLDivElement;
const csvFileInput = document.getElementById('csv-file-input') as HTMLInputElement;
const previewSection = document.getElementById('preview-section') as HTMLDivElement;
const previewRowCount = document.getElementById('preview-row-count') as HTMLSpanElement;
const previewTheadTr = document.getElementById('preview-thead-tr') as HTMLTableRowElement;
const previewTbody = document.getElementById('preview-tbody') as HTMLTableSectionElement;
const schemaConfigTbody = document.getElementById('schema-config-tbody') as HTMLTableSectionElement;
const ingestNamespace = document.getElementById('ingest-namespace') as HTMLInputElement;
const ingestTableName = document.getElementById('ingest-table-name') as HTMLInputElement;
const ingestWriteMode = document.getElementById('ingest-write-mode') as HTMLSelectElement;
const ingestMergeKey = document.getElementById('ingest-merge-key') as HTMLInputElement;
const btnDoIngest = document.getElementById('btn-do-ingest') as HTMLButtonElement;
const ingestLoadingOverlay = document.getElementById('ingest-loading-overlay') as HTMLDivElement;
const ingestLoadingText = document.getElementById('ingest-loading-text') as HTMLHeadingElement;

// Sample CSV Download Buttons
const btnSampleEmployees = document.getElementById('btn-sample-employees') as HTMLButtonElement;
const btnSampleOrders = document.getElementById('btn-sample-orders') as HTMLButtonElement;
const btnSampleTraffic = document.getElementById('btn-sample-traffic') as HTMLButtonElement;

// Graph DOM
const graphStatNodes = document.getElementById('graph-stat-nodes') as HTMLDivElement;
const graphStatEdges = document.getElementById('graph-stat-edges') as HTMLDivElement;
const graphStatActive = document.getElementById('graph-stat-active') as HTMLDivElement;
const cypherQueryInput = document.getElementById('cypher-query-input') as HTMLTextAreaElement;
const btnExecuteCypher = document.getElementById('btn-execute-cypher') as HTMLButtonElement;
const graphResultsTheadTr = document.getElementById('graph-results-thead-tr') as HTMLTableRowElement;
const graphResultsTbody = document.getElementById('graph-results-tbody') as HTMLTableSectionElement;

// Audit DOM
const btnRefreshAudit = document.getElementById('btn-refresh-audit') as HTMLButtonElement;
const auditTimeline = document.getElementById('audit-timeline') as HTMLDivElement;

// Toast DOM Container
const toastContainer = document.getElementById('toast-container') as HTMLDivElement;

// ─────────────────────────────────────────
// UTILS & TOASTS
// ─────────────────────────────────────────
function showToast(message: string, type: 'success' | 'error' | 'info' = 'success') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  
  let icon = 'fa-circle-check';
  if (type === 'error') icon = 'fa-circle-xmark';
  if (type === 'info') icon = 'fa-circle-info';
  
  toast.innerHTML = `
    <div style="display: flex; gap: 0.75rem; align-items: center;">
      <i class="fa-solid ${icon}" style="font-size: 1.1rem; color: ${type === 'success' ? 'var(--color-success)' : type === 'error' ? 'var(--color-danger)' : 'var(--color-primary)'}"></i>
      <div>${message}</div>
    </div>
  `;
  toastContainer.appendChild(toast);
  
  setTimeout(() => {
    toast.style.animation = 'fadeOut 0.3s ease-out forwards';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ─────────────────────────────────────────
// TABS SWITCHING
// ─────────────────────────────────────────
tabButtons.forEach(button => {
  button.addEventListener('click', () => {
    const targetTab = button.getAttribute('data-tab');
    if (!targetTab) return;
    
    // Update active tab buttons
    tabButtons.forEach(btn => btn.classList.remove('active'));
    button.classList.add('active');
    
    // Update active tab contents
    tabContents.forEach(content => content.classList.remove('active'));
    const activeContent = document.getElementById(targetTab);
    if (activeContent) activeContent.classList.add('active');
    
    state.activeTab = targetTab;
    
    // Trigger tab-specific loads
    if (targetTab === 'graph-tab') {
      loadGraphStats();
    } else if (targetTab === 'audit-tab') {
      loadAuditLogs();
    } else if (targetTab === 'studio-tab') {
      initDataStudio();
    } else if (targetTab === 'traffic-tab') {
      initTrafficMonitor();
    }
  });
});

// ─────────────────────────────────────────
// BLOG ARTICLE SWITCHING (Architecture Tab)
// ─────────────────────────────────────────
const blogItems = document.querySelectorAll('.blog-nav-item');
const blogArticles = document.querySelectorAll('.blog-article-content');

blogItems.forEach(item => {
  item.addEventListener('click', () => {
    const targetArticle = item.getAttribute('data-article');
    if (!targetArticle) return;

    // Update active nav items
    blogItems.forEach(btn => btn.classList.remove('active'));
    item.classList.add('active');

    // Update active article content
    blogArticles.forEach(art => art.classList.remove('active'));
    const activeArt = document.getElementById(`art-${targetArticle}`);
    if (activeArt) activeArt.classList.add('active');
  });
});

function switchTab(tabId: string) {
  const button = document.querySelector(`.tab-btn[data-tab="${tabId}"]`) as HTMLButtonElement;
  if (button) button.click();
}

// ─────────────────────────────────────────
// LIGHTWEIGHT MARKDOWN PARSER FOR CHAT
// ─────────────────────────────────────────
function parseMarkdown(text: string): string {
  let html = text;

  // 1. Escaping raw HTML tags to prevent XSS while keeping code styling
  html = html.replace(/</g, '&lt;').replace(/>/g, '&gt;');

  // 2. Preformatted Code Blocks: ```lang ... ```
  html = html.replace(/```(?:[a-zA-Z0-9]+)?\n([\s\S]*?)\n```/g, '<pre><code>$1</code></pre>');

  // 3. Inline Code: `code`
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  // 4. Bold: **text**
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

  // 5. Headings: ### heading
  html = html.replace(/^\s*###\s+(.+)$/gm, '<h4 style="color: var(--color-primary); margin: 0.75rem 0 0.4rem 0;">$1</h4>');
  html = html.replace(/^\s*##\s+(.+)$/gm, '<h3 style="color: var(--color-primary); margin: 1rem 0 0.5rem 0;">$1</h3>');

  // 6. Markdown Tables
  const lines = html.split('\n');
  let inTable = false;
  let tableRows: string[] = [];
  let tableHeaders: string[] = [];
  let processedLines: string[] = [];

  for (let line of lines) {
    const isRow = line.trim().startsWith('|') && line.trim().endsWith('|');
    if (isRow) {
      const cells = line.split('|').map(c => c.trim()).filter((_, i, arr) => i > 0 && i < arr.length - 1);
      
      // Check if separator line
      const isSeparator = cells.every(c => c.startsWith(':') || c.startsWith('-') || c === '');
      if (isSeparator) {
        continue; // Skip the separator row
      }

      if (!inTable) {
        inTable = true;
        tableHeaders = cells;
      } else {
        tableRows.push(`<tr>${cells.map(c => `<td>${c}</td>`).join('')}</tr>`);
      }
    } else {
      if (inTable) {
        // Build table
        const tableHtml = `
          <table>
            <thead>
              <tr>${tableHeaders.map(h => `<th>${h}</th>`).join('')}</tr>
            </thead>
            <tbody>
              ${tableRows.join('')}
            </tbody>
          </table>
        `;
        processedLines.push(tableHtml);
        inTable = false;
        tableRows = [];
        tableHeaders = [];
      }
      processedLines.push(line);
    }
  }
  
  if (inTable) { // Flush remaining table
    const tableHtml = `
      <table>
        <thead>
          <tr>${tableHeaders.map(h => `<th>${h}</th>`).join('')}</tr>
        </thead>
        <tbody>
          ${tableRows.join('')}
        </tbody>
      </table>
    `;
    processedLines.push(tableHtml);
  }

  html = processedLines.join('\n');

  // 7. Bullet lists: - list or * list
  html = html.replace(/^\s*[-*]\s+(.+)$/gm, '<li style="margin-left: 1rem; margin-bottom: 0.25rem;">$1</li>');
  
  // Wrap list items in <ul>
  html = html.replace(/(<li>.*<\/li>)/gs, '<ul style="margin: 0.5rem 0;">$1</ul>');

  // 8. Line breaks
  html = html.replace(/\n/g, '<br>');
  // Cleanup duplicates from code block translations
  html = html.replace(/<pre><code><br>/g, '<pre><code>');
  html = html.replace(/<\/code><\/pre><br>/g, '</code></pre>');
  html = html.replace(/<\/tr><br>/g, '</tr>');
  html = html.replace(/<\/table><br>/g, '</table>');
  html = html.replace(/<\/ul><br>/g, '</ul>');

  return html;
}

// ─────────────────────────────────────────
// AWS CONFIGURATION PANEL LOGIC
// ─────────────────────────────────────────
async function loadAWSConfig() {
  try {
    const config = await api.getAWSConfig();
    const wsS3 = document.getElementById('workspace-s3-display');
    const wsRegion = document.getElementById('workspace-region-display');
    const wsStatus = document.getElementById('workspace-status-badge');

    if (config.s3_warehouse_uri) {
      awsRegionInput.value = config.region;
      awsS3UriInput.value = config.s3_warehouse_uri;
      
      if (config.access_key_id_set) {
        awsAccessKeyInput.value = '••••••••••••••••';
      }
      if (config.secret_access_key_set) {
        awsSecretKeyInput.value = '••••••••••••••••';
      }

      customAwsToggle.checked = true;
      awsConfigForm.style.display = 'flex';
      awsDemoInfo.style.display = 'none';
      
      // Pre-fill target namespace default in ingestion tab
      ingestNamespace.value = 'default';

      // Update Workspace Details Panel
      if (wsS3) wsS3.textContent = config.s3_warehouse_uri;
      if (wsRegion) wsRegion.textContent = config.region;
      if (wsStatus) {
        wsStatus.textContent = 'CONNECTED';
        wsStatus.className = 'badge badge-green';
      }
    } else {
      customAwsToggle.checked = false;
      awsConfigForm.style.display = 'none';
      awsDemoInfo.style.display = 'block';

      // Update Workspace Details Panel for Demo mode
      if (wsS3) wsS3.textContent = 'Local sandbox (SQLite fallback)';
      if (wsRegion) wsRegion.textContent = 'local';
      if (wsStatus) {
        wsStatus.textContent = 'DEMO MODE';
        wsStatus.className = 'badge badge-blue';
      }
    }
  } catch (error) {
    console.error('Failed to load AWS configuration:', error);
  }
}

// Bind scrolling click handlers for integration guides
document.getElementById('btn-goto-databricks')?.addEventListener('click', () => {
  document.getElementById('guide-databricks')?.scrollIntoView({ behavior: 'smooth' });
});
document.getElementById('btn-goto-snowflake')?.addEventListener('click', () => {
  document.getElementById('guide-snowflake')?.scrollIntoView({ behavior: 'smooth' });
});

customAwsToggle.addEventListener('change', () => {
  if (customAwsToggle.checked) {
    awsConfigForm.style.display = 'flex';
    awsDemoInfo.style.display = 'none';
  } else {
    awsConfigForm.style.display = 'none';
    awsDemoInfo.style.display = 'block';
  }
});

btnConnectAws.addEventListener('click', async () => {
  const region = awsRegionInput.value.trim();
  const s3_warehouse_uri = awsS3UriInput.value.trim();
  let access_key_id = awsAccessKeyInput.value.trim();
  let secret_access_key = awsSecretKeyInput.value.trim();

  if (!region || !s3_warehouse_uri) {
    showToast('AWS Region and S3 Warehouse URI are required.', 'error');
    return;
  }

  // If placeholders are unchanged, send undefined so backend doesn't overwrite with '••••••••••••••••'
  if (access_key_id === '••••••••••••••••') access_key_id = undefined as any;
  if (secret_access_key === '••••••••••••••••') secret_access_key = undefined as any;

  btnConnectAws.disabled = true;
  btnConnectAws.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Connecting...';

  try {
    const res = await api.updateAWSConfig({
      region,
      s3_warehouse_uri,
      access_key_id,
      secret_access_key,
    });
    showToast(res.message || 'AWS Catalog connected successfully!', 'success');
    await loadAWSConfig();
  } catch (err: any) {
    showToast(err.message || 'Failed to connect S3 catalog.', 'error');
  } finally {
    btnConnectAws.disabled = false;
    btnConnectAws.innerHTML = '<i class="fa-solid fa-link"></i> Connect Data Lake';
  }
});

// ─────────────────────────────────────────
// CHAT CONSOLE LOGIC
// ─────────────────────────────────────────
function appendMessageBubble(role: 'user' | 'assistant', contentHtml: string, isLoader = false) {
  const messageDiv = document.createElement('div');
  messageDiv.className = `chat-message ${role}`;
  if (isLoader) messageDiv.id = 'chat-typing-bubble';

  const avatarIcon = role === 'user' ? 'fa-user' : 'fa-cube';
  
  messageDiv.innerHTML = `
    <div class="message-avatar">
      <i class="fa-solid ${avatarIcon}"></i>
    </div>
    <div class="message-content-wrapper">
      <div class="message-sender">${role === 'user' ? 'You' : 'meldra.ai assistant'}</div>
      <div class="message-text">${contentHtml}</div>
    </div>
  `;
  
  chatMessages.appendChild(messageDiv);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function initChat() {
  chatMessages.innerHTML = '';
  state.chatHistory = [];
  
  const welcomeText = `
    <p>👋 Welcome to <strong>meldra.ai</strong> — the serverless S3 Iceberg platform for startup data teams!</p>
    <p>I can help you:</p>
    <ul>
      <li>🗂 <strong>Create Iceberg tables</strong> with custom schemas directly on your S3 bucket</li>
      <li>📥 <strong>Ingest CSV datasets</strong> into open Apache Iceberg format in seconds</li>
      <li>🔍 <strong>Query your data lake</strong> using plain English (powered by DuckDB + Claude AI)</li>
      <li>🔗 <strong>Build knowledge graphs</strong> — sync Iceberg data to Neo4j AuraDB and query with Cypher</li>
      <li>🔧 <strong>Schema evolution</strong> — add/rename/drop columns instantly without data rewrites</li>
    </ul>
    <p><strong>Try asking:</strong></p>
    <div class="prompt-box" style="background: rgba(139,92,246,0.08); padding: 0.75rem; border-radius: 6px; border: 1px solid var(--border-glass); font-family: var(--font-mono); font-size: 0.85rem; color: var(--color-primary); margin-top: 0.5rem; cursor: pointer;" id="welcome-sample-prompt">
      Create a table named employees in namespace default with columns: emp_id (integer), name (string), salary (float), dept (string)
    </div>
  `;
  appendMessageBubble('assistant', welcomeText);
  
  // Bind click on welcome sample prompt
  const sampleBox = document.getElementById('welcome-sample-prompt');
  if (sampleBox) {
    sampleBox.addEventListener('click', () => {
      chatInputText.value = sampleBox.innerText.trim();
      chatInputText.focus();
    });
  }
}

async function sendMessage(text: string) {
  if (!text) return;
  
  // Render user prompt
  appendMessageBubble('user', parseMarkdown(text));
  
  // Push to history state
  state.chatHistory.push({ role: 'user', content: text });
  
  // Add typing bubble loader
  const loaderHtml = `
    <div class="typing-loader">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
    </div>
  `;
  appendMessageBubble('assistant', loaderHtml, true);
  
  try {
    // Send to FastAPI Chat agent
    const answer = await api.sendChatMessage(text, state.chatHistory);
    
    // Remove typing bubble loader
    const loader = document.getElementById('chat-typing-bubble');
    if (loader) loader.remove();
    
    // Render bot output
    appendMessageBubble('assistant', parseMarkdown(answer));
    state.chatHistory.push({ role: 'assistant', content: answer });
  } catch (error: any) {
    const loader = document.getElementById('chat-typing-bubble');
    if (loader) loader.remove();
    
    const errText = `❌ <strong>Error during execution:</strong> ${error.message || 'Something went wrong.'}<br><br><span style="font-size: 0.8rem; color: var(--text-muted);">Ensure AWS S3 credentials are configured or the backend server is running.</span>`;
    appendMessageBubble('assistant', errText);
  }
}

btnSendMessage.addEventListener('click', () => {
  const prompt = chatInputText.value.trim();
  if (!prompt) return;
  chatInputText.value = '';
  sendMessage(prompt);
});

chatInputText.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    const prompt = chatInputText.value.trim();
    if (!prompt) return;
    chatInputText.value = '';
    sendMessage(prompt);
  }
});

btnClearChat.addEventListener('click', () => {
  initChat();
  showToast('Chat history cleared.', 'info');
});

// Bind Sidebar quick prompts
document.querySelectorAll('.quick-prompt-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const prompt = btn.getAttribute('data-prompt');
    if (!prompt) return;
    switchTab('chat-tab');
    chatInputText.value = prompt;
    chatInputText.focus();
  });
});


// ─────────────────────────────────────────
// TUTORIAL ACORDION DECK LOGIC
// ─────────────────────────────────────────
interface Lesson {
  num: string;
  title: string;
  icon: string;
  concept: string;
  tryPrompt: string;
  level: string;
}

const lessonsList: Lesson[] = [
  {
    num: "01",
    title: "Ingesting SAP ERP Financial Ledgers",
    icon: "fa-file-invoice-dollar",
    level: "Beginner",
    concept: `
      <p>Enterprise ERP databases (like SAP or Oracle) generate massive tables such as <strong>BSEG</strong> (Accounting Document Segment) and <strong>BKPF</strong> (Accounting Document Header).</p>
      <p>meldra.ai allows data teams to ingest these legacy relational tables directly into partitioned, high-performance S3 Apache Iceberg formats. This bypasses expensive continuous Spark clusters while retaining transactional consistency (ACID).</p>
    `,
    tryPrompt: "Show the first 5 records of the financial ledger table default.sap_bseg"
  },
  {
    num: "02",
    title: "General Ledger Transaction Path Reconciliation",
    icon: "fa-scale-balanced",
    level: "Intermediate",
    concept: `
      <p>Reconciling entries across multiple accounts is a classic enterprise accounting challenge. meldra.ai syncs Iceberg ledger transactions directly into your relational graph layer.</p>
      <p>By mapping accounts to graph nodes and transaction flows to edges, you can run path-finding queries to detect double-entry mismatches, circular payment loops, or audit anomalies instantly.</p>
    `,
    tryPrompt: "Find all transaction loop paths in the default.sap_bseg table"
  },
  {
    num: "03",
    title: "Supply Chain & Order-to-Cash Lineage",
    icon: "fa-truck-ramp-box",
    level: "Intermediate",
    concept: `
      <p>Tracking purchase orders, inventory movements, shipping logs, and customer invoicing is notoriously difficult across fragmented ERP systems.</p>
      <p>Using meldra.ai's unified S3 Iceberg datasets, you can query supply chain snapshots across historical times, mapping ordering status straight to delivery times to find inventory bottlenecks.</p>
    `,
    tryPrompt: "Track supply chain order lifecycle paths for order id 8502"
  },
  {
    num: "04",
    title: "Schema Evolution in Enterprise ERP Data Lakes",
    icon: "fa-sliders",
    level: "Advanced",
    concept: `
      <p>Legacy ERP configurations frequently undergo database migrations (e.g. adding columns for tax changes, reordering fields, or modifying segment codes).</p>
      <p>meldra.ai leverages Apache Iceberg's metadata-driven architecture to perform schema modifications (Add, Drop, Rename) as instant zero-copy metadata updates. Older Parquet data is read dynamically without requiring costly table migrations.</p>
    `,
    tryPrompt: "Show schema history and table evolution stats for default.sap_bseg"
  }
];

function buildLessonsDeck() {
  const appWrapper = document.getElementById('lessons-wrapper');
  const commWrapper = document.getElementById('community-lessons-wrapper');

  [appWrapper, commWrapper].forEach(wrapper => {
    if (!wrapper) return;
    wrapper.innerHTML = '';
    
    lessonsList.forEach(lesson => {
      const card = document.createElement('div');
      card.className = 'lesson-card';
      
      let levelBadge = 'badge-green';
      if (lesson.level === 'Intermediate') levelBadge = 'badge-blue';
      if (lesson.level === 'Advanced') levelBadge = 'badge-orange';
      
      card.innerHTML = `
        <div class="lesson-header">
          <div class="lesson-title-area">
            <span class="lesson-num">${lesson.num}</span>
            <i class="fa-solid ${lesson.icon}" style="color: var(--color-primary);"></i>
            <span class="lesson-title">${lesson.title}</span>
          </div>
          <div class="lesson-meta">
            <span class="badge ${levelBadge}">${lesson.level}</span>
            <i class="fa-solid fa-chevron-down lesson-chevron"></i>
          </div>
        </div>
        <div class="lesson-body">
          <div class="lesson-content">
            <div>${lesson.concept}</div>
            <div class="lesson-try-box">
              <div>
                <div style="font-size: 0.75rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase;">🔥 Interactive prompt to run:</div>
                <div class="lesson-try-text">"${lesson.tryPrompt}"</div>
              </div>
              <button class="btn btn-primary btn-sm btn-try-prompt" data-prompt="${lesson.tryPrompt}">
                <i class="fa-solid fa-play"></i> Run Query
              </button>
            </div>
          </div>
        </div>
      `;
      
      // Toggle expand
      const header = card.querySelector('.lesson-header')!;
      header.addEventListener('click', () => {
        const isExpanded = card.classList.contains('expanded');
        
        // Close other cards in the same wrapper
        wrapper.querySelectorAll('.lesson-card').forEach(c => c.classList.remove('expanded'));
        
        if (!isExpanded) {
          card.classList.add('expanded');
        }
      });
      
      // Run prompt click
      const btnTry = card.querySelector('.btn-try-prompt')!;
      btnTry.addEventListener('click', (e) => {
        e.stopPropagation(); // Avoid folding the card
        const prompt = btnTry.getAttribute('data-prompt');
        if (!prompt) return;
        
        // If we are on the public community portal, trigger login overlay first
        if (wrapper === commWrapper) {
          showToast('Sign in or register to run this query inside your workspace!', 'info');
          document.getElementById('landing-btn-login')?.click();
          return;
        }
        
        switchTab('chat-tab');
        chatInputText.value = prompt;
        chatInputText.focus();
      });
      
      wrapper.appendChild(card);
    });
  });
}


// ─────────────────────────────────────────
// CSV UPLOAD & INGESTION HUB LOGIC
// ─────────────────────────────────────────

// Drag and drop events
['dragenter', 'dragover'].forEach(eventName => {
  dropZone.addEventListener(eventName, (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
  }, false);
});

['dragleave', 'drop'].forEach(eventName => {
  dropZone.addEventListener(eventName, (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
  }, false);
});

dropZone.addEventListener('drop', (e) => {
  const dt = e.dataTransfer;
  if (!dt) return;
  const files = dt.files;
  if (files.length > 0) {
    handleCSVFile(files[0]);
  }
});

dropZone.addEventListener('click', () => {
  csvFileInput.click();
});

csvFileInput.addEventListener('change', () => {
  if (csvFileInput.files && csvFileInput.files.length > 0) {
    handleCSVFile(csvFileInput.files[0]);
  }
});

async function handleCSVFile(file: File) {
  if (file.type !== 'text/csv' && !file.name.endsWith('.csv')) {
    showToast('Only CSV files are supported.', 'error');
    return;
  }
  
  dropZone.innerHTML = `
    <i class="fa-solid fa-spinner fa-spin drop-zone-icon" style="color: var(--color-primary);"></i>
    <span class="drop-zone-text">Uploading and scanning ${file.name}...</span>
    <span class="drop-zone-sub">Parsing metadata structure</span>
  `;
  
  try {
    const data: CSVUploadResponse = await api.uploadCSV(file);
    
    state.uploadedFilePath = data.file_path;
    state.uploadedFileName = data.filename;
    state.uploadedSchema = data.schema;
    
    // Success status
    showToast(`CSV Upload completed! Analyzed ${data.row_count} rows.`, 'success');
    
    // Set file input label
    dropZone.innerHTML = `
      <i class="fa-solid fa-file-circle-check drop-zone-icon" style="color: var(--color-success);"></i>
      <span class="drop-zone-text">${file.name} uploaded successfully</span>
      <span class="drop-zone-sub">${data.row_count.toLocaleString()} rows detected. Click to upload a different file</span>
    `;
    
    // Render Ingest parameters
    const suggestedTable = file.name
      .replace('.csv', '')
      .replace(/[^a-zA-Z0-9]/g, '_')
      .toLowerCase();
    ingestTableName.value = suggestedTable;
    
    // Render preview table
    previewTheadTr.innerHTML = '';
    previewTbody.innerHTML = '';
    
    if (data.schema.length > 0) {
      data.schema.forEach(col => {
        const th = document.createElement('th');
        th.innerText = col.name;
        previewTheadTr.appendChild(th);
      });
      
      data.preview.forEach(row => {
        const tr = document.createElement('tr');
        data.schema.forEach(col => {
          const td = document.createElement('td');
          const val = row[col.name];
          td.innerText = val === null || val === undefined ? 'NULL' : String(val);
          tr.appendChild(td);
        });
        previewTbody.appendChild(tr);
      });
      
      previewRowCount.innerText = `${data.row_count.toLocaleString()} rows`;
      previewSection.style.display = 'flex';
    }
    
    // Render Schema Type configuration editor
    schemaConfigTbody.innerHTML = '';
    data.schema.forEach(col => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="font-family: var(--font-mono); font-weight: 500;">${col.name}</td>
        <td>
          <select class="schema-type-select" data-col-name="${col.name}">
            <option value="string" ${col.type === 'string' ? 'selected' : ''}>string</option>
            <option value="integer" ${col.type === 'integer' ? 'selected' : ''}>integer</option>
            <option value="float" ${col.type === 'float' ? 'selected' : ''}>float</option>
            <option value="double" ${col.type === 'double' ? 'selected' : ''}>double</option>
            <option value="boolean" ${col.type === 'boolean' ? 'selected' : ''}>boolean</option>
            <option value="date" ${col.type === 'date' ? 'selected' : ''}>date</option>
            <option value="timestamp" ${col.type === 'timestamp' ? 'selected' : ''}>timestamp</option>
          </select>
        </td>
      `;
      schemaConfigTbody.appendChild(tr);
    });
    
    // Enable submit
    btnDoIngest.disabled = false;
    
  } catch (err: any) {
    showToast(err.message || 'File upload failed.', 'error');
    dropZone.innerHTML = `
      <i class="fa-solid fa-triangle-exclamation drop-zone-icon" style="color: var(--color-danger);"></i>
      <span class="drop-zone-text">Parsing error</span>
      <span class="drop-zone-sub">Click to retry uploading CSV</span>
    `;
  }
}

// Ingestion Execution
btnDoIngest.addEventListener('click', async () => {
  const namespace = ingestNamespace.value.trim() || 'default';
  const table_name = ingestTableName.value.trim();
  
  if (!table_name) {
    showToast('Please enter a target table name.', 'error');
    return;
  }
  
  if (!state.uploadedFilePath) {
    showToast('No uploaded file in buffer.', 'error');
    return;
  }
  
  // Extract edited schemas
  const schema_json: { name: string; type: string }[] = [];
  const selects = schemaConfigTbody.querySelectorAll('.schema-type-select') as NodeListOf<HTMLSelectElement>;
  selects.forEach(select => {
    const colName = select.getAttribute('data-col-name')!;
    const colType = select.value;
    schema_json.push({ name: colName, type: colType });
  });
  
  // Show loader overlay
  ingestLoadingText.innerText = `Ingesting into "${namespace}.${table_name}"...`;
  ingestLoadingOverlay.style.display = 'flex';
  
  try {
    const res = await api.triggerIngest({
      namespace,
      table_name,
      file_path: state.uploadedFilePath,
      schema_json,
      write_mode: ingestWriteMode.value,
      merge_key: ingestMergeKey.value.trim() || undefined
    });
    
    showToast(res.message || 'Table created and data ingested successfully!', 'success');
    
    // Redirect to chat and prompt confirmation
    switchTab('chat-tab');
    sendMessage(`Show me the schema and first 10 rows of "${namespace}.${table_name}"`);
    
    // Reset ingestion form state
    state.uploadedFilePath = null;
    state.uploadedFileName = null;
    state.uploadedSchema = null;
    btnDoIngest.disabled = true;
    previewSection.style.display = 'none';
    schemaConfigTbody.innerHTML = '<tr><td colspan="2" style="text-align: center; color: var(--text-muted); padding: 1.5rem;">Upload a CSV to view schema settings</td></tr>';
    dropZone.innerHTML = `
      <i class="fa-solid fa-cloud-arrow-up drop-zone-icon"></i>
      <span class="drop-zone-text">Drag & drop your CSV file here</span>
      <span class="drop-zone-sub">or click to browse from explorer (Max 50MB)</span>
    `;
  } catch (err: any) {
    showToast(err.message || 'Ingestion execution failed.', 'error');
  } finally {
    ingestLoadingOverlay.style.display = 'none';
  }
});

// Sample File Downloads client-side
function downloadCSVFile(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.setAttribute('href', url);
  link.setAttribute('download', filename);
  link.style.visibility = 'hidden';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

btnSampleEmployees.addEventListener('click', () => {
  const content = `emp_id,name,department,salary,hire_date
1,Alice Smith,Engineering,85000,2020-01-15
2,Bob Jones,Marketing,72000,2019-03-22
3,Carol White,Engineering,91000,2021-06-01
4,David Brown,Sales,68000,2018-11-30
5,Eva Green,HR,75000,2022-02-14
6,Frank Black,Engineering,88000,2020-08-10
7,Grace Lee,Finance,79000,2017-05-25
8,Henry Martin,Marketing,65000,2023-01-08
9,Iris Wang,Sales,71000,2021-09-15
10,Jack Wilson,HR,77000,2022-07-20`;
  downloadCSVFile('employees_sample.csv', content);
  showToast('Generated employees_sample.csv', 'info');
});

btnSampleOrders.addEventListener('click', () => {
  const content = `order_id,product,quantity,price,order_date
1001,Laptop,1,999.99,2024-01-10
1002,Mouse,2,29.99,2024-01-11
1003,Keyboard,1,79.99,2024-01-11
1004,Monitor,1,399.99,2024-01-12
1005,Headset,3,149.99,2024-01-13
1006,Webcam,2,89.99,2024-01-14
1007,Desk,1,299.99,2024-01-14
1008,Chair,1,499.99,2024-01-15
1009,Lamp,4,39.99,2024-01-16
1010,Notebook,10,4.99,2024-01-16`;
  downloadCSVFile('orders_sample.csv', content);
  showToast('Generated orders_sample.csv', 'info');
});

btnSampleTraffic.addEventListener('click', () => {
  const content = `page,visits,bounces,date
/home,4521,1230,2024-01-15
/about,1203,432,2024-01-15
/products,3897,987,2024-01-15
/contact,876,321,2024-01-15
/blog,2341,765,2024-01-15
/pricing,1654,543,2024-01-15
/login,2987,234,2024-01-15
/signup,1432,567,2024-01-15
/docs,987,123,2024-01-15
/support,654,210,2024-01-15`;
  downloadCSVFile('traffic_sample.csv', content);
  showToast('Generated traffic_sample.csv', 'info');
});


// ─────────────────────────────────────────
// APACHE AGE GRAPH EXPLORER LOGIC
// ─────────────────────────────────────────
async function loadGraphStats() {
  // Reset fields to loading state
  graphStatNodes.innerText = '...';
  graphStatEdges.innerText = '...';
  graphStatActive.innerText = '...';
  
  try {
    const stats = await api.getGraphStats();
    graphStatNodes.innerText = String(stats.nodes);
    graphStatEdges.innerText = String(stats.edges);
    graphStatActive.innerText = stats.graph_name;
  } catch (err: any) {
    graphStatNodes.innerText = '⚠️';
    graphStatEdges.innerText = '⚠️';
    graphStatActive.innerText = 'Error';
    showToast(err.message || 'Could not connect to Apache AGE database. Make sure Postgres AGE container is running.', 'error');
  }
}

async function runCypherQuery() {
  const query = cypherQueryInput.value.trim();
  if (!query) {
    showToast('Query box is empty.', 'error');
    return;
  }
  
  btnExecuteCypher.disabled = true;
  btnExecuteCypher.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Executing...';
  
  graphResultsTheadTr.innerHTML = '';
  graphResultsTbody.innerHTML = '<tr><td style="text-align: center; color: var(--text-muted); padding: 2.5rem;"><i class="fa-solid fa-arrows-spin fa-spin" style="font-size: 1.5rem; color: var(--color-primary);"></i> Running query against Apache AGE graph...</td></tr>';
  
  try {
    const data = await api.executeCypherQuery(query);
    
    graphResultsTheadTr.innerHTML = '';
    graphResultsTbody.innerHTML = '';
    
    if (data.columns.length === 0) {
      graphResultsTbody.innerHTML = '<tr><td style="text-align: center; color: var(--text-muted); padding: 2.5rem;">Query executed successfully. Returned 0 columns.</td></tr>';
      return;
    }
    
    // Render columns
    data.columns.forEach(col => {
      const th = document.createElement('th');
      th.innerText = col;
      graphResultsTheadTr.appendChild(th);
    });
    
    // Render rows
    if (data.rows.length === 0) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = data.columns.length;
      td.style.textAlign = 'center';
      td.style.padding = '2.5rem';
      td.style.color = 'var(--text-muted)';
      td.innerText = 'Query returned 0 rows.';
      tr.appendChild(td);
      graphResultsTbody.appendChild(tr);
    } else {
      data.rows.forEach(row => {
        const tr = document.createElement('tr');
        data.columns.forEach(col => {
          const td = document.createElement('td');
          const val = row[col];
          
          if (val === null || val === undefined) {
            td.innerText = 'NULL';
            td.style.color = 'var(--text-muted)';
          } else if (typeof val === 'object') {
            td.innerHTML = `<pre style="margin: 0; padding: 0.25rem; font-size: 0.75rem; background: transparent; border: none; overflow-x: auto;"><code>${JSON.stringify(val)}</code></pre>`;
          } else {
            td.innerText = String(val);
          }
          tr.appendChild(td);
        });
        graphResultsTbody.appendChild(tr);
      });
    }
    showToast(`Cypher Query completed! Fetch size: ${data.rows.length} records.`, 'success');
  } catch (err: any) {
    graphResultsTheadTr.innerHTML = '<th>Error Details</th>';
    graphResultsTbody.innerHTML = `
      <tr>
        <td style="color: var(--color-danger); padding: 1.5rem; font-family: var(--font-mono); font-size: 0.85rem; line-height: 1.6;">
          <i class="fa-solid fa-triangle-exclamation"></i> AGE SQL Execution Error:<br>
          ${err.message || 'An error occurred during query execution.'}
        </td>
      </tr>
    `;
    showToast('Cypher execution failed.', 'error');
  } finally {
    btnExecuteCypher.disabled = false;
    btnExecuteCypher.innerHTML = '<i class="fa-solid fa-play"></i> Execute Query';
  }
}

btnExecuteCypher.addEventListener('click', runCypherQuery);


// ─────────────────────────────────────────
// SECURITY AUDIT TRAIL LOGS LOGIC
// ─────────────────────────────────────────
async function loadAuditLogs() {
  auditTimeline.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 2.5rem;"><i class="fa-solid fa-arrows-spin fa-spin" style="font-size: 1.5rem; color: var(--color-primary);"></i> Loading system audit timeline...</div>';
  
  try {
    const logs = await api.getAuditLogs();
    auditTimeline.innerHTML = '';
    
    if (logs.length === 0) {
      auditTimeline.innerHTML = '<div style="text-align: center; color: var(--text-muted); padding: 2.5rem;">No audit trails found in database.</div>';
      return;
    }
    
    logs.forEach(log => {
      const card = document.createElement('div');
      card.className = `audit-card status-${log.status}`;
      
      const icon = log.status === 'success' ? 'fa-circle-check' : 'fa-circle-exclamation';
      const statusPill = log.status === 'success' 
        ? '<span class="pill pill-success">SUCCESS</span>' 
        : '<span class="pill pill-error">FAILED</span>';
      
      // Format timestamp to user readable local date-time
      let dateStr = log.timestamp;
      try {
        const d = new Date(log.timestamp);
        dateStr = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      } catch (e) {}
      
      card.innerHTML = `
        <div class="audit-time">
          <i class="fa-regular fa-clock"></i> ${dateStr}
        </div>
        <div class="audit-info">
          <div class="audit-action">
            <i class="fa-solid ${icon}" style="color: ${log.status === 'success' ? 'var(--color-success)' : 'var(--color-danger)'}; margin-right: 0.35rem;"></i>
            ${log.action}
          </div>
          <div class="audit-details">${log.details}</div>
        </div>
        <div class="audit-meta-tags">
          <span class="pill pill-tier">${log.tier}</span>
          ${statusPill}
          <span style="font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono);">UID: ${log.user_id}</span>
        </div>
      `;
      auditTimeline.appendChild(card);
    });
  } catch (err: any) {
    auditTimeline.innerHTML = `<div style="text-align: center; color: var(--color-danger); padding: 2.5rem;"><i class="fa-solid fa-triangle-exclamation"></i> Failed to pull audit logs: ${err.message || 'Connection error.'}</div>`;
  }
}

btnRefreshAudit.addEventListener('click', loadAuditLogs);


// ─────────────────────────────────────────
// APP BOOTSTRAP INITIALIZATION
// ─────────────────────────────────────────
// API HELP TAB
// ─────────────────────────────────────────
const API_BASE = (import.meta.env.VITE_API_BASE_URL as string) || 'http://localhost:8000';

interface EndpointDef {
  method: 'GET' | 'POST';
  path: string;
  desc: string;
  tag: string;
  params?: { name: string; type: string; required: boolean; desc: string }[];
  body?: string;
  response?: string;
  tryable?: boolean;
}

const ENDPOINTS: EndpointDef[] = [
  {
    method: 'GET', path: '/health', desc: 'Health check — confirm the API server is running.', tag: 'Meta',
    response: `{ "status": "ok" }`,
    tryable: true
  },
  {
    method: 'POST', path: '/v1/chat', desc: 'Send a natural language prompt to the Claude AI Iceberg agent. Returns the agent\'s text response.', tag: 'Chat',
    params: [
      { name: 'prompt', type: 'string', required: true, desc: 'The user message / question' },
      { name: 'messages', type: 'ChatMessage[]', required: true, desc: 'Previous conversation history [{role, content}]' }
    ],
    body: `{
  "prompt": "Show me the first 10 rows of employees",
  "messages": []
}`,
    response: `{ "output": "The employees table contains the following records..." }`
  },
  {
    method: 'POST', path: '/v1/upload-csv', desc: 'Upload a CSV file. Returns auto-detected schema and 5-row preview.', tag: 'Ingestion',
    body: `FormData: { file: <CSV File> }`,
    response: `{
  "file_path": "/app/data/uploaded_employees.csv",
  "filename": "employees.csv",
  "row_count": 250,
  "schema": [{"name": "emp_id", "type": "integer"}, ...],
  "preview": [{"emp_id": 1, "name": "Alice"}]
}`
  },
  {
    method: 'POST', path: '/v1/ingest', desc: 'Create an Iceberg table and ingest a previously uploaded CSV file.', tag: 'Ingestion',
    params: [
      { name: 'namespace', type: 'string', required: true, desc: 'Iceberg namespace / database name' },
      { name: 'table_name', type: 'string', required: true, desc: 'Name for the new table' },
      { name: 'file_path', type: 'string', required: true, desc: 'file_path returned from /v1/upload-csv' },
      { name: 'schema_json', type: 'object[]', required: true, desc: '[{name, type}] column definitions' }
    ],
    body: `{
  "namespace": "default",
  "table_name": "employees",
  "file_path": "/app/data/uploaded_employees.csv",
  "schema_json": [{"name": "emp_id", "type": "integer"}, {"name": "name", "type": "string"}]
}`,
    response: `{ "status": "success", "message": "Successfully created and ingested table default.employees" }`
  },
  {
    method: 'GET', path: '/v1/config/aws', desc: 'Get current AWS / S3 data lake configuration.', tag: 'AWS Config',
    response: `{
  "region": "eu-west-2",
  "s3_warehouse_uri": "s3://bucket/warehouse",
  "access_key_id_set": true,
  "secret_access_key_set": true
}`,
    tryable: true
  },
  {
    method: 'POST', path: '/v1/config/aws', desc: 'Update AWS region, S3 warehouse URI, and credentials.', tag: 'AWS Config',
    body: `{
  "region": "eu-west-2",
  "s3_warehouse_uri": "s3://my-bucket/iceberg-warehouse",
  "access_key_id": "AKIA...",
  "secret_access_key": "..."
}`,
    response: `{ "status": "success", "message": "AWS config updated successfully." }`
  },
  {
    method: 'GET', path: '/v1/graph/stats', desc: 'Get node and edge counts for a named Apache AGE graph.', tag: 'Graph',
    params: [{ name: 'graph_name', type: 'string', required: false, desc: 'Graph name (default: pharma_graph)' }],
    response: `{ "nodes": 142, "edges": 389, "graph_name": "pharma_graph" }`,
    tryable: true
  },
  {
    method: 'POST', path: '/v1/graph/cypher', desc: 'Execute a Cypher query against an Apache AGE persistent graph.', tag: 'Graph',
    body: `{
  "graph_name": "pharma_graph",
  "query": "MATCH (a:Entity)-[r]->(b:Entity) RETURN a.id, b.id LIMIT 10"
}`,
    response: `{
  "columns": ["id", "id"],
  "rows": [{"id": "ACC-001", "id2": "ACC-099"}]
}`
  },
  {
    method: 'GET', path: '/v1/audit', desc: 'Retrieve the last 100 audit log entries (actions, statuses, timestamps, user IDs).', tag: 'Audit',
    response: `[
  {
    "id": 42,
    "timestamp": "2026-07-03T00:00:00Z",
    "user_id": "user@example.com",
    "tier": "free",
    "action": "chat_agent",
    "details": "Prompt: Show first 10 rows",
    "status": "success"
  }
]`,
    tryable: true
  }
];

function copyApiBaseUrl() {
  navigator.clipboard.writeText(API_BASE);
  showToast("API Base URL copied to clipboard!", "success");
}
(window as any).copyApiBaseUrl = copyApiBaseUrl;

function buildApiHelpTab() {
  const container = document.getElementById('api-endpoints-list')!;
  const docsLink = document.getElementById('api-docs-link') as HTMLAnchorElement;

  docsLink.href = `${API_BASE}/docs`;

  const tagColors: Record<string, string> = {
    'Meta': 'badge-blue', 'Chat': 'badge-purple', 'Ingestion': 'badge-orange',
    'AWS Config': 'badge-green', 'Graph': 'badge-danger', 'Audit': 'badge-blue'
  };

  ENDPOINTS.forEach((ep, idx) => {
    const card = document.createElement('div');
    card.className = 'api-endpoint-card';
    card.id = `ep-card-${idx}`;

    const methodClass = `method-${ep.method.toLowerCase()}`;
    const tagBadge = tagColors[ep.tag] || 'badge-blue';

    let paramsHtml = '';
    if (ep.params && ep.params.length) {
      paramsHtml = `
        <div>
          <div class="api-section-label">Parameters</div>
          <table class="api-params-table">
            <thead><tr><th>Name</th><th>Type</th><th>Required</th><th>Description</th></tr></thead>
            <tbody>
              ${ep.params.map(p => `<tr>
                <td><code>${p.name}</code></td>
                <td><code>${p.type}</code></td>
                <td>${p.required ? '<span style="color:var(--color-success);">✓</span>' : '<span style="color:var(--text-muted);">–</span>'}</td>
                <td style="color:var(--text-muted);">${p.desc}</td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    }

    let bodyHtml = ep.body ? `
      <div>
        <div class="api-section-label">Request Body</div>
        <div class="api-code-block">${ep.body}</div>
      </div>` : '';

    let responseHtml = ep.response ? `
      <div>
        <div class="api-section-label">Example Response</div>
        <div class="api-code-block">${ep.response}</div>
      </div>` : '';

    let tryBtnHtml = '';
    let tryResultId = `try-result-${idx}`;
    if (ep.tryable) {
      tryBtnHtml = `
        <div style="display:flex; flex-direction:column; gap:0.6rem; align-self:flex-start;">
          <button class="api-try-btn" data-ep-idx="${idx}">
            <i class="fa-solid fa-bolt"></i> Try It Live
          </button>
          <div class="api-try-result" id="${tryResultId}"></div>
        </div>`;
    }

    card.innerHTML = `
      <div class="api-endpoint-header">
        <span class="method-badge ${methodClass}">${ep.method}</span>
        <span class="endpoint-path">${ep.path}</span>
        <span class="endpoint-desc">${ep.desc}</span>
        <span class="badge ${tagBadge}" style="flex-shrink:0;">${ep.tag}</span>
        <i class="fa-solid fa-chevron-down" style="color:var(--text-muted);font-size:0.75rem;flex-shrink:0;transition:transform 0.3s;"></i>
      </div>
      <div class="api-endpoint-body">
        <div class="api-endpoint-content">
          ${paramsHtml}
          ${bodyHtml}
          ${responseHtml}
          ${tryBtnHtml}
        </div>
      </div>`;

    // Toggle expand
    const header = card.querySelector('.api-endpoint-header')!;
    const chevron = card.querySelector('.fa-chevron-down') as HTMLElement;
    header.addEventListener('click', () => {
      const isExpanded = card.classList.contains('expanded');
      document.querySelectorAll('.api-endpoint-card').forEach(c => {
        c.classList.remove('expanded');
        const ch = c.querySelector('.fa-chevron-down') as HTMLElement | null;
        if (ch) ch.style.transform = '';
      });
      if (!isExpanded) {
        card.classList.add('expanded');
        chevron.style.transform = 'rotate(180deg)';
      }
    });

    container.appendChild(card);
  });

  // Try-It handlers
  container.querySelectorAll('.api-try-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const idx = Number((btn as HTMLElement).getAttribute('data-ep-idx'));
      const ep = ENDPOINTS[idx];
      const resultEl = document.getElementById(`try-result-${idx}`)!;
      resultEl.textContent = 'Calling...';
      resultEl.classList.add('visible');
      try {
        const url = `${API_BASE}${ep.path}${ep.path === '/v1/graph/stats' ? '?graph_name=pharma_graph' : ''}`;
        const res = await fetch(url);
        const data = await res.json();
        resultEl.textContent = JSON.stringify(data, null, 2);
      } catch (err: any) {
        resultEl.textContent = `Error: ${err.message}`;
      }
    });
  });
}

// ─────────────────────────────────────────
// LIVE TEST TAB
// ─────────────────────────────────────────
interface TestCase {
  name: string;
  description: string;
  run: () => Promise<{ pass: boolean; detail: string }>;
}

const TEST_CASES: TestCase[] = [
  {
    name: 'Health Check',
    description: 'GET /health → should return {status: "ok"}',
    run: async () => {
      const res = await fetch(`${API_BASE}/health`);
      if (!res.ok) return { pass: false, detail: `HTTP ${res.status}` };
      const d = await res.json();
      const pass = d.status === 'ok';
      return { pass, detail: pass ? 'Backend is healthy ✓' : `Unexpected: ${JSON.stringify(d)}` };
    }
  },
  {
    name: 'AWS Config Read',
    description: 'GET /v1/config/aws → should return config object',
    run: async () => {
      const res = await fetch(`${API_BASE}/v1/config/aws`);
      if (!res.ok) return { pass: false, detail: `HTTP ${res.status}` };
      const d = await res.json();
      const pass = typeof d.region === 'string';
      return { pass, detail: pass ? `Region: ${d.region} ✓` : `Unexpected response: ${JSON.stringify(d)}` };
    }
  },
  {
    name: 'Audit Log Read',
    description: 'GET /v1/audit → should return an array',
    run: async () => {
      const res = await fetch(`${API_BASE}/v1/audit`);
      if (!res.ok) return { pass: false, detail: `HTTP ${res.status}` };
      const d = await res.json();
      const pass = Array.isArray(d);
      return { pass, detail: pass ? `${d.length} audit entries found ✓` : `Expected array, got ${typeof d}` };
    }
  },
  {
    name: 'Graph Stats',
    description: 'GET /v1/graph/stats → should return node/edge counts (requires AGE)',
    run: async () => {
      const res = await fetch(`${API_BASE}/v1/graph/stats?graph_name=pharma_graph`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        return { pass: false, detail: `HTTP ${res.status}: ${err.error || 'AGE database may not be running'}` };
      }
      const d = await res.json();
      const pass = typeof d.nodes === 'number';
      return { pass, detail: pass ? `${d.nodes} nodes, ${d.edges} edges ✓` : `Unexpected response` };
    }
  },
  {
    name: 'Chat Agent (smoke)',
    description: 'POST /v1/chat → "ping" prompt should return a response string',
    run: async () => {
      const res = await fetch(`${API_BASE}/v1/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: 'Hello, what can you do?', messages: [] })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        return { pass: false, detail: `HTTP ${res.status}: ${err.error || 'Agent not available'}` };
      }
      const d = await res.json();
      const pass = typeof d.output === 'string' && d.output.length > 0;
      return { pass, detail: pass ? `Agent responded (${d.output.length} chars) ✓` : 'Empty or missing output' };
    }
  },
  {
    name: 'CORS Headers',
    description: 'Backend should allow cross-origin requests from this origin',
    run: async () => {
      const res = await fetch(`${API_BASE}/health`, { method: 'GET' });
      const allowed = res.headers.get('access-control-allow-origin');
      const pass = allowed !== null;
      return { pass, detail: pass ? `CORS origin: ${allowed} ✓` : 'Missing CORS headers' };
    }
  }
];

function buildTestTab() {
  const list = document.getElementById('test-results-list')!;
  list.innerHTML = '';

  TEST_CASES.forEach((tc, idx) => {
    const row = document.createElement('div');
    row.id = `test-row-${idx}`;
    row.style.cssText = 'background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 10px; padding: 1rem 1.25rem; display: grid; grid-template-columns: 36px 1fr auto; gap: 1rem; align-items: center;';
    row.innerHTML = `
      <div id="test-icon-${idx}" style="width:32px;height:32px;border-radius:50%;background:var(--bg-surface2);display:flex;align-items:center;justify-content:center;font-size:0.95rem;color:var(--text-muted);"><i class="fa-solid fa-circle-dot"></i></div>
      <div>
        <div style="font-family:var(--font-sans);font-weight:600;font-size:0.92rem;">${tc.name}</div>
        <div style="font-size:0.78rem;color:var(--text-muted);margin-top:0.15rem;">${tc.description}</div>
        <div id="test-detail-${idx}" style="font-family:var(--font-mono);font-size:0.75rem;color:var(--text-muted);margin-top:0.35rem;display:none;"></div>
      </div>
      <button class="btn btn-secondary btn-sm" id="test-btn-${idx}" data-test-idx="${idx}">
        <i class="fa-solid fa-play"></i> Run
      </button>`;
    list.appendChild(row);

    document.getElementById(`test-btn-${idx}`)!.addEventListener('click', () => runSingleTest(idx));
  });
}

async function runSingleTest(idx: number) {
  const iconEl  = document.getElementById(`test-icon-${idx}`)!;
  const detail  = document.getElementById(`test-detail-${idx}`)!;
  const btn     = document.getElementById(`test-btn-${idx}`) as HTMLButtonElement;

  iconEl.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="color:var(--color-primary);"></i>';
  btn.disabled = true;
  detail.style.display = 'none';

  try {
    const result = await TEST_CASES[idx].run();
    if (result.pass) {
      iconEl.innerHTML = '<i class="fa-solid fa-circle-check" style="color:var(--color-success);"></i>';
      iconEl.style.background = 'rgba(16,185,129,0.1)';
    } else {
      iconEl.innerHTML = '<i class="fa-solid fa-circle-xmark" style="color:var(--color-danger);"></i>';
      iconEl.style.background = 'rgba(244,63,94,0.1)';
    }
    detail.textContent = result.detail;
    detail.style.display = 'block';
    detail.style.color = result.pass ? 'var(--color-success)' : 'var(--color-danger)';
  } catch (err: any) {
    iconEl.innerHTML = '<i class="fa-solid fa-circle-xmark" style="color:var(--color-danger);"></i>';
    detail.textContent = `Error: ${err.message}`;
    detail.style.display = 'block';
    detail.style.color = 'var(--color-danger)';
  } finally {
    btn.disabled = false;
  }
}

async function runAllTests() {
  const summaryEl = document.getElementById('test-summary')!;
  summaryEl.textContent = 'Running...';
  let passed = 0;
  for (let i = 0; i < TEST_CASES.length; i++) {
    await runSingleTest(i);
    const icon = document.getElementById(`test-icon-${i}`)!;
    if (icon.innerHTML.includes('circle-check')) passed++;
    await new Promise(r => setTimeout(r, 250)); // small delay for visibility
  }
  summaryEl.textContent = `${passed}/${TEST_CASES.length} passed`;
  summaryEl.style.color = passed === TEST_CASES.length ? 'var(--color-success)' : 'var(--color-warning)';
}

function resetTests() {
  document.getElementById('test-summary')!.textContent = '';
  TEST_CASES.forEach((_, idx) => {
    const iconEl = document.getElementById(`test-icon-${idx}`)!;
    const detail = document.getElementById(`test-detail-${idx}`)!;
    iconEl.innerHTML = '<i class="fa-solid fa-circle-dot"></i>';
    iconEl.style.background = 'var(--bg-surface2)';
    iconEl.style.color = 'var(--text-muted)';
    detail.style.display = 'none';
  });
}

// ── MCP GATEWAY PLAYGROUND ──────────────────────────────────────────────
interface MCPToolDef {
  name: string;
  description: string;
  sampleArgs: Record<string, any>;
}

interface MCPServerDef {
  name: string;
  description: string;
  tools: MCPToolDef[];
}

const MCP_REGISTRY: MCPServerDef[] = [
  {
    name: "Iceberg Catalog MCP Server",
    description: "Interact with the Apache Iceberg Glue Catalog to list, create, and query data tables.",
    tools: [
      {
        name: "list_iceberg_tables",
        description: "List all Iceberg tables in a namespace from the Glue Catalog",
        sampleArgs: { "namespace": "default" }
      },
      {
        name: "create_iceberg_table",
        description: "Create a new Apache Iceberg table on S3 with a given schema",
        sampleArgs: {
          "namespace": "default",
          "table_name": "sap_bseg",
          "schema_json": [
            { "name": "MANDT", "type": "string" },
            { "name": "BUKRS", "type": "string" },
            { "name": "BELNR", "type": "string" },
            { "name": "GJAHR", "type": "long" },
            { "name": "BUZEI", "type": "string" },
            { "name": "DMBTR", "type": "double" }
          ]
        }
      },
      {
        name: "query_iceberg_data",
        description: "Run a SQL SELECT query on an existing Iceberg table via DuckDB",
        sampleArgs: {
          "namespace": "default",
          "table_name": "sap_bseg",
          "sql_query": "SELECT * FROM iceberg_table WHERE DMBTR > 10000 LIMIT 5"
        }
      },
      {
        name: "ingest_csv_to_iceberg",
        description: "Parse and ingest a CSV file into an Iceberg table on S3",
        sampleArgs: {
          "csv_path": "c:/Users/sumit/Documents/icebergAgent/sample_data.csv",
          "namespace": "default",
          "table_name": "sap_bseg"
        }
      }
    ]
  },
  {
    name: "SAP BAPI & RFC MCP Agent",
    description: "RFC gateway mapping natural language parameters to secure SAP BAPIs on host SAP-ECC-PRD.",
    tools: [
      {
        name: "approve_purchase_requisition",
        description: "Release a SAP Purchase Requisition (PR) for procurement approval",
        sampleArgs: { "pr_number": "4500012345", "release_code": "A1" }
      },
      {
        name: "release_billing_block",
        description: "Remove a billing block from a SAP sales order",
        sampleArgs: { "sales_order": "1000293", "billing_block": "01" }
      },
      {
        name: "update_vendor_payment_term",
        description: "Update the payment term for a SAP vendor in FI-AP",
        sampleArgs: { "vendor_id": "V10001", "payment_term": "NT30", "company_code": "1000" }
      }
    ]
  },
  {
    name: "Snowflake Zero-Copy MCP",
    description: "Zero-copy data lakehouse connectivity tool facilitating warehouse analytics.",
    tools: [
      {
        name: "revenue_trend_by_period",
        description: "Get monthly revenue totals grouped by cost centre",
        sampleArgs: { "period_from": "2026-01", "period_to": "2026-06", "cost_centre": "CC-100" }
      },
      {
        name: "variance_analysis",
        description: "Compare actual vs planned spend for a department",
        sampleArgs: { "department_id": "DEP-100", "fiscal_year": 2026 }
      },
      {
        name: "top_vendors_by_spend",
        description: "Rank vendors by total AP invoice spend in a fiscal period",
        sampleArgs: { "top_n": 5, "fiscal_quarter": "Q2-2026" }
      }
    ]
  },
  {
    name: "Real-Time Audit Trail MCP",
    description: "Automated SOX/SOC2 audit logger that signs and stores immutable audit entries on S3.",
    tools: [
      {
        name: "log_audit_event",
        description: "Log an append-only audit event directly into the S3 compliance ledger",
        sampleArgs: { "action": "DATA_ACCESS", "user": "finance-analyst@company.com", "details": "Read table default.sap_bseg" }
      }
    ]
  },
  {
    name: "Autonomous Procurement MCP",
    description: "Triggers procurement lifecycle loops in response to safety stock breaches.",
    tools: [
      {
        name: "trigger_procurement_flow",
        description: "Trigger the autonomous procurement flow for an under-stocked material",
        sampleArgs: { "sku": "PCB-44A", "trigger_reason": "SAFETY_BREACH" }
      }
    ]
  },
  {
    name: "Zero-Trust IAM Provisioning MCP",
    description: "Automated employee onboarding/offboarding workflow mediating Okta, AD, and AWS.",
    tools: [
      {
        name: "sync_employee_termination",
        description: "Trigger instant zero-trust revocation of credentials for a terminated employee",
        sampleArgs: { "employee_id": "EMP-9023", "email": "johndoe@company.com" }
      }
    ]
  },
  {
    name: "Fraud Ring Detection MCP",
    description: "AGE Graph database recursive Cypher loop traversal for anti-collusion protection.",
    tools: [
      {
        name: "detect_payment_rings",
        description: "Detect circular payment rings above a transaction velocity threshold",
        sampleArgs: { "min_hops": 3, "max_hops": 8, "threshold_usd": 10000.00 }
      }
    ]
  },
  {
    name: "Multi-Agent A2A Orchestration",
    description: "Month-end closing mediator orchestrating complex sub-agent task dependencies.",
    tools: [
      {
        name: "run_month_end_close",
        description: "Execute the autonomous multi-agent month-end financial close orchestration chain",
        sampleArgs: { "fiscal_period": "2026-06", "reconciliation_mode": "strict" }
      }
    ]
  }
];

function buildMcpTab() {
  const sidebarContainer = document.querySelector('.mcp-server-list') as HTMLDivElement;
  const nameEl = document.getElementById('mcp-selected-server-name') as HTMLElement;
  const descEl = document.getElementById('mcp-selected-server-desc') as HTMLElement;
  const selectEl = document.getElementById('mcp-tool-select') as HTMLSelectElement;
  const toolDescEl = document.getElementById('mcp-tool-desc') as HTMLElement;
  const argsEl = document.getElementById('mcp-tool-arguments') as HTMLTextAreaElement;
  const btnExecute = document.getElementById('btn-execute-mcp-tool') as HTMLButtonElement;
  const durationBadge = document.getElementById('mcp-duration-badge') as HTMLElement;
  const consoleEl = document.getElementById('mcp-execution-logs') as HTMLElement;
  const resultEl = document.getElementById('mcp-execution-result') as HTMLElement;

  if (!sidebarContainer || !nameEl || !descEl || !selectEl || !toolDescEl || !argsEl || !btnExecute || !durationBadge || !consoleEl || !resultEl) {
    console.warn("MCP Gateway elements not fully loaded in DOM.");
    return;
  }

  let selectedServerIdx = 0;

  // Render Sidebar Items
  sidebarContainer.innerHTML = '';
  MCP_REGISTRY.forEach((srv, srvIdx) => {
    const item = document.createElement('div');
    item.className = `mcp-server-item blog-nav-item ${srvIdx === 0 ? 'active' : ''}`;
    item.setAttribute('data-server', srv.name);
    item.setAttribute('data-desc', srv.description);
    
    item.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.25rem;">
        <span class="blog-nav-domain" style="color: var(--color-primary); margin: 0; font-size: 0.65rem;">Port ${8001 + srvIdx}</span>
        <span class="status-dot online" style="margin-left: auto;"></span>
      </div>
      <h4>${srv.name.split(' MCP')[0]}</h4>
      <span>${srv.tools.length} active tools</span>
    `;

    item.addEventListener('click', () => {
      // Toggle active states
      sidebarContainer.querySelectorAll('.mcp-server-item').forEach(el => {
        el.classList.remove('active');
      });
      item.classList.add('active');

      selectedServerIdx = srvIdx;
      updateServerPanel();
    });

    sidebarContainer.appendChild(item);
  });

  function updateServerPanel() {
    const srv = MCP_REGISTRY[selectedServerIdx];
    nameEl.textContent = srv.name;
    descEl.textContent = srv.description;

    // Populate tools dropdown
    selectEl.innerHTML = '';
    srv.tools.forEach((t, tIdx) => {
      const opt = document.createElement('option');
      opt.value = String(tIdx);
      opt.textContent = t.name;
      selectEl.appendChild(opt);
    });

    updateToolFields();
  }

  function updateToolFields() {
    const srv = MCP_REGISTRY[selectedServerIdx];
    const toolIdx = Number(selectEl.value);
    const tool = srv.tools[toolIdx];
    if (!tool) return;

    toolDescEl.textContent = tool.description;
    argsEl.value = JSON.stringify(tool.sampleArgs, null, 2);
  }

  selectEl.addEventListener('change', updateToolFields);

  // Initialize first view
  updateServerPanel();

  // Button Execute Click Handler
  btnExecute.addEventListener('click', async () => {
    const srv = MCP_REGISTRY[selectedServerIdx];
    const toolIdx = Number(selectEl.value);
    const tool = srv.tools[toolIdx];
    if (!tool) return;

    let parsedArgs = {};
    try {
      parsedArgs = JSON.parse(argsEl.value);
    } catch (e: any) {
      alert(`Invalid JSON in Arguments field: ${e.message}`);
      return;
    }

    // UI Feedback
    btnExecute.disabled = true;
    btnExecute.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Invoking...';
    durationBadge.style.display = 'none';
    consoleEl.innerHTML = '<span style="color: #64748b;">[~] Executing...</span>';
    resultEl.textContent = '{}';

    try {
      const res = await api.executeMcpTool(srv.name, tool.name, parsedArgs);
      
      // Update logs
      consoleEl.innerHTML = '';
      res.logs.forEach(line => {
        const span = document.createElement('span');
        if (line.startsWith('[*]')) {
          span.style.color = '#38bdf8';
        } else if (line.startsWith('[+]')) {
          span.style.color = '#34d399';
        } else if (line.startsWith('[error]') || line.startsWith('[-]')) {
          span.style.color = '#f87171';
        } else if (line.startsWith('[info]')) {
          span.style.color = '#cbd5e1';
        } else if (line.startsWith('[sql]') || line.startsWith('[sap]') || line.startsWith('[snowflake]') || line.startsWith('[compliance]') || line.startsWith('[agent]') || line.startsWith('[iam]') || line.startsWith('[fraud]') || line.startsWith('[orchestrator]')) {
          span.style.color = '#fb923c';
        } else {
          span.style.color = '#94a3b8';
        }
        span.textContent = line;
        consoleEl.appendChild(span);
      });

      // Update Result and Duration
      resultEl.textContent = JSON.stringify(res.result, null, 2);
      durationBadge.textContent = `${res.duration_ms}ms`;
      durationBadge.style.display = 'inline-block';
    } catch (e: any) {
      consoleEl.innerHTML = `<span style="color: #f87171;">[-] API Execution failed: ${e.message || e}</span>`;
      resultEl.textContent = JSON.stringify({ error: e.message || e }, null, 2);
    } finally {
      btnExecute.disabled = false;
      btnExecute.innerHTML = '<i class="fa-solid fa-play"></i> Execute Tool Call';
    }
  });
}

// ─────────────────────────────────────────
// BACKEND HEALTH STATUS
// ─────────────────────────────────────────
async function checkBackendStatus() {
  const dot  = document.getElementById('backend-status-dot')!;
  const text = document.getElementById('backend-status-text')!;
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(4000) });
    if (res.ok) {
      dot.className  = 'status-dot online';
      text.textContent = 'Backend online';
      text.style.color = 'var(--color-success)';
    } else {
      throw new Error('not ok');
    }
  } catch {
    dot.className  = 'status-dot offline';
    text.textContent = 'Backend offline';
    text.style.color = 'var(--color-danger)';
  }
}

// ─────────────────────────────────────────
// AUTH OVERLAY CONTROLLER
// ─────────────────────────────────────────
function initAuthController() {
  const overlay = document.getElementById('auth-overlay')!;
  const mainApp = document.getElementById('main-app')!;
  const landingPage = document.getElementById('landing-page')!;

  // ─ Landing page buttons
  const landingBtnLogin = document.getElementById('landing-btn-login')!;
  const landingBtnSignup = document.getElementById('landing-btn-signup')!;
  const landingHeroSignup = document.getElementById('landing-hero-signup')!;

  // ─ Screen references
  const screenLogin    = document.getElementById('auth-screen-login')!;
  const screenRegister = document.getElementById('auth-screen-register')!;
  const screenMfa      = document.getElementById('auth-screen-mfa')!;
  const screenForgot   = document.getElementById('auth-screen-forgot')!;
  const screenResetOtp = document.getElementById('auth-screen-reset-otp')!;
  const screenNewPwd   = document.getElementById('auth-screen-new-password')!;

  // ─ Login elements
  const loginEmailEl    = document.getElementById('login-email') as HTMLInputElement;
  const loginPasswordEl = document.getElementById('login-password') as HTMLInputElement;
  const loginErrorEl    = document.getElementById('login-error')!;
  const btnLogin        = document.getElementById('btn-login') as HTMLButtonElement;
  const gotoRegister    = document.getElementById('goto-register')!;

  // ─ Register elements
  const regEmailEl    = document.getElementById('register-email') as HTMLInputElement;
  const regPasswordEl = document.getElementById('register-password') as HTMLInputElement;
  const regPassword2El= document.getElementById('register-password2') as HTMLInputElement;
  const regErrorEl    = document.getElementById('register-error')!;
  const btnRegister   = document.getElementById('btn-register') as HTMLButtonElement;
  const gotoLogin     = document.getElementById('goto-login')!;
  const pwdBar        = document.getElementById('pwd-strength-bar') as HTMLDivElement;

  // ─ MFA elements
  const otpEmailBadge = document.getElementById('otp-target-email')!;
  const mfaErrorEl    = document.getElementById('mfa-error')!;
  const mfaSuccessEl  = document.getElementById('mfa-success')!;
  const btnVerify     = document.getElementById('btn-verify-otp') as HTMLButtonElement;
  const btnResend     = document.getElementById('btn-resend-otp') as HTMLButtonElement;
  const gotoLoginFromMfa = document.getElementById('goto-login-from-mfa')!;
  const otpTimer      = document.getElementById('otp-timer')!;
  const otpDigits     = Array.from({length:6}, (_,i) => document.getElementById(`otp-${i}`) as HTMLInputElement);

  // ─ Header user/logout
  const headerEmail = document.getElementById('header-user-email')!;
  const btnLogout   = document.getElementById('btn-logout') as HTMLButtonElement;

  // ─ Forgot Password elements
  const forgotEmailEl      = document.getElementById('forgot-email') as HTMLInputElement;
  const forgotErrorEl      = document.getElementById('forgot-error')!;
  const forgotSuccessEl    = document.getElementById('forgot-success')!;
  const btnSendReset       = document.getElementById('btn-send-reset') as HTMLButtonElement;
  const gotoForgotPwd      = document.getElementById('goto-forgot-password')!;
  const gotoLoginFromForgot = document.getElementById('goto-login-from-forgot')!;

  // ─ Reset OTP elements
  const resetOtpEmailBadge = document.getElementById('reset-otp-target-email')!;
  const resetOtpErrorEl    = document.getElementById('reset-otp-error')!;
  const resetOtpSuccessEl  = document.getElementById('reset-otp-success')!;
  const resetOtpTimer      = document.getElementById('reset-otp-timer')!;
  const btnVerifyResetOtp  = document.getElementById('btn-verify-reset-otp') as HTMLButtonElement;
  const gotoForgotFromResetOtp = document.getElementById('goto-forgot-from-reset-otp')!;
  const resetOtpDigits     = Array.from({length:6}, (_,i) => document.getElementById(`rotp-${i}`) as HTMLInputElement);

  // ─ New Password elements
  const newPwdInput        = document.getElementById('new-password-input') as HTMLInputElement;
  const newPwdConfirm      = document.getElementById('new-password-confirm') as HTMLInputElement;
  const newPwdErrorEl      = document.getElementById('new-pwd-error')!;
  const newPwdSuccessEl    = document.getElementById('new-pwd-success')!;
  const newPwdBar          = document.getElementById('new-pwd-strength-bar') as HTMLDivElement;
  const btnSetNewPwd       = document.getElementById('btn-set-new-password') as HTMLButtonElement;
  const gotoLoginFromNewPwd = document.getElementById('goto-login-from-new-pwd')!;

  // ─ Reset flow state
  let resetTempToken = '';

  // ─ State
  let currentTempToken = sessionStorage.getItem('meldra_temp_token') || '';
  let otpCountdown: ReturnType<typeof setInterval> | null = null;
  let resendCountdown: ReturnType<typeof setInterval> | null = null;

  // ── Helpers─────────────────────────────────────────────
  function showScreen(screen: HTMLElement) {
    [screenLogin, screenRegister, screenMfa, screenForgot, screenResetOtp, screenNewPwd].forEach(s => s.classList.remove('active'));
    screen.classList.add('active');
  }

  function setError(el: HTMLElement, msg: string) {
    el.textContent = msg;
    el.classList.add('show');
  }

  // Clear errors
  function clearError(el: HTMLElement) {
    el.textContent = '';
    el.classList.remove('show');
  }

  function setSuccess(el: HTMLElement, msg: string) {
    el.textContent = msg;
    el.classList.add('show');
  }

  function showMainApp() {
    landingPage.classList.add('hidden');
    overlay.classList.add('hidden');
    overlay.classList.remove('active');
    setTimeout(() => { 
      overlay.style.display = 'none'; 
      landingPage.style.display = 'none';
    }, 400);
    mainApp.style.display = 'flex';
    const user = tokenStore.getUser();
    if (user) {
      headerEmail.textContent = user.email;
      const avatarCharEl = document.getElementById('user-avatar-char');
      if (avatarCharEl) avatarCharEl.textContent = user.email.charAt(0).toUpperCase();
      const dropdownEmailEl = document.getElementById('dropdown-user-email');
      if (dropdownEmailEl) dropdownEmailEl.textContent = user.email;
      const settingsEmailEl = document.getElementById('settings-info-email');
      if (settingsEmailEl) settingsEmailEl.textContent = user.email;
    }
    bootstrapApp();
  }

  function openAuthModal(mode: 'login' | 'register') {
    overlay.style.display = 'flex';
    overlay.classList.remove('hidden');
    overlay.classList.add('active');
    if (mode === 'login') {
      showScreen(screenLogin);
    } else {
      showScreen(screenRegister);
    }
  }

  // Close modal if user clicks on the backdrop overlay
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) {
      overlay.classList.remove('active');
      overlay.classList.add('hidden');
      setTimeout(() => { overlay.style.display = 'none'; }, 400);
    }
  });

  // Bind landing page buttons to open auth card
  landingBtnLogin.addEventListener('click', () => openAuthModal('login'));
  landingBtnSignup.addEventListener('click', () => openAuthModal('register'));
  landingHeroSignup.addEventListener('click', () => openAuthModal('register'));

  function startOtpTimer(seconds = 600) {
    if (otpCountdown) clearInterval(otpCountdown);
    let remaining = seconds;
    const update = () => {
      const m = Math.floor(remaining / 60).toString().padStart(2,'0');
      const s = (remaining % 60).toString().padStart(2,'0');
      otpTimer.textContent = `${m}:${s}`;
      if (remaining <= 0) {
        clearInterval(otpCountdown!);
        otpTimer.textContent = 'Expired';
        otpTimer.style.color = '#F87171';
      }
      remaining--;
    };
    update();
    otpCountdown = setInterval(update, 1000);
  }

  function startResendCooldown(seconds = 60) {
    if (resendCountdown) clearInterval(resendCountdown);
    btnResend.disabled = true;
    let remaining = seconds;
    const update = () => {
      btnResend.textContent = `Resend code (${remaining}s)`;
      if (remaining <= 0) {
        clearInterval(resendCountdown!);
        btnResend.disabled = false;
        btnResend.textContent = 'Resend code';
      }
      remaining--;
    };
    update();
    resendCountdown = setInterval(update, 1000);
  }

  function getOtpValue(): string {
    return otpDigits.map(d => d.value).join('');
  }

  function clearOtpInputs() {
    otpDigits.forEach(d => { d.value = ''; d.classList.remove('filled'); });
    otpDigits[0]?.focus();
  }

  // Password strength
  function updatePwdStrength(pwd: string) {
    let score = 0;
    if (pwd.length >= 8) score++;
    if (/[A-Z]/.test(pwd)) score++;
    if (/[0-9]/.test(pwd)) score++;
    if (/[^A-Za-z0-9]/.test(pwd)) score++;
    const colors = ['#EF4444','#F59E0B','#10B981','#6D28D9'];
    const widths = ['25%','50%','75%','100%'];
    pwdBar.style.width = score > 0 ? widths[score-1] : '0';
    pwdBar.style.background = score > 0 ? colors[score-1] : 'transparent';
  }
  regPasswordEl.addEventListener('input', () => updatePwdStrength(regPasswordEl.value));

  // OTP digit keyboard navigation
  otpDigits.forEach((input, idx) => {
    input.addEventListener('input', () => {
      const val = input.value.replace(/\D/g,'');
      input.value = val.slice(-1);
      input.classList.toggle('filled', val.length > 0);
      if (val && idx < 5) otpDigits[idx+1].focus();
      // Auto-submit when all 6 filled
      if (getOtpValue().length === 6) btnVerify.click();
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Backspace' && !input.value && idx > 0) {
        otpDigits[idx-1].focus();
      }
    });
    input.addEventListener('paste', (e) => {
      e.preventDefault();
      const pasted = (e.clipboardData?.getData('text') || '').replace(/\D/g,'').slice(0,6);
      pasted.split('').forEach((ch, i) => {
        if (otpDigits[i]) { otpDigits[i].value = ch; otpDigits[i].classList.add('filled'); }
      });
      if (pasted.length === 6) btnVerify.click();
    });
  });

  // ── Screen transitions──────────────────────────────────────
  gotoRegister.addEventListener('click', () => {
    clearError(loginErrorEl);
    showScreen(screenRegister);
  });
  gotoLogin.addEventListener('click', () => {
    clearError(regErrorEl);
    showScreen(screenLogin);
  });
  gotoLoginFromMfa.addEventListener('click', () => {
    if (otpCountdown) clearInterval(otpCountdown);
    if (resendCountdown) clearInterval(resendCountdown);
    currentTempToken = '';
    sessionStorage.removeItem('meldra_temp_token');
    sessionStorage.removeItem('meldra_mfa_email');
    clearOtpInputs();
    clearError(mfaErrorEl);
    showScreen(screenLogin);
  });

  // ─ Forgot password navigation
  gotoForgotPwd.addEventListener('click', () => {
    clearError(loginErrorEl);
    clearError(forgotErrorEl);
    forgotSuccessEl.classList.remove('show');
    forgotEmailEl.value = '';
    showScreen(screenForgot);
    setTimeout(() => forgotEmailEl.focus(), 100);
  });
  gotoLoginFromForgot.addEventListener('click', () => {
    clearError(forgotErrorEl);
    forgotSuccessEl.classList.remove('show');
    showScreen(screenLogin);
  });
  gotoForgotFromResetOtp.addEventListener('click', () => {
    clearError(resetOtpErrorEl);
    resetOtpSuccessEl.classList.remove('show');
    showScreen(screenForgot);
  });
  gotoLoginFromNewPwd.addEventListener('click', () => {
    clearError(newPwdErrorEl);
    newPwdSuccessEl.classList.remove('show');
    resetTempToken = '';
    showScreen(screenLogin);
  });

  // ─ Reset OTP helpers
  let resetOtpCountdown: ReturnType<typeof setInterval> | null = null;

  function getResetOtpValue(): string {
    return resetOtpDigits.map(d => d.value).join('');
  }
  function clearResetOtpInputs() {
    resetOtpDigits.forEach(d => { d.value = ''; d.classList.remove('filled'); });
    resetOtpDigits[0]?.focus();
  }
  function startResetOtpTimer(seconds = 600) {
    if (resetOtpCountdown) clearInterval(resetOtpCountdown);
    let remaining = seconds;
    const update = () => {
      const m = Math.floor(remaining / 60).toString().padStart(2,'0');
      const s = (remaining % 60).toString().padStart(2,'0');
      resetOtpTimer.textContent = `${m}:${s}`;
      if (remaining <= 0) { clearInterval(resetOtpCountdown!); resetOtpTimer.textContent = 'Expired'; resetOtpTimer.style.color = '#F87171'; }
      remaining--;
    };
    update();
    resetOtpCountdown = setInterval(update, 1000);
  }

  // ─ Reset OTP digit keyboard navigation
  resetOtpDigits.forEach((input, idx) => {
    input.addEventListener('input', () => {
      const val = input.value.replace(/\D/g,'');
      input.value = val.slice(-1);
      input.classList.toggle('filled', val.length > 0);
      if (val && idx < 5) resetOtpDigits[idx+1].focus();
      if (getResetOtpValue().length === 6) btnVerifyResetOtp.click();
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Backspace' && !input.value && idx > 0) resetOtpDigits[idx-1].focus();
    });
    input.addEventListener('paste', (e) => {
      e.preventDefault();
      const pasted = (e.clipboardData?.getData('text') || '').replace(/\D/g,'').slice(0,6);
      pasted.split('').forEach((ch, i) => {
        if (resetOtpDigits[i]) { resetOtpDigits[i].value = ch; resetOtpDigits[i].classList.add('filled'); }
      });
      if (pasted.length === 6) btnVerifyResetOtp.click();
    });
  });

  // ─ New password strength bar
  newPwdInput.addEventListener('input', () => {
    const pwd = newPwdInput.value;
    let score = 0;
    if (pwd.length >= 8) score++;
    if (/[A-Z]/.test(pwd)) score++;
    if (/[0-9]/.test(pwd)) score++;
    if (/[^A-Za-z0-9]/.test(pwd)) score++;
    const colors = ['#EF4444','#F59E0B','#10B981','#6D28D9'];
    const widths = ['25%','50%','75%','100%'];
    newPwdBar.style.width = score > 0 ? widths[score-1] : '0';
    newPwdBar.style.background = score > 0 ? colors[score-1] : 'transparent';
  });

  // ── FORGOT PASSWORD — Step 1: send reset code
  async function doForgotPassword() {
    clearError(forgotErrorEl);
    forgotSuccessEl.classList.remove('show');
    const email = forgotEmailEl.value.trim();
    if (!email) { setError(forgotErrorEl, 'Please enter your email address.'); return; }

    btnSendReset.disabled = true;
    btnSendReset.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Sending...';
    try {
      const res = await api.auth.forgotPassword(email);
      resetTempToken = res.temp_token;
      if (resetTempToken) {
        resetOtpEmailBadge.textContent = email;
        clearResetOtpInputs();
        clearError(resetOtpErrorEl);
        resetOtpSuccessEl.classList.remove('show');
        showScreen(screenResetOtp);
        startResetOtpTimer(600);
        setTimeout(() => resetOtpDigits[0]?.focus(), 100);
      } else {
        setSuccess(forgotSuccessEl, '✓ If that email is registered, a reset code has been sent.');
        forgotSuccessEl.classList.add('show');
      }
    } catch(e: any) {
      setError(forgotErrorEl, e.message || 'Failed to send reset code. Please try again.');
    } finally {
      btnSendReset.disabled = false;
      btnSendReset.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Send Reset Code';
    }
  }
  btnSendReset.addEventListener('click', doForgotPassword);
  forgotEmailEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') doForgotPassword(); });

  // ── FORGOT PASSWORD — Step 2: verify reset OTP
  btnVerifyResetOtp.addEventListener('click', async () => {
    clearError(resetOtpErrorEl);
    const code = getResetOtpValue();
    if (code.length < 6) { setError(resetOtpErrorEl, 'Please enter all 6 digits.'); return; }

    btnVerifyResetOtp.disabled = true;
    btnVerifyResetOtp.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Verifying...';
    try {
      clearError(newPwdErrorEl);
      newPwdSuccessEl.classList.remove('show');
      newPwdInput.value = '';
      newPwdConfirm.value = '';
      newPwdBar.style.width = '0';
      sessionStorage.setItem('meldra_reset_otp', code);
      showScreen(screenNewPwd);
      setTimeout(() => newPwdInput.focus(), 100);
    } catch(e: any) {
      setError(resetOtpErrorEl, e.message || 'Invalid code. Please try again.');
      clearResetOtpInputs();
    } finally {
      btnVerifyResetOtp.disabled = false;
      btnVerifyResetOtp.innerHTML = '<i class="fa-solid fa-shield-check"></i> Verify Code';
    }
  });

  // ── FORGOT PASSWORD — Step 3: set new password
  btnSetNewPwd.addEventListener('click', async () => {
    clearError(newPwdErrorEl);
    const pwd = newPwdInput.value;
    const confirm = newPwdConfirm.value;
    const code = sessionStorage.getItem('meldra_reset_otp') || '';

    if (pwd.length < 8) { setError(newPwdErrorEl, 'Password must be at least 8 characters.'); return; }
    if (!/[A-Z]/.test(pwd)) { setError(newPwdErrorEl, 'Password must contain at least one uppercase letter.'); return; }
    if (!/[0-9]/.test(pwd)) { setError(newPwdErrorEl, 'Password must contain at least one number.'); return; }
    if (pwd !== confirm)   { setError(newPwdErrorEl, 'Passwords do not match.'); return; }
    if (!code || !resetTempToken) { setError(newPwdErrorEl, 'Session expired. Please restart the reset flow.'); return; }

    btnSetNewPwd.disabled = true;
    btnSetNewPwd.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Resetting...';
    try {
      await api.auth.resetPassword(resetTempToken, code, pwd);
      sessionStorage.removeItem('meldra_reset_otp');
      resetTempToken = '';
      if (resetOtpCountdown) clearInterval(resetOtpCountdown);
      setSuccess(newPwdSuccessEl, '✓ Password reset! Redirecting to login...');
      newPwdSuccessEl.classList.add('show');
      setTimeout(() => {
        clearError(newPwdErrorEl);
        newPwdSuccessEl.classList.remove('show');
        loginEmailEl.value = '';
        loginPasswordEl.value = '';
        showScreen(screenLogin);
        showToast('Password reset successfully! Please sign in.', 'success');
      }, 1800);
    } catch(e: any) {
      setError(newPwdErrorEl, e.message || 'Reset failed. Please go back and re-enter the code.');
    } finally {
      btnSetNewPwd.disabled = false;
      btnSetNewPwd.innerHTML = '<i class="fa-solid fa-lock"></i> Reset Password';
    }
  });

  // ── LOGIN ───────────────────────────────────────────────
  async function doLogin() {
    clearError(loginErrorEl);
    const email = loginEmailEl.value.trim();
    const password = loginPasswordEl.value;
    if (!email || !password) { setError(loginErrorEl, 'Please enter your email and password.'); return; }

    btnLogin.disabled = true;
    btnLogin.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Sending code...';
    try {
      const res = await api.auth.login(email, password);
      currentTempToken = res.temp_token;
      sessionStorage.setItem('meldra_temp_token', res.temp_token);
      sessionStorage.setItem('meldra_mfa_email', email);
      otpEmailBadge.textContent = email;
      clearOtpInputs();
      clearError(mfaErrorEl);
      mfaSuccessEl.classList.remove('show');
      showScreen(screenMfa);
      startOtpTimer(600);
      startResendCooldown(60);
      setTimeout(() => otpDigits[0]?.focus(), 100);
    } catch(e: any) {
      setError(loginErrorEl, e.message || 'Login failed. Check your credentials.');
    } finally {
      btnLogin.disabled = false;
      btnLogin.innerHTML = '<i class="fa-solid fa-arrow-right-to-bracket"></i> Continue';
    }
  }
  btnLogin.addEventListener('click', doLogin);
  loginPasswordEl.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });

  // ── REGISTER ────────────────────────────────────────────
  async function doRegister() {
    clearError(regErrorEl);
    const email = regEmailEl.value.trim();
    const password = regPasswordEl.value;
    const confirm = regPassword2El.value;
    if (!email) { setError(regErrorEl, 'Email address is required.'); return; }
    if (!password) { setError(regErrorEl, 'Password is required.'); return; }
    if (password !== confirm) { setError(regErrorEl, 'Passwords do not match.'); return; }

    btnRegister.disabled = true;
    btnRegister.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Creating account...';
    try {
      const res = await api.auth.register(email, password);
      currentTempToken = res.temp_token;
      sessionStorage.setItem('meldra_temp_token', res.temp_token);
      sessionStorage.setItem('meldra_mfa_email', email);
      otpEmailBadge.textContent = email;
      clearOtpInputs();
      clearError(mfaErrorEl);
      mfaSuccessEl.classList.remove('show');
      showScreen(screenMfa);
      startOtpTimer(600);
      startResendCooldown(60);
      setTimeout(() => otpDigits[0]?.focus(), 100);
    } catch(e: any) {
      setError(regErrorEl, e.message || 'Registration failed. Please try again.');
    } finally {
      btnRegister.disabled = false;
      btnRegister.innerHTML = '<i class="fa-solid fa-user-plus"></i> Create Account';
    }
  }
  btnRegister.addEventListener('click', doRegister);

  // ── VERIFY OTP ─────────────────────────────────────────
  btnVerify.addEventListener('click', async () => {
    clearError(mfaErrorEl);
    const code = getOtpValue();
    if (code.length < 6) { setError(mfaErrorEl, 'Please enter all 6 digits.'); return; }

    btnVerify.disabled = true;
    btnVerify.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Verifying...';
    try {
      await api.auth.verifyMfa(currentTempToken, code);
      currentTempToken = '';
      sessionStorage.removeItem('meldra_temp_token');
      sessionStorage.removeItem('meldra_mfa_email');
      if (otpCountdown) clearInterval(otpCountdown);
      if (resendCountdown) clearInterval(resendCountdown);
      showMainApp();
    } catch(e: any) {
      setError(mfaErrorEl, e.message || 'Invalid code. Please try again.');
      if (e.message && e.message.includes('Please log in again')) {
        currentTempToken = '';
        sessionStorage.removeItem('meldra_temp_token');
        sessionStorage.removeItem('meldra_mfa_email');
        showScreen(screenLogin);
      }
      otpDigits.forEach(d => { d.value = ''; d.classList.remove('filled'); });
      otpDigits[0]?.focus();
    } finally {
      btnVerify.disabled = false;
      btnVerify.innerHTML = '<i class="fa-solid fa-shield-check"></i> Verify Code';
    }
  });

  // ── RESEND OTP ─────────────────────────────────────────
  btnResend.addEventListener('click', async () => {
    clearError(mfaErrorEl);
    mfaSuccessEl.classList.remove('show');
    try {
      await api.auth.resendOtp(currentTempToken);
      setSuccess(mfaSuccessEl, '✓ New code sent! Check your email.');
      mfaSuccessEl.classList.add('show');
      clearOtpInputs();
      startOtpTimer(600);
      startResendCooldown(60);
    } catch(e: any) {
      setError(mfaErrorEl, e.message || 'Failed to resend. Please wait and try again.');
    }
  });

  // ── LOGOUT ──────────────────────────────────────────────
  btnLogout.addEventListener('click', async () => {
    await api.auth.logout();
    mainApp.style.display = 'none';
    landingPage.style.display = 'flex';
    landingPage.classList.remove('hidden');
    overlay.style.display = 'none';
    overlay.classList.remove('active');
    overlay.classList.remove('hidden');
    loginEmailEl.value = '';
    loginPasswordEl.value = '';
    showScreen(screenLogin);
    showToast('Signed out successfully.', 'info');
  });

  // ── INIT: check if already logged in ────────────────────────
  if (tokenStore.isLoggedIn()) {
    showMainApp();
  } else if (currentTempToken) {
    otpEmailBadge.textContent = sessionStorage.getItem('meldra_mfa_email') || 'your email';
    showScreen(screenMfa);
    startOtpTimer(600);
    startResendCooldown(60);
    setTimeout(() => otpDigits[0]?.focus(), 100);
  }
}


// ─────────────────────────────────────────
// VIDEO LIBRARY — MODAL CONTROLLER
// ─────────────────────────────────────────
interface VideoEntry {
  title: string;
  desc: string;
  ytId: string | null;
  videoUrl?: string; // Native HTML5 MP4 URL
  tags: { label: string; cls: string }[];
}

const videoLibrary: VideoEntry[] = [
  {
    title: 'What is meldra.ai & the Zero-Copy Lakehouse?',
    desc: 'A complete walkthrough of what meldra.ai is, why we built it, and how the Zero-Copy Lakehouse architecture works without ever replicating or moving your raw data.',
    ytId: '8yL0bI-PmqU',
    tags: [
      { label: 'Introduction',    cls: 'vmt-green'  },
      { label: 'Architecture',    cls: 'vmt-blue'   },
      { label: '8 min',           cls: 'vmt-orange' },
    ]
  },
  {
    title: 'Why Zero-Copy? The Business Problems We Solve',
    desc: 'Learn the real business problems — ERP data silos, Spark cluster costs, and audit complexity — and how meldra resolves them without rewriting your existing stack.',
    ytId: 'hK8YlXp-g1E',
    tags: [
      { label: 'Business Case',   cls: 'vmt-orange' },
      { label: 'Enterprise',      cls: 'vmt-blue'   },
      { label: '12 min',          cls: 'vmt-green'  },
    ]
  },
  {
    title: 'Build Your First Pipeline: SAP → Iceberg → AI',
    desc: 'Step-by-step: ingest a SAP ERP financial table into S3 Iceberg, build a knowledge graph, and run AI-powered SQL queries in under 10 minutes.',
    ytId: '91q8-W7z-bY',
    tags: [
      { label: 'Hands-On',        cls: 'vmt-green'  },
      { label: 'Pipeline',        cls: 'vmt-blue'   },
      { label: '10 min',          cls: 'vmt-orange' },
    ]
  }
];

interface Slide {
  title: string;
  subtitle: string;
  graphicHtml: string;
  contentHtml: string;
}

const trainingSimulations: Record<number, Slide[]> = {
  1: [
    {
      title: "The Zero-Copy Architecture Concept",
      subtitle: "Lesson 1: Eliminating Data Replication",
      graphicHtml: `
        <div style="display:flex; flex-direction:column; gap:0.75rem; width:100%; align-items:center; box-sizing:border-box;">
          <div style="display:flex; gap:1rem; align-items:center;">
            <div style="background:#1e293b; border:1px solid #3b82f6; padding:0.6rem; border-radius:8px; text-align:center;">
              <i class="fa-solid fa-database" style="color:#3b82f6; font-size:1.2rem;"></i>
              <div style="font-size:0.6rem; color:#fff; font-weight:700; margin-top:0.25rem;">SAP / ERP DB</div>
            </div>
            <i class="fa-solid fa-arrow-right-long" style="color:#64748b; font-size:1rem;"></i>
            <div style="background:#14532d; border:1px solid #22c55e; padding:0.6rem; border-radius:8px; text-align:center; position:relative; box-shadow:0 0 12px rgba(34,197,94,0.25);">
              <i class="fa-solid fa-cloud" style="color:#22c55e; font-size:1.2rem;"></i>
              <div style="font-size:0.6rem; color:#fff; font-weight:700; margin-top:0.25rem;">AWS S3 (Iceberg)</div>
              <span class="badge badge-green" style="position:absolute; top:-0.4rem; right:-0.4rem; font-size:0.45rem; padding:0.15rem 0.35rem;">Secure Pointers</span>
            </div>
          </div>
          <div style="font-size:0.65rem; color:#94a3b8; text-align:center; max-width:220px; line-height:1.4;">
            meldra.ai reads metadata directories directly from your own S3 bucket. There are no intermediate copies.
          </div>
        </div>
      `,
      contentHtml: `
        <p style="margin:0 0 0.5rem 0;">Traditional data analytics platforms require you to <strong>replicate, copy, and ingest</strong> your enterprise data into their proprietary data warehouses before you can query it.</p>
        <p style="margin:0 0 0.5rem 0;">This creates security vulnerabilities, incurs high egress fees, and duplicates storage costs.</p>
        <p style="margin:0;"><strong>meldra.ai</strong> solves this with a <strong>Zero-Copy Lakehouse</strong>. Your data remains in your own S3 bucket, structured in the open **Apache Iceberg** format. Our query agent reads S3 metadata directly, avoiding any duplication.</p>
      `
    },
    {
      title: "DuckDB Serverless Column Pushdowns",
      subtitle: "Lesson 2: Bypassing Spark Clusters",
      graphicHtml: `
        <div style="display:flex; flex-direction:column; gap:0.5rem; width:100%; box-sizing:border-box;">
          <div style="background:#0f172a; border:1px solid #1e293b; border-radius:6px; padding:0.6rem; font-family:monospace; font-size:0.65rem; color:#a7f3d0; text-align:left; line-height:1.4;">
            <span style="color:#64748b;">-- Pushdown Filters to S3</span><br>
            <span style="color:#f472b6;">SELECT</span> company_code, <span style="color:#f472b6;">SUM</span>(amount)<br>
            <span style="color:#f472b6;">FROM</span> s3.finance_ledger<br>
            <span style="color:#f472b6;">WHERE</span> year = 2025<br>
            <span style="color:#f472b6;">GROUP BY</span> company_code;
          </div>
          <div style="background:rgba(22,163,74,0.1); border:1px solid rgba(22,163,74,0.3); border-radius:6px; padding:0.4rem; font-size:0.65rem; color:#86efac; text-align:center; font-weight:700;">
            ⚡ DuckDB scanned 12.4M rows in 0.08s
          </div>
        </div>
      `,
      contentHtml: `
        <p style="margin:0 0 0.5rem 0;">Instead of spinning up heavy virtual machine clusters (like Databricks Spark clusters) that sit idle and cost money, meldra.ai compiles natural language queries into optimized **DuckDB SQL**.</p>
        <p style="margin:0;">By leveraging Apache Iceberg columns and metadata files, our serverless engine runs directly over S3, scanning only the relevant bytes. This delivers sub-second query speeds with **$0 idle cluster compute costs**.</p>
      `
    },
    {
      title: "Context-Grounded Querying",
      subtitle: "Lesson 3: Zero-Hallucination SQL",
      graphicHtml: `
        <div style="display:flex; flex-direction:column; gap:0.6rem; width:100%; text-align:left; box-sizing:border-box;">
          <div style="border-left:2px solid #a855f7; padding-left:0.5rem; font-size:0.65rem;">
            <strong style="color:#a855f7; display:block; font-weight:700;">1. USER ASKED:</strong>
            <span style="color:#e2e8f0;">"Show SAP ledger matches"</span>
          </div>
          <div style="border-left:2px solid #3b82f6; padding-left:0.5rem; font-size:0.65rem;">
            <strong style="color:#3b82f6; display:block; font-weight:700;">2. CONTEXT ROUTER:</strong>
            <span style="color:#cbd5e1;">Maps SAP BSEG graph path</span>
          </div>
          <div style="border-left:2px solid #22c55e; padding-left:0.5rem; font-size:0.65rem;">
            <strong style="color:#22c55e; display:block; font-weight:700;">3. EXECUTION:</strong>
            <span style="color:#86efac;">Runs DuckDB Iceberg query</span>
          </div>
        </div>
      `,
      contentHtml: `
        <p style="margin:0 0 0.5rem 0;">Standard AI systems fail on databases because they are blind to the underlying schemas, transaction rules, and relationships. They hallucinate table names and columns.</p>
        <p style="margin:0;">meldra.ai uses a **Context-Grounded Router** that queries a local graph representation of your database catalog first. The AI agent immediately identifies the correct columns, tables, and partitions to execute, guaranteeing 100% SQL accuracy.</p>
      `
    }
  ],
  2: [
    {
      title: "Stopping the Spark Cluster Tax",
      subtitle: "Problem 1: Idle Server Waste",
      graphicHtml: `
        <div style="display:flex; flex-direction:column; gap:0.75rem; width:100%; align-items:center; box-sizing:border-box;">
          <div style="display:flex; gap:1rem; align-items:center;">
            <div style="text-align:center; opacity:0.4;">
              <div style="font-size:1.2rem;">💸</div>
              <div style="font-size:0.6rem; color:#f87171; font-weight:700;">Idle Spark Cluster</div>
            </div>
            <i class="fa-solid fa-xmark" style="color:#f87171; font-size:1rem;"></i>
            <div style="text-align:center; background:#14532d; border:1px solid #22c55e; padding:0.4rem 0.6rem; border-radius:8px;">
              <div style="font-size:1.2rem;">⚡</div>
              <div style="font-size:0.6rem; color:#86efac; font-weight:700;">meldra.ai Serverless</div>
            </div>
          </div>
          <span class="badge badge-green" style="font-size:0.65rem; padding:0.25rem 0.5rem;">Saves up to $5,000 / month</span>
        </div>
      `,
      contentHtml: `
        <p style="margin:0 0 0.5rem 0;">Traditional data warehouses require you to maintain active compute clusters (Spark instances) just to wait for occasional queries or daily pipelines. This results in paying thousands of dollars every month for servers that sit idle 90% of the time.</p>
        <p style="margin:0;">meldra.ai relies on a serverless executor that scales down to exactly **$0 compute cost** when no queries are active. You pay only for storage and active query execution milliseconds.</p>
      `
    },
    {
      title: "Data Replication Security Risk",
      subtitle: "Problem 2: GDPR & HIPAA Compliance",
      graphicHtml: `
        <div style="display:flex; flex-direction:column; gap:0.5rem; width:100%; font-size:0.65rem; color:#cbd5e1; text-align:left; box-sizing:border-box;">
          <div style="display:flex; align-items:center; gap:0.5rem; background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.2); padding:0.4rem; border-radius:6px;">
            <i class="fa-solid fa-triangle-exclamation" style="color:#ef4444; font-size:0.8rem;"></i>
            <span>Replication creates duplicate audit trails</span>
          </div>
          <div style="display:flex; align-items:center; gap:0.5rem; background:rgba(34,197,94,0.1); border:1px solid rgba(34,197,94,0.2); padding:0.4rem; border-radius:6px;">
            <i class="fa-solid fa-shield-halved" style="color:#22c55e; font-size:0.8rem;"></i>
            <span>Zero-Copy: Pointers stay in S3</span>
          </div>
        </div>
      `,
      contentHtml: `
        <p style="margin:0 0 0.5rem 0;">Copying general ledger records or customer databases across analytical environments violates strict data sovereignty rules (GDPR, HIPAA, SOC2).</p>
        <p style="margin:0;">Because duplicate copies are difficult to track, trace, and audit, each copy represents a massive liability risk. With meldra.ai, **no data replication takes place**. Pointers to S3 parquet blocks remain strictly under your own AWS IAM policies, with every action logged in our **Audit Trail**.</p>
      `
    },
    {
      title: "Lock-in to Closed Formats",
      subtitle: "Problem 3: Duplicate Storage Fees",
      graphicHtml: `
        <div style="display:flex; flex-direction:column; gap:0.6rem; width:100%; align-items:center; box-sizing:border-box;">
          <div style="display:flex; gap:0.5rem; font-size:0.6rem;">
            <div style="background:#1e293b; padding:0.3rem 0.5rem; border-radius:4px; border:1px solid #64748b; color:#fff;">Snowflake Table</div>
            <div style="background:#1e293b; padding:0.3rem 0.5rem; border-radius:4px; border:1px solid #64748b; color:#fff;">Databricks Spark</div>
          </div>
          <i class="fa-solid fa-link" style="color:#16a34a; font-size:1rem;"></i>
          <div style="background:#14532d; padding:0.4rem 0.6rem; border-radius:6px; border:1px solid #22c55e; font-weight:700; color:#fff; font-size:0.65rem; text-align:center;">
            Shared S3 Apache Iceberg Catalog
          </div>
        </div>
      `,
      contentHtml: `
        <p style="margin:0 0 0.5rem 0;">Proprietary databases store your tables in encrypted, closed formats that force you to buy their expensive egress adapters if other software needs access.</p>
        <p style="margin:0;">meldra.ai uses the **Apache Iceberg** format. This means your tables can be queried simultaneously by Snowflake, Databricks, Spark, or DuckDB without ever copying the data or paying duplicate storage fees.</p>
      `
    }
  ],
  3: [
    {
      title: "Step 1: Connecting S3 & Uploading",
      subtitle: "Hands-on Step 1: Configuration",
      graphicHtml: `
        <div style="display:flex; flex-direction:column; gap:0.5rem; width:100%; text-align:left; font-size:0.65rem; box-sizing:border-box;">
          <div style="background:#1e293b; border:1px solid #3b82f6; border-radius:6px; padding:0.4rem 0.6rem;">
            <span style="color:#94a3b8; display:block; font-size:0.55rem; font-weight:700; text-transform:uppercase;">S3 BUCKET URI:</span>
            <strong style="color:#fff; font-family:monospace; font-size:0.6rem;">s3://meldra-lake/warehouse</strong>
          </div>
          <div style="background:#1e293b; border:1px solid #3b82f6; border-radius:6px; padding:0.4rem 0.6rem;">
            <span style="color:#94a3b8; display:block; font-size:0.55rem; font-weight:700; text-transform:uppercase;">AWS ROLE ARN:</span>
            <strong style="color:#fff; font-family:monospace; font-size:0.55rem; word-break:break-all;">arn:aws:iam::12345:role/meldra-s3</strong>
          </div>
        </div>
      `,
      contentHtml: `
        <p style="margin:0 0 0.5rem 0;">To begin, navigate to the **Data Lake Config** tab. Input your S3 Bucket URI where your tables will be kept, and enter your AWS Role ARN credentials.</p>
        <p style="margin:0;">This securely delegates permission to the meldra.ai query engine to execute DuckDB read/write pushdowns on your behalf, without storing any persistent access keys.</p>
      `
    },
    {
      title: "Step 2: Table Schema Mapping",
      subtitle: "Hands-on Step 2: Mapping",
      graphicHtml: `
        <div style="display:flex; flex-direction:column; gap:0.5rem; width:100%; font-size:0.65rem; color:#cbd5e1; box-sizing:border-box;">
          <div style="background:#0f172a; border:1px solid #1e293b; border-radius:6px; padding:0.5rem; text-align:left; font-family:monospace; font-size:0.6rem; line-height:1.4;">
            <span style="color:#f472b6;">CREATE TABLE</span> default.sap_bseg (<br>
            &nbsp;&nbsp;belnr <span style="color:#38bdf8;">VARCHAR</span>,<br>
            &nbsp;&nbsp;dmbtr <span style="color:#38bdf8;">DECIMAL</span>(15,2)<br>
            ) <span style="color:#f472b6;">USING</span> ICEBERG;
          </div>
          <div style="font-size:0.6rem; color:#94a3b8; text-align:center;">
            meldra creates metadata partition files automatically.
          </div>
        </div>
      `,
      contentHtml: `
        <p style="margin:0 0 0.5rem 0;">In the **Ingest** tab, upload a CSV dataset or link your SAP/ERP database source. our catalog sweeps the schema and registers the columns.</p>
        <p style="margin:0;">This automatically partitions the data in Apache Iceberg layout on S3, mapping it so it can be queried by external tools instantly.</p>
      `
    },
    {
      title: "Step 3: AI-Driven S3 Querying",
      subtitle: "Hands-on Step 3: Run Queries",
      graphicHtml: `
        <div style="display:flex; flex-direction:column; gap:0.5rem; width:100%; text-align:left; font-size:0.65rem; box-sizing:border-box;">
          <div style="background:#1e293b; border:1px solid #a855f7; border-radius:6px; padding:0.4rem 0.6rem; color:#e2e8f0;">
            <i class="fa-solid fa-robot" style="color:#a855f7; margin-right:0.3rem;"></i>
            <span>"What is the sum of ledger amounts in SAP BSEG by company code?"</span>
          </div>
          <div style="background:#0b0f19; border:1px solid #22c55e; border-radius:6px; padding:0.4rem 0.6rem; color:#86efac; font-family:monospace; font-size:0.6rem;">
            SUM(dmbtr) = $240,500,124.00
          </div>
        </div>
      `,
      contentHtml: `
        <p style="margin:0 0 0.5rem 0;">Navigate to the **Chat** tab. Enter any natural language question about your tables, such as asking to sum transactional values or find record matches.</p>
        <p style="margin:0;">The AI agent ground-checks the query against the schema graph, translates it into optimized SQL, executes DuckDB over S3, and renders the result in real-time.</p>
      `
    }
  ]
};

let currentSimulationIdx = 1;
let currentSlideIdx = 0;

function loadSimulationSlide(videoIndex: number, slideIndex: number) {
  const slides = trainingSimulations[videoIndex];
  if (!slides || !slides[slideIndex]) return;
  
  currentSimulationIdx = videoIndex;
  currentSlideIdx = slideIndex;
  
  const stepEl = document.getElementById('demo-slide-step')!;
  const progressEl = document.getElementById('demo-slide-progress')!;
  const graphicEl = document.getElementById('demo-slide-graphic')!;
  const titleEl = document.getElementById('demo-slide-title')!;
  const subtitleEl = document.getElementById('demo-slide-subtitle')!;
  const contentEl = document.getElementById('demo-slide-content')!;
  
  const slide = slides[slideIndex];
  
  stepEl.textContent = `Slide ${slideIndex + 1} of ${slides.length}`;
  progressEl.style.width = `${((slideIndex + 1) / slides.length) * 100}%`;
  
  graphicEl.innerHTML = slide.graphicHtml;
  titleEl.textContent = slide.title;
  subtitleEl.textContent = slide.subtitle;
  contentEl.innerHTML = slide.contentHtml;
  
  const btnPrev = document.getElementById('btn-demo-prev') as HTMLButtonElement;
  const btnNext = document.getElementById('btn-demo-next') as HTMLButtonElement;
  
  if (btnPrev) btnPrev.disabled = (slideIndex === 0);
  if (btnNext) {
    if (slideIndex === slides.length - 1) {
      btnNext.innerHTML = 'Finish Training <i class="fa-solid fa-circle-check"></i>';
    } else {
      btnNext.innerHTML = 'Next <i class="fa-solid fa-arrow-right"></i>';
    }
  }
}

function handleDemoNext() {
  const slides = trainingSimulations[currentSimulationIdx];
  if (!slides) return;
  
  if (currentSlideIdx < slides.length - 1) {
    loadSimulationSlide(currentSimulationIdx, currentSlideIdx + 1);
  } else {
    closeVideoModal();
    showToast("Training Simulation completed successfully!", "success");
  }
}

function handleDemoPrev() {
  if (currentSlideIdx > 0) {
    loadSimulationSlide(currentSimulationIdx, currentSlideIdx - 1);
  }
}

function openVideoModal(videoIndex: number) {
  const overlay   = document.getElementById('video-modal-overlay')!;
  const titleEl   = document.getElementById('video-modal-title')!;
  const descEl    = document.getElementById('video-modal-desc')!;
  const tagsEl    = document.getElementById('video-modal-tags')!;
  
  const iframeEl  = document.getElementById('video-iframe') as HTMLIFrameElement;
  const nativeEl  = document.getElementById('video-player-native') as HTMLVideoElement;
  const placeholderEl = document.getElementById('video-placeholder')!;
  const demoEl    = document.getElementById('video-interactive-demo')!;

  const entry = videoLibrary[videoIndex - 1];
  if (!entry) return;

  // Set title
  titleEl.innerHTML = `<i class="fa-solid fa-graduation-cap" style="color:#16a34a;"></i> ${entry.title}`;
  descEl.textContent = entry.desc;
  tagsEl.innerHTML = entry.tags
    .map(t => `<span class="video-modal-tag ${t.cls}">${t.label}</span>`)
    .join('');

  // Hide media elements, show interactive presentation simulation!
  iframeEl.style.display = 'none';
  iframeEl.src = '';
  nativeEl.style.display = 'none';
  nativeEl.src = '';
  placeholderEl.style.display = 'none';
  
  demoEl.style.display = 'flex';
  loadSimulationSlide(videoIndex, 0);

  overlay.classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeVideoModal() {
  const overlay  = document.getElementById('video-modal-overlay')!;
  const iframeEl = document.getElementById('video-iframe') as HTMLIFrameElement;
  const nativeEl = document.getElementById('video-player-native') as HTMLVideoElement;
  const demoEl   = document.getElementById('video-interactive-demo')!;
  overlay.classList.remove('active');
  
  // Pause and reset players
  nativeEl.pause();
  nativeEl.src = '';
  nativeEl.style.display = 'none';
  
  iframeEl.src = '';   // Stop playback
  iframeEl.style.display = 'none';
  
  demoEl.style.display = 'none';
  
  document.body.style.overflow = '';
}

function closeAuthModal() {
  const overlay = document.getElementById('auth-overlay');
  if (overlay) {
    overlay.classList.remove('active');
    overlay.classList.add('hidden');
    setTimeout(() => { overlay.style.display = 'none'; }, 400);
  }
}

// Expose to window so inline onclick attributes can call them
(window as any).openVideoModal  = openVideoModal;
(window as any).closeVideoModal = closeVideoModal;
(window as any).closeAuthModal  = closeAuthModal;
(window as any).handleDemoNext   = handleDemoNext;
(window as any).handleDemoPrev   = handleDemoPrev;

// Close video modal when clicking backdrop
document.getElementById('video-modal-overlay')?.addEventListener('click', (e) => {
  if (e.target === e.currentTarget) closeVideoModal();
});

// Close article modal when clicking backdrop
document.getElementById('article-modal-overlay')?.addEventListener('click', (e) => {
  if (e.target === e.currentTarget) closePublicArticle();
});

// Close article modal when clicking close button
document.getElementById('btn-close-article')?.addEventListener('click', () => {
  closePublicArticle();
});

// Close all modals on Escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeVideoModal();
    closePublicArticle();
    closeAuthModal();
  }
});

// ─────────────────────────────────────────
// APP BOOTSTRAP
// ─────────────────────────────────────────
function bootstrapApp() {
  try { loadAWSConfig(); } catch (e) { console.error("Error loading AWS config:", e); }
  try { initChat(); } catch (e) { console.error("Error initializing chat:", e); }
  try { buildLessonsDeck(); } catch (e) { console.error("Error building lessons deck:", e); }
  try { buildApiHelpTab(); } catch (e) { console.error("Error building API help tab:", e); }
  try { buildTestTab(); } catch (e) { console.error("Error building test tab:", e); }
  try { buildMcpTab(); } catch (e) { console.error("Error building MCP tab:", e); }
  try { checkBackendStatus(); } catch (e) { console.error("Error checking backend status:", e); }
  setInterval(checkBackendStatus, 30_000);

  try {
    const runBtn = document.getElementById('btn-run-all-tests');
    const clearBtn = document.getElementById('btn-clear-tests');
    if (runBtn) runBtn.addEventListener('click', runAllTests);
    if (clearBtn) clearBtn.addEventListener('click', resetTests);
  } catch (e) { console.error("Error binding test handlers:", e); }

  try { initUserControls(); } catch (e) { console.error("Error initializing user controls:", e); }
}

function initUserControls() {
  const userProfilePill = document.getElementById('user-profile-pill');
  const profileDropdownPanel = document.getElementById('profile-dropdown-panel');
  const btnOpenSettings = document.getElementById('btn-open-settings');
  const settingsModalOverlay = document.getElementById('settings-modal-overlay');
  const btnCloseSettings = document.getElementById('btn-close-settings');
  
  const settingsCurrentPwd = document.getElementById('settings-current-pwd') as HTMLInputElement;
  const settingsNewPwd = document.getElementById('settings-new-pwd') as HTMLInputElement;
  const settingsNewPwd2 = document.getElementById('settings-new-pwd2') as HTMLInputElement;
  const btnSettingsUpdatePwd = document.getElementById('btn-settings-update-pwd') as HTMLButtonElement;
  const settingsPwdError = document.getElementById('settings-pwd-error')!;
  const settingsPwdSuccess = document.getElementById('settings-pwd-success')!;
  const settingsPwdBar = document.getElementById('settings-pwd-bar') as HTMLDivElement;

  const btnToggleSidebar = document.getElementById('btn-toggle-sidebar');
  const btnCloseSidebar = document.getElementById('btn-close-sidebar');
  const sidebarEl = document.querySelector('.sidebar') as HTMLElement;
  const sidebarOverlay = document.getElementById('sidebar-overlay')!;

  // Toggle Profile Dropdown
  userProfilePill?.addEventListener('click', (e) => {
    e.stopPropagation();
    profileDropdownPanel?.classList.toggle('show');
    userProfilePill.parentElement?.classList.toggle('open');
  });

  // Close dropdown when clicking outside
  document.addEventListener('click', (e) => {
    if (!userProfilePill?.contains(e.target as Node) && !profileDropdownPanel?.contains(e.target as Node)) {
      profileDropdownPanel?.classList.remove('show');
      userProfilePill?.parentElement?.classList.remove('open');
    }
  });

  // Toggle Settings Modal
  btnOpenSettings?.addEventListener('click', async () => {
    profileDropdownPanel?.classList.remove('show');
    userProfilePill?.parentElement?.classList.remove('open');
    
    // Clear inputs and errors
    if (settingsCurrentPwd) settingsCurrentPwd.value = '';
    if (settingsNewPwd) settingsNewPwd.value = '';
    if (settingsNewPwd2) settingsNewPwd2.value = '';
    if (settingsPwdError) { settingsPwdError.textContent = ''; settingsPwdError.classList.remove('show'); }
    if (settingsPwdSuccess) { settingsPwdSuccess.textContent = ''; settingsPwdSuccess.classList.remove('show'); }
    if (settingsPwdBar) settingsPwdBar.style.width = '0%';

    // Populate user metadata from api
    try {
      const userProfile = await api.auth.me();
      const settingsCreated = document.getElementById('settings-info-created');
      if (settingsCreated && userProfile.created_at) {
        const date = new Date(userProfile.created_at);
        settingsCreated.textContent = date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
      }
    } catch (err) {
      console.error('Failed to load user settings data:', err);
    }

    settingsModalOverlay?.classList.add('active');
  });

  const closeSettings = () => {
    settingsModalOverlay?.classList.remove('active');
  };

  btnCloseSettings?.addEventListener('click', closeSettings);
  settingsModalOverlay?.addEventListener('click', (e) => {
    if (e.target === settingsModalOverlay) closeSettings();
  });

  // Password strength meter
  settingsNewPwd?.addEventListener('input', () => {
    const pwd = settingsNewPwd.value;
    let score = 0;
    if (pwd.length >= 8) score++;
    if (/[A-Z]/.test(pwd)) score++;
    if (/[0-9]/.test(pwd)) score++;
    if (/[^A-Za-z0-9]/.test(pwd)) score++;
    const colors = ['#EF4444','#F59E0B','#10B981','#6D28D9'];
    const widths = ['25%','50%','75%','100%'];
    if (settingsPwdBar) {
      settingsPwdBar.style.width = score > 0 ? widths[score-1] : '0';
      settingsPwdBar.style.background = score > 0 ? colors[score-1] : 'transparent';
    }
  });

  // Change password submission
  btnSettingsUpdatePwd?.addEventListener('click', async () => {
    if (!settingsCurrentPwd || !settingsNewPwd || !settingsNewPwd2) return;
    if (settingsPwdError) { settingsPwdError.textContent = ''; settingsPwdError.classList.remove('show'); }
    if (settingsPwdSuccess) { settingsPwdSuccess.textContent = ''; settingsPwdSuccess.classList.remove('show'); }

    const currentVal = settingsCurrentPwd.value;
    const newVal = settingsNewPwd.value;
    const confirmVal = settingsNewPwd2.value;

    if (!currentVal) {
      settingsPwdError.textContent = 'Please enter your current password.';
      settingsPwdError.classList.add('show');
      return;
    }
    if (newVal.length < 8) {
      settingsPwdError.textContent = 'New password must be at least 8 characters.';
      settingsPwdError.classList.add('show');
      return;
    }
    if (!/[A-Z]/.test(newVal)) {
      settingsPwdError.textContent = 'New password must contain at least one uppercase letter.';
      settingsPwdError.classList.add('show');
      return;
    }
    if (!/[0-9]/.test(newVal)) {
      settingsPwdError.textContent = 'New password must contain at least one number.';
      settingsPwdError.classList.add('show');
      return;
    }
    if (newVal !== confirmVal) {
      settingsPwdError.textContent = 'Passwords do not match.';
      settingsPwdError.classList.add('show');
      return;
    }

    btnSettingsUpdatePwd.disabled = true;
    btnSettingsUpdatePwd.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Updating...';

    try {
      await api.auth.changePassword(currentVal, newVal);
      if (settingsPwdSuccess) {
        settingsPwdSuccess.textContent = '✓ Password updated successfully!';
        settingsPwdSuccess.classList.add('show');
      }
      settingsCurrentPwd.value = '';
      settingsNewPwd.value = '';
      settingsNewPwd2.value = '';
      if (settingsPwdBar) settingsPwdBar.style.width = '0%';
      showToast('Password updated successfully!', 'success');
      setTimeout(closeSettings, 1500);
    } catch (err: any) {
      if (settingsPwdError) {
        settingsPwdError.textContent = err.message || 'Failed to update password.';
        settingsPwdError.classList.add('show');
      }
    } finally {
      btnSettingsUpdatePwd.disabled = false;
      btnSettingsUpdatePwd.innerHTML = '<i class="fa-solid fa-key"></i> Update Password';
    }
  });

  // Load saved desktop sidebar state on initialization
  if (window.innerWidth > 1024) {
    const isCollapsed = localStorage.getItem('meldra_sidebar_collapsed') === 'true';
    if (isCollapsed && sidebarEl) {
      sidebarEl.classList.add('collapsed');
    }
  }

  // Toggle Sidebar (collapses on desktop, opens drawer overlay on mobile)
  btnToggleSidebar?.addEventListener('click', () => {
    if (window.innerWidth > 1024) {
      sidebarEl?.classList.toggle('collapsed');
      const isCollapsed = sidebarEl?.classList.contains('collapsed');
      localStorage.setItem('meldra_sidebar_collapsed', isCollapsed ? 'true' : 'false');
    } else {
      sidebarEl?.classList.add('open');
      sidebarOverlay?.classList.add('active');
    }
  });

  const closeSidebar = () => {
    sidebarEl?.classList.remove('open');
    sidebarOverlay?.classList.remove('active');
  };

  btnCloseSidebar?.addEventListener('click', closeSidebar);
  sidebarOverlay?.addEventListener('click', closeSidebar);

  // Close sidebar on tab item click (mobile convenience)
  const navTabs = document.querySelectorAll('.tab-headers .tab-btn');
  navTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      if (window.innerWidth <= 1024) {
        closeSidebar();
      }
    });
  });

}

const publicArticles = [
  {
    title: "Enterprise AI Agents Grounded in Context",
    tag: "Enterprise AI",
    meta: "Published by Meldra AI Team · 6 Min Read",
    body: `
      <p>
        Building reliable AI agents for enterprise data lakes is not just about using the largest language model. Raw models are blind to the database schemas, access policies, and real-time transaction updates of your active storage systems. Without context grounding, agents hallucinate schemas and produce incorrect SQL.
      </p>
      <p>
        <strong>meldra.ai</strong> resolves this by implementing a metadata-first context router. Our engine sweeps a PostgreSQL AGE graph catalog mapping database dependencies (such as SAP ledgers and company codes). When a query is asked, the agent immediately binds the exact schemas and issues serverless DuckDB queries over S3 partitions.
      </p>
      <div style="background: rgba(34, 197, 94, 0.05); padding: 1.25rem; border-radius: 8px; border: 1px solid rgba(34, 197, 94, 0.2); margin: 1rem 0;">
        <h4 style="color: #22c55e; margin-top: 0; margin-bottom: 0.5rem; font-weight: 700;">Context-Grounded Routing vs RAG</h4>
        <p style="margin: 0; font-size: 0.88rem; color: #94a3b8;">
          Standard Retrieval-Augmented Generation (RAG) splits text into vector chunks. This fails for structural databases where transactions are linked by parent-child relations. Meldra's graph-grounded engine paths ledger schemas directly, yielding 100% accuracy.
        </p>
      </div>
    `
  },
  {
    title: "Why meldra.ai Bypasses the Databricks & Snowflake Spark Tax",
    tag: "Data Engineering",
    meta: "Published by Meldra Infrastructure Team · 6 Min Read",
    body: `
      <p>
        Traditional cloud data warehouses (like <strong>Databricks</strong> or <strong>Snowflake</strong>) force teams to spin up heavy virtual machine clusters (Spark nodes) just to handle simple queries or basic ingestion pipelines. This results in thousands of dollars of idle server costs every single month.
      </p>
      <p>
        <strong>meldra.ai</strong> completely eliminates this "Spark Tax". By compiling natural language questions directly into optimized <strong>DuckDB SQL</strong>, our architecture queries <strong>S3 Apache Iceberg</strong> files locally and serverless on-the-fly. There is no warm cluster compute node kept running, meaning your monthly compute idle cost is exactly <strong>$0</strong>.
      </p>
      <p>
        Because we write S3 data files using open-standard <strong>Apache Iceberg</strong> metadata and Parquet rows, external platforms can read these tables directly from your S3 bucket without requiring you to export, copy, or transfer a single byte of data.
      </p>
    `
  },
  {
    title: "Zero-Replication Architecture Deep Dive",
    tag: "Architecture",
    meta: "Published by Meldra Systems Team · 7 Min Read",
    body: `
      <p>
        Copying transactional databases across staging and analysis environments is a severe security vulnerability. Under GDPR, HIPAA, and SOC2, duplicated records represent an untracked surface area. Furthermore, copying terabytes of data over cloud regions incurs huge egress fees.
      </p>
      <p>
        <strong>meldra.ai</strong> leverages a zero-copy metadata framework. Instead of copying ledger tables, we map directory pointers directly to S3 Parquet blocks. Analytical engines read the metadata catalog on S3 to retrieve column statistics and partition values on-the-fly.
      </p>
      <p>
        This guarantees that your raw enterprise ledgers stay securely in your own S3 bucket. Access is audited via AWS IAM roles and postgres-based trails, ensuring full enterprise compliance.
      </p>
    `
  }
];

function openPublicArticle(index: number) {
  const overlay = document.getElementById('article-modal-overlay')!;
  const titleEl = document.getElementById('article-modal-title')!;
  const bodyEl = document.getElementById('article-modal-body')!;
  
  const article = publicArticles[index - 1];
  if (!article) return;
  
  titleEl.innerHTML = `<i class="fa-solid fa-book-open" style="color: #22c55e;"></i> ${article.title}`;
  bodyEl.innerHTML = `
    <div style="font-size: 0.8rem; color: #64748b; margin-bottom: 0.5rem; text-align: left;">
      <span style="color: #22c55e; font-weight: 700; text-transform: uppercase; margin-right: 0.5rem;">${article.tag}</span> | ${article.meta}
    </div>
    <div style="border-bottom: 1px solid #1e293b; margin-bottom: 0.5rem; padding-bottom: 0.5rem;"></div>
    ${article.body}
  `;
  
  overlay.classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closePublicArticle() {
  const overlay = document.getElementById('article-modal-overlay')!;
  overlay.classList.remove('active');
  document.body.style.overflow = '';
}

// Expose to window
(window as any).openPublicArticle = openPublicArticle;
(window as any).closePublicArticle = closePublicArticle;

async function logoutToHome() {
  try {
    await api.auth.logout();
  } catch (e) {}
  
  const landing = document.getElementById('landing-page');
  const app = document.getElementById('main-app');
  const overlay = document.getElementById('auth-overlay');
  
  if (app) app.style.display = 'none';
  if (landing) {
    landing.style.display = 'block';
    landing.classList.remove('hidden');
  }
  if (overlay) {
    overlay.style.display = 'none';
    overlay.classList.remove('active');
  }
  
  window.scrollTo(0, 0);
  showToast('Signed out successfully.', 'info');
}

function toggleLandingMobileMenu(btn: HTMLElement) {
  const navLinks = btn.parentElement?.querySelector('.landing-nav-links');
  if (navLinks) {
    const isActive = navLinks.classList.toggle('mobile-active');
    const icon = btn.querySelector('i');
    if (icon) {
      icon.className = isActive ? 'fa-solid fa-xmark' : 'fa-solid fa-bars';
    }
  }
}

// ─────────────────────────────────────────
// LIVE TRAFFIC MONITOR CONTROLLER
// ─────────────────────────────────────────
let trafficWebSocket: WebSocket | null = null;
let trafficEvents: any[] = [];
let trafficPaused = false;
let selectedTrafficEventId: string | null = null;

function initTrafficMonitor() {
  // Bind buttons
  const btnPause = document.getElementById('btn-traffic-pause') as HTMLButtonElement;
  const btnClear = document.getElementById('btn-traffic-clear') as HTMLButtonElement;
  const searchInput = document.getElementById('traffic-search') as HTMLInputElement;
  const filterSelect = document.getElementById('traffic-filter') as HTMLSelectElement;

  if (btnPause) {
    btnPause.onclick = () => {
      trafficPaused = !trafficPaused;
      btnPause.innerHTML = trafficPaused ? '<i class="fa-solid fa-play"></i> Resume' : '<i class="fa-solid fa-pause"></i> Pause';
      showToast(trafficPaused ? 'Traffic streaming paused.' : 'Traffic streaming resumed.', 'info');
    };
  }

  if (btnClear) {
    btnClear.onclick = () => {
      trafficEvents = [];
      selectedTrafficEventId = null;
      renderTrafficTimeline();
      renderTrafficInspector();
      updateTrafficStats();
      showToast('Traffic logs cleared.', 'info');
    };
  }

  if (searchInput) {
    searchInput.oninput = () => renderTrafficTimeline();
  }

  if (filterSelect) {
    filterSelect.onchange = () => renderTrafficTimeline();
  }

  // Connect WebSocket
  if (!trafficWebSocket || trafficWebSocket.readyState !== WebSocket.OPEN) {
    connectTrafficWS();
  }
}

function connectTrafficWS() {
  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const apiBase = (import.meta.env.VITE_API_BASE_URL as string) || 'http://localhost:8000';
  const wsHost = apiBase.replace(/^https?:\/\//, '').replace(/\/$/, '');
  const token = tokenStore.getAccessToken();
  const wsUrl = `${wsProto}//${wsHost}/ws/traffic?token=${token}`;

  const statusBadge = document.getElementById('traffic-stream-status')!;
  
  try {
    trafficWebSocket = new WebSocket(wsUrl);

    trafficWebSocket.onopen = () => {
      if (statusBadge) {
        statusBadge.innerHTML = '<span style="display: inline-block; width: 6px; height: 6px; background: #22c55e; border-radius: 50%;"></span> CONNECTED';
        statusBadge.style.color = '#22c55e';
      }
    };

    trafficWebSocket.onmessage = (event) => {
      if (trafficPaused) return;
      try {
        const data = JSON.parse(event.data);
        // Deduplicate
        if (!trafficEvents.some(e => e.id === data.id)) {
          trafficEvents.unshift(data); // Newest at the top
          if (trafficEvents.length > 500) {
            trafficEvents.pop();
          }
          renderTrafficTimeline();
          updateTrafficStats();
        }
      } catch (e) {
        console.error('Error parsing traffic event:', e);
      }
    };

    trafficWebSocket.onclose = () => {
      if (statusBadge) {
        statusBadge.innerHTML = '<span style="display: inline-block; width: 6px; height: 6px; background: #ef4444; border-radius: 50%;"></span> DISCONNECTED';
        statusBadge.style.color = '#ef4444';
      }
      // Reconnect after 3 seconds if active tab is still traffic
      setTimeout(() => {
        if (state.activeTab === 'traffic-tab') {
          connectTrafficWS();
        }
      }, 3000);
    };

    trafficWebSocket.onerror = () => {
      if (statusBadge) {
        statusBadge.innerHTML = '<span style="display: inline-block; width: 6px; height: 6px; background: #ef4444; border-radius: 50%;"></span> ERROR';
        statusBadge.style.color = '#ef4444';
      }
    };
  } catch (err) {
    console.error('WebSocket connection error:', err);
  }
}

function renderTrafficTimeline() {
  const container = document.getElementById('traffic-timeline-list')!;
  if (!container) return;

  const searchVal = (document.getElementById('traffic-search') as HTMLInputElement)?.value.toLowerCase() || '';
  const filterVal = (document.getElementById('traffic-filter') as HTMLSelectElement)?.value || 'all';

  // Filter events
  let filtered = trafficEvents.filter(event => {
    // Search
    const matchesSearch = 
      (event.path && event.path.toLowerCase().includes(searchVal)) ||
      (event.tool_name && event.tool_name.toLowerCase().includes(searchVal)) ||
      (event.method && event.method.toLowerCase().includes(searchVal));

    // Filter type
    let matchesFilter = true;
    if (filterVal === 'http') matchesFilter = event.type === 'http_request';
    if (filterVal === 'tool') matchesFilter = event.type === 'tool_call';
    if (filterVal === 'error') {
      matchesFilter = event.status === 'error' || (event.status && parseInt(event.status) >= 400);
    }

    return matchesSearch && matchesFilter;
  });

  if (filtered.length === 0) {
    container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.8rem; font-style: italic; padding: 2rem; text-align: center;">No matching traffic events.</div>';
    return;
  }

  // Render rows
  let idx = filtered.length;
  container.innerHTML = filtered.map(event => {
    const isHttp = event.type === 'http_request';
    const num = idx--;
    const methodText = isHttp ? event.method : '🤖 AI';
    const pathText = isHttp ? event.path : `└─ Tool: ${event.tool_name}`;
    const statusText = event.status || 'success';
    const isError = statusText === 'error' || parseInt(statusText) >= 400;
    const statusColor = isError ? '#ef4444' : (isHttp ? '#38bdf8' : '#22c55e');
    const latencyVal = event.latency_ms ? (event.latency_ms / 1000).toFixed(2) + 's' : '0.00s';
    
    const isActiveClass = event.id === selectedTrafficEventId ? 'background: rgba(255,255,255,0.06);' : '';
    const leftPadding = isHttp ? '0.75rem' : '1.75rem';
    
    return `
      <div class="traffic-row" data-id="${event.id}" style="display: grid; grid-template-columns: 50px 70px 1fr 60px 70px; padding: 0.6rem 1rem; border-bottom: 1px solid rgba(255,255,255,0.03); font-size: 0.78rem; cursor: pointer; align-items: center; ${isActiveClass} padding-left: ${leftPadding};" onclick="selectTrafficEvent('${event.id}')">
        <span style="color: var(--text-muted);">${num}</span>
        <span style="font-weight: 700; color: ${isHttp ? '#e2e8f0' : '#86efac'};">${methodText}</span>
        <span style="color: ${isHttp ? '#f8fafc' : '#cbd5e1'}; font-family: var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${pathText}</span>
        <span style="color: ${statusColor}; font-weight: 700;">${statusText}</span>
        <span style="text-align: right; color: var(--text-muted); font-family: var(--font-mono);">${latencyVal}</span>
      </div>
    `;
  }).join('');
}

function selectTrafficEvent(eventId: string) {
  selectedTrafficEventId = eventId;
  renderTrafficTimeline();
  renderTrafficInspector();
}
(window as any).selectTrafficEvent = selectTrafficEvent;

function renderTrafficInspector() {
  const container = document.getElementById('traffic-inspector-content')!;
  if (!container) return;

  const event = trafficEvents.find(e => e.id === selectedTrafficEventId);
  if (!event) {
    container.innerHTML = '<div style="color: var(--text-muted); font-style: italic; text-align: center; padding-top: 5rem;">Select an event row from the timeline to inspect payloads.</div>';
    return;
  }

  const isHttp = event.type === 'http_request';
  const headerTitle = isHttp ? `${event.method} ${event.path}` : `AI Agent Tool Call: ${event.tool_name}`;
  const requestLabel = isHttp ? 'HTTP Request Body' : 'Input Arguments';
  const responseLabel = isHttp ? 'HTTP Response Payload' : 'Output Result';

  // Format request/response body safely
  let reqPayload = 'No payload';
  if (event.request_body || event.tool_args) {
    try {
      const parsed = JSON.parse(event.request_body || event.tool_args);
      reqPayload = JSON.stringify(parsed, null, 2);
    } catch {
      reqPayload = event.request_body || event.tool_args;
    }
  }

  let resPayload = 'No response payload';
  if (event.response_body || event.tool_result) {
    try {
      const parsed = JSON.parse(event.response_body || event.tool_result);
      resPayload = JSON.stringify(parsed, null, 2);
    } catch {
      resPayload = event.response_body || event.tool_result;
    }
  }

  container.innerHTML = `
    <div>
      <h4 style="color:#fff; margin:0 0 0.5rem 0; font-size:0.85rem; border-bottom:1px solid rgba(255,255,255,0.08); padding-bottom:0.35rem;">${headerTitle}</h4>
      <div style="display:flex; justify-content:space-between; font-size:0.72rem; color:var(--text-muted); margin-bottom:0.75rem;">
        <span>Timestamp: ${new Date(event.timestamp).toLocaleTimeString()}</span>
        <span>Latency: ${event.latency_ms ? event.latency_ms.toFixed(0) + 'ms' : 'N/A'}</span>
      </div>
    </div>
    
    <div>
      <h5 style="color:#bef264; margin:0 0 0.4rem 0; font-size:0.75rem;">${requestLabel}</h5>
      <pre style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); padding:0.75rem; border-radius:6px; overflow-x:auto; max-height:160px; color:#cbd5e1; font-size:0.72rem; margin:0;">${reqPayload}</pre>
    </div>

    <div>
      <h5 style="color:#38bdf8; margin:0 0 0.4rem 0; font-size:0.75rem;">${responseLabel}</h5>
      <pre style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); padding:0.75rem; border-radius:6px; overflow-x:auto; max-height:220px; color:#cbd5e1; font-size:0.72rem; margin:0;">${resPayload}</pre>
    </div>
  `;
}

function updateTrafficStats() {
  const total = trafficEvents.length;
  const http = trafficEvents.filter(e => e.type === 'http_request').length;
  const tools = trafficEvents.filter(e => e.type === 'tool_call').length;
  const errors = trafficEvents.filter(e => e.status === 'error' || (e.status && parseInt(e.status) >= 400)).length;

  document.getElementById('traffic-stat-total')!.textContent = total.toString();
  document.getElementById('traffic-stat-http')!.textContent = http.toString();
  document.getElementById('traffic-stat-tools')!.textContent = tools.toString();
  document.getElementById('traffic-stat-errors')!.textContent = errors.toString();
}


// ─────────────────────────────────────────
// DATA ENGINEERING STUDIO CONTROLLER
// ─────────────────────────────────────────
let activeNamespace = 'default';
let activeTableName = '';
let studioSubTab = 'studio-tab-sql';
let currentTableSchema: any[] = [];
let contractRules: any[] = [];

async function initDataStudio() {
  // Bind sub-tabs
  const subTabButtons = document.querySelectorAll('.studio-sub-tab-btn') as NodeListOf<HTMLElement>;
  subTabButtons.forEach(btn => {
    btn.onclick = () => {
      subTabButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const target = btn.getAttribute('data-subtab')!;
      
      const contents = document.querySelectorAll('.studio-sub-tab-content');
      contents.forEach(c => (c as HTMLElement).style.display = 'none');
      
      const targetEl = document.getElementById(target);
      if (targetEl) {
        if (target === 'studio-tab-sql') targetEl.style.display = 'flex';
        else targetEl.style.display = 'block';
      }
      
      studioSubTab = target;
      if (target === 'studio-tab-schema') renderSchemaTab();
      if (target === 'studio-tab-travel') loadTableHistory();
      if (target === 'studio-tab-contracts') loadTableContracts();
    };
  });

  // Namespace selector changes
  const nsSelect = document.getElementById('studio-namespace-select') as HTMLSelectElement;
  if (nsSelect) {
    nsSelect.onchange = () => {
      activeNamespace = nsSelect.value;
      loadStudioTables();
    };
  }

  // Create/Delete Namespace buttons
  const btnCreateNs = document.getElementById('btn-create-ns') as HTMLButtonElement;
  if (btnCreateNs) {
    btnCreateNs.onclick = async () => {
      const newNs = prompt('Enter name of new namespace (e.g. production, staging, dev):');
      if (!newNs) return;
      try {
        await api.catalog.createNamespace(newNs.trim());
        showToast(`Namespace '${newNs}' created successfully.`);
        await loadStudioNamespaces();
      } catch (e: any) {
        showToast(e.message, 'error');
      }
    };
  }

  const btnDeleteNs = document.getElementById('btn-delete-ns') as HTMLButtonElement;
  if (btnDeleteNs) {
    btnDeleteNs.onclick = async () => {
      const confirmDelete = confirm(`Are you sure you want to drop namespace '${activeNamespace}'? This fails if tables exist.`);
      if (!confirmDelete) return;
      try {
        await api.catalog.deleteNamespace(activeNamespace);
        showToast(`Namespace '${activeNamespace}' dropped.`);
        await loadStudioNamespaces();
      } catch (e: any) {
        showToast(e.message, 'error');
      }
    };
  }

  // Create Table button
  const btnCreateTable = document.getElementById('btn-create-table-studio') as HTMLButtonElement;
  if (btnCreateTable) {
    btnCreateTable.onclick = () => {
      switchTab('ingest-tab');
      showToast('Upload a CSV file to define and create your Iceberg table.', 'info');
    };
  }

  // Run SQL button
  const btnRunSql = document.getElementById('btn-run-sql') as HTMLButtonElement;
  if (btnRunSql) {
    btnRunSql.onclick = executeStudioSQL;
  }

  // Add column button
  const btnAddCol = document.getElementById('btn-schema-add-col') as HTMLButtonElement;
  if (btnAddCol) {
    btnAddCol.onclick = executeAddColumn;
  }

  // Maintenance buttons
  const btnCompaction = document.getElementById('btn-maintenance-optimize') as HTMLButtonElement;
  if (btnCompaction) {
    btnCompaction.onclick = () => runMaintenanceTask('optimize');
  }

  const btnExpireSnapshots = document.getElementById('btn-maintenance-expire') as HTMLButtonElement;
  if (btnExpireSnapshots) {
    btnExpireSnapshots.onclick = () => runMaintenanceTask('expire_snapshots');
  }

  // Contract rules buttons
  const btnAddRule = document.getElementById('btn-add-contract-rule') as HTMLButtonElement;
  if (btnAddRule) {
    btnAddRule.onclick = addContractRuleItem;
  }

  const btnSaveContracts = document.getElementById('btn-save-contracts') as HTMLButtonElement;
  if (btnSaveContracts) {
    btnSaveContracts.onclick = saveTableContracts;
  }

  // Initialize data
  await loadStudioNamespaces();
}

async function loadStudioNamespaces() {
  try {
    const res = await api.catalog.listNamespaces();
    const select = document.getElementById('studio-namespace-select') as HTMLSelectElement;
    if (select) {
      select.innerHTML = res.namespaces.map(ns => `<option value="${ns}">${ns}</option>`).join('');
      // Select the active one
      if (res.namespaces.includes(activeNamespace)) {
        select.value = activeNamespace;
      } else if (res.namespaces.length > 0) {
        activeNamespace = res.namespaces[0];
        select.value = activeNamespace;
      }
    }
    await loadStudioTables();
  } catch (e: any) {
    showToast('Failed to load namespaces catalog.', 'error');
  }
}

async function loadStudioTables() {
  const container = document.getElementById('studio-table-list')!;
  if (!container) return;

  try {
    const res = await api.catalog.listTables(activeNamespace);
    if (res.tables.length === 0) {
      container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.8rem; font-style: italic; padding: 1rem 0;">No tables found.</div>';
      activeTableName = '';
      return;
    }

    container.innerHTML = res.tables.map(tbl => {
      // Color coded badge by layers
      let badgeColor = '#bef264'; // Bronze
      let layerTag = 'Bronze';
      if (tbl.includes('silver') || tbl.includes('clean')) {
        badgeColor = '#38bdf8';
        layerTag = 'Silver';
      } else if (tbl.includes('gold') || tbl.includes('analytics') || tbl.includes('summary')) {
        badgeColor = '#c084fc';
        layerTag = 'Gold';
      }

      const activeStyle = tbl === activeTableName ? 'background: rgba(255,255,255,0.06); border-color: var(--border-glass);' : '';
      return `
        <button class="btn btn-secondary btn-sm" style="display:flex; justify-content:space-between; align-items:center; width:100%; text-align:left; font-family:var(--font-mono); font-size:0.78rem; padding:0.5rem 0.75rem; margin:0; ${activeStyle}" onclick="selectStudioTable('${tbl}')">
          <span><i class="fa-solid fa-table" style="margin-right:0.35rem; color:var(--text-muted);"></i> ${tbl}</span>
          <span style="font-size:0.6rem; font-weight:700; color:${badgeColor}; border:1px solid ${badgeColor}40; background:${badgeColor}10; padding:0.1rem 0.3rem; border-radius:3px;">${layerTag}</span>
        </button>
      `;
    }).join('');

    // Select the first table by default if none selected
    if (!activeTableName || !res.tables.includes(activeTableName)) {
      selectStudioTable(res.tables[0]);
    }
  } catch (e: any) {
    showToast('Failed to list tables in namespace.', 'error');
  }
}

async function selectStudioTable(tableName: string) {
  activeTableName = tableName;
  // Reload sidebar highlights
  await loadStudioTables();
  
  // Fetch details
  try {
    const details = await api.catalog.getTableDetails(activeNamespace, tableName);
    currentTableSchema = details.schema || [];
    
    // Auto populate SQL Console query
    const sqlEditor = document.getElementById('studio-sql-editor') as HTMLTextAreaElement;
    if (sqlEditor && sqlEditor.value.trim().startsWith('-- Type your SQL') || sqlEditor.value.trim().includes('FROM')) {
      sqlEditor.value = `SELECT * FROM ${tableName} LIMIT 10;`;
    }

    // Refresh active subtab
    if (studioSubTab === 'studio-tab-schema') renderSchemaTab();
    if (studioSubTab === 'studio-tab-travel') loadTableHistory();
    if (studioSubTab === 'studio-tab-contracts') loadTableContracts();
  } catch (e: any) {
    showToast('Failed to fetch table details.', 'error');
  }
}
(window as any).selectStudioTable = selectStudioTable;

// SUB-TAB 1: SQL Console query runner
async function executeStudioSQL() {
  const sql = (document.getElementById('studio-sql-editor') as HTMLTextAreaElement).value.trim();
  if (!sql) return;

  const btn = document.getElementById('btn-run-sql') as HTMLButtonElement;
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Running...';

  try {
    const res = await api.catalog.runQuery(sql, activeNamespace);
    
    // Stats
    const statsEl = document.getElementById('studio-sql-stats')!;
    statsEl.textContent = `${res.row_count} rows returned in ${res.duration_ms.toFixed(0)}ms`;

    // Render table headers
    const thead = document.getElementById('studio-sql-thead')!;
    thead.innerHTML = `<tr>${res.columns.map((c: string) => `<th>${c}</th>`).join('')}</tr>`;

    // Render table rows
    const tbody = document.getElementById('studio-sql-tbody')!;
    if (res.rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="${res.columns.length}" style="text-align:center; color:var(--text-muted); font-style:italic;">Query executed successfully. Empty dataset returned.</td></tr>`;
    } else {
      tbody.innerHTML = res.rows.map((row: any) => {
        return `<tr>${res.columns.map((col: string) => `<td>${row[col] !== null ? row[col] : '<span style="color:var(--text-muted); font-style:italic;">NULL</span>'}</td>`).join('')}</tr>`;
      }).join('');
    }
    showToast('SQL query completed.');
  } catch (e: any) {
    showToast(e.message, 'error');
    // Display error message directly in table
    const tbody = document.getElementById('studio-sql-tbody')!;
    tbody.innerHTML = `<tr><td style="color:#ef4444; font-family:var(--font-mono); font-size:0.75rem; text-align:left;">Error executing SQL:<br>${e.message}</td></tr>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fa-solid fa-play"></i> Run Query';
  }
}

// SUB-TAB 2: Schema evolution renderer & commands
function renderSchemaTab() {
  const tbody = document.getElementById('studio-schema-tbody')!;
  if (!tbody) return;

  if (currentTableSchema.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--text-muted); font-style:italic;">No columns found. Select a table.</td></tr>';
    return;
  }

  tbody.innerHTML = currentTableSchema.map(col => {
    return `
      <tr>
        <td style="font-family:var(--font-mono);">${col.id}</td>
        <td style="font-weight:600; color:#fff;">${col.name}</td>
        <td style="font-family:var(--font-mono); color:#bef264;">${col.type}</td>
        <td>${col.required ? '✅ Required' : 'Optional'}</td>
        <td>
          <button class="btn btn-secondary btn-sm" style="color:#ef4444; padding:0.2rem 0.4rem; margin:0;" onclick="executeDropColumn('${col.name}')"><i class="fa-solid fa-trash"></i> Drop</button>
          <button class="btn btn-secondary btn-sm" style="padding:0.2rem 0.4rem; margin:0 0 0 0.25rem;" onclick="promptRenameColumn('${col.name}')"><i class="fa-solid fa-pen-to-square"></i> Rename</button>
        </td>
      </tr>
    `;
  }).join('');
}

async function executeAddColumn() {
  if (!activeTableName) {
    showToast('Select a table first.', 'error');
    return;
  }
  const nameInput = document.getElementById('schema-add-name') as HTMLInputElement;
  const typeSelect = document.getElementById('schema-add-type') as HTMLSelectElement;
  const name = nameInput.value.trim();
  const type = typeSelect.value;

  if (!name) {
    showToast('Please specify column name.', 'error');
    return;
  }

  try {
    await api.catalog.evolveSchema(activeNamespace, activeTableName, [{ op: 'add', name, type }]);
    showToast(`Successfully added column '${name}' to ${activeTableName}.`);
    nameInput.value = '';
    await selectStudioTable(activeTableName);
  } catch (e: any) {
    showToast(e.message, 'error');
  }
}

async function executeDropColumn(colName: string) {
  const confirmDrop = confirm(`Are you sure you want to drop column '${colName}'? Historical data will be preserved but inaccessible.`);
  if (!confirmDrop) return;

  try {
    await api.catalog.evolveSchema(activeNamespace, activeTableName, [{ op: 'drop', name: colName }]);
    showToast(`Successfully dropped column '${colName}'.`);
    await selectStudioTable(activeTableName);
  } catch (e: any) {
    showToast(e.message, 'error');
  }
}
(window as any).executeDropColumn = executeDropColumn;

async function promptRenameColumn(oldName: string) {
  const newName = prompt(`Enter new name for column '${oldName}':`);
  if (!newName || newName.trim() === oldName) return;

  try {
    await api.catalog.evolveSchema(activeNamespace, activeTableName, [{ op: 'rename', name: oldName, new_name: newName.trim() }]);
    showToast(`Column '${oldName}' renamed to '${newName.trim()}'.`);
    await selectStudioTable(activeTableName);
  } catch (e: any) {
    showToast(e.message, 'error');
  }
}
(window as any).promptRenameColumn = promptRenameColumn;

// SUB-TAB 3: Time Travel historical loader
async function loadTableHistory() {
  const container = document.getElementById('studio-travel-timeline')!;
  if (!container) return;

  if (!activeTableName) {
    container.innerHTML = '<div style="color:var(--text-muted); font-style:italic;">No table selected.</div>';
    return;
  }

  try {
    const details = await api.catalog.getTableDetails(activeNamespace, activeTableName);
    const history = details.history || [];

    if (history.length === 0) {
      container.innerHTML = '<div style="color:var(--text-muted); font-size:0.8rem; font-style:italic;">No historical snapshots recorded yet.</div>';
      return;
    }

    // Sort historical snapshots newest first
    const sorted = [...history].reverse();
    container.innerHTML = sorted.map((snap: any) => {
      const commitDate = new Date(snap.timestamp_ms);
      return `
        <button class="btn btn-secondary btn-sm" style="display:flex; flex-direction:column; text-align:left; width:100%; padding:0.6rem 0.8rem; gap:0.25rem; font-size:0.75rem;" onclick="loadTimeTravelPreview(${snap.snapshot_id})">
          <div style="font-weight:700; color:#38bdf8; display:flex; justify-content:space-between; width:100%;">
            <span>Snapshot #${snap.snapshot_id.toString().substring(0, 8)}...</span>
            <span style="font-size:0.65rem; color:var(--text-muted);">${commitDate.toLocaleTimeString()}</span>
          </div>
          <div style="font-size:0.68rem; color:var(--text-muted); font-family:var(--font-mono);">${commitDate.toLocaleDateString()}</div>
        </button>
      `;
    }).join('');

    // Load default query preview on current snapshot
    loadTimeTravelPreview(0); // 0 translates to current/latest
  } catch (e: any) {
    container.innerHTML = '<div style="color:#ef4444; font-size:0.75rem;">Failed to load history list.</div>';
  }
}

async function loadTimeTravelPreview(snapshotId: number) {
  const thead = document.getElementById('studio-travel-thead')!;
  const tbody = document.getElementById('studio-travel-tbody')!;
  const activeSnapBadge = document.getElementById('studio-travel-active-snap')!;

  if (!activeTableName) return;

  activeSnapBadge.textContent = snapshotId === 0 ? 'Current State' : `Snapshot: ${snapshotId.toString().substring(0, 10)}...`;

  try {
    // Execute a simple limit query at that snapshot state
    const res = await api.catalog.runQuery(`SELECT * FROM ${activeTableName} LIMIT 10;`, activeNamespace, snapshotId || undefined);
    
    // Render
    thead.innerHTML = `<tr>${res.columns.map((c: string) => `<th>${c}</th>`).join('')}</tr>`;
    tbody.innerHTML = res.rows.map((row: any) => {
      return `<tr>${res.columns.map((col: string) => `<td>${row[col] !== null ? row[col] : '<span style="color:var(--text-muted);">NULL</span>'}</td>`).join('')}</tr>`;
    }).join('');
  } catch (e: any) {
    tbody.innerHTML = `<tr><td style="color:#ef4444; font-family:var(--font-mono); font-size:0.7rem; text-align:left;">Failed to load historical snapshot:<br>${e.message}</td></tr>`;
  }
}
(window as any).loadTimeTravelPreview = loadTimeTravelPreview;

// SUB-TAB 4: Data contracts builder
async function loadTableContracts() {
  const container = document.getElementById('contracts-rules-container')!;
  if (!container) return;

  if (!activeTableName) {
    container.innerHTML = '<div style="color:var(--text-muted); font-style:italic;">No table selected.</div>';
    return;
  }

  try {
    const res = await api.catalog.getContracts(activeNamespace, activeTableName);
    contractRules = res.rules || [];
    renderContractRulesList();
  } catch (e) {
    container.innerHTML = '<div style="color:#ef4444; font-size:0.75rem;">Failed to load contracts.</div>';
  }
}

function renderContractRulesList() {
  const container = document.getElementById('contracts-rules-container')!;
  if (!container) return;

  if (contractRules.length === 0) {
    container.innerHTML = '<div style="color:var(--text-muted); font-size:0.8rem; font-style:italic; padding:0.5rem 0;">No active rules. Click below to add.</div>';
    return;
  }

  container.innerHTML = contractRules.map((rule, idx) => {
    return `
      <div style="display:flex; gap:0.4rem; align-items:center; background:rgba(255,255,255,0.02); border:1px solid var(--border-subtle); padding:0.4rem; border-radius:6px;">
        <input type="text" class="input-field rule-col" placeholder="column" value="${rule.column || ''}" style="padding:0.3rem; font-size:0.8rem; flex:1;">
        <select class="input-field rule-op" style="padding:0.3rem; font-size:0.8rem; width:100px;">
          <option value="not_null" ${rule.rule === 'not_null' ? 'selected' : ''}>not_null</option>
          <option value="min" ${rule.rule === 'min' ? 'selected' : ''}>min</option>
          <option value="max" ${rule.rule === 'max' ? 'selected' : ''}>max</option>
          <option value="regex" ${rule.rule === 'regex' ? 'selected' : ''}>regex</option>
        </select>
        <input type="text" class="input-field rule-val" placeholder="value" value="${rule.value || ''}" style="padding:0.3rem; font-size:0.8rem; width:80px;">
        <button class="btn btn-secondary btn-sm" style="color:#ef4444; padding:0.3rem; margin:0;" onclick="removeContractRuleItem(${idx})"><i class="fa-solid fa-trash"></i></button>
      </div>
    `;
  }).join('');
}

function addContractRuleItem() {
  contractRules.push({ column: '', rule: 'not_null', value: '' });
  renderContractRulesList();
}

function removeContractRuleItem(idx: number) {
  contractRules.splice(idx, 1);
  renderContractRulesList();
}
(window as any).removeContractRuleItem = removeContractRuleItem;

async function saveTableContracts() {
  if (!activeTableName) return;

  const container = document.getElementById('contracts-rules-container')!;
  const rows = container.querySelectorAll('div');
  const rulesList: any[] = [];

  rows.forEach(row => {
    const col = (row.querySelector('.rule-col') as HTMLInputElement).value.trim();
    const op = (row.querySelector('.rule-op') as HTMLSelectElement).value;
    const val = (row.querySelector('.rule-val') as HTMLInputElement).value.trim();

    if (col) {
      rulesList.push({ column: col, rule: op, value: val });
    }
  });

  try {
    await api.catalog.saveContracts(activeNamespace, activeTableName, rulesList);
    showToast('Data contracts saved successfully.');
    // Log message emulator
    const logEl = document.getElementById('contracts-validation-log')!;
    logEl.innerHTML += `<br>[contracts] Saved ${rulesList.length} metadata validation constraints to properties.`;
    logEl.scrollTop = logEl.scrollHeight;
  } catch (e: any) {
    showToast(e.message, 'error');
  }
}

// SUB-TAB 6: Maintenance Optimize & Expire
async function runMaintenanceTask(action: 'optimize' | 'expire_snapshots') {
  if (!activeTableName) {
    showToast('Select a table first.', 'error');
    return;
  }

  const confirmAction = confirm(`Are you sure you want to run '${action}' maintenance on ${activeTableName}?`);
  if (!confirmAction) return;

  try {
    const res = await api.catalog.runMaintenance(activeNamespace, activeTableName, action);
    showToast(res.message);
  } catch (e: any) {
    showToast(e.message, 'error');
  }
}


// Expose functions to window for DOM bindings
(window as any).initDataStudio = initDataStudio;
(window as any).initTrafficMonitor = initTrafficMonitor;
(window as any).logoutToHome = logoutToHome;
(window as any).toggleLandingMobileMenu = toggleLandingMobileMenu;

if (document.readyState === 'loading') {
  window.addEventListener('DOMContentLoaded', initAuthController);
} else {
  initAuthController();
}
