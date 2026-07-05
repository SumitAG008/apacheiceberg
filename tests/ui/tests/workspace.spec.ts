/**
 * workspace.spec.ts — Tests for the Workspace & Integration Hub tab
 *
 * Covers:
 *  ✅ Workspace tab renders correctly
 *  ✅ "Workspace & Integration Hub" heading is shown
 *  ✅ Active Workspace Details card shows S3 / AWS Region
 *  ✅ Metadata Catalog AWS Glue badge is visible
 *  ✅ Demo mode status badge appears
 *  ✅ Snowflake & Databricks Interoperability section present
 *  ✅ Databricks Guide and Snowflake Guide buttons are clickable
 *  ✅ SparkConf code block is displayed
 *  ✅ AWS config form appears when toggle is enabled
 *  ✅ Connect S3 toggle is in sidebar
 */
import { test, expect, Page } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'https://zerocopy.meldra.ai';

async function goToWorkspace(page: Page) {
  await page.goto(BASE_URL);
  await page.locator('#main-app').waitFor({ state: 'visible', timeout: 15_000 });
  await page.locator('#nav-workspace').click();
  await page.locator('#workspace-tab').waitFor({ state: 'visible' });
}

test.describe('Workspace & Integration Hub Tab', () => {

  test('Workspace tab is accessible from nav bar', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.locator('#main-app').waitFor({ state: 'visible', timeout: 15_000 });

    const workspaceBtn = page.locator('#nav-workspace');
    await expect(workspaceBtn).toBeVisible();
    await workspaceBtn.click();
    await expect(page.locator('#workspace-tab')).toBeVisible();
  });

  test('"Workspace & Integration Hub" heading is visible', async ({ page }) => {
    await goToWorkspace(page);
    await expect(page.getByText('Workspace & Integration Hub')).toBeVisible();
  });

  test('subtitle about S3, Glue, Databricks is present', async ({ page }) => {
    await goToWorkspace(page);
    await expect(page.getByText(/S3 Data Lake/i)).toBeVisible();
  });

  test('"ACTIVE WORKSPACE DETAILS" section is shown', async ({ page }) => {
    await goToWorkspace(page);
    await expect(page.getByText(/ACTIVE WORKSPACE DETAILS/i)).toBeVisible();
  });

  test('S3 Warehouse label is visible', async ({ page }) => {
    await goToWorkspace(page);
    await expect(page.getByText(/S3 Warehouse/i)).toBeVisible();
  });

  test('AWS Region is displayed', async ({ page }) => {
    await goToWorkspace(page);
    await expect(page.getByText(/AWS Region/i)).toBeVisible();
  });

  test('Metadata Catalog with AWS Glue badge is visible', async ({ page }) => {
    await goToWorkspace(page);
    await expect(page.getByText(/Metadata Catalog/i)).toBeVisible();
    await expect(page.getByText(/AWS GLUE/i)).toBeVisible();
  });

  test('DEMO MODE status badge is shown', async ({ page }) => {
    await goToWorkspace(page);
    await expect(page.getByText(/DEMO MODE/i)).toBeVisible();
  });

  test('Snowflake & Databricks interoperability section is present', async ({ page }) => {
    await goToWorkspace(page);
    await expect(page.getByText(/SNOWFLAKE.*DATABRICKS INTEROPERABILITY/i)).toBeVisible();
  });

  test('Databricks Guide button is visible and clickable', async ({ page }) => {
    await goToWorkspace(page);
    const databricksBtn = page.getByRole('button', { name: /Databricks Guide/i });
    await expect(databricksBtn).toBeVisible();
    await databricksBtn.click();
    // After click, some content or modal should change — at minimum no crash
    await expect(page.locator('#workspace-tab')).toBeVisible();
  });

  test('Snowflake Guide button is visible', async ({ page }) => {
    await goToWorkspace(page);
    const snowflakeBtn = page.getByRole('button', { name: /Snowflake Guide/i });
    await expect(snowflakeBtn).toBeVisible();
  });

  test('SparkConf code block is displayed', async ({ page }) => {
    await goToWorkspace(page);
    // Should show the Spark configuration code
    await expect(page.getByText(/spark.sql.catalog/i)).toBeVisible();
  });

  test('SparkConf shows org.apache.iceberg reference', async ({ page }) => {
    await goToWorkspace(page);
    await expect(page.getByText(/org.apache.iceberg/i)).toBeVisible();
  });

  test('"Connect your S3 lake" toggle is in sidebar', async ({ page }) => {
    await goToWorkspace(page);
    await expect(page.getByText(/Connect your S3 lake/i)).toBeVisible();
  });

  test('AWS config form appears when custom AWS toggle is enabled', async ({ page }) => {
    await goToWorkspace(page);
    // Enable custom AWS toggle
    const awsToggle = page.locator('#custom-aws-toggle');
    await expect(awsToggle).toBeAttached();
    await awsToggle.check();

    // AWS config form should now be visible
    const awsForm = page.locator('#aws-config-form');
    await expect(awsForm).toBeVisible({ timeout: 3_000 });
    await expect(page.locator('#aws-region')).toBeVisible();
    await expect(page.locator('#aws-s3-uri')).toBeVisible();
    await expect(page.locator('#btn-connect-aws')).toBeVisible();
  });

  test('SELECT query example is shown below SparkConf', async ({ page }) => {
    await goToWorkspace(page);
    await expect(page.getByText(/SELECT \* FROM/i)).toBeVisible();
  });
});
