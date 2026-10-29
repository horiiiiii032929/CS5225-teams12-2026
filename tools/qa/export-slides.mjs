import { chromium } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, resolve } from 'node:path';

const destination = resolve(
  process.argv[2] ?? '.qa-artifacts/flatsplit-initial-deck.pdf',
);
mkdirSync(dirname(destination), { recursive: true });
// Serve only the deck and its redacted image over loopback. Managed Chromium
// may disallow file://; do not disable browser policy or expose the checkout.
const assets = new Map([
  ['/presentation/index.html', ['docs/presentation/index.html', 'text/html']],
  [
    '/demo/evidence/local-synthetic/results-mobile.png',
    ['docs/demo/evidence/local-synthetic/results-mobile.png', 'image/png'],
  ],
]);
const server = createServer(async (request, response) => {
  const asset = assets.get(new URL(request.url, 'http://127.0.0.1').pathname);
  if (!asset) {
    response.writeHead(404);
    response.end();
    return;
  }
  try {
    const body = await readFile(resolve(asset[0]));
    response.writeHead(200, { 'Content-Type': asset[1] });
    response.end(body);
  } catch {
    response.writeHead(404);
    response.end();
  }
});
await new Promise((done) => server.listen(0, '127.0.0.1', done));
let browser;
try {
  browser = await chromium.launch({
    headless: true,
    ...(process.env.QA_CHROMIUM_PATH
      ? { executablePath: process.env.QA_CHROMIUM_PATH }
      : {}),
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 810 },
  });
  await page.goto(
    `http://127.0.0.1:${server.address().port}/presentation/index.html`,
  );
  const missingImages = await page
    .locator('img')
    .evaluateAll((images) =>
      images.some((image) => !image.complete || !image.naturalWidth),
    );
  if (missingImages)
    throw new Error(
      'A slide image is missing; run the documented capture handoff first.',
    );
  await page.pdf({
    path: destination,
    preferCSSPageSize: true,
    printBackground: true,
  });
  console.log(`Initial draft PDF written to ${destination}`);
} finally {
  await browser?.close();
  await new Promise((done) => server.close(done));
}
