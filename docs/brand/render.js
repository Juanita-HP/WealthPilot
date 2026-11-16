// Export the logo SVGs to PNG (2x) with the Inter font, and a one-page preview of all versions.
//   node docs/brand/render.js
const path = require('path');
const fs = require('fs');
const { chromium } = require('playwright');

(async () => {
  const here = __dirname;
  const b = await chromium.launch();
  for (const [svg, w, h] of [['wealthpilot-logo.svg', 1040, 320], ['wealthpilot-logo-dark.svg', 1040, 320], ['wealthpilot-icon.svg', 512, 512]]) {
    const p = await b.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 2 });
    await p.setContent(`<html><body style="margin:0;background:transparent">${fs.readFileSync(path.join(here, svg), 'utf8')}</body></html>`);
    await p.evaluate(() => document.fonts.ready);
    await p.screenshot({ path: path.join(here, svg.replace('.svg', '.png')), omitBackground: true, clip: { x: 0, y: 0, width: w, height: h } });
    await p.close();
  }
  await b.close();
})();
