// Export the logo SVGs to PNG (logos at 8x, icon at 2x of 512).
//   node docs/brand/render.js
const path = require('path');
const fs = require('fs');
const { chromium } = require('playwright');

(async () => {
  const here = __dirname;
  const b = await chromium.launch();
  for (const [svg, scale] of [['wealthpilot-logo.svg', 8], ['wealthpilot-logo-dark.svg', 8], ['wealthpilot-icon.svg', 2]]) {
    const src = fs.readFileSync(path.join(here, svg), 'utf8');
    const [w, h] = [/width="([\d.]+)"/, /height="([\d.]+)"/].map(r => Math.ceil(parseFloat(src.match(r)[1])));
    const p = await b.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: scale });
    await p.setContent(`<html><body style="margin:0;background:transparent">${src}</body></html>`);
    await p.screenshot({ path: path.join(here, svg.replace('.svg', '.png')), omitBackground: true, clip: { x: 0, y: 0, width: w, height: h } });
    await p.close();
  }
  await b.close();
})();
