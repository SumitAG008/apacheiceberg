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
import type { ChatMessage, AWSConfig, CSVUploadResponse } from './api';


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
const uploadStatus = document.getElementById('upload-status') as HTMLDivElement;
const previewSection = document.getElementById('preview-section') as HTMLDivElement;
const previewRowCount = document.getElementById('preview-row-count') as HTMLSpanElement;
const csvPreviewTable = document.getElementById('csv-preview-table') as HTMLTableElement;
const previewTheadTr = document.getElementById('preview-thead-tr') as HTMLTableRowElement;
const previewTbody = document.getElementById('preview-tbody') as HTMLTableSectionElement;
const schemaConfigTbody = document.getElementById('schema-config-tbody') as HTMLTableSectionElement;
const ingestNamespace = document.getElementById('ingest-namespace') as HTMLInputElement;
const ingestTableName = document.getElementById('ingest-table-name') as HTMLInputElement;
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
const graphResultsTable = document.getElementById('graph-results-table') as HTMLTableElement;
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
    }
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
    } else {
      customAwsToggle.checked = false;
      awsConfigForm.style.display = 'none';
      awsDemoInfo.style.display = 'block';
    }
  } catch (error) {
    console.error('Failed to load AWS configuration:', error);
  }
}

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
      <div class="message-sender">${role === 'user' ? 'You' : 'LakeMind AI'}</div>
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
    <p>👋 Welcome to <strong>LakeMind</strong> — your intelligent Apache Iceberg data platform!</p>
    <p>I can help you:</p>
    <ul>
      <li>🗂 <strong>Create tables</strong> with custom schemas in your S3 data lake</li>
      <li>📥 <strong>Ingest CSV datasets</strong> into Iceberg table format on S3</li>
      <li>🔍 <strong>Query your data lake</strong> using plain English (powered by DuckDB + Claude AI)</li>
      <li>🔗 <strong>Build knowledge graphs</strong> — sync data to Apache AGE and query with Cypher</li>
      <li>🔧 <strong>Schema evolution</strong> — add/rename/drop columns without rewriting data</li>
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
    title: "What is Apache Iceberg?",
    icon: "fa-snowflake",
    level: "Beginner",
    concept: `
      <p>Apache Iceberg is a high-performance open table format for massive analytical datasets. It acts as a transactional interface on top of object stores like Amazon S3, Azure ADLS, or Google Cloud Storage.</p>
      <p><strong>Why do we need it?</strong> Traditional object-based file structures (like directories of Parquet/CSV files) lack transaction support, schema history, and isolation. Iceberg brings ACID properties to files in S3.</p>
      <ul>
        <li><strong>Metadata files:</strong> JSON schemas tracking table states and snapshots.</li>
        <li><strong>Manifest lists:</strong> Log sheets tracking data files in each commit.</li>
        <li><strong>Data files:</strong> Raw storage files containing information (e.g. Parquet).</li>
      </ul>
    `,
    tryPrompt: "List all schemas and tables in my default namespace"
  },
  {
    num: "02",
    title: "Creating Your First Iceberg Table",
    icon: "fa-table",
    level: "Beginner",
    concept: `
      <p>Creating an Iceberg table defines its columns and types, registering the definition inside AWS Glue/REST Catalogs. Physical storage files are written into S3.</p>
      <p><strong>Supported data types:</strong> <code>string</code>, <code>integer</code>, <code>float</code>, <code>double</code>, <code>boolean</code>, <code>date</code>, <code>timestamp</code>.</p>
    `,
    tryPrompt: "Create a table called customers in namespace default with columns: customer_id (integer), name (string), email (string), signup_date (string)"
  },
  {
    num: "03",
    title: "Ingesting Data into Your Lake",
    icon: "fa-cloud-arrow-down",
    level: "Intermediate",
    concept: `
      <p>Iceberg structures ingestion into atomic commits. When appending rows, Iceberg writes new Parquet data, creates a manifest files snapshot, and points the catalog to the new metadata location.</p>
      <p>To try ingestion visually, use the <strong>Ingest</strong> tab on the header to drag-and-drop your local files.</p>
    `,
    tryPrompt: "Show the structure and columns of the customers table"
  },
  {
    num: "04",
    title: "Querying Your Data Lake with SQL",
    icon: "fa-magnifying-glass",
    level: "Intermediate",
    concept: `
      <p>The backend integrates <strong>DuckDB</strong>, a fast analytical engine that fetches Iceberg data directly from S3 using intelligent filters (predicate pushdown), skipping unnecessary columns/files.</p>
    `,
    tryPrompt: "Show me the first 5 records of the customers table"
  },
  {
    num: "05",
    title: "Schema Evolution — Safe & Instant",
    icon: "fa-arrows-spin",
    level: "Advanced",
    concept: `
      <p>Iceberg supports schema evolution as <strong>metadata-only changes</strong>. Adding, renaming, dropping, or reordering columns does not require rewriting any data files, unlike classic Hive structures.</p>
    `,
    tryPrompt: "Add a column phone_number (string) to customers"
  },
  {
    num: "06",
    title: "Time Travel — Recovering Snapshots",
    icon: "fa-clock-rotate-left",
    level: "Advanced",
    concept: `
      <p>Each transaction creates a new historical snapshot. Users can query tables as they looked at specific times, helping troubleshoot data corruption or rollback audits.</p>
    `,
    tryPrompt: "Show the snapshot history for the table customers"
  }
];

function buildLessonsDeck() {
  const wrapper = document.getElementById('lessons-wrapper')!;
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
      
      // Close other cards
      document.querySelectorAll('.lesson-card').forEach(c => c.classList.remove('expanded'));
      
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
      
      switchTab('chat-tab');
      chatInputText.value = prompt;
      chatInputText.focus();
    });
    
    wrapper.appendChild(card);
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
      schema_json
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

function buildApiHelpTab() {
  const container = document.getElementById('api-endpoints-list')!;
  const baseUrlDisplay = document.getElementById('api-base-url-display')!;
  const docsLink = document.getElementById('api-docs-link') as HTMLAnchorElement;

  baseUrlDisplay.textContent = API_BASE;
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

  // ─ Screen references
  const screenLogin    = document.getElementById('auth-screen-login')!;
  const screenRegister = document.getElementById('auth-screen-register')!;
  const screenMfa      = document.getElementById('auth-screen-mfa')!;

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

  // ─ State
  let currentTempToken = '';
  let currentEmail = '';
  let otpCountdown: ReturnType<typeof setInterval> | null = null;
  let resendCountdown: ReturnType<typeof setInterval> | null = null;

  // ── Helpers─────────────────────────────────────────────
  function showScreen(screen: HTMLElement) {
    [screenLogin, screenRegister, screenMfa].forEach(s => s.classList.remove('active'));
    screen.classList.add('active');
  }

  function setError(el: HTMLElement, msg: string) {
    el.textContent = msg;
    el.classList.add('show');
  }

  function clearError(el: HTMLElement) {
    el.textContent = '';
    el.classList.remove('show');
  }

  function setSuccess(el: HTMLElement, msg: string) {
    el.textContent = msg;
    el.classList.add('show');
  }

  function showMainApp() {
    overlay.classList.add('hidden');
    setTimeout(() => { overlay.style.display = 'none'; }, 400);
    mainApp.style.display = 'flex';
    const user = tokenStore.getUser();
    if (user) headerEmail.textContent = user.email;
    bootstrapApp();
  }

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
    clearOtpInputs();
    clearError(mfaErrorEl);
    showScreen(screenLogin);
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
      currentEmail = email;
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
      currentEmail = email;
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
      if (otpCountdown) clearInterval(otpCountdown);
      if (resendCountdown) clearInterval(resendCountdown);
      showMainApp();
    } catch(e: any) {
      setError(mfaErrorEl, e.message || 'Invalid code. Please try again.');
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
    overlay.style.display = 'flex';
    overlay.classList.remove('hidden');
    loginEmailEl.value = '';
    loginPasswordEl.value = '';
    showScreen(screenLogin);
    showToast('Signed out successfully.', 'info');
  });

  // ── INIT: check if already logged in ────────────────────────
  if (tokenStore.isLoggedIn()) {
    showMainApp();
  }
  // Otherwise overlay stays visible, user must log in
}

// ─────────────────────────────────────────
// APP BOOTSTRAP
// ─────────────────────────────────────────
function bootstrapApp() {
  loadAWSConfig();
  initChat();
  buildLessonsDeck();
  buildApiHelpTab();
  buildTestTab();
  checkBackendStatus();
  setInterval(checkBackendStatus, 30_000);

  document.getElementById('btn-run-all-tests')!.addEventListener('click', runAllTests);
  document.getElementById('btn-clear-tests')!.addEventListener('click', resetTests);
}

if (document.readyState === 'loading') {
  window.addEventListener('DOMContentLoaded', initAuthController);
} else {
  initAuthController();
}
