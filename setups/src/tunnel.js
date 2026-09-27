const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { pipeline } = require('node:stream/promises');
const { Readable } = require('node:stream');

const DIR = path.join(__dirname, '..', 'tools');

const BINARIES = {
	win32: { file: 'cloudflared.exe', asset: 'cloudflared-windows-amd64.exe' },
	linux: { file: 'cloudflared', asset: 'cloudflared-linux-amd64' },
};

const RELEASES = 'https://github.com/cloudflare/cloudflared/releases/latest/download';

const URL_PATTERN = /https:\/\/(?!api\.)[a-z0-9-]+\.trycloudflare\.com(?![\w./-])/;

const TIMEOUT_MS = 45_000;

function forThisPlatform() {
	const choice = BINARIES[process.platform];

	if (!choice) {
		throw new Error(
			`No tunnel binary for ${process.platform}. `
			+ 'Install cloudflared manually and leave it on the PATH.',
		);
	}

	return { ...choice, filePath: path.join(DIR, choice.file) };
}

async function ensureBinary() {
	const { filePath, asset } = forThisPlatform();

	if (fs.existsSync(filePath)) return filePath;

	console.log('Downloading cloudflared (one time only)…');

	const response = await fetch(`${RELEASES}/${asset}`);
	if (!response.ok) throw new Error(`Could not download cloudflared: HTTP ${response.status}`);

	await fsp.mkdir(DIR, { recursive: true });

	const partial = `${filePath}.partial`;
	await pipeline(Readable.fromWeb(response.body), fs.createWriteStream(partial));
	await fsp.rename(partial, filePath);

	if (process.platform !== 'win32') await fsp.chmod(filePath, 0o755);

	return filePath;
}

let child = null;

async function open({ port, timeoutMs = TIMEOUT_MS } = {}) {
	const binary = await ensureBinary();

	return new Promise((resolve, reject) => {
		child = spawn(binary, ['tunnel', '--url', `http://localhost:${port}`], {
			stdio: ['ignore', 'pipe', 'pipe'],
		});

		let resolved = false;
		let log = '';

		const timer = setTimeout(() => {
			if (resolved) return;

			close();
			reject(new Error(`The tunnel did not answer within ${timeoutMs / 1000}s.\n${log.slice(-500)}`));
		}, timeoutMs);

		const watch = chunk => {
			log += chunk;

			const found = log.match(URL_PATTERN);
			if (!found || resolved) return;

			resolved = true;
			clearTimeout(timer);
			resolve(found[0]);
		};

		child.stdout.setEncoding('utf8').on('data', watch);
		child.stderr.setEncoding('utf8').on('data', watch);

		child.on('error', error => {
			clearTimeout(timer);
			if (!resolved) reject(error);
		});

		child.on('exit', code => {
			child = null;

			if (!resolved) {
				clearTimeout(timer);
				return reject(new Error(`The tunnel exited before opening (code ${code}).\n${log.slice(-500)}`));
			}

			console.error('\nThe tunnel went down. Links already handed out stopped working — restart the bot.\n');
		});
	});
}

function close() {
	if (!child) return;

	child.kill();
	child = null;
}

function cleanupOnExit() {
	for (const signal of ['exit', 'SIGINT', 'SIGTERM', 'SIGHUP']) {
		process.once(signal, () => {
			close();
			if (signal !== 'exit') process.exit(0);
		});
	}
}

module.exports = { open, close, cleanupOnExit, URL_PATTERN, BINARIES, DIR };
