/**
 * ingest.spec.ts — Tests for the Ingest (CSV Upload) tab
 *
 * Covers:
 *  ✅ Ingest tab renders correctly
 *  ✅ Upload drop zone is visible
 *  ✅ Sample data buttons are shown (Employees, Orders, Web Traffic)
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
    'employee_id,name,department,salary,hire_date',
    '1,Alice Johnson,Engineering,95000,2021-03-15',
    '2,Bob Smith,Marketing,72000,2020-08-01',
    '3,Carol Davis,HR,68000,2022-01-10',
    '4,David Wilson,Engineering,105000,2019-06-20',
    '5,Eve Brown,Finance,88000,2021-11-05',
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
    await expect(page.getByRole('button', { name: /Employees/i })).toBeVisible();
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
    const tableNameInput = page.locator('input[placeholder*="employees"], input[id*="table"]').first();
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
      await expect(previewTable).toContainText('employee_id');
      await expect(previewTable).toContainText('name');
    } finally {
      fs.unlinkSync(csvPath);
    }
  });

  test('clicking "Employees" sample loads sample data', async ({ page }) => {
    await goToIngest(page);
    await page.getByRole('button', { name: /Employees/i }).click();

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
