import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../../', import.meta.url));

export default defineConfig({
  testDir: '.',
  testMatch: 'journey.spec.ts',
  timeout: 120_000,
  workers: 1,
  reporter: 'list',
  outputDir: '../../.qa-artifacts/playwright',
  use: {
    baseURL: 'http://127.0.0.1:5180',
    headless: true,
    launchOptions: process.env.QA_CHROMIUM_PATH
      ? { executablePath: process.env.QA_CHROMIUM_PATH }
      : {},
    trace: 'off',
    video: 'off',
    screenshot: 'off',
  },
  webServer: [
    {
      cwd: root,
      command:
        'uv run --package flatsplit-api --extra local python tools/qa/local_stack.py',
      url: 'http://127.0.0.1:8010/health',
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      cwd: root,
      command:
        'pnpm --filter @flatsplit/web exec vite --config ../../tools/qa/vite.config.mts',
      url: 'http://127.0.0.1:5180',
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
