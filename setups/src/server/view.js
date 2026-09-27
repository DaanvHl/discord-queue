const {
	ORDER, currentAction, optionsFor, getItem, list, progress, STATUS, FOLDERS,
} = require('../draft');

const CATEGORIES = ['turret', 'hull', 'paint'];

const SIDE_LABEL = { host: 'Host', guest: 'Guest' };
const KIND_LABEL = { hull: 'hull', turret: 'turret', paint: 'paint' };

const VERB = {
	ban: 'Ban',
	turret: 'Pick the turret',
	hull: 'Pick the hull',
	paint: 'Pick the paint',
};

const urlOf = item => `/assets/${FOLDERS[item.kind]}/${encodeURIComponent(item.attachment)}`;

const forPage = item => ({
	id: item.id,
	kind: item.kind,
	name: item.name,
	img: urlOf(item),
});

function resolved(kind, id) {
	const item = getItem(kind, id);
	return item ? forPage(item) : { id, kind, name: id, img: null };
}

function choiceType(session) {
	const current = currentAction(session.state);
	if (!current) return null;

	if (current.action.type !== 'pick') return current.action.type;
	return session.pendingTurret ? 'hull' : 'turret';
}

function itemsForTurn(session) {
	const { state, pendingTurret } = session;
	const current = currentAction(state);
	if (!current) return [];

	const opts = optionsFor(state, current.action);

	if (current.action.type === 'ban') return opts.items;
	if (current.action.type === 'paint') return opts.paints;

	return pendingTurret ? opts.hullsFor(pendingTurret) : opts.turrets;
}

function categoryForTurn(session) {
	const current = currentAction(session.state);
	if (!current) return null;

	if (current.action.type === 'ban') return current.action.target;
	if (current.action.type === 'paint') return 'paint';

	return session.pendingTurret ? 'hull' : 'turret';
}

function bannedByCategory(state) {
	const map = Object.fromEntries(CATEGORIES.map(kind => [kind, new Set()]));

	for (const ban of [...state.bans.host, ...state.bans.guest]) map[ban.kind]?.add(ban.id);

	return map;
}

function grid(session, myTurn) {
	const banned = bannedByCategory(session.state);
	const activeCategory = myTurn ? categoryForTurn(session) : null;
	const playable = myTurn ? new Set(itemsForTurn(session).map(item => item.id)) : new Set();

	return Object.fromEntries(CATEGORIES.map(kind => [
		kind,
		list(kind).map(item => ({
			...forPage(item),
			playable: kind === activeCategory && playable.has(item.id),
			banned: banned[kind].has(item.id),
		})),
	]));
}

function describeChoice(session) {
	const current = currentAction(session.state);
	if (!current) return null;

	const type = choiceType(session);
	const { action } = current;

	if (action.type === 'ban') return `${VERB.ban} a ${KIND_LABEL[action.target]}`;
	if (action.type === 'paint') return `${VERB.paint} of setup ${action.n}`;

	return type === 'turret'
		? `${VERB.turret} of setup ${action.n}`
		: `${VERB.hull} of setup ${action.n}`;
}

function bansOfSide(state, side) {
	return state.bans[side].map(ban => resolved(ban.kind, ban.id));
}

function setupsOfSide(state, side) {
	return state.picks[side].map(setup => ({
		n: setup.n,
		turret: resolved('turret', setup.turret),
		hull: resolved('hull', setup.hull),
		paint: setup.paint ? resolved('paint', setup.paint) : null,
	}));
}

function history(state) {
	return state.history
		.map(move => {
			const who = SIDE_LABEL[move.side];

			if (move.type === 'ban') {
				return { step: move.step, side: move.side, text: `${who} banned ${resolved(move.kind, move.item).name}` };
			}

			if (move.type === 'pick') {
				const turret = resolved('turret', move.turret).name;
				const hull = resolved('hull', move.hull).name;
				return { step: move.step, side: move.side, text: `${who} built setup ${move.n}: ${turret} + ${hull}` };
			}

			return { step: move.step, side: move.side, text: `${who} painted setup ${move.n} with ${resolved('paint', move.paint).name}` };
		})
		.reverse();
}

function view(session, side) {
	const { state } = session;
	const current = currentAction(state);
	const { done, total } = progress(state);
	const myTurn = Boolean(current) && current.side === side;

	return {
		draftId: state.id,
		status: state.status,
		finished: state.status !== STATUS.IN_PROGRESS,
		me: side,
		turn: current?.side ?? null,
		myTurn,
		names: session.names,
		step: current ? { number: current.step.step, total: ORDER.length } : null,
		progress: { done, total },
		title: current
			? (myTurn ? `Your turn — ${describeChoice(session)}` : `${SIDE_LABEL[current.side]}'s turn`)
			: (state.status === STATUS.COMPLETED ? 'Draft completed' : 'Draft cancelled'),
		sides: {
			host: { bans: bansOfSide(state, 'host'), setups: setupsOfSide(state, 'host') },
			guest: { bans: bansOfSide(state, 'guest'), setups: setupsOfSide(state, 'guest') },
		},
		grid: grid(session, myTurn),
		choice: myTurn
			? {
				type: choiceType(session),
				category: categoryForTurn(session),
				title: describeChoice(session),
				pendingTurret: session.pendingTurret ? resolved('turret', session.pendingTurret) : null,
			}
			: null,
		history: history(state),
	};
}

module.exports = { view, choiceType, itemsForTurn };
