// Copies .env.example → .env if .env doesn't already exist.
// Cross-platform replacement for `cp` / `copy`.
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const targets = [
  ["backend/.env.example", "backend/.env"],
  ["frontend/.env.example", "frontend/.env"],
];

for (const [src, dst] of targets) {
  const srcPath = path.join(root, src);
  const dstPath = path.join(root, dst);
  if (!fs.existsSync(srcPath)) {
    console.log(`! ${src} missing, skipping`);
    continue;
  }
  if (fs.existsSync(dstPath)) {
    console.log(`- ${dst} already exists`);
  } else {
    fs.copyFileSync(srcPath, dstPath);
    console.log(`+ created ${dst}`);
  }
}
