const fs = require('node:fs');
const path = require('node:path');

const FILE = path.join(__dirname, '..', 'data', 'bot.lock');

function processAlive(pid) {
	try {
		process.kill(pid, 0);
		return true;
	} catch (error) {
		return error.code === 'EPERM';
	}
}

function read(file) {
	try {
		return JSON.parse(fs.readFileSync(file, 'utf8'));
	} catch {
		return null;
	}
}

function acquire({ file = FILE, pid = process.pid, alive = processAlive } = {}) {
	const owner = read(file);

	if (owner && owner.pid !== pid && alive(owner.pid)) {
		const error = new Error(
			`A bot is already running (PID ${owner.pid}, since ${new Date(owner.startedAt).toLocaleString('en-US')}).\n`
			+ 'Two instances sharing a token fight over the same interaction and break the draft.\n'
			+ `Stop the other one first, or delete ${file} if you are sure it is gone.`,
		);
		error.code = 'BOT_ALREADY_RUNNING';
		error.pid = owner.pid;
		throw error;
	}

	fs.mkdirSync(path.dirname(file), { recursive: true });
	fs.writeFileSync(file, JSON.stringify({ pid, startedAt: Date.now() }), 'utf8');

	return () => release({ file, pid });
}

function release({ file = FILE, pid = process.pid } = {}) {
	const owner = read(file);
	if (!owner || owner.pid !== pid) return false;

	try {
		fs.unlinkSync(file);
		return true;
	} catch {
		return false;
	}
}

function protect() {
	const drop = acquire();

	process.once('exit', () => release());
	for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
		process.once(signal, () => {
			release();
			process.exit(0);
		});
	}

	return drop;
}

module.exports = { acquire, release, protect, processAlive };
