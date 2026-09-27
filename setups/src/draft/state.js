const { ORDER, TOTAL_ACTIONS } = require('./order');
const rules = require('./rules');

const STATUS = {
	IN_PROGRESS: 'in_progress',
	COMPLETED: 'completed',
	CANCELLED: 'cancelled',
};

function createDraft({ id, hostId, guestId, now = Date.now() }) {
	return {
		id,
		hostId,
		guestId,
		createdAt: now,
		stepIndex: 0,
		actionIndex: 0,
		turnStartedAt: now,
		bans: { host: [], guest: [] },
		picks: { host: [], guest: [] },
		status: STATUS.IN_PROGRESS,
		history: [],
	};
}

function currentAction(state) {
	if (state.status !== STATUS.IN_PROGRESS) return null;

	const step = ORDER[state.stepIndex];
	if (!step) return null;

	const action = step.actions[state.actionIndex];
	if (!action) return null;

	return { step, side: step.side, action };
}

function sideOf(state, userId) {
	if (userId === state.hostId) return 'host';
	if (userId === state.guestId) return 'guest';
	return null;
}

const userIdOf = (state, side) => (side === 'host' ? state.hostId : state.guestId);

const progress = state => ({
	done: state.history.length,
	total: TOTAL_ACTIONS,
});

function advance(state, now) {
	const step = ORDER[state.stepIndex];

	const sameStep = state.actionIndex + 1 < step.actions.length;
	const stepIndex = sameStep ? state.stepIndex : state.stepIndex + 1;
	const actionIndex = sameStep ? state.actionIndex + 1 : 0;

	const over = stepIndex >= ORDER.length;

	return {
		...state,
		stepIndex: over ? ORDER.length : stepIndex,
		actionIndex: over ? 0 : actionIndex,
		status: over ? STATUS.COMPLETED : state.status,
		turnStartedAt: sameStep ? state.turnStartedAt : now,
	};
}

function commit(state, { side, action }, input, now) {
	const next = structuredClone(state);

	switch (action.type) {
		case 'ban':
			next.bans[side].push({ kind: action.target, id: input.item, at: now });
			break;

		case 'pick':
			next.picks[side].push({
				n: action.n,
				turret: input.turret,
				hull: input.hull,
				paint: null,
			});
			break;

		case 'paint': {
			const setup = next.picks[side].find(s => s.n === action.n);
			setup.paint = input.paint;
			break;
		}
	}

	next.history.push({
		side,
		userId: userIdOf(state, side),
		step: ORDER[state.stepIndex].step,
		type: action.type,
		...(action.type === 'ban' && { kind: action.target, item: input.item }),
		...(action.type === 'pick' && { n: action.n, turret: input.turret, hull: input.hull }),
		...(action.type === 'paint' && { n: action.n, paint: input.paint }),
		at: now,
	});

	return advance(next, now);
}

function applyAction(state, input, now = Date.now()) {
	const current = currentAction(state);

	if (!current) {
		const reason = state.status === STATUS.COMPLETED ? 'has already ended' : 'was cancelled';
		return { state, error: `This draft ${reason}.` };
	}

	const side = sideOf(state, input.userId);
	if (!side) return { state, error: 'You are not part of this draft.' };

	if (side !== current.side) {
		return { state, error: `It is not your turn — the ${current.side === 'host' ? 'Host' : 'Guest'} plays now.` };
	}

	const error = rules.validate(state, current.action, side, input);
	if (error) return { state, error };

	return { state: commit(state, current, input, now), error: null };
}

function cancel(state, now = Date.now()) {
	return { ...state, status: STATUS.CANCELLED, cancelledAt: now };
}

function undo(state) {
	if (state.history.length === 0) return { state, error: 'There is no move to undo.' };

	const previous = state.history.slice(0, -1);
	const base = createDraft({
		id: state.id,
		hostId: state.hostId,
		guestId: state.guestId,
		now: state.createdAt,
	});

	const rebuilt = previous.reduce((acc, move) => {
		const { state: next, error } = applyAction(acc, {
			userId: move.userId,
			item: move.item,
			turret: move.turret,
			hull: move.hull,
			paint: move.paint,
		}, move.at);

		if (error) throw new Error(`Replay failed at step ${move.step}: ${error}`);

		return next;
	}, base);

	return { state: rebuilt, error: null };
}

module.exports = {
	STATUS,
	createDraft,
	currentAction,
	sideOf,
	progress,
	applyAction,
	cancel,
	undo,
};
