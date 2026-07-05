import { defineConfig, devices } from '@playwright/test';

/**
 * Meldra AI — Playwright Configuration
 * Tests run against the live production URL: https://zerocopy.meldra.ai
 * 
 * Change BASE_URL env var to test against local dev:
 *   BASE_URL=http://localhost:5173 npx playwright test
 */
export default defineConfig({
  // Directory where test files live
  testDir: './tests',

  // Run tests in parallel
  fullyParallel: false, // Keep false — login state is shared

  // Fail the build on CI if any test.only left accidentally
  forbidOnly: !!process.env.CI,

  // Retry on CI, no retries locally
  retries: process.env.CI ? 2 : 0,

  // Parallel workers
  workers: process.env.CI ? 1 : 2,

  // Reporter
  reporter: [
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
    ['list'],
  ],

  use: {
    // Live production site by default
    baseURL: process.env.BASE_URL || 'https://zerocopy.meldra.ai',

    // Capture screenshot on failure
    screenshot: 'only-on-failure',

    // Record video on first retry
    video: 'on-first-retry',

    // Capture trace on first retry for debugging
    trace: 'on-first-retry',

    // Reasonable timeouts
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  projects: [
    // ── Setup: Login once, save auth state ─────────────────────────────────
    {
      name: 'setup',
      testMatch: /global\.setup\.ts/,
    },

    // ── Chromium (Primary) ──────────────────────────────────────────────────
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // Reuse saved auth cookies from setup
        storageState: 'playwright/.auth/user.json',
      },
      dependencies: ['setup'],
    },

    // ── Mobile Safari (Responsive check) ───────────────────────────────────
    {
      name: 'mobile-safari',
      use: {
        ...devices['iPhone 13'],
        storageState: 'playwright/.auth/user.json',
      },
      dependencies: ['setup'],
    },
  ],

  // Global test timeout
  timeout: 60_000,
});
