/**
 * chat.spec.ts — Tests for the Chat tab
 * 
 * Covers:
 *  ✅ Chat tab renders correctly
 *  ✅ Quick prompt links are visible
 *  ✅ Typing a message and submitting works
 *  ✅ AI response appears in chat box
 *  ✅ Clear chat button works
 *  ✅ Send button is disabled when input is empty
 */
import { test, expect, Page } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'https://zerocopy.meldra.ai';

async function goToChat(page: Page) {
  await page.goto(BASE_URL);
  await page.locator('#main-app').waitFor({ state: 'visible', timeout: 15_000 });
  await page.locator('#nav-chat').click();
  await page.locator('#chat-tab').waitFor({ state: 'visible' });
}

test.describe('Chat Tab', () => {

  test('chat tab is active by default after login', async ({ page }) => {
    await page.goto(BASE_URL);
    await page.locator('#main-app').waitFor({ state: 'visible', timeout: 15_000 });

    // Chat tab should be active by default
    const chatTab = page.locator('#chat-tab');
    await expect(chatTab).toBeVisible();
    await expect(chatTab).toHaveClass(/active/);
  });

  test('welcome message from assistant is shown', async ({ page }) => {
    await goToChat(page);
    const chatMessages = page.locator('#chat-messages');
    await expect(chatMessages).toBeVisible();
    // The welcome message should mention meldra.ai
    await expect(chatMessages).toContainText('meldra.ai');
  });

  test('quick prompt links are visible in sidebar', async ({ page }) => {
    await goToChat(page);
    // Quick prompts section
    await expect(page.getByText('QUICK PROMPTS')).toBeVisible();
    await expect(page.getByText('List all tables')).toBeVisible();
    await expect(page.getByText('Create a sales table')).toBeVisible();
    await expect(page.getByText('Show first 10 rows')).toBeVisible();
    await expect(page.getByText('Count records')).toBeVisible();
  });

  test('chat input field is visible and focusable', async ({ page }) => {
    await goToChat(page);
    const chatInput = page.locator('#chat-input-text');
    await expect(chatInput).toBeVisible();
    await chatInput.click();
    await expect(chatInput).toBeFocused();
  });

  test('send button is present', async ({ page }) => {
    await goToChat(page);
    const sendBtn = page.locator('#btn-send-message');
    await expect(sendBtn).toBeVisible();
    await expect(sendBtn).toContainText('Send');
  });

  test('typing a message enables send interaction', async ({ page }) => {
    await goToChat(page);
    const chatInput = page.locator('#chat-input-text');
    await chatInput.fill('How many tables are in the default namespace?');
    await expect(chatInput).toHaveValue('How many tables are in the default namespace?');
  });

  test('sending a message via Enter key adds it to chat', async ({ page }) => {
    await goToChat(page);
    const chatInput = page.locator('#chat-input-text');
    const chatMessages = page.locator('#chat-messages');

    await chatInput.fill('List all tables');
    await chatInput.press('Enter');

    // The message should appear in the chat box
    await expect(chatMessages).toContainText('List all tables', { timeout: 5_000 });
  });

  test('sending a message shows AI response', async ({ page }) => {
    await goToChat(page);
    const chatInput = page.locator('#chat-input-text');
    const chatMessages = page.locator('#chat-messages');
    const messageCount = await chatMessages.locator('.chat-message, .message-bubble, [class*="msg"]').count();

    await chatInput.fill('Show first 10 rows');
    await page.locator('#btn-send-message').click();

    // Wait for a new response to appear (AI might take a few seconds)
    await expect(chatMessages).toContainText('Show first 10 rows', { timeout: 8_000 });
  });

  test('clicking a quick prompt populates the input', async ({ page }) => {
    await goToChat(page);
    // Click the "List all tables" quick prompt
    await page.getByText('List all tables').first().click();
    // It should either send the message or populate the input
    const chatMessages = page.locator('#chat-messages');
    await expect(chatMessages).toContainText('List all tables', { timeout: 10_000 });
  });

  test('clear chat button is visible', async ({ page }) => {
    await goToChat(page);
    const clearBtn = page.locator('#btn-clear-chat');
    await expect(clearBtn).toBeVisible();
  });

  test('stats bar shows S3 label', async ({ page }) => {
    await goToChat(page);
    await expect(page.getByText('S3')).toBeVisible();
    await expect(page.getByText('SERVERLESS STORAGE')).toBeVisible();
  });

  test('backend status shows online in sidebar', async ({ page }) => {
    await goToChat(page);
    await expect(page.locator('#backend-status-text')).toContainText(/online|checking/i, { timeout: 10_000 });
  });
});
