const test = require('node:test');
const assert = require('node:assert');

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'setups-archive-'));
process.env.DATA_DIR = DIR;

const archive = require('../src/store/archive');
const { createDraft, applyAction, currentAction, optionsFor, cancel, STATUS } = require('../src/draft');

test.after(() => fs.rmSync(DIR, { recursive: true, force: true }));

let n = 0;

const newDraft = () => {
	n += 1;
	return createDraft({ id: `a${n}`, hostId: `ah${n}`, guestId: `ag${n}` });
};

function complete(state) {
	while (currentAction(state)) {
		const { side, action } = currentAction(state);
		const userId = side === 'host' ? state.hostId : state.guestId;
		const opts = optionsFor(state, action);

		const move = { userId };

		if (action.type === 'ban') move.item = opts.items[0].id;
		else if (action.type === 'paint') move.paint = opts.paints[0].id;
		else {
			move.turret = opts.turrets[0].id;
			move.hull = opts.hullsFor(move.turret)[0].id;
		}

		const { state: next, error } = applyAction(state, move);
		assert.ok(!error, `stuck: ${error}`);
		state = next;
	}

	return state;
}

test('the completed one goes to a file, the unfinished one to another', async () => {
	const done = complete(newDraft());
	const dropped = cancel(newDraft());

	await archive.save(done, { channelId: 'c1' });
	await archive.save(dropped, { channelId: 'c2', reason: 'abandoned' });

	const completed = await archive.completed();
	const unfinished = await archive.unfinished();

	assert.deepEqual(completed.map(d => d.id), [done.id]);
	assert.deepEqual(unfinished.map(d => d.id), [dropped.id]);
});

test('the completed one keeps only the result', async () => {
	const done = complete(newDraft());
	const record = await archive.save(done, { channelId: 'c3' });

	assert.equal(record.setups.host.length, 7);
	assert.equal(record.setups.guest.length, 7);
	assert.deepEqual(
		Object.keys(record.setups.host[0]).sort(),
		['hull', 'n', 'paint', 'turret'],
	);

	for (const field of ['history', 'bans', 'picks', 'stepIndex', 'actionIndex', 'turnStartedAt', 'status']) {
		assert.equal(record[field], undefined, `the result still carries '${field}'`);
	}

	assert.equal(record.hostId, done.hostId);
	assert.equal(record.channelId, 'c3');
	assert.ok(record.finishedAt > 0);
});

test('the unfinished one keeps everything, so it is possible to see where it stopped', async () => {
	const state = newDraft();
	const { state: withOneBan } = applyAction(state, {
		userId: state.hostId,
		item: optionsFor(state, currentAction(state).action).items[0].id,
	});

	const record = await archive.save(cancel(withOneBan), { channelId: 'c4', reason: 'abandoned' });

	assert.equal(record.status, STATUS.CANCELLED);
	assert.equal(record.reason, 'abandoned');
	assert.equal(record.history.length, 1, 'without the history there is no telling where it stopped');
	assert.equal(record.bans.host.length, 1);
});

test('a player history is their results, newest first', async () => {
	const first = complete(newDraft());
	const second = complete(newDraft());

	second.guestId = first.hostId;

	await archive.save(first, {});
	await new Promise(ok => setTimeout(ok, 2));
	await archive.save(second, {});

	const list = await archive.listByPlayer(first.hostId);

	assert.deepEqual(list.map(d => d.id), [second.id, first.id]);
});

test('a dropped draft does not enter the player history', async () => {
	const dropped = cancel(newDraft());
	await archive.save(dropped, { reason: 'cancelled' });

	assert.deepEqual(await archive.listByPlayer(dropped.hostId), []);
});

test('looking up by id finds it in both files', async () => {
	const done = complete(newDraft());
	const dropped = cancel(newDraft());

	await archive.save(done, {});
	await archive.save(dropped, {});

	assert.equal((await archive.get(done.id)).id, done.id);
	assert.equal((await archive.get(dropped.id)).id, dropped.id);
	assert.equal(await archive.get('does-not-exist'), null);
});
