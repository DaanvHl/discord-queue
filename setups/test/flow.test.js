const test = require('node:test');
const assert = require('node:assert');

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'setups-flow-'));
process.env.DATA_DIR = DIR;

const sessions = require('../src/store/sessions');
const flow = require('../src/flow');
const stream = require('../src/server/stream');
const { createDraft, currentAction, optionsFor, STATUS } = require('../src/draft');

let n = 0;

function newSession() {
	n += 1;

	const state = createDraft({ id: sessions.newId(), hostId: `fh-${n}`, guestId: `fg-${n}` });
	return sessions.create({ channelId: `fc-${n}`, state, names: { host: 'H', guest: 'G' } });
}

const firstItem = session => {
	const { action } = currentAction(session.state);
	const opts = optionsFor(session.state, action);

	return (action.type === 'ban' ? opts.items : action.type === 'paint' ? opts.paints : opts.turrets)[0].id;
};

const clearAll = () => sessions.all().forEach(s => sessions.remove(s.id));

test.beforeEach(clearAll);
test.after(() => {
	clearAll();
	fs.rmSync(DIR, { recursive: true, force: true });
});

test('a move in one draft does not touch the other', async () => {
	const a = newSession();
	const b = newSession();

	await flow.choose(a, 'host', firstItem(a));

	assert.equal(a.state.history.length, 1);
	assert.equal(b.state.history.length, 0, 'the move leaked into the other draft');
});

test('the same item can be played in different drafts', async () => {
	const a = newSession();
	const b = newSession();
	const item = firstItem(a);

	assert.equal((await flow.choose(a, 'host', item)).ok, true);
	assert.equal((await flow.choose(b, 'host', item)).ok, true);

	assert.equal(a.state.bans.host[0].id, item);
	assert.equal(b.state.bans.host[0].id, item);
});

test('playing marks activity, which protects from the sweep', async () => {
	const session = newSession();
	session.touchedAt = Date.now() - 60_000;

	await flow.choose(session, 'host', firstItem(session));

	assert.deepEqual(sessions.abandoned(30_000), [], 'an active draft would be collected');
});

test('the sweep collects only the abandoned one', async () => {
	const idle = newSession();
	const active = newSession();

	idle.touchedAt = Date.now() - 60_000;

	const count = await flow.sweepAbandoned({ ageMs: 30_000 });

	assert.equal(count, 1);
	assert.equal(sessions.get(idle.id), undefined, 'the abandoned one stayed in memory');
	assert.equal(sessions.get(active.id).id, active.id, 'the sweep took an active draft along');
});

test('whoever has the page open is told about the abandonment', async () => {
	const session = newSession();
	session.touchedAt = Date.now() - 60_000;

	const received = [];
	let closed = false;

	const fakeSocket = {
		send(text) { received.push(JSON.parse(text)); },
		close() { closed = true; },
		on() {},
	};

	stream.subscribe(session.id, 'host', fakeSocket);
	await flow.sweepAbandoned({ ageMs: 30_000 });

	const states = received.filter(r => r.type === 'state');
	assert.ok(states.length > 0, 'the page never received the final state');
	assert.equal(states.at(-1).view.status, 'cancelled', 'the last state does not say it ended');

	assert.ok(received.some(r => r.type === 'end'), 'the page was not told about the end');
	assert.ok(closed, 'the connection was not closed');
});

test('the abandoned one is finished and frees the players', async () => {
	const session = newSession();
	const { hostId, guestId } = session.state;
	session.touchedAt = Date.now() - 60_000;

	await flow.sweepAbandoned({ ageMs: 30_000 });

	assert.equal(session.state.status, STATUS.CANCELLED, 'it left memory without being finished');
	assert.deepEqual(sessions.busy(hostId, guestId), [], 'the players would stay stuck');
});

test('cancelling frees the player to start another right away', async () => {
	const session = newSession();
	const { hostId, guestId } = session.state;

	await flow.cancel(session);

	assert.equal(sessions.get(session.id), undefined);
	assert.deepEqual(sessions.busy(hostId, guestId), []);
});

test('the sweep does not complain when there is nothing to do', async () => {
	newSession();

	assert.equal(await flow.sweepAbandoned({ ageMs: 60_000 }), 0);
	assert.equal(sessions.size(), 1);
});
