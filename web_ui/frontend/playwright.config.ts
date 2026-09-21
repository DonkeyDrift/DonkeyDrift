import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://localhost:5188',
    locale: 'zh-CN',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5188',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
