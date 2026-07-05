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

  // ── Audit trail logs ─────────────────────────────────────────────────
  async getAuditLogs(): Promise<AuditLog[]> {
    const res = await authFetch(`${BASE_URL}/v1/audit`);
    if (!res.ok) throw new Error('Failed to fetch audit logs');
    return res.json();
  },

  // ── MCP execution ────────────────────────────────────────────────────
  async executeMcpTool(serverName: string, toolName: string, argumentsObj: Record<string, any>): Promise<{ logs: string[]; result: any; duration_ms: number }> {
    const res = await authFetch(`${BASE_URL}/v1/mcp/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ server_name: serverName, tool_name: toolName, arguments: argumentsObj }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || err.detail || 'Failed to execute MCP tool call');
    }
    return res.json();
  },
};
