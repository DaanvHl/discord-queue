const { getItem, list } = require('./catalog');
const { ORDER } = require('./order');

const RULES = {
	uniqueTurretHullPair: true,
	paintUniquePerDraft: false,
	paintUniquePerPlayer: true,
	banAlreadyUsedItem: true,
};

const bannedIds = (state, kind) => new Set(
	[...state.bans.host, ...state.bans.guest]
		.filter(ban => ban.kind === kind)
		.map(ban => ban.id),
);

const allSetups = state => [...state.picks.host, ...state.picks.guest];

const pairKey = (turretId, hullId) => `${turretId}|${hullId}`;

const usedPairs = state => new Set(
	allSetups(state)
		.filter(setup => setup.turret && setup.hull)
		.map(setup => pairKey(setup.turret, setup.hull)),
);

const sideOnTurn = state => ORDER[state.stepIndex]?.side ?? null;

const usedPaints = (state, side) => new Set(
	(side ? state.picks[side] : allSetups(state))
		.map(setup => setup.paint)
		.filter(Boolean),
);

const usedItems = (state, kind) => new Set(
	allSetups(state).map(setup => setup[kind]).filter(Boolean),
);

function consumedForBan(state, kind) {
	if (kind === 'paint') {
		return RULES.paintUniquePerDraft ? usedPaints(state) : new Set();
	}

	return RULES.banAlreadyUsedItem ? new Set() : usedItems(state, kind);
}

function bannableItems(state, kind) {
	const banned = bannedIds(state, kind);
	const consumed = consumedForBan(state, kind);

	return list(kind).filter(item => !banned.has(item.id) && !consumed.has(item.id));
}

function pickableHulls(state, turretId) {
	const banned = bannedIds(state, 'hull');
	const pairs = usedPairs(state);

	return list('hull').filter(hull =>
		!banned.has(hull.id)
		&& !(RULES.uniqueTurretHullPair && pairs.has(pairKey(turretId, hull.id))));
}

function pickableTurrets(state) {
	const banned = bannedIds(state, 'turret');

	return list('turret').filter(turret =>
		!banned.has(turret.id) && pickableHulls(state, turret.id).length > 0);
}

function pickablePaints(state, side = sideOnTurn(state)) {
	const banned = bannedIds(state, 'paint');

	const used = new Set([
		...(RULES.paintUniquePerDraft ? usedPaints(state) : []),
		...(RULES.paintUniquePerPlayer && side ? usedPaints(state, side) : []),
	]);

	return list('paint').filter(paint => !banned.has(paint.id) && !used.has(paint.id));
}

function optionsFor(state, action) {
	switch (action.type) {
		case 'ban':
			return { kind: action.target, items: bannableItems(state, action.target) };
		case 'pick':
			return { turrets: pickableTurrets(state), hullsFor: id => pickableHulls(state, id) };
		case 'paint':
			return { paints: pickablePaints(state) };
		default:
			return {};
	}
}

const kindLabel = { hull: 'hull', turret: 'turret', paint: 'paint' };

function validateBan(state, action, input) {
	const kind = action.target;

	if (!input.item) return `Choose a ${kindLabel[kind]} to ban.`;
	if (!getItem(kind, input.item)) return `"${input.item}" is not a valid ${kindLabel[kind]}.`;

	if (bannedIds(state, kind).has(input.item)) {
		return `${getItem(kind, input.item).name} has already been banned.`;
	}

	if (consumedForBan(state, kind).has(input.item)) {
		return `${getItem(kind, input.item).name} is already used in a setup and cannot be banned.`;
	}

	return null;
}

function validatePick(state, action, input) {
	if (!input.turret || !input.hull) return 'Choose the turret and the hull.';

	const turret = getItem('turret', input.turret);
	const hull = getItem('hull', input.hull);

	if (!turret) return `"${input.turret}" is not a valid turret.`;
	if (!hull) return `"${input.hull}" is not a valid hull.`;

	if (bannedIds(state, 'turret').has(turret.id)) return `${turret.name} is banned.`;
	if (bannedIds(state, 'hull').has(hull.id)) return `${hull.name} is banned.`;

	if (RULES.uniqueTurretHullPair && usedPairs(state).has(pairKey(turret.id, hull.id))) {
		return `${turret.name} + ${hull.name} is already used in this draft. The turret may repeat, but with another hull.`;
	}

	return null;
}

function validatePaint(state, action, side, input) {
	if (!input.paint) return 'Choose a paint.';

	const paint = getItem('paint', input.paint);
	if (!paint) return `"${input.paint}" is not a valid paint.`;

	if (bannedIds(state, 'paint').has(paint.id)) return `${paint.name} is banned.`;

	if (RULES.paintUniquePerDraft && usedPaints(state).has(paint.id)) {
		return `${paint.name} is already used in this draft.`;
	}

	if (RULES.paintUniquePerPlayer && usedPaints(state, side).has(paint.id)) {
		return `You already used ${paint.name} in another setup of yours.`;
	}

	const setup = state.picks[side].find(s => s.n === action.n);
	if (!setup) return `Setup ${action.n} has not been picked yet.`;

	return null;
}

function validate(state, action, side, input) {
	switch (action.type) {
		case 'ban': return validateBan(state, action, input);
		case 'pick': return validatePick(state, action, input);
		case 'paint': return validatePaint(state, action, side, input);
		default: return `Unknown action: ${action.type}`;
	}
}

module.exports = {
	RULES,
	optionsFor,
	validate,
};
