// Render the one-pagers to PDF and validate them.
//   node docs/architecture/render.js [path/to/mermaid.min.js]
// Mermaid 11 is taken from the given path, or MERMAID_JS, or web/node_modules/mermaid (npm i -D mermaid@11.4.1).
// Checks, for each diagram in light and dark themes: Mermaid parses it, no label is wider than its box.
// Checks, for each one-pager: the PDF has exactly one page. Exits with an error if any check fails.
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const here = __dirname;
const lib = process.argv[2] || process.env.MERMAID_JS ||
  path.join(here, '..', '..', 'web', 'node_modules', 'mermaid', 'dist', 'mermaid.min.js');
const mermaidJs = fs.readFileSync(lib, 'utf8');
const diagrams = JSON.parse(fs.readFileSync(path.join(here, 'diagrams.json'), 'utf8'));


// Every label must fit: SVG text inside its node's shape, HTML labels (foreignObject) wide enough for their text.
// Text width is measured with a Range on the text itself, so a label cut by its box is caught.
function labelProblems(root) {
  const problems = [];
  root.querySelectorAll('g.node').forEach(n => {
    const shape = n.querySelector('rect, path, polygon');
    if (!shape) return;
    const a = shape.getBoundingClientRect();
    n.querySelectorAll('text').forEach(t => {
      const b = t.getBoundingClientRect();
      if (b.width && (b.left < a.left - 1 || b.right > a.right + 1)) problems.push('outside box: ' + t.textContent.slice(0, 40));
    });
  });
  root.querySelectorAll('foreignObject').forEach(f => {
    const text = f.textContent.trim();
    if (!text) return;
    const range = document.createRange();
    range.selectNodeContents(f);
    const need = range.getBoundingClientRect().width, have = f.getBoundingClientRect().width;
    if (need > have + 1) problems.push(`cut (${Math.round(need)} > ${Math.round(have)}): ` + text.slice(0, 40));
  });
  return problems;
}

async function checkDiagram(browser, name, src, dark) {
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, deviceScaleFactor: 2 });
  await page.setContent(`<html><body style="margin:0;padding:16px;background:${dark ? '#0d1117' : '#fff'};font-family: Inter, Helvetica, Arial, sans-serif;font-size:14px;line-height:normal"><div id="out"></div></body></html>`);
  await page.addScriptTag({ content: mermaidJs });
  await page.addScriptTag({ content: labelProblems.toString() });
  const r = await page.evaluate(async (src) => {
    mermaid.initialize({ startOnLoad: false });
    try { await mermaid.parse(src); } catch (e) { return { error: 'parse: ' + e.message }; }
    try { document.getElementById('out').innerHTML = (await mermaid.render('d', src)).svg; }
    catch (e) { return { error: 'render: ' + e.message }; }
    const overflow = labelProblems(document.getElementById('out'));
    return { overflow, nodes: document.querySelectorAll('#out g.node').length,
             svg: document.querySelector('#out svg').outerHTML };
  }, src);
  // the validated light render becomes the image shown on GitHub (GitHub's own Mermaid renderer can cut labels)
  if (!dark && !r.error) await (await page.$('#out svg')).screenshot({ path: path.join(here, `${name}-diagram.png`) });
  await page.close();
  return r;
}

(async () => {
  const browser = await chromium.launch();
  let ok = true;
  const svgs = {};
  for (const [name, src] of Object.entries(diagrams)) {
    for (const dark of [false, true]) {
      const r = await checkDiagram(browser, name, src, dark);
      const pass = !r.error && r.overflow.length === 0;
      ok = ok && pass;
      if (!dark && r.svg) svgs[name] = r.svg;
      delete r.svg;
      console.log(`${pass ? 'PASS' : 'FAIL'} diagram ${name} (${dark ? 'dark' : 'light'}): ${JSON.stringify(r)}`);
    }
  }
  for (const [file, out, name] of [['solution.html', 'WealthPilot_Solution_Architecture.pdf', 'solution'], ['aws.html', 'WealthPilot_AWS_Architecture.pdf', 'aws']]) {
    const page = await browser.newPage({ viewport: { width: 816, height: 1056 } });
    await page.goto('file://' + path.join(here, file));
    // all: initial cuts the page's inherited font settings, so the SVG renders exactly as where it was measured
    await page.evaluate(svg => {
      document.querySelector('.diagram').innerHTML = '<div style="all: initial; display: block; font-family: Inter, Helvetica, Arial, sans-serif; font-size: 14px">' + svg + '</div>';
    }, svgs[name]);
    await page.evaluate(() => document.fonts.ready);
    // the same overflow check, inside the one-pager itself
    await page.addScriptTag({ content: labelProblems.toString() });
    const clipped = await page.evaluate(() => labelProblems(document.querySelector('.diagram')));
    if (clipped.length) { ok = false; console.log(`FAIL ${out}: labels outside their box ${JSON.stringify(clipped)}`); }
    const pdf = await page.pdf({ path: path.join(here, out), format: 'Letter', printBackground: true, preferCSSPageSize: true });
    const pages = (pdf.toString('latin1').match(/\/Type\s*\/Page[^s]/g) || []).length;
    const pass = pages === 1;
    ok = ok && pass;
    console.log(`${pass ? 'PASS' : 'FAIL'} ${out}: ${pages} page(s)`);
    await page.close();
  }
  await browser.close();
  process.exit(ok ? 0 : 1);
})();
