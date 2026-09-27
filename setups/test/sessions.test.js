const test = require('node:test');
const assert = require('node:assert');

const sessions = require('../src/store/sessions');
const { createDraft } = require('../src/draft');

let n = 0;

function newSession(extras = {}) {
	n += 1;

	const state = createDraft({
		id: sessions.newId(),
		hostId: extras.hostId ?? `host-${n}`,
		guestId: extras.guestId ?? `guest-${n}`,
	});

	return sessions.create({ channelId: extras.channelId ?? `channel-${n}`, state });
}

const clearAll = () => sessions.all().forEach(s => sessions.remove(s.id));

test.beforeEach(clearAll);
test.after(clearAll);

test('several drafts coexist, even in the same channel', () => {
	const a = newSession({ channelId: 'same-channel' });
	const b = newSession({ channelId: 'same-channel' });
	const c = newSession({ channelId: 'other-channel' });

	assert.equal(sessions.size(), 3);

	for (const s of [a, b, c]) assert.equal(sessions.get(s.id).id, s.id);

	assert.equal(sessions.ofPlayer(a.state.hostId).id, a.id);
	assert.equal(sessions.ofPlayer(b.state.hostId).id, b.id);
});

test('the same player does not join two drafts', () => {
	const first = newSession();

	assert.throws(
		() => newSession({ hostId: first.state.hostId }),
		/already a draft/i,
		'let the same player into two drafts — /draft cancel would be ambiguous',
	);

	assert.throws(() => newSession({ guestId: first.state.hostId }), /already a draft/i);

	assert.equal(sessions.size(), 1, 'the refused attempt left garbage behind');
});

test('ending a draft frees both players', () => {
	const session = newSession();
	const { hostId, guestId } = session.state;

	assert.deepEqual(sessions.busy(hostId, guestId), [hostId, guestId]);

	sessions.remove(session.id);

	assert.deepEqual(sessions.busy(hostId, guestId), []);
	assert.equal(sessions.ofPlayer(hostId), undefined);

	assert.doesNotThrow(() => newSession({ hostId, guestId }));
});

test('a token does not outlive the draft', () => {
	const session = newSession();
	const token = session.tokens.host;

	assert.equal(sessions.byToken(token).side, 'host');

	sessions.remove(session.id);

	assert.equal(sessions.byToken(token), null, 'the link would keep opening after the end');
});

test('each draft has tokens of its own', () => {
	const drafts = [newSession(), newSession(), newSession()];
	const every = drafts.flatMap(s => Object.values(s.tokens));

	assert.equal(new Set(every).size, 6, 'token repeated across drafts');

	for (const session of drafts) {
		assert.equal(sessions.byToken(session.tokens.host).session.id, session.id);
		assert.equal(sessions.byToken(session.tokens.guest).session.id, session.id);
	}
});

test('the cap on simultaneous drafts is enforced', () => {
	for (let i = 0; i < sessions.LIMIT; i++) newSession();

	assert.equal(sessions.size(), sessions.LIMIT);
	assert.throws(() => newSession(), /limit of \d+ simultaneous drafts/i);
});

test('abandoned means nobody touched it', () => {
	const idle = newSession();
	const active = newSession();

	idle.touchedAt = Date.now() - 60_000;

	const stale = sessions.abandoned(30_000).map(s => s.id);

	assert.deepEqual(stale, [idle.id]);
	assert.ok(!stale.includes(active.id));

	sessions.touch(idle.id);
	assert.deepEqual(sessions.abandoned(30_000), []);
});
