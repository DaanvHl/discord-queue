const { randomUUID, randomBytes } = require('node:crypto');

const byId = new Map();
const byPlayer = new Map();
const byTokenIndex = new Map();

const LIMIT = Number(process.env.MAX_DRAFTS) || 100;

const newId = () => randomUUID().slice(0, 8);

const newToken = () => randomBytes(24).toString('base64url');

const ofPlayer = userId => byId.get(byPlayer.get(userId));

const busy = (...userIds) => userIds.filter(id => byPlayer.has(id));

function create({ channelId, state, names = {} }) {
	if (byId.size >= LIMIT) {
		throw new Error(`Reached the limit of ${LIMIT} simultaneous drafts. End one before starting another.`);
	}

	const alreadyPlaying = busy(state.hostId, state.guestId);
	if (alreadyPlaying.length > 0) {
		throw new Error(`There is already a draft running for ${alreadyPlaying.join(' and ')}.`);
	}

	const session = {
		id: state.id,
		channelId,
		messageId: null,
		state,
		pendingTurret: null,
		names: { host: names.host ?? 'Host', guest: names.guest ?? 'Guest' },
		tokens: { host: newToken(), guest: newToken() },
		touchedAt: Date.now(),
	};

	byId.set(session.id, session);
	byPlayer.set(state.hostId, session.id);
	byPlayer.set(state.guestId, session.id);

	for (const side of ['host', 'guest']) {
		byTokenIndex.set(session.tokens[side], { draftId: session.id, side });
	}

	return session;
}

const get = draftId => byId.get(draftId);

function byToken(token) {
	const owner = token && byTokenIndex.get(token);
	if (!owner) return null;

	const session = byId.get(owner.draftId);
	if (!session) return null;

	return { session, side: owner.side };
}

function touch(draftId) {
	const session = byId.get(draftId);
	if (session) session.touchedAt = Date.now();

	return session;
}

function update(draftId, patch) {
	const session = byId.get(draftId);
	if (!session) return null;

	Object.assign(session, patch);
	return session;
}

function remove(draftId) {
	const session = byId.get(draftId);
	if (!session) return false;

	byId.delete(draftId);

	byPlayer.delete(session.state.hostId);
	byPlayer.delete(session.state.guestId);
	for (const token of Object.values(session.tokens)) byTokenIndex.delete(token);

	return true;
}

const abandoned = ms => [...byId.values()].filter(s => Date.now() - s.touchedAt > ms);

const all = () => [...byId.values()];

const size = () => byId.size;

module.exports = {
	LIMIT,
	newId,
	create,
	get,
	ofPlayer,
	busy,
	byToken,
	touch,
	update,
	remove,
	abandoned,
	all,
	size,
};
