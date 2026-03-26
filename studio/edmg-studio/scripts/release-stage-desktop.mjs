import { defaultStageDir, stageDesktopRelease } from "./release-stage-lib.mjs";

const STAGE_DIR = defaultStageDir();

async function main() {
  const staged = await stageDesktopRelease({ outDir: STAGE_DIR, clean: true });
  process.stdout.write(JSON.stringify(staged, null, 2) + "\n");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
