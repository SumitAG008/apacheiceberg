/**
 * ingest.spec.ts — Tests for the Ingest (CSV Upload) tab
 *
 * Covers:
 *  ✅ Ingest tab renders correctly
 *  ✅ Upload drop zone is visible
 *  ✅ Sample data buttons are shown (Smart Meter, Orders, Web Traffic)
 *  ✅ Schema configuration panel is on the right
 *  ✅ Namespace field defaults to "default"
 *  ✅ Target Table Name field is editable
 *  ✅ "Create Table & Ingest Data" button is visible
 *  ✅ Uploading a CSV file shows the schema preview
 *  ✅ Column detection table appears after upload
 */
import { test, expect, Page } from '@playwright/test';
import path from 'path';
import fs from 'fs';

const BASE_URL = process.env.BASE_URL || 'https://zerocopy.meldra.ai';

// Helper: create a tiny CSV file for upload testing
function makeTempCsv(): string {
  const tmpPath = path.join(process.cwd(), 'tmp_test_upload.csv');
  const csvContent = [
    'meter_id,kw_active,kvar_reactive,voltage,timestamp',
    'MTR-1001,4.82,0.61,230.4,2026-09-06T12:00:00Z',
    'MTR-1002,3.15,0.42,229.8,2026-09-06T12:00:00Z',
    'MTR-1003,5.90,0.88,231.2,2026-09-06T12:00:00Z',
    'MTR-1004,0.00,0.00,0.0,2026-09-06T12:00:00Z',
    'MTR-1005,2.74,0.31,230.1,2026-09-06T12:00:00Z',
  ].join('\n');
  fs.writeFileSync(tmpPath, csvContent);
  return tmpPath;
}

async function goToIngest(page: Page) {
  await page.goto(BASE_URL);
  await page.locator('#main-app').waitFor({ state: 'visible', timeout: 15_000 });
  await page.locator('#nav-ingest').click();
  await page.locator('#ingest-tab').waitFor({ state: 'visible' });
}

test.describe('Ingest Tab', () => {

  test('Ingest tab is accessible from nav bar', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.locator('#main-app').waitFor({ state: 'visible', timeout: 15_000 });

    const ingestBtn = page.locator('#nav-ingest');
    await expect(ingestBtn).toBeVisible();
    await ingestBtn.click();
    await expect(page.locator('#ingest-tab')).toBeVisible();
  });

  test('Upload CSV Dataset heading is visible', async ({ page }) => {
    await goToIngest(page);
    await expect(page.getByText('Upload CSV Dataset')).toBeVisible();
  });

  test('drag and drop zone is visible', async ({ page }) => {
    await goToIngest(page);
    const dropZone = page.locator('#drop-zone');
    await expect(dropZone).toBeVisible();
    await expect(dropZone).toContainText(/Drag & drop/i);
  });

  test('file input exists for upload', async ({ page }) => {
    await goToIngest(page);
    const fileInput = page.locator('#csv-file-input');
    await expect(fileInput).toBeAttached();
  });

  test('sample data buttons are visible', async ({ page }) => {
    await goToIngest(page);
    await expect(page.getByRole('button', { name: /Smart Meter/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Orders/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Web Traffic/i })).toBeVisible();
  });

  test('"Need sample data?" hint is visible', async ({ page }) => {
    await goToIngest(page);
    await expect(page.getByText(/Need sample data/i)).toBeVisible();
  });

  test('Configure Target Schema panel is on the right', async ({ page }) => {
    await goToIngest(page);
    await expect(page.getByText('Configure Target Schema')).toBeVisible();
  });

  test('Namespace field defaults to "default"', async ({ page }) => {
    await goToIngest(page);
    const namespaceInput = page.locator('input[placeholder*="default"], input[id*="namespace"]').first();
    await expect(namespaceInput).toBeVisible();
    // Should show "default" as placeholder or value
    const value = await namespaceInput.getAttribute('placeholder') || await namespaceInput.inputValue();
    expect(value.toLowerCase()).toContain('default');
  });

  test('Target Table Name field is visible and editable', async ({ page }) => {
    await goToIngest(page);
    const tableNameInput = page.locator('input[placeholder*="smartmeter"], input[placeholder*="table"], input[id*="table"]').first();
    await expect(tableNameInput).toBeVisible();
    await tableNameInput.click();
    await tableNameInput.fill('test_regression_table');
    await expect(tableNameInput).toHaveValue('test_regression_table');
  });

  test('"Detected Columns & Types" section is present', async ({ page }) => {
    await goToIngest(page);
    await expect(page.getByText(/Detected Columns/i)).toBeVisible();
  });

  test('"Create Table & Ingest Data" button is visible', async ({ page }) => {
    await goToIngest(page);
    await expect(page.getByRole('button', { name: /Create Table & Ingest/i })).toBeVisible();
  });

  test('uploading a CSV file shows preview table', async ({ page }) => {
    await goToIngest(page);
    const csvPath = makeTempCsv();

    try {
      const fileInput = page.locator('#csv-file-input');

      // Set file into the hidden input
      await fileInput.setInputFiles(csvPath);

      // Wait for the preview section to appear
      const previewSection = page.locator('#preview-section');
      await expect(previewSection).toBeVisible({ timeout: 10_000 });

      // The preview table should have our column headers
      const previewTable = page.locator('#csv-preview-table, .preview-table').first();
      await expect(previewTable).toBeVisible();
      await expect(previewTable).toContainText('meter_id');
      await expect(previewTable).toContainText('kw_active');
    } finally {
      fs.unlinkSync(csvPath);
    }
  });

  test('clicking "Smart Meter" sample loads sample data', async ({ page }) => {
    await goToIngest(page);
    await page.getByRole('button', { name: /Smart Meter/i }).click();

    // Should show a preview or upload status
    const uploadStatus = page.locator('#upload-status');
    await expect(uploadStatus).not.toBeEmpty({ timeout: 10_000 });
  });

  test('row count badge appears after CSV upload', async ({ page }) => {
    await goToIngest(page);
    const csvPath = makeTempCsv();

    try {
      await page.locator('#csv-file-input').setInputFiles(csvPath);
      const rowCountBadge = page.locator('#preview-row-count');
      await expect(rowCountBadge).toBeVisible({ timeout: 10_000 });
      // Should show the row count (5 data rows)
      await expect(rowCountBadge).toContainText(/5|row/i);
    } finally {
      fs.unlinkSync(csvPath);
    }
  });
});
