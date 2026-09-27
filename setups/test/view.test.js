const test = require('node:test');
const assert = require('node:assert');

const { createDraft, currentAction, applyAction, optionsFor, list, STATUS, TOTAL_ACTIONS } = require('../src/draft');
const { view, choiceType, itemsForTurn } = require('../src/server/view');

const sessionOf = (state, extras = {}) => ({
	id: state.id,
	channelId: 'c1',
	messageId: 'm1',
	state,
	pendingTurret: null,
	names: { host: 'Desert', guest: 'Lever' },
	tokens: { host: 'th', guest: 'tg' },
	...extras,
});

const newDraft = () => createDraft({ id: 'ab12cd34', hostId: '111', guestId: '222' });

const clickable = v => Object.values(v.grid).flat().filter(item => item.playable);

function legalMove(state) {
	const { side, action } = currentAction(state);
	const userId = side === 'host' ? state.hostId : state.guestId;
	const opts = optionsFor(state, action);

	if (action.type === 'ban') return { userId, item: opts.items[0].id };
	if (action.type === 'paint') return { userId, paint: opts.paints[0].id };

	const turret = opts.turrets[0];
	return { userId, turret: turret.id, hull: opts.hullsFor(turret.id)[0].id };
}

test('whoever is not on turn receives nothing clickable', () => {
	let state = newDraft();

	while (currentAction(state)) {
		const { side, step } = currentAction(state);
		const other = side === 'host' ? 'guest' : 'host';

		const onTurn = view(sessionOf(state), side);
		const offTurn = view(sessionOf(state), other);

		assert.ok(onTurn.choice, `step ${step.step}: the player on turn got no options`);
		assert.ok(clickable(onTurn).length > 0, `step ${step.step}: empty list`);

		assert.equal(offTurn.choice, null, `step ${step.step}: options leaked to the ${other}`);
		assert.equal(offTurn.myTurn, false);

		assert.ok(offTurn.grid.paint.length > 0, `step ${step.step}: the opponent got no catalog`);
		assert.deepEqual(clickable(offTurn), [], `step ${step.step}: a clickable item leaked to the ${other}`);

		state = applyAction(state, legalMove(state)).state;
	}
});

test('both sides see the same log', () => {
	let state = newDraft();
	for (let i = 0; i < 12; i++) state = applyAction(state, legalMove(state)).state;

	const host = view(sessionOf(state), 'host');
	const guest = view(sessionOf(state), 'guest');

	assert.deepEqual(host.sides, guest.sides, 'the log diverged between sides');
	assert.deepEqual(host.history, guest.history);
});

test('the offered list is exactly what the engine allows', () => {
	let state = newDraft();

	while (currentAction(state)) {
		const { side, action, step } = currentAction(state);
		const session = sessionOf(state);
		const opts = optionsFor(state, action);

		const expected = action.type === 'ban' ? opts.items
			: action.type === 'paint' ? opts.paints
				: opts.turrets;

		const v = view(session, side);

		assert.deepEqual(
			clickable(v).map(i => i.id),
			expected.map(i => i.id),
			`step ${step.step}: the page would offer something the engine does not accept`,
		);

		const category = action.type === 'ban' ? action.target
			: action.type === 'paint' ? 'paint' : 'turret';

		assert.equal(v.choice.category, category, `step ${step.step}: wrong category lit`);
		assert.ok(
			v.grid[category].some(i => i.playable),
			`step ${step.step}: the lit category has nothing clickable`,
		);

		state = applyAction(state, legalMove(state)).state;
	}
});

test('the grid carries the whole catalog on every step', () => {
	const v = view(sessionOf(newDraft()), 'host');

	assert.deepEqual(Object.keys(v.grid).sort(), ['hull', 'paint', 'turret']);

	for (const kind of ['turret', 'hull', 'paint']) {
		assert.deepEqual(
			v.grid[kind].map(i => i.id),
			list(kind).map(i => i.id),
			`the ${kind} grid is not the full catalog`,
		);
	}
});

test('a banned item shows up marked, and does not vanish from the grid', () => {
	let state = newDraft();

	const { action } = currentAction(state);
	const banned = optionsFor(state, action).items[0];

	state = applyAction(state, legalMove(state)).state;

	const inGrid = view(sessionOf(state), 'host').grid[banned.kind].find(i => i.id === banned.id);

	assert.ok(inGrid, 'the banned item vanished from the grid');
	assert.equal(inGrid.banned, true, 'the banned one came unmarked — it would look like one merely locked by the turn');
	assert.equal(inGrid.playable, false);
});

test('a pick becomes two clicks: turret and then hull', () => {
	let state = newDraft();
	while (currentAction(state).action.type !== 'pick') {
		state = applyAction(state, legalMove(state)).state;
	}

	const { side, action } = currentAction(state);
	const turret = optionsFor(state, action).turrets[0];

	const before = sessionOf(state);
	assert.equal(choiceType(before), 'turret');
	assert.match(view(before, side).choice.title, /turret/i);
	assert.equal(view(before, side).choice.pendingTurret, null);

	const after = sessionOf(state, { pendingTurret: turret.id });
	assert.equal(choiceType(after), 'hull');

	const v = view(after, side);
	assert.match(v.choice.title, /hull/i);
	assert.equal(v.choice.category, 'hull', 'the grid would stay lit on the turrets');
	assert.equal(v.choice.pendingTurret.id, turret.id, 'the page would forget which turret was chosen');
	assert.deepEqual(
		clickable(v).map(i => i.id),
		optionsFor(state, action).hullsFor(turret.id).map(i => i.id),
		'the offered hulls are not the ones compatible with the turret',
	);
});

test('every item comes with an art URL', () => {
	let state = newDraft();

	while (currentAction(state)) {
		const { side } = currentAction(state);

		for (const item of itemsForTurn(sessionOf(state))) {
			assert.ok(item.id, 'item without id');
		}

		for (const item of Object.values(view(sessionOf(state), side).grid).flat()) {
			assert.match(item.img, /^\/assets\/(hulls|turrets|paints)\/.+\.png$/, `odd URL: ${item.img}`);
		}

		state = applyAction(state, legalMove(state)).state;
	}
});

test('when it ends, the view stops offering a move', () => {
	let state = newDraft();
	let actions = 0;

	while (currentAction(state)) {
		state = applyAction(state, legalMove(state)).state;
		actions++;
	}

	assert.equal(actions, TOTAL_ACTIONS);
	assert.equal(state.status, STATUS.COMPLETED);

	for (const side of ['host', 'guest']) {
		const v = view(sessionOf(state), side);

		assert.equal(v.choice, null);
		assert.deepEqual(clickable(v), [], 'the draft ended and there was still something to click');
		assert.equal(v.finished, true);
		assert.match(v.title, /completed/i);
		assert.equal(v.sides[side].setups.length, 7, 'the final result lost setups');
	}
});

test('the history comes newest first', () => {
	let state = newDraft();
	for (let i = 0; i < 5; i++) state = applyAction(state, legalMove(state)).state;

	const { history } = view(sessionOf(state), 'host');

	assert.equal(history.length, 5);
	assert.deepEqual(history.map(l => l.step), [...history.map(l => l.step)].sort((a, b) => b - a));
	assert.match(history[0].text, /banned|built|painted/);
});
