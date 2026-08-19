import { readFileSync, writeFileSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
import { markdownToHwpx } from 'kordoc';

const [markdownPath, outputPath, preset, ...imageNames] = process.argv.slice(2);
if (!markdownPath || !outputPath || !preset) {
  console.error('usage: node kordoc_bridge.mjs <markdown> <output> <preset> [image ...]');
  process.exit(2);
}

const markdown = readFileSync(markdownPath, 'utf8');
const baseDir = dirname(markdownPath);
const images = {};
for (const imageName of imageNames) {
  const safeName = basename(imageName);
  images[safeName] = new Uint8Array(readFileSync(join(baseDir, safeName)));
}

const output = await markdownToHwpx(markdown, {
  gongmun: { preset },
  images,
});
writeFileSync(outputPath, Buffer.from(output));
