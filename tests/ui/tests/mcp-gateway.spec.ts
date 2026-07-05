/**
 * mcp-gateway.spec.ts — Tests for the MCP Gateway tab
 *
 * Covers:
 *  ✅ MCP tab navigates correctly
 *  ✅ MCP Registry list shows active servers
 *  ✅ Iceberg Catalog server is shown with correct port (8001)
 *  ✅ Clicking a server shows its tools in the right panel
 *  ✅ Tool dropdown shows available tools
 *  ✅ Arguments textarea is editable
 *  ✅ Execute button is visible and clickable
 *  ✅ Execution result panel appears after execution
 *  ✅ Active server count badge is shown
 */
import { test, expect, Page } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'https://zerocopy.meldra.ai';

async function goToMCP(page: Page) {
  await page.goto(BASE_URL);
  await page.locator('#main-app').waitFor({ state: 'visible', timeout: 15_000 });
  await page.locator('#nav-mcp').click();
  await page.locator('#mcp-tab').waitFor({ state: 'visible' });
}

test.describe('MCP Gateway Tab', () => {

  test('MCP tab is accessible from nav bar', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.locator('#main-app').waitFor({ state: 'visible', timeout: 15_000 });

    const mcpNavBtn = page.locator('#nav-mcp');
    await expect(mcpNavBtn).toBeVisible();
    await mcpNavBtn.click();
    await expect(page.locator('#mcp-tab')).toBeVisible();
  });

  test('MCP Registry heading is visible', async ({ page }) => {
    await goToMCP(page);
    await expect(page.getByText('MCP Registry')).toBeVisible();
  });

  test('active server count badge is shown', async ({ page }) => {
    await goToMCP(page);
    // The badge shows "8 ACTIVE" or similar
    const badge = page.locator('.badge, [class*="active"]').filter({ hasText: /ACTIVE/i });
    await expect(badge.first()).toBeVisible();
  });

  test('Iceberg Catalog server is listed with PORT 8001', async ({ page }) => {
    await goToMCP(page);
    await expect(page.getByText('Iceberg Catalog')).toBeVisible();
    await expect(page.getByText('PORT 8001')).toBeVisible();
  });

  test('SAP BAPI & RFC server is listed', async ({ page }) => {
    await goToMCP(page);
    await expect(page.getByText('SAP BAPI & RFC')).toBeVisible();
  });

  test('Snowflake Zero-Copy server is listed', async ({ page }) => {
    await goToMCP(page);
    await expect(page.getByText('Snowflake Zero-Copy')).toBeVisible();
  });

  test('Real-Time Audit Trail server is listed', async ({ page }) => {
    await goToMCP(page);
    await expect(page.getByText('Real-Time Audit Trail')).toBeVisible();
  });

  test('clicking a server loads it in the right panel', async ({ page }) => {
    await goToMCP(page);
    // Click on the Iceberg Catalog server card
    await page.getByText('Iceberg Catalog').first().click();

    // Right panel should show the server details
    await expect(page.locator('#mcp-selected-server-name')).toContainText(/Iceberg/i, { timeout: 5_000 });
    await expect(page.locator('#mcp-selected-server-desc')).toBeVisible();
  });

  test('tool dropdown is populated after server selection', async ({ page }) => {
    await goToMCP(page);
    await page.getByText('Iceberg Catalog').first().click();

    const toolSelect = page.locator('#mcp-tool-select');
    await expect(toolSelect).toBeVisible();

    // Should have at least one option
    const options = toolSelect.locator('option');
    await expect(options).toHaveCount({ min: 1 });
  });

  test('list_iceberg_tables tool is available', async ({ page }) => {
    await goToMCP(page);
    await page.getByText('Iceberg Catalog').first().click();

    const toolSelect = page.locator('#mcp-tool-select');
    await expect(toolSelect).toBeVisible();
    // Check the dropdown contains list_iceberg_tables
    await expect(toolSelect).toContainText('list_iceberg_tables');
  });

  test('arguments textarea is editable', async ({ page }) => {
    await goToMCP(page);
    await page.getByText('Iceberg Catalog').first().click();

    const argsTextarea = page.locator('#mcp-tool-arguments');
    await expect(argsTextarea).toBeVisible();
    await argsTextarea.click();
    await argsTextarea.fill('{\n  "namespace": "default"\n}');
    await expect(argsTextarea).toHaveValue(/namespace.*default/s);
  });

  test('Execute Tool Call button is present', async ({ page }) => {
    await goToMCP(page);
    await page.getByText('Iceberg Catalog').first().click();

    const executeBtn = page.locator('#btn-execute-mcp-tool');
    await expect(executeBtn).toBeVisible();
    await expect(executeBtn).toContainText(/Execute/i);
  });

  test('execution console output panel is present', async ({ page }) => {
    await goToMCP(page);
    await page.getByText('Iceberg Catalog').first().click();

    await expect(page.locator('#mcp-execution-logs')).toBeVisible();
    await expect(page.getByText('EXECUTION CONSOLE OUTPUT')).toBeVisible();
  });

  test('returned value panel is present', async ({ page }) => {
    await goToMCP(page);
    await page.getByText('Iceberg Catalog').first().click();

    await expect(page.locator('#mcp-execution-result')).toBeVisible();
    await expect(page.getByText('RETURNED VALUE (JSON)')).toBeVisible();
  });

  test('executing a tool call populates result panel', async ({ page }) => {
    await goToMCP(page);
    await page.getByText('Iceberg Catalog').first().click();

    // Set up arguments
    const argsTextarea = page.locator('#mcp-tool-arguments');
    await argsTextarea.fill('{\n  "namespace": "default"\n}');

    // Execute
    await page.locator('#btn-execute-mcp-tool').click();

    // Wait for result to appear (backend call might take a moment)
    const resultPanel = page.locator('#mcp-execution-result');
    await expect(resultPanel).not.toBeEmpty({ timeout: 15_000 });
  });
});
