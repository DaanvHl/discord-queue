const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');

const { STATUS } = require('../draft');

const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, '..', '..', 'data');

const FILES = {
	completed: path.join(DATA_DIR, 'completed.jsonl'),
	unfinished: path.join(DATA_DIR, 'unfinished.jsonl'),
};

function ensureDir() {
	if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
}

const result = (state, meta) => ({
	id: state.id,
	hostId: state.hostId,
	guestId: state.guestId,
	channelId: meta.channelId ?? null,
	createdAt: state.createdAt,
	finishedAt: Date.now(),
	setups: {
		host: state.picks.host.map(({ n, turret, hull, paint }) => ({ n, turret, hull, paint })),
		guest: state.picks.guest.map(({ n, turret, hull, paint }) => ({ n, turret, hull, paint })),
	},
});

const unfinishedRecord = (state, meta) => ({
	...state,
	...meta,
	finishedAt: Date.now(),
});

async function save(state, meta = {}) {
	ensureDir();

	const completed = state.status === STATUS.COMPLETED;
	const record = completed ? result(state, meta) : unfinishedRecord(state, meta);
	const file = completed ? FILES.completed : FILES.unfinished;

	await fsp.appendFile(file, `${JSON.stringify(record)}\n`, 'utf8');

	return record;
}

async function read(file) {
	ensureDir();
	if (!fs.existsSync(file)) return [];

	const content = await fsp.readFile(file, 'utf8');

	return content
		.split('\n')
		.filter(line => line.trim())
		.map(line => JSON.parse(line));
}

const completed = () => read(FILES.completed);
const unfinished = () => read(FILES.unfinished);

const mostRecent = (a, b) => b.finishedAt - a.finishedAt;

async function listByPlayer(userId, limit = 10) {
	const all = await completed();

	return all
		.filter(d => d.hostId === userId || d.guestId === userId)
		.sort(mostRecent)
		.slice(0, limit);
}

async function get(draftId) {
	const [done, dropped] = await Promise.all([completed(), unfinished()]);

	return [...done, ...dropped].find(d => d.id === draftId) ?? null;
}

module.exports = { save, completed, unfinished, listByPlayer, get };
