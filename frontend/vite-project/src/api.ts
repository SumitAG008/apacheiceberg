/**
 * Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
 * This software is proprietary and confidential. Unauthorised use is prohibited.
 *
 * meldra.ai — BACKEND CLIENT API INTERCEPTOR
 *
 * Dependencies:
 * - Browser Fetch API: Handles standard Promise-based HTTP GET/POST queries.
 * - Browser FormData API: Orchestrates multipart file streams for CSV dataset transmission.
 */

// Uses VITE_API_BASE_URL env var for production (Railway URL), falls back to localhost for dev
const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string) || 'http://localhost:8000';

// ─── Token Storage ──────────────────────────────────────────────────────────
// Use sessionStorage so tokens don't persist across browser restarts
const TOKEN_KEY = 'meldra_access_token';
const REFRESH_KEY = 'meldra_refresh_token';
const USER_KEY = 'meldra_user';

export const tokenStore = {
  getAccessToken: (): string | null => sessionStorage.getItem(TOKEN_KEY),
  getRefreshToken: (): string | null => sessionStorage.getItem(REFRESH_KEY),
  getUser: (): AuthUser | null => {
    const s = sessionStorage.getItem(USER_KEY);
    return s ? JSON.parse(s) : null;
  },
  setTokens: (access: string, refresh: string, user: AuthUser) => {
    sessionStorage.setItem(TOKEN_KEY, access);
    sessionStorage.setItem(REFRESH_KEY, refresh);
    sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  clear: () => {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(REFRESH_KEY);
    sessionStorage.removeItem(USER_KEY);
  },
  isLoggedIn: (): boolean => !!sessionStorage.getItem(TOKEN_KEY),
};

async function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const token = tokenStore.getAccessToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> || {}),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    tokenStore.clear();
    window.location.reload();
  }
  return res;
}

// ─── Auth Types ──────────────────────────────────────────────────────────────
export interface AuthUser {
  id: string;
  email: string;
  mfa_method: string;
  is_verified: boolean;
  created_at?: string;
  last_login_at?: string;
  role?: string;
  is_approver?: boolean;
}

export interface PlatformUser {
  id: string;
  email: string;
  role: string;
  is_approver: boolean;
  is_verified: boolean;
  is_active: boolean;
  created_at: string | null;
  last_login_at: string | null;
}

export interface Promotion {
  id: number;
  tenant_id: string;
  pipeline_name: string;
  environment: 'staging' | 'production';
  version_ref: string;
  notes: string | null;
  status: 'pending' | 'deployed' | 'rejected';
  requested_by: string;
  requested_by_email?: string;
  requested_at: string;
  decided_by: string | null;
  decided_by_email?: string;
  decided_at: string | null;
  decision_notes: string | null;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  refresh_token: string;
  user: AuthUser;
}

export interface LoginResponse {
  message: string;
  temp_token: string;
  mfa_required: boolean;
}

export interface RegisterResponse {
  message: string;
  temp_token: string;
}


export interface AWSConfig {
  region: string;
  s3_warehouse_uri: string;
  access_key_id?: string;
  secret_access_key?: string;
  access_key_id_set?: boolean;
  secret_access_key_set?: boolean;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface IngestPayload {
  namespace: string;
  table_name: string;
  file_path: string;
  schema_json: { name: string; type: string }[];
  write_mode?: string;
  merge_key?: string;
}

export interface CSVUploadResponse {
  file_path: string;
  filename: string;
  row_count: number;
  schema: { name: string; type: string }[];
  preview: Record<string, any>[];
}

export interface GraphStats {
  nodes: number;
  edges: number;
  graph_name: string;
  error?: string;
}

export interface CypherResponse {
  columns: string[];
  rows: Record<string, any>[];
}

export interface AuditLog {
  id: number;
  timestamp: string;
  user_id: string;
  tier: string;
  action: string;
  details: string;
  status: 'success' | 'error';
}

export const api = {
  // ── Auth ──────────────────────────────────────────────────────────────────
  auth: {
    async register(email: string, password: string, mfaMethod: string = 'email'): Promise<RegisterResponse> {
      const res = await fetch(`${BASE_URL}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, mfa_method: mfaMethod }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Registration failed');
      return data;
    },

    async login(email: string, password: string): Promise<LoginResponse> {
      const res = await fetch(`${BASE_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Login failed');
      return data;
    },

    async verifyMfa(tempToken: string, code: string): Promise<AuthTokenResponse> {
      const res = await fetch(`${BASE_URL}/auth/verify-mfa`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ temp_token: tempToken, code }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'OTP verification failed');
      // Store tokens on success
      tokenStore.setTokens(data.access_token, data.refresh_token, data.user);
      return data;
    },

    async resendOtp(tempToken: string): Promise<{ message: string }> {
      const res = await fetch(`${BASE_URL}/auth/resend-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ temp_token: tempToken }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to resend OTP');
      return data;
    },

    async me(): Promise<AuthUser> {
      const res = await authFetch(`${BASE_URL}/auth/me`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Not authenticated');
      return data;
    },

    async logout(): Promise<void> {
      const refreshToken = tokenStore.getRefreshToken();
      try {
        await authFetch(`${BASE_URL}/auth/logout`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
      } catch (_) {
        // Ignore errors — clear tokens regardless
      }
      tokenStore.clear();
    },

    async ssoStatus(): Promise<{ configured: boolean; provider_name: string | null }> {
      const res = await fetch(`${BASE_URL}/auth/sso/status`);
      if (!res.ok) return { configured: false, provider_name: null };
      return res.json();
    },

    ssoLoginUrl(): string {
      return `${BASE_URL}/auth/sso/login`;
    },

    async forgotPassword(email: string): Promise<{ message: string; temp_token: string }> {
      const res = await fetch(`${BASE_URL}/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to send reset code');
      return data;
    },

    async resetPassword(tempToken: string, code: string, newPassword: string): Promise<{ message: string }> {
      const res = await fetch(`${BASE_URL}/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ temp_token: tempToken, code, new_password: newPassword }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Password reset failed');
      return data;
    },

    async changePassword(currentPassword: string, newPassword: string): Promise<{ message: string }> {
      const res = await authFetch(`${BASE_URL}/auth/change-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to change password');
      return data;
    },
  },

  // ── AWS Configuration ────────────────────────────────────────────────────
  async getAWSConfig(): Promise<AWSConfig> {
    const res = await authFetch(`${BASE_URL}/v1/config/aws`);
    if (!res.ok) throw new Error('Failed to fetch AWS configuration');
    return res.json();
  },

  async updateAWSConfig(config: AWSConfig): Promise<{ status: string; message: string }> {
    const res = await authFetch(`${BASE_URL}/v1/config/aws`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || err.detail || 'Failed to update AWS configuration');
    }
    return res.json();
  },

  // ── Chat agent ───────────────────────────────────────────────────────────
  async sendChatMessage(prompt: string, messages: ChatMessage[]): Promise<string> {
    const res = await authFetch(`${BASE_URL}/v1/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, messages }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || err.detail || 'Agent failed to respond');
    }
    const data = await res.json();
    return data.output;
  },

  // ── Ingestion: 1. Upload ────────────────────────────────────────────────
  async uploadCSV(file: File): Promise<CSVUploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await authFetch(`${BASE_URL}/v1/upload-csv`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || err.detail || 'Failed to upload CSV');
    }
    return res.json();
  },

  // ── Ingestion: SuccessFactors OData connector ──────────────────────────
  async triggerSFIngest(payload: Record<string, any>): Promise<any> {
    const res = await authFetch(`${BASE_URL}/v1/ingest/successfactors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || err.error || 'SuccessFactors ingest failed');
    }
    return res.json();
  },

  // ── Ingestion: 2. Create + Ingest ─────────────────────────────────────
  async triggerIngest(payload: IngestPayload): Promise<{ status: string; message: string }> {
    const res = await authFetch(`${BASE_URL}/v1/ingest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || err.detail || 'Failed to trigger ingestion');
    }
    return res.json();
  },

  // ── Apache AGE Graph Stats ──────────────────────────────────────────────
  async getGraphStats(graphName: string = 'pharma_graph'): Promise<GraphStats> {
    const res = await authFetch(`${BASE_URL}/v1/graph/stats?graph_name=${graphName}`);
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || err.detail || 'Failed to fetch graph stats');
    }
    return res.json();
  },

  // ── Apache AGE Cypher execution ────────────────────────────────────────
  async executeCypherQuery(query: string, graphName: string = 'pharma_graph'): Promise<CypherResponse> {
    const res = await authFetch(`${BASE_URL}/v1/graph/cypher`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ graph_name: graphName, query }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || err.detail || 'Failed to execute Cypher query');
    }
    return res.json();
  },

  async projectTableToGraph(tableName: string, sourceCol: string, targetCol: string, edgeLabel: string = 'RELATED_TO', graphName: string = 'pharma_graph'): Promise<any> {
    const res = await authFetch(`${BASE_URL}/v1/graph/project`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        table_name: tableName,
        source_col: sourceCol,
        target_col: targetCol,
        edge_label: edgeLabel,
        graph_name: graphName
      }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || err.detail || 'Failed to project table to graph');
    }
    return res.json();
  },

  async resetTenantState(): Promise<any> {
    const res = await authFetch(`${BASE_URL}/v1/admin/reset-tenant`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || err.detail || 'Failed to reset tenant state');
    }
    return res.json();
  },

  // ── Audit trail logs ─────────────────────────────────────────────────
  async getAuditLogs(): Promise<AuditLog[]> {
    const res = await authFetch(`${BASE_URL}/v1/audit`);
    if (!res.ok) throw new Error('Failed to fetch audit logs');
    return res.json();
  },

  // ── API token for external/programmatic clients (e.g. the real MCP server) ──
  async generateApiToken(): Promise<{ api_token: string; expires_at: string; token_type: string }> {
    const res = await authFetch(`${BASE_URL}/auth/api-token`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || err.detail || 'Failed to generate API token');
    }
    return res.json();
  },

  async getRecentTraffic(): Promise<any[]> {
    const res = await authFetch(`${BASE_URL}/v1/traffic/recent`);
    if (!res.ok) throw new Error('Failed to fetch recent traffic logs');
    return res.json();
  },

  // ── Catalog & Data Studio ───────────────────────────────────────────────
  catalog: {
    async listNamespaces(): Promise<{ namespaces: string[] }> {
      const res = await authFetch(`${BASE_URL}/v1/catalog/namespaces`);
      if (!res.ok) throw new Error('Failed to list namespaces');
      return res.json();
    },
    async createNamespace(namespace: string): Promise<any> {
      const res = await authFetch(`${BASE_URL}/v1/catalog/namespaces`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ namespace }),
      });
      if (!res.ok) throw new Error('Failed to create namespace');
      return res.json();
    },
    async deleteNamespace(namespace: string): Promise<any> {
      const res = await authFetch(`${BASE_URL}/v1/catalog/namespaces/${namespace}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error('Failed to delete namespace');
      return res.json();
    },
    async listTables(namespace: string): Promise<{ tables: string[] }> {
      const res = await authFetch(`${BASE_URL}/v1/catalog/namespaces/${namespace}/tables`);
      if (!res.ok) throw new Error('Failed to list tables');
      return res.json();
    },
    async getTableDetails(namespace: string, tableName: string): Promise<any> {
      const res = await authFetch(`${BASE_URL}/v1/catalog/namespaces/${namespace}/tables/${tableName}`);
      if (!res.ok) throw new Error('Failed to get table details');
      return res.json();
    },
    async evolveSchema(namespace: string, tableName: string, actions: any[]): Promise<any> {
      const res = await authFetch(`${BASE_URL}/v1/catalog/namespaces/${namespace}/tables/${tableName}/schema`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actions }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || err.detail || 'Failed to evolve schema');
      }
      return res.json();
    },
    async runQuery(sql: string, namespace: string = 'default', snapshotId?: number): Promise<any> {
      const res = await authFetch(`${BASE_URL}/v1/catalog/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql, namespace, snapshot_id: snapshotId }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || err.detail || 'Failed to run SQL query');
      }
      return res.json();
    },
    async runMaintenance(namespace: string, tableName: string, action: 'optimize' | 'expire_snapshots'): Promise<any> {
      const res = await authFetch(`${BASE_URL}/v1/catalog/namespaces/${namespace}/tables/${tableName}/maintenance`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      });
      if (!res.ok) throw new Error('Failed to run maintenance task');
      return res.json();
    },
    async getContracts(namespace: string, tableName: string): Promise<{ rules: any[] }> {
      const res = await authFetch(`${BASE_URL}/v1/catalog/namespaces/${namespace}/tables/${tableName}/contracts`);
      if (!res.ok) throw new Error('Failed to get data contracts');
      return res.json();
    },
    async saveContracts(namespace: string, tableName: string, rules: any[]): Promise<any> {
      const res = await authFetch(`${BASE_URL}/v1/catalog/namespaces/${namespace}/tables/${tableName}/contracts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rules }),
      });
      if (!res.ok) throw new Error('Failed to save data contracts');
      return res.json();
    }
  },
  // ── Studio / Notebook & Command Search ────────────────────────────────────
  // Note: free-form executePython() was removed along with the backend
  // /v1/studio/execute-python endpoint (unsandboxed RCE). Use Query Lab's
  // Python mode (api.query.submit with mode: "python") instead.
  studio: {
    async search(q: string): Promise<any[]> {
      const res = await authFetch(`${BASE_URL}/v1/studio/search?q=${encodeURIComponent(q)}`);
      if (!res.ok) throw new Error('Search failed');
      return res.json();
    }
  },
  // ── RBAC Policy controls ──────────────────────────────────────────────────
  rbac: {
    async getPolicies(): Promise<any[]> {
      const res = await authFetch(`${BASE_URL}/v1/rbac/policies`);
      if (!res.ok) throw new Error('Failed to load RBAC policies');
      return res.json();
    },
    async savePolicies(policies: any[]): Promise<any> {
      const res = await authFetch(`${BASE_URL}/v1/rbac/policies`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ policies }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || err.detail || 'Failed to save RBAC policies');
      }
      return res.json();
    },
    async getRowFilters(): Promise<any[]> {
      const res = await authFetch(`${BASE_URL}/v1/rbac/row-filters`);
      if (!res.ok) throw new Error('Failed to load row-level filters');
      return res.json();
    },
    async saveRowFilters(filters: any[]): Promise<any> {
      const res = await authFetch(`${BASE_URL}/v1/rbac/row-filters`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filters }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || err.detail || 'Failed to save row-level filters');
      }
      return res.json();
    },
    async updateUserRole(email: string, role: string): Promise<any> {
      const res = await authFetch(`${BASE_URL}/v1/rbac/user-role`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, role }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || err.detail || 'Failed to update user role');
      }
      return res.json();
    },
    async listRoles(): Promise<{ roles: { name: string; description: string }[] }> {
      const res = await authFetch(`${BASE_URL}/v1/rbac/roles`);
      if (!res.ok) throw new Error('Failed to load role list');
      return res.json();
    },
    async setApprover(email: string, isApprover: boolean): Promise<any> {
      const res = await authFetch(`${BASE_URL}/v1/rbac/user-approver`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, is_approver: isApprover }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || err.detail || 'Failed to update Approver status');
      }
      return res.json();
    },
    async listApprovers(): Promise<{ approvers: { id: string; email: string; user_role: string }[] }> {
      const res = await authFetch(`${BASE_URL}/v1/rbac/approvers`);
      if (!res.ok) throw new Error('Failed to load approver list');
      return res.json();
    },
    async listAllUsers(): Promise<{ users: PlatformUser[] }> {
      const res = await authFetch(`${BASE_URL}/v1/admin/users`);
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || err.detail || 'Failed to load user directory');
      }
      return res.json();
    }
  },

  // ── Real pipeline promotion workflow (four-eyes enforced server-side) ──
  promotions: {
    async create(pipelineName: string, environment: 'staging' | 'production', versionRef: string, notes?: string): Promise<Promotion> {
      const res = await authFetch(`${BASE_URL}/v1/promotions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pipeline_name: pipelineName, environment, version_ref: versionRef, notes }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || err.detail || 'Failed to submit promotion');
      }
      return res.json();
    },
    async list(): Promise<{ promotions: Promotion[] }> {
      const res = await authFetch(`${BASE_URL}/v1/promotions`);
      if (!res.ok) throw new Error('Failed to load promotions');
      return res.json();
    },
    async decide(id: number, approve: boolean, decisionNotes?: string): Promise<Promotion> {
      const res = await authFetch(`${BASE_URL}/v1/promotions/${id}/decide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approve, decision_notes: decisionNotes }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || err.detail || 'Failed to record decision');
      }
      return res.json();
    }
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// DISTRIBUTED QUERY ENGINE (DQE) — Types & Client
// ─────────────────────────────────────────────────────────────────────────────

export type QueryMode = 'sql' | 'graph' | 'python';
export type QueryStatus = 'pending' | 'running' | 'success' | 'failed';

export interface DQEResult {
  columns: string[];
  rows: Record<string, any>[];
  total_rows: number;
  truncated: boolean;
  execution_plan?: string;
  engine_used?: string;
  duration_ms?: number;
}

export interface DQEJob {
  job_id: string;
  mode: QueryMode;
  status: QueryStatus;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  result?: DQEResult;
  error?: string;
}

export interface DQEHistoryEntry {
  job_id: string;
  mode: QueryMode;
  status: QueryStatus;
  created_at: string;
  completed_at?: string;
  total_rows?: number;
  error?: string;
}

export interface DQESubmitPayload {
  mode: QueryMode;
  // SQL
  namespace?: string;
  table_name?: string;
  sql?: string;
  // Graph
  cypher?: string;
  graph_name?: string;
  algorithm?: string;
  // Python
  python_script?: string;
  // Common
  filters?: Record<string, any>;
  limit?: number;
}

export interface DQEMultiPayload {
  queries: DQESubmitPayload[];
  merge_strategy?: 'union' | 'join_on_key';
  join_key?: string;
}

export interface DQEMultiResult {
  jobs: DQEJob[];
  merged_result?: DQEResult;
  merge_strategy: string;
}

export interface DQEModeInfo {
  mode: QueryMode;
  description: string;
  required_fields: string[];
  optional_fields?: string[];
  supported_algorithms?: string[];
  example_sql?: string;
  example_cypher?: string;
  example_script?: string;
}

/**
 * Distributed Query Engine client.
 * All methods require the user to be authenticated (Bearer token auto-attached).
 */
export const dqe = {

  /**
   * Submit a query job (SQL / Graph / Python) and wait for its result.
   * Returns the completed DQEJob including result rows.
   */
  async submit(payload: DQESubmitPayload): Promise<DQEJob> {
    const res = await authFetch(`${BASE_URL}/v1/query/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || err.error || 'DQE query failed');
    }
    return res.json();
  },

  /**
   * Poll the status and result of a previously submitted job.
   */
  async getJob(jobId: string): Promise<DQEJob> {
    const res = await authFetch(`${BASE_URL}/v1/query/${jobId}`);
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `Job ${jobId} not found`);
    }
    return res.json();
  },

  /**
   * Dry-run: get the execution plan for a query without running it.
   */
  async explain(payload: Omit<DQESubmitPayload, 'limit'>): Promise<{ mode: string; execution_plan: string }> {
    const res = await authFetch(`${BASE_URL}/v1/query/explain`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Explain failed');
    }
    return res.json();
  },

  /**
   * Return the current user's recent query history (newest first).
   */
  async history(limit: number = 20): Promise<DQEHistoryEntry[]> {
    const res = await authFetch(`${BASE_URL}/v1/query/history?limit=${limit}`);
    if (!res.ok) throw new Error('Failed to fetch query history');
    return res.json();
  },

  /**
   * Fan-out multiple queries across SQL/Graph/Python engines.
   * Results are union-merged if merge_strategy='union'.
   */
  async multi(payload: DQEMultiPayload): Promise<DQEMultiResult> {
    const res = await authFetch(`${BASE_URL}/v1/query/multi`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Multi-query failed');
    }
    return res.json();
  },

  /**
   * Return supported query modes, required fields, and examples.
   */
  async getModes(): Promise<{ modes: DQEModeInfo[] }> {
    const res = await authFetch(`${BASE_URL}/v1/query/modes`);
    if (!res.ok) throw new Error('Failed to fetch DQE modes');
    return res.json();
  },

  // ── Convenience helpers ──────────────────────────────────────────────────

  /** Quick SQL query against an Iceberg table. */
  async sql(namespace: string, tableName: string, sql: string, limit = 1000): Promise<DQEResult> {
    const job = await this.submit({ mode: 'sql', namespace, table_name: tableName, sql, limit });
    if (job.status === 'failed') throw new Error(job.error || 'SQL query failed');
    return job.result!;
  },

  /** Graph algorithm on the persistent graph store. */
  async graphAlgorithm(
    graphName: string,
    algorithm: string,
    filters?: Record<string, any>,
  ): Promise<DQEResult> {
    const job = await this.submit({ mode: 'graph', graph_name: graphName, algorithm, filters });
    if (job.status === 'failed') throw new Error(job.error || 'Graph algorithm failed');
    return job.result!;
  },

  /** Cypher-pattern match on the persistent graph store. */
  async graphCypher(graphName: string, cypher: string, limit = 500): Promise<DQEResult> {
    const job = await this.submit({ mode: 'graph', graph_name: graphName, cypher, limit });
    if (job.status === 'failed') throw new Error(job.error || 'Graph query failed');
    return job.result!;
  },

  /** Safe Python transformation against an Iceberg table. */
  async python(
    namespace: string,
    tableName: string,
    pythonScript: string,
    limit = 500,
  ): Promise<DQEResult> {
    const job = await this.submit({
      mode: 'python',
      namespace,
      table_name: tableName,
      python_script: pythonScript,
      limit,
    });
    if (job.status === 'failed') throw new Error(job.error || 'Python extraction failed');
    return job.result!;
  },
};

