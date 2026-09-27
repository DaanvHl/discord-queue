const ban = target => ({ type: 'ban', target });
const pick = n => ({ type: 'pick', n });
const paint = n => ({ type: 'paint', n });

const pickWithPaint = n => [pick(n), paint(n)];

const ORDER = [
	{ step: 1, side: 'host', actions: [ban('paint')] },
	{ step: 2, side: 'guest', actions: [ban('paint')] },
	{ step: 3, side: 'guest', actions: [ban('turret')] },
	{ step: 4, side: 'host', actions: [ban('turret')] },
	{ step: 5, side: 'host', actions: pickWithPaint(1) },
	{ step: 6, side: 'guest', actions: pickWithPaint(1) },
	{ step: 7, side: 'guest', actions: pickWithPaint(2) },
	{ step: 8, side: 'host', actions: pickWithPaint(2) },
	{ step: 9, side: 'guest', actions: [ban('hull')] },
	{ step: 10, side: 'host', actions: [ban('hull')] },
	{ step: 11, side: 'guest', actions: [ban('paint')] },
	{ step: 12, side: 'guest', actions: pickWithPaint(3) },
	{ step: 13, side: 'host', actions: pickWithPaint(3) },
	{ step: 14, side: 'host', actions: pickWithPaint(4) },
	{ step: 15, side: 'guest', actions: pickWithPaint(4) },
	{ step: 16, side: 'host', actions: [ban('paint'), ban('hull')] },
	{ step: 17, side: 'guest', actions: [ban('paint'), ban('turret'), ban('hull')] },
	{ step: 18, side: 'host', actions: [ban('turret')] },
	{ step: 19, side: 'host', actions: pickWithPaint(5) },
	{ step: 20, side: 'guest', actions: pickWithPaint(5) },
	{ step: 21, side: 'guest', actions: [ban('paint')] },
	{ step: 22, side: 'host', actions: [ban('paint')] },
	{ step: 23, side: 'guest', actions: pickWithPaint(6) },
	{ step: 24, side: 'host', actions: pickWithPaint(6) },
	{ step: 25, side: 'host', actions: pickWithPaint(7) },
	{ step: 26, side: 'guest', actions: pickWithPaint(7) },
];

const TOTAL_ACTIONS = ORDER.reduce((sum, step) => sum + step.actions.length, 0);

const SETUPS_PER_SIDE = Math.max(
	...ORDER.flatMap(s => s.actions.filter(a => a.type === 'pick').map(a => a.n)),
);

module.exports = { ORDER, TOTAL_ACTIONS, SETUPS_PER_SIDE };
