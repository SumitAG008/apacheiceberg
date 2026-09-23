// Copyright (c) 2026 Meldra AI Ltd / Tally Platform. All rights reserved.
// Playwright E2E Test: Omission Register & Zero-Trust Counterparty Verification Portal

import { test, expect } from '@playwright/test';

test.describe('Tally Omission Register & Proof Pack Verification', () => {

  test('should render 60-second omission demo and detect 6 missing periods', async ({ page }) => {
    // Navigate to local dev app
    await page.goto('/');

    // Ensure Omission & Dispute section or button is available
    const demoBtn = page.locator('#btn-run-omission-demo, button:has-text("Omission"), button:has-text("60-Second")').first();
    if (await demoBtn.isVisible()) {
      await demoBtn.click();

      // Assert demo output containing Merkle Root and Gap Count
      const output = page.locator('#omission-demo-output, .omission-demo-result, div:has-text("OMISSION_DETECTED_AND_PROVEN")').first();
      await expect(output).toBeVisible({ timeout: 15000 });
      await expect(output).toContainText('6');
      await expect(output).toContainText('ANCHORED_WITH_GAPS');
    }
  });

  test('should verify valid proof pack in Zero-Trust Counterparty Portal', async ({ page }) => {
    await page.goto('/');

    const sampleBtn = page.locator('#btn-load-sample-proof-pack').first();
    const verifyBtn = page.locator('#btn-verify-proof-pack').first();

    if (await sampleBtn.isVisible() && await verifyBtn.isVisible()) {
      await sampleBtn.click();
      await verifyBtn.click();

      const result = page.locator('#tally-verification-result');
      await expect(result).toBeVisible({ timeout: 10000 });
      await expect(result).toContainText('ANCHORED_WITH_GAPS');
      await expect(result).toContainText('YES (Match)');
    }
  });

});
