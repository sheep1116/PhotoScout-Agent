import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './tests', fullyParallel: false, workers: 1, timeout: 45_000,
  reporter: [['list'], ['json', {outputFile: 'test-results/report.json'}]],
  use: {baseURL: process.env.E2E_URL || 'http://127.0.0.1:3800', trace: 'retain-on-failure', screenshot: 'only-on-failure'},
  projects: [{name:'chromium',use:{...devices['Desktop Chrome']}}],
});
