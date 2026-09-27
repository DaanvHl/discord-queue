const test = require('node:test');
const assert = require('node:assert');

const {
	ORDER,
	TOTAL_ACTIONS,
	SETUPS_PER_SIDE,
	createDraft,
	currentAction,
	applyAction,
	optionsFor,
	undo,
	cancel,
	list,
	STATUS,
	RULES,
} = require('../src/draft');

const HOST = 'user-host';
const GUEST = 'user-guest';

const newDraft = () => createDraft({ id: 'test', hostId: HOST, guestId: GUEST });

const userOfSide = (state, side) => (side === 'host' ? state.hostId : state.guestId);

function prng(seed) {
	let s = seed >>> 0;
	return () => {
		s = (s * 1664525 + 1013904223) >>> 0;
		return s / 0x100000000;
	};
}

function legalMove(state, pickIndex = () => 0) {
	const { side, action } = currentAction(state);
	const userId = userOfSide(state, side);
	const opts = optionsFor(state, action);

	if (action.type === 'ban') {
		assert.ok(opts.items.length > 0, `no legal ${action.target} ban`);
		return { userId, item: opts.items[pickIndex(opts.items.length)].id };
	}

	if (action.type === 'pick') {
		assert.ok(opts.turrets.length > 0, 'no legal turret');
		const turret = opts.turrets[pickIndex(opts.turrets.length)];
		const hulls = opts.hullsFor(turret.id);
		assert.ok(hulls.length > 0, `no legal hull for ${turret.id}`);
		return { userId, turret: turret.id, hull: hulls[pickIndex(hulls.length)].id };
	}

	assert.ok(opts.paints.length > 0, 'no legal paint');
	return { userId, paint: opts.paints[pickIndex(opts.paints.length)].id };
}

function playToTheEnd(state, pickIndex) {
	while (currentAction(state)) {
		const { state: next, error } = applyAction(state, legalMove(state, pickIndex));
		assert.equal(error, null, `legal move refused: ${error}`);
		state = next;
	}
	return state;
}

test('the order has 26 steps and 7 setups per side', () => {
	assert.equal(ORDER.length, 26);
	assert.equal(SETUPS_PER_SIDE, 7);
	assert.equal(ORDER.every((s, i) => s.step === i + 1), true);
});

test('the order consumes the expected bans of each category', () => {
	const count = { host: {}, guest: {} };

	for (const step of ORDER) {
		for (const a of step.actions) {
			if (a.type !== 'ban') continue;
			count[step.side][a.target] = (count[step.side][a.target] ?? 0) + 1;
		}
	}

	assert.deepEqual(count.host, { paint: 3, turret: 2, hull: 2 });
	assert.deepEqual(count.guest, { paint: 4, turret: 2, hull: 2 });
});

test('exactly 7 turrets and 3 hulls remain after every ban', () => {
	assert.equal(list('turret').length - 4, 7);
	assert.equal(list('hull').length - 4, 3);
});

test('a complete draft ends with 7 painted setups on each side', () => {
	const final = playToTheEnd(newDraft());

	assert.equal(final.status, STATUS.COMPLETED);
	assert.equal(final.history.length, TOTAL_ACTIONS);

	for (const side of ['host', 'guest']) {
		const setups = final.picks[side];
		assert.equal(setups.length, 7);
		assert.deepEqual(setups.map(s => s.n), [1, 2, 3, 4, 5, 6, 7]);
		assert.ok(setups.every(s => s.turret && s.hull && s.paint), `setup missing a field on ${side}`);
	}
});

test('no turret+hull pair repeats in the whole draft', () => {
	const final = playToTheEnd(newDraft());
	const pairs = [...final.picks.host, ...final.picks.guest].map(s => `${s.turret}|${s.hull}`);

	assert.equal(new Set(pairs).size, pairs.length);
});

test('the same paint can be used by both sides', () => {
	let state = newDraft();
	for (let i = 0; i < 4; i++) state = applyAction(state, legalMove(state)).state;

	state = applyAction(state, legalMove(state)).state; // Host pick 1
	const paint = optionsFor(state, currentAction(state).action).paints[0].id;
	state = applyAction(state, { userId: HOST, paint }).state;

	state = applyAction(state, legalMove(state)).state; // Guest pick 1
	const { state: after, error } = applyAction(state, { userId: GUEST, paint });

	assert.equal(error, null, `repeated paint was refused: ${error}`);
	assert.equal(after.picks.host[0].paint, paint);
	assert.equal(after.picks.guest[0].paint, paint);
});

test('no setup uses an item that was already banned when it was picked', () => {
	const final = playToTheEnd(newDraft());
	const banned = { hull: new Set(), turret: new Set(), paint: new Set() };

	for (const move of final.history) {
		if (move.type === 'ban') {
			banned[move.kind].add(move.item);
		} else if (move.type === 'pick') {
			assert.ok(!banned.turret.has(move.turret), `${move.turret} was already banned at step ${move.step}`);
			assert.ok(!banned.hull.has(move.hull), `${move.hull} was already banned at step ${move.step}`);
		} else {
			assert.ok(!banned.paint.has(move.paint), `${move.paint} was already banned at step ${move.step}`);
		}
	}
});

test('banning an already used item must stay allowed, or the format deadlocks', () => {
	assert.equal(RULES.banAlreadyUsedItem, true);
});

test('fuzz: 300 random drafts always reach the end with a legal move available', () => {
	for (let seed = 1; seed <= 300; seed++) {
		const rand = prng(seed);
		const pickIndex = n => Math.floor(rand() * n);

		const final = playToTheEnd(newDraft(), pickIndex);
		assert.equal(final.status, STATUS.COMPLETED, `seed ${seed} did not complete`);

		const pairs = [...final.picks.host, ...final.picks.guest].map(s => `${s.turret}|${s.hull}`);
		assert.equal(new Set(pairs).size, 14, `seed ${seed} repeated a pair`);
	}
});

test('whoever is not on turn is refused', () => {
	const state = newDraft();
	assert.equal(currentAction(state).side, 'host');

	const { error } = applyAction(state, { userId: GUEST, item: 'africa' });
	assert.match(error, /not your turn/i);
});

test('someone outside the draft is refused', () => {
	const state = newDraft();
	const { error } = applyAction(state, { userId: 'stranger', item: 'africa' });

	assert.match(error, /not part of this draft/i);
});

test('the turn does not switch inside a step with several actions', () => {
	let state = newDraft();
	while (currentAction(state) && currentAction(state).step.step < 16) {
		state = applyAction(state, legalMove(state)).state;
	}

	assert.equal(currentAction(state).side, 'host');
	assert.equal(currentAction(state).action.type, 'ban');

	state = applyAction(state, legalMove(state)).state;

	assert.equal(currentAction(state).step.step, 16);
	assert.equal(currentAction(state).side, 'host');
	assert.equal(state.actionIndex, 1);
});

test('the same item cannot be banned twice', () => {
	let state = newDraft();
	state = applyAction(state, { userId: HOST, item: 'africa' }).state;

	const { error } = applyAction(state, { userId: GUEST, item: 'africa' });
	assert.match(error, /already been banned/i);
});

test('a nonexistent item is refused', () => {
	const state = newDraft();
	const { error } = applyAction(state, { userId: HOST, item: 'does-not-exist' });

	assert.match(error, /is not a valid paint/i);
});

test('a turret may repeat between players, as long as the hull differs', () => {
	let state = newDraft();

	for (let i = 0; i < 4; i++) state = applyAction(state, legalMove(state)).state;

	const { action } = currentAction(state);
	assert.equal(action.type, 'pick');

	const turret = optionsFor(state, action).turrets[0];
	const hulls = optionsFor(state, action).hullsFor(turret.id);

	state = applyAction(state, { userId: HOST, turret: turret.id, hull: hulls[0].id }).state;
	state = applyAction(state, { userId: HOST, paint: optionsFor(state, currentAction(state).action).paints[0].id }).state;

	const repeated = applyAction(state, { userId: GUEST, turret: turret.id, hull: hulls[0].id });
	assert.match(repeated.error, /already used/i);

	const valid = applyAction(state, { userId: GUEST, turret: turret.id, hull: hulls[1].id });
	assert.equal(valid.error, null);
	assert.equal(valid.state.picks.guest[0].turret, turret.id);
});

test('the same player cannot repeat a paint across their own setups', () => {
	let state = newDraft();

	while (currentAction(state)) {
		const { side, action } = currentAction(state);
		if (side === 'host' && action.type === 'paint' && action.n === 2) break;
		state = applyAction(state, legalMove(state)).state;
	}

	const fromSetup1 = state.picks.host[0].paint;
	const { error } = applyAction(state, { userId: HOST, paint: fromSetup1 });

	assert.match(error, /already used/i);
});

test('each side closes the draft with 7 different paints', () => {
	const final = playToTheEnd(newDraft());

	for (const side of ['host', 'guest']) {
		const paints = final.picks[side].map(s => s.paint);
		assert.equal(new Set(paints).size, 7, `${side} repeated a paint`);
	}
});

test('an already used paint can still be banned', () => {
	let state = newDraft();
	while (currentAction(state) && currentAction(state).step.step < 11) {
		state = applyAction(state, legalMove(state)).state;
	}

	const alreadyUsed = state.picks.host[0].paint;
	assert.ok(alreadyUsed, 'expected the Host to have painted setup 1 already');

	const { action, side } = currentAction(state);
	assert.equal(action.type, 'ban');
	assert.equal(action.target, 'paint');
	assert.equal(side, 'guest');

	const { state: after, error } = applyAction(state, { userId: GUEST, item: alreadyUsed });

	assert.equal(error, null, `banning an already used paint was refused: ${error}`);
	assert.ok(after.bans.guest.some(b => b.kind === 'paint' && b.id === alreadyUsed));
});

test('a banned paint can no longer be chosen', () => {
	let state = newDraft();
	const banned = optionsFor(state, currentAction(state).action).items[0].id;

	state = applyAction(state, { userId: HOST, item: banned }).state;
	while (currentAction(state) && currentAction(state).action.type !== 'paint') {
		state = applyAction(state, legalMove(state)).state;
	}

	const { error } = applyAction(state, { userId: HOST, paint: banned });
	assert.match(error, /is banned/i);
});

test('undo reverts exactly one move and keeps the rest', () => {
	let state = newDraft();
	for (let i = 0; i < 8; i++) state = applyAction(state, legalMove(state)).state;

	const before = structuredClone(state);
	state = applyAction(state, legalMove(state)).state;

	const { state: undone, error } = undo(state);

	assert.equal(error, null);
	assert.equal(undone.history.length, before.history.length);
	assert.deepEqual(undone.history, before.history);
	assert.deepEqual(undone.picks, before.picks);
	assert.deepEqual(undone.bans, before.bans);
	assert.equal(undone.stepIndex, before.stepIndex);
	assert.equal(undone.actionIndex, before.actionIndex);
});

test('undo at the start of the draft says there is nothing to undo', () => {
	const { error } = undo(newDraft());
	assert.match(error, /no move to undo/i);
});

test('a cancelled draft accepts no more moves', () => {
	const state = cancel(newDraft());
	const { error } = applyAction(state, { userId: HOST, item: 'africa' });

	assert.match(error, /cancelled/i);
});

test('a completed draft accepts no more moves', () => {
	const final = playToTheEnd(newDraft());
	const { error } = applyAction(final, { userId: HOST, item: 'africa' });

	assert.match(error, /already ended/i);
});

test('applyAction does not mutate the state it receives', () => {
	const state = newDraft();
	const copy = structuredClone(state);

	applyAction(state, { userId: HOST, item: 'africa' });

	assert.deepEqual(state, copy);
});
