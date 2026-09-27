// Headless entrypoint: runs ONLY the pick & ban web server + API, with no Discord
// bot. Another bot (e.g. the Python queue bot) creates drafts over the API, and
// when a draft finishes the setups are POSTed back to CALLBACK_URL.
//
// The Discord version (index.js) is untouched — this is a separate way to run it.
require('dotenv').config();

const server = require('./src/server');
const flow = require('./src/flow');
const { getItem } = require('./src/draft');

const SECRET = process.env.SETUPS_SECRET || process.env.SECRET || '';
const CALLBACK_URL = process.env.CALLBACK_URL || '';

function nameOf(kind, id) {
	if (!id) return null;
	const item = getItem(kind, id);
	return item ? item.name : id;
}

function sideResult(state, side, name) {
	return {
		name,
		discordId: side === 'host' ? state.hostId : state.guestId,
		bans: state.bans[side].map(ban => ({ kind: ban.kind, name: nameOf(ban.kind, ban.id) })),
		setups: state.picks[side].map(setup => ({
			n: setup.n,
			turret: nameOf('turret', setup.turret),
			hull: nameOf('hull', setup.hull),
			paint: nameOf('paint', setup.paint),
		})),
	};
}

function payloadFor(session) {
	const { state } = session;

	return {
		draftId: state.id,
		meta: session.meta ?? null,
		host: sideResult(state, 'host', session.names.host),
		guest: sideResult(state, 'guest', session.names.guest),
	};
}

if (CALLBACK_URL) {
	flow.onCompletion(async session => {
		const response = await fetch(CALLBACK_URL, {
			method: 'POST',
			headers: { 'content-type': 'application/json', 'x-setups-secret': SECRET },
			body: JSON.stringify(payloadFor(session)),
		});

		if (!response.ok) {
			console.error(`Completion callback returned HTTP ${response.status}.`);
		}
	});
}

async function boot() {
	await server.start();

	// Collect drafts players abandon so they don't leak memory.
	flow.scheduleSweep();

	if (!SECRET) {
		console.warn('WARNING: no SETUPS_SECRET/SECRET set — the create API is disabled.');
	}
	if (!CALLBACK_URL) {
		console.warn('WARNING: no CALLBACK_URL set — finished setups will not be posted back.');
	}

	console.log('Setups headless service ready.');
}

boot().catch(error => {
	console.error(`\nCould not start the setups service: ${error.message}\n`);
	process.exit(1);
});
