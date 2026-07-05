/**
 * global.setup.ts
 * ───────────────
 * Runs ONCE before all tests. Logs in with real credentials and saves
 * browser cookies + localStorage to `playwright/.auth/user.json`.
 * All subsequent tests reuse this session — no re-login needed.
 *
 * Set credentials via environment variables:
 *   TEST_EMAIL=sumit@meldra.ai TEST_PASSWORD=YourPass npx playwright test
 */
import { test as setup, expect } from '@playwright/test';
import path from 'path';
import fs from 'fs';

const AUTH_FILE = path.join('playwright', '.auth', 'user.json');
const BASE_URL = process.env.BASE_URL || 'https://zerocopy.meldra.ai';
const TEST_EMAIL = process.env.TEST_EMAIL || 'sumit@meldra.ai';
const TEST_PASSWORD = process.env.TEST_PASSWORD || '';

setup('authenticate and save session', async ({ page }) => {
  if (!TEST_PASSWORD) {
    throw new Error(
      'Set TEST_PASSWORD env var before running UI tests.\n' +
      'Example: $env:TEST_PASSWORD="YourPassword"; npx playwright test'
    );
  }

  await page.goto(BASE_URL);

  // ── Wait for the auth overlay to appear ────────────────────────────────────
  const authOverlay = page.locator('#auth-overlay');
  await authOverlay.waitFor({ state: 'visible', timeout: 15_000 });

  // ── Fill login form ────────────────────────────────────────────────────────
  await page.locator('#login-email').fill(TEST_EMAIL);
  await page.locator('#login-password').fill(TEST_PASSWORD);
  await page.locator('#btn-login').click();

  // ── Handle MFA OTP screen ──────────────────────────────────────────────────
  const mfaScreen = page.locator('#auth-screen-mfa');
  await mfaScreen.waitFor({ state: 'visible', timeout: 10_000 });
  console.log('\n⚠️  MFA screen appeared. Check your email for the OTP code.');
  console.log('   Enter it manually in the browser window that opened, then press Enter here...');

  // Give enough time for the user to receive and enter the OTP
  // In CI, use a shared test account with OTP intercepted via the API mock
  await page.locator('#auth-screen-mfa').waitFor({ state: 'hidden', timeout: 120_000 });

  // ── Confirm the main app is now visible ───────────────────────────────────
  await expect(page.locator('#main-app')).toBeVisible({ timeout: 10_000 });
  console.log('✅ Login successful — session saved.');

  // ── Save auth state ────────────────────────────────────────────────────────
  fs.mkdirSync(path.dirname(AUTH_FILE), { recursive: true });
  await page.context().storageState({ path: AUTH_FILE });
});
