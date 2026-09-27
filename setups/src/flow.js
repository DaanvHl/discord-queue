const { applyAction, currentAction, undo: undoMove, cancel: cancelDraft, STATUS } = require('./draft');
const sessions = require('./store/sessions');
const archive = require('./store/archive');
const board = require('./discord/board');
const stream = require('./server/stream');
const { view, choiceType, itemsForTurn } = require('./server/view');

let client = null;

const useClient = c => { client = c; };

// Optional hook fired once, when a draft reaches COMPLETED (not on cancel/abandon).
// The headless service registers this to POST the finished setups to the bot.
let onComplete = null;

const onCompletion = cb => { onComplete = cb; };

const userIdOf = (state, side) => (side === 'host' ? state.hostId : state.guestId);

async function updateChannel(session) {
	if (!client || !session.messageId) return;

	const channel = await client.channels.fetch(session.channelId).catch(() => null);
	const message = await channel?.messages.fetch(session.messageId).catch(() => null);

	await message?.edit(board.board(session)).catch(() => {});
}

async function notify(session) {
	sessions.touch(session.id);

	stream.publish(session.id, side => view(session, side));
	await updateChannel(session);
}

async function finish(session, reason) {
	const record = await archive.save(session.state, { channelId: session.channelId, reason });

	if (reason === STATUS.COMPLETED && onComplete) {
		try {
			await onComplete(session, record);
		} catch (error) {
			console.error('Completion hook failed:', error.message);
		}
	}

	stream.close(session.id);
	sessions.remove(session.id);
}

async function choose(session, side, itemId) {
	const current = currentAction(session.state);
	if (!current) return { error: 'This draft has already ended.' };
	if (current.side !== side) return { error: 'It is not your turn.' };

	const offered = itemsForTurn(session);
	if (!offered.some(item => item.id === itemId)) {
		return { error: 'That option is not available on this move.' };
	}

	const type = choiceType(session);

	if (type === 'turret') {
		session.pendingTurret = itemId;
		await notify(session);

		return { ok: true };
	}

	const move = { userId: userIdOf(session.state, side) };

	if (type === 'ban') move.item = itemId;
	else if (type === 'paint') move.paint = itemId;
	else Object.assign(move, { turret: session.pendingTurret, hull: itemId });

	const { state, error } = applyAction(session.state, move);
	if (error) return { error };

	session.state = state;
	session.pendingTurret = null;

	await notify(session);
	if (state.status === STATUS.COMPLETED) await finish(session, STATUS.COMPLETED);

	return { ok: true };
}

async function undo(session) {
	const { state, error } = undoMove(session.state);
	if (error) return { error };

	const undone = session.state.history.at(-1);

	session.state = state;
	session.pendingTurret = null;

	await notify(session);

	return { ok: true, undone };
}

async function cancel(session) {
	session.state = cancelDraft(session.state);
	session.pendingTurret = null;

	await notify(session);
	await finish(session, STATUS.CANCELLED);

	return { ok: true };
}

const MAX_AGE_MS = Number(process.env.DRAFT_TTL_MS) || 2 * 60 * 60 * 1000;

const SWEEP_INTERVAL_MS = 10 * 60 * 1000;

async function sweepAbandoned({ ageMs = MAX_AGE_MS } = {}) {
	const stale = sessions.abandoned(ageMs);

	for (const session of stale) {
		session.state = cancelDraft(session.state);

		await notify(session).catch(() => {});
		await finish(session, 'abandoned');
	}

	return stale.length;
}

function scheduleSweep({ intervalMs = SWEEP_INTERVAL_MS, ageMs = MAX_AGE_MS } = {}) {
	const timer = setInterval(() => {
		sweepAbandoned({ ageMs })
			.then(count => { if (count > 0) console.log(`${count} abandoned draft(s) collected.`); })
			.catch(error => console.error('Failed to collect abandoned drafts:', error.message));
	}, intervalMs);

	timer.unref?.();

	return () => clearInterval(timer);
}

module.exports = {
	useClient,
	onCompletion,
	choose,
	undo,
	cancel,
	sweepAbandoned,
	scheduleSweep,
};
