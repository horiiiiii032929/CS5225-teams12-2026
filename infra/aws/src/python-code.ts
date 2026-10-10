import { createHash } from 'node:crypto';
import {
  cpSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative } from 'node:path';
import { spawnSync } from 'node:child_process';
import { AssetHashType, DockerImage } from 'aws-cdk-lib';
import { Code, Runtime } from 'aws-cdk-lib/aws-lambda';
import { repoRoot } from './paths.js';

const serviceDir = join(repoRoot, 'services', 'api');
const packageDir = join(serviceDir, 'src', 'flatsplit_api');

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true })
    .filter((entry) => entry.name !== '__pycache__')
    .flatMap((entry) =>
      entry.isDirectory()
        ? sourceFiles(join(dir, entry.name))
        : [join(dir, entry.name)],
    )
    .sort();
}

// Hash the lockfile and package source so dependency bumps also produce a new asset.
function assetHash(): string {
  const hash = createHash('sha256');
  for (const file of [join(repoRoot, 'uv.lock'), ...sourceFiles(packageDir)]) {
    hash.update(relative(repoRoot, file));
    hash.update(readFileSync(file));
  }
  return hash.digest('hex');
}

function run(command: string, args: string[]): void {
  const result = spawnSync(command, args, { cwd: repoRoot, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(
      `${command} ${args.join(' ')} exited with ${result.status}`,
    );
  }
}

/**
 * Lambda code for every Python handler: locked runtime dependencies built for
 * arm64 Linux by uv, plus the flatsplit_api package. No Docker is needed.
 */
export function pythonApiCode(): Code {
  return Code.fromAsset(serviceDir, {
    assetHashType: AssetHashType.CUSTOM,
    assetHash: assetHash(),
    bundling: {
      image: DockerImage.fromRegistry('unused-local-bundling-only'),
      local: {
        tryBundle(outputDir) {
          const scratch = mkdtempSync(join(tmpdir(), 'flatsplit-lambda-'));
          const requirements = join(scratch, 'requirements.txt');
          try {
            run('uv', [
              'export',
              '--quiet',
              '--package',
              'flatsplit-api',
              '--frozen',
              '--no-dev',
              '--no-hashes',
              '--no-header',
              '--no-emit-workspace',
              '--output-file',
              requirements,
            ]);
            run('uv', [
              'pip',
              'install',
              '--quiet',
              '--target',
              outputDir,
              '--python-platform',
              'aarch64-manylinux2014',
              '--python-version',
              Runtime.PYTHON_3_13.name.replace('python', ''),
              '--only-binary',
              ':all:',
              '--requirement',
              requirements,
            ]);
          } finally {
            rmSync(scratch, { recursive: true, force: true });
          }
          cpSync(packageDir, join(outputDir, 'flatsplit_api'), {
            recursive: true,
            filter: (source) => !source.includes('__pycache__'),
          });
          return true;
        },
      },
    },
  });
}
